"""Hardware-free tests for AprilTag target selection and I2 pickup."""

import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nodes.decision.pick_alignment_core import (
    FiducialDetectionFrame,
    FiducialPoseFrame,
    I2Target,
    PickConfig,
    PickOneExecutor,
    PickState,
    parse_fiducial_frame,
)


def quaternion_for_yaw(yaw):
    return (0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0))


class FakeRuntime:
    def __init__(self):
        self.time = 0.0
        self.frame = None
        self.commands = []
        self.grasp_calls = 0
        self.grasp_results = []

    def now(self):
        return self.time

    def stop(self):
        self.commands.append(("stop", 0.0))

    def command(self, axis, speed):
        self.commands.append((axis, speed))

    def current_fiducial_frame(self):
        return self.frame

    def start_grasp(self):
        self.grasp_calls += 1
        return True

    def grasp_result(self):
        return self.grasp_results.pop(0) if self.grasp_results else None


def pose(tag_id, sequence, x, y, yaw):
    return FiducialPoseFrame(tag_id, sequence, float(sequence), (x, y, 0.0), quaternion_for_yaw(yaw))


def frame(sequence, *poses):
    return FiducialDetectionFrame(sequence, float(sequence), tuple(poses))


def configured(**overrides):
    values = dict(
        red_tag_ids=(0, 1),
        i2_targets={0: I2Target(0.70, -0.20, math.pi), 1: I2Target(0.60, 0.15, math.pi)},
        initial_settle_s=0.0,
        stable_frames=3,
        lifted_hold_s=0.0,
    )
    values.update(overrides)
    return PickConfig(**values)


