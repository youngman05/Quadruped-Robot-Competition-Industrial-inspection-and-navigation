"""Unit tests for the hardware-independent red-block manipulation core."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "src" / "nodes" / "decision" / "manipulation_core.py"
SPEC = importlib.util.spec_from_file_location("manipulation_core", CORE_PATH)
CORE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = CORE
SPEC.loader.exec_module(CORE)


def packet(sequence, red_points, green_points=((0.2, 0.1, 0.05), (0.2, -0.1, 0.05))):
    detections = []
    for point in red_points:
        detections.append({
            "class_name": "red", "confidence": 0.9,
            "depth_valid_ratio": 0.9, "position_valid": True,
            "position_m": list(point),
        })
    for point in green_points:
        detections.append({
            "class_name": "green", "confidence": 0.9,
            "depth_valid_ratio": 0.9, "position_valid": True,
            "position_m": list(point),
        })
    return {"sequence": sequence, "frame_id": "base_link", "detections": detections}


def frame(sequence, red_points, green_points=((0.2, 0.1, 0.05), (0.2, -0.1, 0.05))):
    return CORE.parse_host_detection_packet(packet(sequence, red_points, green_points), sequence / 10.0, 0.5, 0.6)


class ManipulationCoreTest(unittest.TestCase):
    def test_rejects_non_base_link_packet(self) -> None:
        invalid = packet(1, [(0.5, 0.0, 0.05)])
        invalid["frame_id"] = "camera_link"
        with self.assertRaises(CORE.DetectionContractError):
            CORE.parse_host_detection_packet(invalid, 0.0, 0.5, 0.6)

    def test_observer_selects_spatial_target_when_detector_order_changes(self) -> None:
        observer = CORE.StableRedObserver(window_size=8, required_stable_frames=5, match_gate_m=0.05)
        # The left-side block is closer to the desired y=0 reference.  Its list
        # index alternates deliberately to prove that selection is spatial.
        for sequence in range(1, 6):
            near = (0.70 + sequence * 0.001, 0.015, 0.06)
            far = (0.55 - sequence * 0.001, -0.160, 0.06)
            points = (near, far) if sequence % 2 else (far, near)
            observer.add(frame(sequence, points))

        selected = observer.select_target(2, 2, (0.60, 0.0))
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertAlmostEqual(selected[1], 0.015, places=3)

    def test_locked_target_does_not_follow_reordered_array(self) -> None:
        locked = CORE.LockedTarget((0.70, 0.02, 0.06), last_sequence=5)
        # A different red block is first in this frame, but the nearest point
        # remains the physical target selected on the previous frame.
        matched = locked.match(frame(6, ((0.48, -0.15, 0.06), (0.69, 0.021, 0.06))), 0.08)
        self.assertEqual(matched, (0.69, 0.021, 0.06))

    def test_lost_target_is_rejected_outside_spatial_gate(self) -> None:
        locked = CORE.LockedTarget((0.70, 0.02, 0.06), last_sequence=1)
        self.assertIsNone(locked.match(frame(2, ((0.20, 0.20, 0.06),)), 0.10))
        self.assertEqual(locked.lost_frames, 1)

    def test_incremental_p_pulse_has_speed_and_duration_bounds(self) -> None:
        pulse = CORE.proportional_axis_pulse(0.20, 0.6, 0.06, 0.025, 0.15, 0.40)
        self.assertEqual(pulse.speed_mps, 0.06)
        self.assertEqual(pulse.duration_s, 0.40)
        slow = CORE.proportional_axis_pulse(-0.001, 0.6, 0.06, 0.025, 0.15, 0.40)
        self.assertEqual(slow.speed_mps, -0.025)
        self.assertEqual(slow.duration_s, 0.15)

    def test_job_queue_only_advances_after_place_success(self) -> None:
        jobs = CORE.JobQueue.from_zones(["D", "B"])
        self.assertEqual(jobs.zones, ("B", "D"))
        self.assertEqual(jobs.current_zone, "B")
        self.assertFalse(jobs.complete_current(False))
        self.assertEqual(jobs.current_zone, "B")
        self.assertTrue(jobs.complete_current(True))
        self.assertEqual(jobs.current_zone, "D")
        self.assertTrue(jobs.complete_current(True))
        self.assertTrue(jobs.complete)

    def test_uncalibrated_site_file_fails_closed(self) -> None:
        content = """
calibration_set: {id: unit-test}
dog_poses:
  grasp_i0: {pose_map_m_rad: [1.0, 2.0, 0.0], status: calibrated}
  placement_A: {pose_map_m_rad: [1.0, 3.0, 0.0], status: provisional}
  placement_B: {pose_map_m_rad: [1.0, 4.0, 0.0], status: calibrated}
"""
        with tempfile.TemporaryDirectory() as directory:
            calibration = Path(directory) / "sites.yaml"
            calibration.write_text(content, encoding="utf-8")
            with self.assertRaises(CORE.CalibrationError):
                CORE.load_manipulation_sites(calibration, ["A", "B"])


if __name__ == "__main__":
    unittest.main()
