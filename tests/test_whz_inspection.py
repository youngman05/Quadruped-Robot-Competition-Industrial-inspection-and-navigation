import sys
import unittest
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
WHZ_ROOT = REPO_ROOT / "whz"
if str(WHZ_ROOT) not in sys.path:
    sys.path.insert(0, str(WHZ_ROOT))

from whz.inspection import InspectionRunner, Inspector
from whz.yolo_detector import (
    DetectionResult,
    GaugeDetection,
    LetterDetection,
    PairedDetection,
)


def detection(area, color, letter_confidence=0.9, gauge_confidence=0.8):
    letter = LetterDetection(
        letter=area,
        confidence=letter_confidence,
        bbox=(80, 20, 120, 60),
    )
    gauge = GaugeDetection(
        color=color,
        confidence=gauge_confidence,
        bbox=(50, 100, 150, 200),
    )
    return DetectionResult(
        letters=[letter],
        gauges=[gauge],
        pair=PairedDetection(
            letter=letter,
            gauge=gauge,
            score=0.82,
            horizontal_offset_ratio=0.0,
            vertical_gap_ratio=1.1,
        ),
    )


class FakeDetector:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def detect(self, image):
        del image
        result = self.results[self.calls]
        self.calls += 1
        return result


class FakePlayer:
    def __init__(self, fail=False):
        self.fail = fail
        self.played = []

    def audio_path_for(self, area, state_key):
        return Path("/fake") / (area + "_" + state_key + ".mp3")

    def play(self, path):
        self.played.append(Path(path))
        if self.fail:
            raise RuntimeError("speaker unavailable")


class FakeCamera:
    def __init__(self, frames=None, error=None):
        self.frames = list(frames or [])
        self.error = error
        self.calls = []
        self.close_calls = 0

    def read_frames(self, count, timeout_sec):
        self.calls.append((count, timeout_sec))
        if self.error is not None:
            raise self.error
        return self.frames[:count]

    def close(self):
        self.close_calls += 1


class InspectorTests(unittest.TestCase):
    def test_runner_reads_three_frames_votes_and_plays_once(self):
        frames = [np.zeros((2, 2, 3), dtype=np.uint8) for _ in range(3)]
        camera = FakeCamera(frames)
        detector = FakeDetector(
            [detection("A", "green"), detection("A", "green"), detection("B", "red")]
        )
        player = FakePlayer()
        inspector = Inspector(detector, player, play_audio=True, min_agree_frames=2)
        runner = InspectionRunner(camera, inspector, required_frames=3, frame_timeout_sec=1.25)

        result = runner.run()

        self.assertTrue(result.ok)
        self.assertEqual(result.area, "A")
        self.assertEqual(result.state_key, "middle")
        self.assertFalse(result.is_abnormal)
        self.assertEqual(result.state_text, "正常")
        self.assertEqual(result.status_text, "正常")
        self.assertEqual(result.agree_frames, 2)
        self.assertEqual(result.total_frames, 3)
        self.assertTrue(result.audio_played)
        self.assertEqual(len(player.played), 1)
        self.assertEqual(camera.calls, [(3, 1.25)])

    def test_abnormal_is_derived_from_state_key(self):
        player = FakePlayer()
        inspector = Inspector(
            FakeDetector([detection("C", "yellow")]),
            player,
            play_audio=True,
            min_agree_frames=1,
        )

        result = inspector.inspect_once(np.zeros((2, 2, 3), dtype=np.uint8))

        self.assertTrue(result.ok)
        self.assertEqual(result.state_key, "low")
        self.assertTrue(result.is_abnormal)
        self.assertEqual(player.played, [])

    def test_failed_vote_does_not_play_audio(self):
        player = FakePlayer()
        inspector = Inspector(
            FakeDetector(
                [
                    detection("A", "green"),
                    detection("B", "yellow"),
                    detection("C", "red"),
                ]
            ),
            player,
            play_audio=True,
            min_agree_frames=2,
        )

        result = inspector.inspect_frames([object(), object(), object()])

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "ambiguous_vote")
        self.assertEqual(player.played, [])

    def test_audio_failure_is_reported_after_one_attempt(self):
        player = FakePlayer(fail=True)
        inspector = Inspector(
            FakeDetector([detection("D", "red"), detection("D", "red")]),
            player,
            play_audio=True,
            min_agree_frames=2,
        )

        result = inspector.inspect_frames([object(), object()])

        self.assertFalse(result.ok)
        self.assertTrue(result.is_abnormal)
        self.assertFalse(result.audio_played)
        self.assertIn("audio_play_failed", result.error)
        self.assertEqual(len(player.played), 1)

    def test_camera_error_is_structured(self):
        camera = FakeCamera(error=TimeoutError("no fresh frame"))
        inspector = Inspector(FakeDetector([]), FakePlayer(), min_agree_frames=2)
        runner = InspectionRunner(camera, inspector, required_frames=3, frame_timeout_sec=0.5)

        result = runner.run()

        self.assertFalse(result.ok)
        self.assertIn("camera_read_failed", result.error)
        self.assertEqual(result.total_frames, 0)

    def test_short_camera_batch_is_rejected(self):
        camera = FakeCamera([object(), object()])
        inspector = Inspector(FakeDetector([]), FakePlayer(), min_agree_frames=2)
        runner = InspectionRunner(camera, inspector, required_frames=3, frame_timeout_sec=0.5)

        result = runner.run()

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "camera_frame_count_mismatch=2/3")
        self.assertEqual(result.total_frames, 2)

    def test_on_demand_camera_is_closed_after_capture(self):
        frames = [np.zeros((2, 2, 3), dtype=np.uint8) for _ in range(3)]
        camera = FakeCamera(frames)
        detector = FakeDetector([detection("D", "green") for _ in range(3)])
        inspector = Inspector(detector, FakePlayer(), play_audio=False, min_agree_frames=2)
        factory_calls = []

        def camera_factory():
            factory_calls.append(True)
            return camera

        runner = InspectionRunner(
            None,
            inspector,
            required_frames=3,
            frame_timeout_sec=0.5,
            camera_factory=camera_factory,
        )

        result = runner.run()

        self.assertTrue(result.ok)
        self.assertEqual(len(factory_calls), 1)
        self.assertEqual(camera.close_calls, 1)

    def test_on_demand_camera_closes_after_read_error(self):
        camera = FakeCamera(error=TimeoutError("no fresh frame"))
        inspector = Inspector(FakeDetector([]), FakePlayer(), min_agree_frames=2)
        runner = InspectionRunner(
            None,
            inspector,
            required_frames=3,
            frame_timeout_sec=0.5,
            camera_factory=lambda: camera,
        )

        result = runner.run()

        self.assertFalse(result.ok)
        self.assertIn("camera_read_failed", result.error)
        self.assertEqual(camera.close_calls, 1)

    def test_on_demand_camera_open_error_is_structured(self):
        inspector = Inspector(FakeDetector([]), FakePlayer(), min_agree_frames=2)

        def camera_factory():
            raise RuntimeError("RTSP unavailable")

        runner = InspectionRunner(
            None,
            inspector,
            required_frames=3,
            frame_timeout_sec=0.5,
            camera_factory=camera_factory,
        )

        result = runner.run()

        self.assertFalse(result.ok)
        self.assertIn("camera_open_failed", result.error)
        self.assertEqual(result.total_frames, 0)


if __name__ == "__main__":
    unittest.main()
