"""Pure consecutive-health and velocity policy for cone avoidance."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple


Command3 = Tuple[float, float, float]
ZERO_COMMAND: Command3 = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class ConeGateDecision:
    command: Command3
    allowed: bool
    reason: str


@dataclass(frozen=True)
class ConeLayerAppliedStatus:
    requested_enabled: bool
    applied_enabled: bool
    applied_revision: int
    status_sequence: int
    received_at: float


class ConeLayerAppliedTracker:
    SOURCES = ("local", "global")

    def __init__(self) -> None:
        self._latest: Dict[str, ConeLayerAppliedStatus] = {}
        self._baseline: Dict[str, Tuple[int, int]] = {}
        self._expected_enabled: Optional[bool] = None
        self.last_reason = "waiting for cone layer applied status"

    def observe(self, source: str, data: dict, now: float) -> None:
        if source not in self.SOURCES:
            raise ValueError("unknown cone layer source: %s" % source)
        if str(data.get("plugin", "")) != "cone_obstacle_layer":
            raise ValueError("unexpected cone layer plugin name")
        requested = data.get("requested_enabled")
        applied = data.get("applied_enabled")
        revision = data.get("applied_revision")
        sequence = data.get("status_sequence")
        if not isinstance(requested, bool) or not isinstance(applied, bool):
            raise ValueError("cone layer enabled fields must be bool")
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 0
            or isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence < 1
        ):
            raise ValueError("cone layer revision and sequence must be non-negative integers")
        now = float(now)
        if not math.isfinite(now):
            raise ValueError("cone layer status timestamp must be finite")
        previous = self._latest.get(source)
        if previous is not None and sequence <= previous.status_sequence:
            self.last_reason = "%s cone layer status did not advance" % source
            return
        self._latest[source] = ConeLayerAppliedStatus(
            requested_enabled=requested,
            applied_enabled=applied,
            applied_revision=revision,
            status_sequence=sequence,
            received_at=now,
        )
        self.last_reason = "ready for cone layer transition"

    def record_error(self, source: str, reason: str) -> None:
        self.last_reason = "%s cone layer status invalid: %s" % (source, reason)

    def baseline_ready(self) -> bool:
        return all(source in self._latest for source in self.SOURCES)

    def begin_transition(self, expected_enabled: bool) -> bool:
        if not self.baseline_ready():
            self.last_reason = "waiting for local/global cone layer applied status"
            return False
        self._expected_enabled = bool(expected_enabled)
        self._baseline = {
            source: (
                self._latest[source].status_sequence,
                self._latest[source].applied_revision,
            )
            for source in self.SOURCES
        }
        self.last_reason = "waiting for local/global cone layer application"
        return True

    def cancel_transition(self) -> None:
        self._baseline = {}
        self._expected_enabled = None

    def readiness(self) -> Tuple[bool, str]:
        if self._expected_enabled is None or not self._baseline:
            return False, "cone layer transition has not started"
        expected = self._expected_enabled
        for source in self.SOURCES:
            status = self._latest.get(source)
            if status is None:
                return False, "waiting for %s cone layer applied status" % source
            baseline_sequence, baseline_revision = self._baseline[source]
            if status.status_sequence <= baseline_sequence:
                return False, "waiting for %s cone layer status sequence" % source
            if status.applied_revision <= baseline_revision:
                return False, "waiting for %s cone layer applied revision" % source
            if status.requested_enabled != expected:
                return False, "%s cone layer requested state mismatch" % source
            if status.applied_enabled != expected:
                return False, "%s cone layer applied state mismatch" % source
        return True, "local/global cone layers applied"


class ConeScanHealthTracker:
    def __init__(self, required_consecutive: int = 3, max_age_sec: float = 0.25):
        self.required_consecutive = max(1, int(required_consecutive))
        self.max_age_sec = max(0.05, float(max_age_sec))
        self.stream_id = ""
        self.last_sequence = 0
        self.last_healthy_time: Optional[float] = None
        self.consecutive = 0
        self.last_reason = "waiting for cone scan health"

    def observe(
        self,
        stream_id: str,
        sequence: int,
        healthy: bool,
        now: float,
        reason: str = "",
    ) -> None:
        stream_id = str(stream_id)
        sequence = int(sequence)
        now = float(now)
        new_stream = bool(stream_id and stream_id != self.stream_id)
        regressed = bool(
            stream_id
            and stream_id == self.stream_id
            and sequence <= self.last_sequence
        )
        stale_gap = bool(
            self.last_healthy_time is not None
            and now - self.last_healthy_time > self.max_age_sec
        )
        if new_stream or regressed or stale_gap or not healthy:
            self.consecutive = 0
        if new_stream:
            self.stream_id = stream_id
            self.last_sequence = 0
        if regressed:
            self.last_reason = "health sequence did not advance"
            self.last_healthy_time = None
            return
        if not healthy:
            self.last_reason = reason or "cone scan source is unhealthy"
            self.last_healthy_time = None
            if stream_id:
                self.stream_id = stream_id
                self.last_sequence = max(self.last_sequence, sequence)
            return
        if not stream_id or sequence < 1 or not math.isfinite(now):
            self.last_reason = "invalid cone scan health metadata"
            self.last_healthy_time = None
            self.consecutive = 0
            return
        self.stream_id = stream_id
        self.last_sequence = sequence
        self.last_healthy_time = now
        self.consecutive += 1
        if self.consecutive < self.required_consecutive:
            self.last_reason = "warming up healthy cone scans (%d/%d)" % (
                self.consecutive,
                self.required_consecutive,
            )
        else:
            self.last_reason = "ready"

    def readiness(self, now: float) -> Tuple[bool, str]:
        now = float(now)
        if self.last_healthy_time is None:
            return False, self.last_reason
        age = now - self.last_healthy_time
        if not math.isfinite(age) or age < 0.0 or age > self.max_age_sec:
            self.consecutive = 0
            self.last_healthy_time = None
            self.last_reason = "cone scan health is stale"
            return False, self.last_reason
        if self.consecutive < self.required_consecutive:
            return False, self.last_reason
        return True, "ready"

    def evaluate(
        self,
        command: Command3,
        command_time: Optional[float],
        now: float,
        command_timeout_sec: float,
        require_scan_health: bool = True,
    ) -> ConeGateDecision:
        if not all(math.isfinite(float(value)) for value in command):
            return ConeGateDecision(ZERO_COMMAND, False, "non-finite velocity command")
        if command_time is None:
            return ConeGateDecision(ZERO_COMMAND, False, "waiting for velocity command")
        command_age = float(now) - float(command_time)
        if (
            not math.isfinite(command_age)
            or command_age < 0.0
            or command_age > float(command_timeout_sec)
        ):
            return ConeGateDecision(ZERO_COMMAND, False, "velocity command is stale")
        if require_scan_health:
            ready, reason = self.readiness(now)
            if not ready:
                return ConeGateDecision(ZERO_COMMAND, False, reason)
        return ConeGateDecision(
            tuple(float(value) for value in command),
            True,
            "ready" if require_scan_health else "cone avoidance bypassed",
        )
