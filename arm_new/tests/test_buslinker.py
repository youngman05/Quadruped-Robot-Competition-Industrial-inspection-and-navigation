"""Tests for runtime BusLinker command helpers."""

from __future__ import annotations

import unittest
from unittest.mock import call, patch

from arm_api import MotionStep
from arm_api.buslinker import BusLinkerExecutor, interpolate_pulse_ramp


class BusLinkerPulseRampTest(unittest.TestCase):
    def test_descending_ramp_finishes_at_target(self) -> None:
        pulses = interpolate_pulse_ramp(900, 10, 100)
        self.assertEqual(pulses, (800, 700, 600, 500, 400, 300, 200, 100, 10))
        self.assertTrue(
            all(abs(right - left) <= 100 for left, right in zip((900,) + pulses, pulses))
        )

    def test_ascending_ramp_finishes_at_target(self) -> None:
        self.assertEqual(interpolate_pulse_ramp(256, 400, 100), (356, 400))

    def test_short_change_sends_target_once(self) -> None:
        self.assertEqual(interpolate_pulse_ramp(384, 400, 100), (400,))

    def test_equal_position_still_sends_target_once(self) -> None:
        self.assertEqual(interpolate_pulse_ramp(400, 400, 100), (400,))

    def test_invalid_step_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            interpolate_pulse_ramp(400, 256, 0)

    def test_close_gripper_reads_feedback_and_sends_each_ramp_target(self) -> None:
        executor = BusLinkerExecutor()
        executor.ser = object()
        step = MotionStep("close_gripper", None, 600, ((1, 10),))

        with patch(
            "arm_api.buslinker.read_position", return_value=310
        ) as read, patch("arm_api.buslinker.move_to_position") as move, patch(
            "arm_api.buslinker.time.sleep"
        ):
            executor.execute_step(
                step,
                dry_run=False,
                pause_s=0.2,
                gripper_ramp_step_pulse=100,
            )

        read.assert_called_once_with(executor.ser, 1)
        self.assertEqual(
            move.call_args_list,
            [
                call(executor.ser, 1, 210, 200),
                call(executor.ser, 1, 110, 200),
                call(executor.ser, 1, 10, 200),
            ],
        )

    def test_pre_grasp_open_ramps_id1_and_sends_id2_once(self) -> None:
        executor = BusLinkerExecutor()
        executor.ser = object()
        step = MotionStep(
            "pre_grasp_open_and_rotate", None, 500, ((1, 900), (2, 504))
        )

        with patch(
            "arm_api.buslinker.read_position", return_value=500
        ) as read, patch(
            "arm_api.buslinker.move_to_position"
        ) as move, patch("arm_api.buslinker.time.sleep"):
            executor.execute_step(
                step,
                dry_run=False,
                pause_s=0.2,
                gripper_ramp_step_pulse=100,
            )

        read.assert_called_once_with(executor.ser, 1)
        self.assertEqual(
            move.call_args_list,
            [
                call(executor.ser, 2, 504, 500),
                call(executor.ser, 1, 600, 125),
                call(executor.ser, 1, 700, 125),
                call(executor.ser, 1, 800, 125),
                call(executor.ser, 1, 900, 125),
            ],
        )

    def test_place_open_ramps_to_release_target(self) -> None:
        executor = BusLinkerExecutor()
        executor.ser = object()
        step = MotionStep("open_gripper", None, 600, ((1, 400),))

        with patch(
            "arm_api.buslinker.read_position", return_value=10
        ) as read, patch(
            "arm_api.buslinker.move_to_position"
        ) as move, patch("arm_api.buslinker.time.sleep"):
            executor.execute_step(
                step,
                dry_run=False,
                pause_s=0.2,
                gripper_ramp_step_pulse=100,
            )

        read.assert_called_once_with(executor.ser, 1)
        self.assertEqual(
            move.call_args_list,
            [
                call(executor.ser, 1, 110, 150),
                call(executor.ser, 1, 210, 150),
                call(executor.ser, 1, 310, 150),
                call(executor.ser, 1, 400, 150),
            ],
        )


if __name__ == "__main__":
    unittest.main()
