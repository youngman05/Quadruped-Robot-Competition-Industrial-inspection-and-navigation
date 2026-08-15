"""Regression tests for standalone ArmPi grasp and placement planning."""

from __future__ import annotations

import unittest

from arm_api import ArmGrabPlannerNew, IKNoSolution


class ArmGrabPlannerNewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = ArmGrabPlannerNew()
        # Valid for the current L4=0.270 m physical model. This must change
        # together with calibrated arm dimensions, not with ad hoc test data.
        self.target = (0.0, 0.42, 0.06)

    def test_horizontal_face_grasp_has_approach_close_and_lift(self) -> None:
        steps = self.planner.plan_horizontal_face_grab(self.target)
        names = [step.name for step in steps]

        self.assertEqual(names[:3], ["pre_grasp_open_and_rotate", "safe_pose", "pre_grasp"])
        self.assertEqual(dict(steps[0].servos)[1], 400)
        self.assertIn("close_gripper", names)
        close_step = next(step for step in steps if step.name == "close_gripper")
        self.assertEqual(dict(close_step.servos)[1], 256)
        self.assertEqual(names[-1], "lift")
        self.assertTrue(all(0 <= pulse <= 1000 for step in steps for _, pulse in step.servos))

    def test_direct_placement_reaches_target_then_opens_gripper(self) -> None:
        steps = self.planner.plan_place(self.target, duration_ms=900)

        self.assertEqual([step.name for step in steps], ["place_target", "open_gripper"])
        self.assertEqual(steps[0].coordinate, self.target)
        self.assertEqual(steps[0].duration_ms, 900)
        self.assertEqual(steps[1].servos, ((1, 400),))
        self.assertTrue(all(0 <= pulse <= 1000 for step in steps for _, pulse in step.servos))

    def test_direct_placement_can_append_home(self) -> None:
        steps = self.planner.plan_place(self.target, include_home=True)

        self.assertEqual(steps[-1].name, "home_from_sorting_py")

    def test_direct_placement_rejects_unreachable_target(self) -> None:
        with self.assertRaises(IKNoSolution):
            self.planner.plan_place((0.0, 2.0, 0.06))


if __name__ == "__main__":
    unittest.main()
