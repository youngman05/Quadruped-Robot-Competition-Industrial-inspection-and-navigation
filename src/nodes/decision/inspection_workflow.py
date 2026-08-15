"""ROS-free inspection workflow and `/whz/inspect` response validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional


VALID_AREAS = frozenset("ABCD")
STATE_TO_STATUS = {
    "low": "low",
    "middle": "normal",
    "high": "high",
}
STATE_TO_COLOR = {
    "low": "yellow",
    "middle": "green",
    "high": "red",
}


class InspectionContractError(ValueError):
    """The WHZ Trigger response is missing or contradicts required fields."""


class InspectionStage(Enum):
    NAVIGATING = "navigating"
    SETTLING = "settling"
    WAITING_SERVICE = "waiting_service"
    INSPECTING = "inspecting"
    COMPLETE = "complete"
    ABORTED = "aborted"


@dataclass(frozen=True)
class InspectionReading:
    area: str
    state_key: str
    status: str
    is_abnormal: bool
    color: str
    audio_played: bool
    agree_frames: int
    total_frames: int

    @classmethod
    def from_trigger(
        cls,
        success: bool,
        message: str,
        require_audio: bool = True,
    ) -> "InspectionReading":
        try:
            payload = json.loads(message)
        except (json.JSONDecodeError, TypeError) as exc:
            raise InspectionContractError("invalid_json: %s" % exc) from exc

        if not isinstance(payload, dict):
            raise InspectionContractError("response_payload_not_object")
        if not success or payload.get("ok") is not True:
            error = payload.get("error") or "inspection_unsuccessful"
            raise InspectionContractError(str(error))

        area = payload.get("area")
        if area not in VALID_AREAS:
            raise InspectionContractError("invalid_area=%r" % area)

        state_key = payload.get("state_key")
        if state_key not in STATE_TO_STATUS:
            raise InspectionContractError("invalid_state_key=%r" % state_key)

        color = payload.get("color")
        expected_color = STATE_TO_COLOR[state_key]
        if color != expected_color:
            raise InspectionContractError(
                "color_state_mismatch=%r/%s" % (color, state_key)
            )

        is_abnormal = payload.get("is_abnormal")
        expected_abnormal = state_key != "middle"
        if not isinstance(is_abnormal, bool) or is_abnormal != expected_abnormal:
            raise InspectionContractError(
                "abnormal_state_mismatch=%r/%s" % (is_abnormal, state_key)
            )

        audio_played = payload.get("audio_played")
        if not isinstance(audio_played, bool):
            raise InspectionContractError("audio_played_not_bool")
        if require_audio and not audio_played:
            raise InspectionContractError("audio_not_played")

        agree_frames = payload.get("agree_frames")
        total_frames = payload.get("total_frames")
        if (
            not isinstance(agree_frames, int)
            or isinstance(agree_frames, bool)
            or not isinstance(total_frames, int)
            or isinstance(total_frames, bool)
            or agree_frames < 1
            or total_frames < agree_frames
        ):
            raise InspectionContractError(
                "invalid_vote=%r/%r" % (agree_frames, total_frames)
            )

        return cls(
            area=area,
            state_key=state_key,
            status=STATE_TO_STATUS[state_key],
            is_abnormal=is_abnormal,
            color=color,
            audio_played=audio_played,
            agree_frames=agree_frames,
            total_frames=total_frames,
        )


class InspectionWorkflow:
    """Deterministic per-observation state and retry accounting."""

    def __init__(
        self,
        step_count: int,
        settle_duration_sec: float,
        max_nav_retries: int,
        max_inspection_retries: int,
    ) -> None:
        if step_count < 1 or step_count > len(VALID_AREAS):
            raise ValueError("step_count must be between 1 and 4")
        if settle_duration_sec < 0.0:
            raise ValueError("settle_duration_sec must be non-negative")
        if max_nav_retries < 0 or max_inspection_retries < 0:
            raise ValueError("retry counts must be non-negative")

        self.step_count = step_count
        self.settle_duration_sec = float(settle_duration_sec)
        self.max_nav_retries = int(max_nav_retries)
        self.max_inspection_retries = int(max_inspection_retries)

        self.stage = InspectionStage.NAVIGATING
        self.step_index = 0
        self.nav_retries = 0
        self.inspection_retries = 0
        self.stable_since: Optional[float] = None
        self.abort_reason = ""
        self.readings: Dict[str, InspectionReading] = {}
        self.uncertain_attempts: List[str] = []

    def navigation_succeeded(self) -> None:
        self._require_stage(InspectionStage.NAVIGATING)
        self.nav_retries = 0
        self.stable_since = None
        self.stage = InspectionStage.SETTLING

    def navigation_failed(self, reason: str) -> bool:
        self._require_stage(InspectionStage.NAVIGATING)
        if self.nav_retries >= self.max_nav_retries:
            self.abort(
                "navigation_failed_after_%d_attempts: %s"
                % (self.max_nav_retries + 1, reason)
            )
            return False
        self.nav_retries += 1
        return True

    def update_stationary(self, now: float, stationary: bool) -> bool:
        self._require_stage(InspectionStage.SETTLING)
        if not stationary:
            self.stable_since = None
            return False
        if self.stable_since is None:
            self.stable_since = float(now)
        if float(now) - self.stable_since < self.settle_duration_sec:
            return False
        self.stage = InspectionStage.WAITING_SERVICE
        return True

    def service_started(self) -> None:
        self._require_stage(InspectionStage.WAITING_SERVICE)
        self.stage = InspectionStage.INSPECTING

    def inspection_failed(self, reason: str) -> bool:
        if self.stage not in (
            InspectionStage.WAITING_SERVICE,
            InspectionStage.INSPECTING,
        ):
            raise RuntimeError("inspection failure in stage %s" % self.stage.value)
        if self.inspection_retries >= self.max_inspection_retries:
            self.abort(
                "inspection_failed_after_%d_attempts: %s"
                % (self.max_inspection_retries + 1, reason)
            )
            return False
        self.inspection_retries += 1
        self.stable_since = None
        self.stage = InspectionStage.SETTLING
        return True

    def inspection_timed_out(self, reason: str) -> None:
        if self.stage != InspectionStage.INSPECTING:
            raise RuntimeError("inspection timeout in stage %s" % self.stage.value)
        self.abort("inspection_outcome_unknown: %s" % reason)

    def inspection_uncertain(self, reason: str) -> None:
        if self.stage not in (
            InspectionStage.WAITING_SERVICE,
            InspectionStage.INSPECTING,
        ):
            raise RuntimeError("uncertain inspection in stage %s" % self.stage.value)
        self.uncertain_attempts.append(str(reason))
        self.step_index += 1
        self.nav_retries = 0
        self.inspection_retries = 0
        self.stable_since = None
        self.stage = (
            InspectionStage.COMPLETE
            if self.step_index >= self.step_count
            else InspectionStage.NAVIGATING
        )

    def inspection_succeeded(self, reading: InspectionReading) -> None:
        self._require_stage(InspectionStage.INSPECTING)
        if reading.area in self.readings:
            self.abort("duplicate_area=%s" % reading.area)
            return

        self.readings[reading.area] = reading
        self.step_index += 1
        self.nav_retries = 0
        self.inspection_retries = 0
        self.stable_since = None

        if self.step_index >= self.step_count:
            self.stage = InspectionStage.COMPLETE
        else:
            self.stage = InspectionStage.NAVIGATING

    def require_complete_abcd(self) -> None:
        if self.stage != InspectionStage.COMPLETE:
            raise RuntimeError("completeness checked before workflow completion")
        actual = frozenset(self.readings)
        if actual != VALID_AREAS:
            missing = "".join(sorted(VALID_AREAS - actual)) or "none"
            extra = "".join(sorted(actual - VALID_AREAS)) or "none"
            self.abort("incomplete_areas: missing=%s extra=%s" % (missing, extra))

    def abort(self, reason: str) -> None:
        self.abort_reason = str(reason)
        self.stage = InspectionStage.ABORTED

    def _require_stage(self, expected: InspectionStage) -> None:
        if self.stage != expected:
            raise RuntimeError(
                "expected stage %s, got %s" % (expected.value, self.stage.value)
            )
