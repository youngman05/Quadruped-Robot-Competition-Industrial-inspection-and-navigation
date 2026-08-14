"""Hardware-free tests for the YOLO contract and place executor."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "nodes" / "decision" / "manipulation_segments.py"
SPEC = importlib.util.spec_from_file_location("manipulation_segments", MODULE_PATH)
SEGMENTS = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = SEGMENTS
SPEC.loader.exec_module(SEGMENTS)


def packet(sequence, red_points):
    detections = [
        {
            "class_name": "red",
            "confidence": 0.9,
            "depth_valid_ratio": 0.9,
            "position_valid": True,
            "position_m": list(point),
        }
        for point in red_points
    ]
    return {
        "frame_id": "base_link",
        "sequence": sequence,
        "stamp": {"sec": sequence, "nanosec": 0},
        "detections": detections,
    }


class FakePlaceRuntime:
    def __init__(self):
        self.time = 0.0
        self.commands = []
        self.place_calls = 0
        self.place_results = []
        self.place_error_value = (0.0, 0.0, 0.0)

    def now(self):
        return self.time

    def stop(self):
        self.commands.append(("stop", 0.0))

    def command(self, axis, speed):
        self.commands.append((axis, speed))

    def next_detection(self):
        return None

    def placement_error(self, _zone):
        return self.place_error_value

    def start_place(self):
        self.place_calls += 1
        return True

    def place_result(self):
        return self.place_results.pop(0) if self.place_results else None


class ManipulationSegmentsTest(unittest.TestCase):
    def test_parser_uses_only_valid_base_link_blocks(self):
        frame = SEGMENTS.parse_detection_frame(packet(3, [(0.42, 0.0, 0.15)]), 0.5, 0.6)
        self.assertEqual(frame.sequence, 3)
        self.assertEqual(len(frame.red_blocks), 1)

        invalid = packet(4, [(0.42, 0.0, 0.15)])
        invalid["frame_id"] = "camera_link"
        with self.assertRaises(SEGMENTS.DetectionContractError):
            SEGMENTS.parse_detection_frame(invalid, 0.5, 0.6)

        missing_stamp = packet(5, [(0.42, 0.0, 0.15)])
        del missing_stamp["stamp"]
        with self.assertRaises(SEGMENTS.DetectionContractError):
            SEGMENTS.parse_detection_frame(missing_stamp, 0.5, 0.6)

    def test_place_requires_positive_service_result(self):
        runtime = FakePlaceRuntime()
        executor = SEGMENTS.PlaceOneExecutor(runtime, "A")
        executor.start()
        runtime.place_results = [None, True]
        runtime.time = 2.0
        executor.tick()
        executor.tick()
        executor.tick()
        executor.tick()
        self.assertEqual(executor.state, SEGMENTS.SegmentState.WAIT_ARM)
        self.assertIsNone(executor.tick())
        result = executor.tick()
        self.assertTrue(result.success)
        self.assertTrue(result.place_success)

    def test_place_rejection_never_reports_success(self):
        runtime = FakePlaceRuntime()
        runtime.place_results = [False]
        executor = SEGMENTS.PlaceOneExecutor(runtime, "A")
        executor.start()
        runtime.time = 2.0
        executor.tick()
        executor.tick()
        executor.tick()
        executor.tick()
        result = executor.tick()
        self.assertFalse(result.success)
        self.assertFalse(result.place_success)


if __name__ == "__main__":
    unittest.main()
