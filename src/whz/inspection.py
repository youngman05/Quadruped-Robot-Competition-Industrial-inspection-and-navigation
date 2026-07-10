"""Cabinet inspection pipeline — YOLO-based."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

from cv.gauge_detector import GaugeDetector
from whz.audio_player import AudioPlayer

# green→normal, yellow→low, red→high
_COLOR_TO_STATE = {"green": ("middle", "正常"), "yellow": ("low", "异常"), "red": ("high", "异常")}


@dataclass
class InspectionResult:
    ok: bool
    area: Optional[str] = None
    state_key: Optional[str] = None
    level: Optional[str] = None
    status: Optional[str] = None
    color: Optional[str] = None
    audio_file: Optional[str] = None
    letter_score: Optional[float] = None
    gauge_confidence: Optional[float] = None
    letter_above_gauge: Optional[bool] = None
    agree_frames: Optional[int] = None
    total_frames: Optional[int] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class Inspector:
    """Run letter + gauge detection with YOLO, play audio on success."""

    def __init__(
        self,
        detector: GaugeDetector,
        audio_player: AudioPlayer,
        play_audio: bool = True,
        min_agree_frames: int = 1,
    ) -> None:
        self.detector = detector
        self.audio_player = audio_player
        self.play_audio = bool(play_audio)
        self.min_agree_frames = max(1, int(min_agree_frames))

    def inspect_once(self, image) -> InspectionResult:
        try:
            result = self._inspect_image(image)
            if result.ok and self.play_audio and result.audio_file:
                self.audio_player.play(Path(result.audio_file))
            return result
        except Exception as exc:
            return InspectionResult(ok=False, error=str(exc))

    def inspect_frames(self, images: Iterable) -> InspectionResult:
        frame_results = [self._inspect_image(image) for image in images]
        successes = [r for r in frame_results if r.ok]
        total = len(frame_results)
        if not successes:
            return InspectionResult(ok=False, error="no_valid_frame", total_frames=total, agree_frames=0)

        votes = Counter((r.area, r.state_key) for r in successes)
        (area, state_key), agree_count = votes.most_common(1)[0]
        if agree_count < self.min_agree_frames:
            return InspectionResult(
                ok=False, error=f"not_enough_agreement={agree_count}/{self.min_agree_frames}",
                area=area, state_key=state_key, total_frames=total, agree_frames=agree_count,
            )

        matching = [r for r in successes if r.area == area and r.state_key == state_key]
        best = max(matching, key=lambda r: (r.letter_score or 0) + (r.gauge_confidence or 0))
        best.agree_frames = agree_count
        best.total_frames = total

        if self.play_audio and best.audio_file:
            try:
                self.audio_player.play(Path(best.audio_file))
            except Exception as exc:
                return InspectionResult(
                    ok=False, area=best.area, state_key=best.state_key,
                    level=best.level, status=best.status, color=best.color,
                    audio_file=best.audio_file, agree_frames=agree_count,
                    total_frames=total, error=f"audio_play_failed: {exc}",
                )
        return best

    def _inspect_image(self, image) -> InspectionResult:
        det = self.detector.detect(image)

        letter = det.best_letter
        if letter is None:
            return InspectionResult(ok=False, error="letter_not_detected")

        gauge = det.best_gauge
        if gauge is None:
            return InspectionResult(ok=False, area=letter.label, error="gauge_not_detected")

        state_key, status = _COLOR_TO_STATE.get(gauge.color, ("unknown", "未知"))
        level = {"middle": "正常", "low": "偏低", "high": "偏高"}.get(state_key, "未知")

        audio_path = self.audio_player.audio_path_for(letter.label, state_key)

        # letter above gauge check
        x0, y0, x1, y1 = letter.bbox
        letter_center_y = (y0 + y1) / 2.0
        gx0, gy0, gx1, gy1 = gauge.bbox
        gauge_center_y = (gy0 + gy1) / 2.0

        return InspectionResult(
            ok=True,
            area=letter.label,
            state_key=state_key,
            level=level,
            status=status,
            color=gauge.color,
            audio_file=str(audio_path),
            letter_score=round(letter.conf, 4),
            gauge_confidence=round(gauge.conf, 4),
            letter_above_gauge=letter_center_y < gauge_center_y,
        )
