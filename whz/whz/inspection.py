"""Multi-frame cabinet inspection, voting, and one-shot audio playback."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Callable, Iterable, Optional

from whz.audio_player import AudioPlayer
from whz.yolo_detector import YOLODetector


COLOR_TO_STATE_KEY = {
    "yellow": "low",
    "green": "middle",
    "red": "high",
}

STATE_DISPLAY = {
    "low": ("偏低", "异常"),
    "middle": ("正常", "正常"),
    "high": ("偏高", "异常"),
}


@dataclass
class InspectionResult:
    ok: bool
    area: Optional[str] = None
    state_key: Optional[str] = None
    is_abnormal: Optional[bool] = None
    state_text: Optional[str] = None
    status_text: Optional[str] = None
    color: Optional[str] = None
    audio_file: Optional[str] = None
    audio_played: bool = False
    letter_confidence: Optional[float] = None
    gauge_confidence: Optional[float] = None
    pair_score: Optional[float] = None
    agree_frames: Optional[int] = None
    total_frames: Optional[int] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class Inspector:
    """Normalize paired detections, vote, then play exactly one announcement."""

    def __init__(
        self,
        detector: YOLODetector,
        audio_player: AudioPlayer,
        play_audio: bool = True,
        min_agree_frames: int = 2,
    ) -> None:
        self.detector = detector
        self.audio_player = audio_player
        self.play_audio = bool(play_audio)
        self.min_agree_frames = max(1, int(min_agree_frames))

    def inspect_once(self, image) -> InspectionResult:
        """Inspect one frame without audio; service audio is gated by voting."""
        try:
            return self._inspect_image(image)
        except Exception as exc:  # noqa: BLE001
            return InspectionResult(ok=False, error=str(exc))

    def inspect_frames(self, images: Iterable) -> InspectionResult:
        frame_results = [self.inspect_once(image) for image in images]
        successes = [result for result in frame_results if result.ok]
        total = len(frame_results)
        if not successes:
            return InspectionResult(
                ok=False,
                error="no_valid_frame",
                total_frames=total,
                agree_frames=0,
            )

        votes = Counter((result.area, result.state_key) for result in successes)
        ranked_votes = votes.most_common()
        (area, state_key), agree_count = ranked_votes[0]
        if len(ranked_votes) > 1 and ranked_votes[1][1] == agree_count:
            return InspectionResult(
                ok=False,
                error="ambiguous_vote",
                total_frames=total,
                agree_frames=agree_count,
            )
        if agree_count < self.min_agree_frames:
            return InspectionResult(
                ok=False,
                error="not_enough_agreement=%d/%d"
                % (agree_count, self.min_agree_frames),
                area=area,
                state_key=state_key,
                total_frames=total,
                agree_frames=agree_count,
            )

        matching = [
            result
            for result in successes
            if result.area == area and result.state_key == state_key
        ]
        best = max(
            matching,
            key=lambda result: (
                (result.letter_confidence or 0.0)
                + (result.gauge_confidence or 0.0)
                + (result.pair_score or 0.0)
            ),
        )
        best = replace(best, agree_frames=agree_count, total_frames=total)

        if not self.play_audio or not best.audio_file:
            return best
        try:
            self.audio_player.play(Path(best.audio_file))
        except Exception as exc:  # noqa: BLE001
            return replace(
                best,
                ok=False,
                audio_played=False,
                error="audio_play_failed: %s" % exc,
            )
        return replace(best, audio_played=True)

    def _inspect_image(self, image) -> InspectionResult:
        detection = self.detector.detect(image)
        if not detection.ok or detection.pair is None:
            return InspectionResult(ok=False, error=detection.error or "detection_failed")

        pair = detection.pair
        area = pair.letter.letter
        color = pair.gauge.color
        state_key = COLOR_TO_STATE_KEY.get(color)
        if state_key is None:
            return InspectionResult(ok=False, area=area, color=color, error="unknown_color")

        state_text, status_text = STATE_DISPLAY[state_key]
        is_abnormal = state_key != "middle"
        audio_path = self.audio_player.audio_path_for(area, state_key)
        return InspectionResult(
            ok=True,
            area=area,
            state_key=state_key,
            is_abnormal=is_abnormal,
            state_text=state_text,
            status_text=status_text,
            color=color,
            audio_file=str(audio_path),
            letter_confidence=round(pair.letter.confidence, 4),
            gauge_confidence=round(pair.gauge.confidence, 4),
            pair_score=round(pair.score, 4),
        )


class InspectionRunner:
    """ROS-free camera-to-result orchestration for tests and the service node."""

    def __init__(
        self,
        camera,
        inspector: Inspector,
        required_frames: int = 3,
        frame_timeout_sec: float = 2.0,
        camera_factory: Optional[Callable[[], object]] = None,
    ) -> None:
        self.camera = camera
        self.camera_factory = camera_factory
        self.inspector = inspector
        self.required_frames = int(required_frames)
        self.frame_timeout_sec = float(frame_timeout_sec)
        if (self.camera is None) == (self.camera_factory is None):
            raise ValueError("provide exactly one of camera or camera_factory")
        if self.required_frames < 1:
            raise ValueError("required_frames must be at least 1")
        if self.inspector.min_agree_frames > self.required_frames:
            raise ValueError("min_agree_frames cannot exceed required_frames")

    def run(self) -> InspectionResult:
        camera = self.camera
        close_after_capture = False
        if self.camera_factory is not None:
            try:
                camera = self.camera_factory()
                close_after_capture = True
            except Exception as exc:  # noqa: BLE001
                return InspectionResult(
                    ok=False,
                    error="camera_open_failed: %s" % exc,
                    total_frames=0,
                    agree_frames=0,
                )

        try:
            frames = camera.read_frames(
                count=self.required_frames,
                timeout_sec=self.frame_timeout_sec,
            )
        except Exception as exc:  # noqa: BLE001
            return InspectionResult(
                ok=False,
                error="camera_read_failed: %s" % exc,
                total_frames=0,
                agree_frames=0,
            )
        finally:
            if close_after_capture:
                camera.close()

        if len(frames) != self.required_frames:
            return InspectionResult(
                ok=False,
                error="camera_frame_count_mismatch=%d/%d"
                % (len(frames), self.required_frames),
                total_frames=len(frames),
                agree_frames=0,
            )
        return self.inspector.inspect_frames(frames)
