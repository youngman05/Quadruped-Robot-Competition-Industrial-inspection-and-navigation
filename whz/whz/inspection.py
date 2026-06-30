"""Single-shot cabinet inspection pipeline."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

from whz.audio_player import AudioPlayer
from whz.gauge_detector import detect_gauge
from whz.letter_detector import LetterDetector


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
    """Run letter recognition, gauge recognition, and optional audio playback."""

    def __init__(
        self,
        letter_detector: LetterDetector,
        audio_player: AudioPlayer,
        play_audio: bool = True,
        min_agree_frames: int = 1,
    ) -> None:
        self.letter_detector = letter_detector
        self.audio_player = audio_player
        self.play_audio = bool(play_audio)
        self.min_agree_frames = max(1, int(min_agree_frames))

    def inspect_once(self, image) -> InspectionResult:
        try:
            result = self._inspect_image(image)
            if result.ok and self.play_audio and result.audio_file:
                self.audio_player.play(Path(result.audio_file))
            return result
        except Exception as exc:  # noqa: BLE001
            return InspectionResult(ok=False, error=str(exc))

    def inspect_frames(self, images: Iterable) -> InspectionResult:
        frame_results = [self._inspect_image(image, play_audio=False) for image in images]
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
        (area, state_key), agree_count = votes.most_common(1)[0]
        if agree_count < self.min_agree_frames:
            return InspectionResult(
                ok=False,
                error=f"not_enough_agreement={agree_count}/{self.min_agree_frames}",
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
            key=lambda result: (result.letter_score or 0.0) + (result.gauge_confidence or 0.0),
        )
        best.agree_frames = agree_count
        best.total_frames = total
        if self.play_audio and best.audio_file:
            try:
                self.audio_player.play(Path(best.audio_file))
            except Exception as exc:  # noqa: BLE001
                return InspectionResult(
                    ok=False,
                    area=best.area,
                    state_key=best.state_key,
                    level=best.level,
                    status=best.status,
                    color=best.color,
                    audio_file=best.audio_file,
                    agree_frames=agree_count,
                    total_frames=total,
                    error=f"audio_play_failed: {exc}",
                )
        return best

    def _inspect_image(self, image, play_audio: bool = False) -> InspectionResult:
        del play_audio
        depth = None
        if isinstance(image, tuple):
            image, depth = image

        letter = self.letter_detector.detect(image)
        if letter is None:
            return InspectionResult(ok=False, error="letter_not_detected")

        gauge = detect_gauge(image, depth)
        if gauge is None:
            return InspectionResult(ok=False, area=letter.area, error="gauge_not_detected")

        if letter.bbox is None:
            return InspectionResult(ok=False, area=letter.area, error="letter_bbox_missing")

        x0, y0, x1, y1 = letter.bbox
        letter_center_y = (y0 + y1) / 2.0
        if letter_center_y >= gauge.center_y:
            return InspectionResult(
                ok=False,
                area=letter.area,
                state_key=gauge.state_key,
                level=gauge.level,
                status=gauge.status,
                color=gauge.color,
                letter_score=round(letter.score, 4),
                gauge_confidence=round(gauge.confidence, 4),
                letter_above_gauge=False,
                error="letter_not_above_gauge",
            )

        audio_path = self.audio_player.audio_path_for(letter.area, gauge.state_key)
        return InspectionResult(
            ok=True,
            area=letter.area,
            state_key=gauge.state_key,
            level=gauge.level,
            status=gauge.status,
            color=gauge.color,
            audio_file=str(audio_path),
            letter_score=round(letter.score, 4),
            gauge_confidence=round(gauge.confidence, 4),
            letter_above_gauge=True,
        )