class PickAlignmentCoreTest(unittest.TestCase):
    def test_parse_multi_tag_base_link_frame(self):
        parsed = parse_fiducial_frame({
            "sequence": 4,
            "stamp": {"sec": 10, "nanosec": 20},
            "frame_id": "base_link",
            "detections": [
                {"tag_id": 0, "position_m": [0.8, 0.1, 0.2], "orientation_xyzw": [0, 0, 0, 1]},
                {"tag_id": 3, "position_m": [0.7, -0.2, 0.2], "orientation_xyzw": [0, 0, 1, 0]},
            ],
        })
        self.assertEqual(parsed.sequence, 4)
        self.assertEqual([item.tag_id for item in parsed.detections], [0, 3])

    def test_nearest_red_tag_is_selected_and_locked(self):
        runtime = FakeRuntime()
        runtime.frame = frame(1, pose(0, 1, 0.9, 0.0, math.pi), pose(1, 1, 0.6, 0.0, math.pi))
        executor = PickOneExecutor(runtime, configured())
        executor.start(); executor.tick(); executor.tick()
        self.assertEqual(executor.target_tag_id, 1)

        runtime.frame = frame(2, pose(0, 2, 0.3, 0.0, math.pi), pose(1, 2, 0.6, 0.0, math.pi))
        executor.tick()
        self.assertEqual(executor.target_tag_id, 1)

    def test_forced_tag_bypasses_nearest_red_selection(self):
        runtime = FakeRuntime()
        runtime.frame = frame(
            1,
            pose(0, 1, 0.9, 0.0, math.pi),
            pose(1, 1, 0.2, 0.0, math.pi),
        )
        executor = PickOneExecutor(runtime, configured(forced_tag_id=0))
        executor.start(); executor.tick(); executor.tick()
        self.assertEqual(executor.target_tag_id, 0)

    def test_untaught_selected_tag_fails_without_motion(self):
        runtime = FakeRuntime()
        runtime.frame = frame(1, pose(1, 1, 0.5, 0.0, math.pi))
        executor = PickOneExecutor(runtime, configured(i2_targets={0: I2Target(0.7, 0.0, math.pi)}))
        executor.start(); executor.tick()
        result = executor.tick()
        self.assertFalse(result.success)
        self.assertIn("I2_NOT_TAUGHT", result.reason)
        self.assertFalse(any(axis != "stop" for axis, _speed in runtime.commands))
        self.assertEqual(runtime.grasp_calls, 0)

    def test_previously_picked_tag_is_excluded(self):
        runtime = FakeRuntime()
        runtime.frame = frame(1, pose(0, 1, 0.4, 0.0, math.pi), pose(1, 1, 0.7, 0.0, math.pi))
        executor = PickOneExecutor(runtime, configured(excluded_tag_ids=(0,)))
        executor.start(); executor.tick(); executor.tick()
        self.assertEqual(executor.target_tag_id, 1)

    def test_alignment_starts_yaw_then_y_then_x(self):
        runtime = FakeRuntime()
        executor = PickOneExecutor(runtime, configured(stable_frames=1))
        runtime.frame = frame(1, pose(0, 1, 0.75, -0.25, math.pi + 0.2))
        executor.start(); executor.tick(); executor.tick(); executor.tick(); executor.tick()
        self.assertEqual(runtime.commands[-1], ("yaw", 0.10))

        runtime.time = 1.0; executor.tick()
        runtime.frame = frame(2, pose(0, 2, 0.75, -0.25, math.pi))
        runtime.time = 2.0; executor.tick(); executor.tick(); executor.tick(); executor.tick()
        self.assertEqual(runtime.commands[-1][0], "y")

        runtime.time = 3.0; executor.tick()
        runtime.frame = frame(3, pose(0, 3, 0.75, -0.20, math.pi))
        runtime.time = 4.0; executor.tick(); executor.tick(); executor.tick(); executor.tick(); executor.tick()
        self.assertEqual(runtime.commands[-1][0], "x")

    def test_x_and_y_use_independent_calibrated_speeds(self):
        runtime = FakeRuntime()
        executor = PickOneExecutor(
            runtime,
            configured(
                stable_frames=1,
                x_speed_mps=0.12,
                y_speed_mps=0.05,
                min_x_speed_mps=0.12,
                min_y_speed_mps=0.05,
            ),
        )
        runtime.frame = frame(1, pose(0, 1, 0.85, -0.30, math.pi))
        executor.start(); executor.tick(); executor.tick(); executor.tick(); executor.tick()
        runtime.time = 1.0; executor.tick()
        runtime.frame = frame(2, pose(0, 2, 0.85, -0.30, math.pi))
        runtime.time = 2.0; executor.tick(); executor.tick(); executor.tick(); executor.tick()
        self.assertEqual(runtime.commands[-1], ("y", -0.05))

        runtime.time = 3.0; executor.tick()
        runtime.frame = frame(3, pose(0, 3, 0.85, -0.20, math.pi))
        runtime.time = 4.0; executor.tick(); executor.tick(); executor.tick(); executor.tick(); executor.tick()
        self.assertEqual(runtime.commands[-1], ("x", 0.12))

    def test_three_new_frames_confirm_then_call_grasp_once(self):
        runtime = FakeRuntime()
        executor = PickOneExecutor(runtime, configured())
        runtime.frame = frame(1, pose(0, 1, 0.70, -0.20, math.pi))
        executor.start(); executor.tick(); executor.tick()
        executor.tick(); executor.tick(); executor.tick()
        self.assertEqual(executor.state, PickState.CONFIRM_I2)
        for sequence in (2, 3, 4):
            runtime.frame = frame(sequence, pose(0, sequence, 0.70, -0.20, math.pi))
            executor.tick()
        self.assertEqual(executor.state, PickState.WAIT_ARM)
        self.assertEqual(runtime.grasp_calls, 1)
        executor.tick()
        self.assertEqual(runtime.grasp_calls, 1)

        runtime.grasp_results = [True]
        executor.tick()
        result = executor.tick()
        self.assertTrue(result.success)
        self.assertTrue(result.grasp_success)
        self.assertEqual(result.outputs["target_tag_id"], 0)

    def test_i2_acceptance_stops_before_grasp(self):
        runtime = FakeRuntime()
        executor = PickOneExecutor(runtime, configured(stable_frames=1, stop_after_stage="i2"))
        runtime.frame = frame(1, pose(0, 1, 0.70, -0.20, math.pi))
        executor.start(); executor.tick(); executor.tick()
        result = None
        for sequence in range(2, 7):
            runtime.frame = frame(sequence, pose(0, sequence, 0.70, -0.20, math.pi))
            result = executor.tick()
            if result is not None:
                break
        self.assertTrue(result.success)
        self.assertEqual(result.outputs["test_stage"], "i2")
        self.assertEqual(runtime.grasp_calls, 0)


if __name__ == "__main__":
    unittest.main()
