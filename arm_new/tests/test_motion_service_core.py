"""Pure tests for the arm_motion_node service planning helpers."""

from __future__ import annotations

import unittest

from arm_api import ArmGrabPlannerNew
from arm_api.motion_service_core import (
    MotionServiceValidationError,
    arm_base_to_api,
    plan_face_approach_grasp,
    plan_fixed_place,
    validate_grasp_target,
)


class MotionServiceCoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = ArmGrabPlannerNew()
        self.target_arm_base = (0.42, 0.0, 0.06)

    def test_arm_base_to_api_axes_match_documented_convention(self) -> None:
        self.assertEqual(arm_base_to_api((0.42, 0.10, 0.06)), (-0.10, 0.42, 0.06))

    def test_grasp_target_requires_i1_xy_and_calibrated_z_range(self) -> None:
        self.assertEqual(
            validate_grasp_target(self.target_arm_base, (0.40, 0.0), 0.03, 0.04, 0.10),
            self.target_arm_base,
        )
        with self.assertRaises(MotionServiceValidationError):
            validate_grasp_target((0.46, 0.0, 0.06), (0.40, 0.0), 0.03, 0.04, 0.10)
        with self.assertRaises(MotionServiceValidationError):
            validate_grasp_target((0.40, 0.0, 0.12), (0.40, 0.0), 0.03, 0.04, 0.10)

    def test_grasp_plan_matches_face_approach_sequence_and_stays_lifted(self) -> None:
        target_api, _pose, steps = plan_face_approach_grasp(
            self.planner,
            self.target_arm_base,
            rotation_deg=0.0,
            pre_distance_m=0.05,
            lift_height_m=0.08,
        )
        names = [step.name for step in steps]
        self.assertEqual(target_api, (0.0, 0.42, 0.06))
        self.assertEqual(names[:3], ["pre_grasp_open_and_rotate", "safe_pose", "pre_grasp"])
        self.assertIn("close_gripper", names)
        self.assertEqual(names[-1], "lift")
        self.assertNotIn("home_from_sorting_py", names)

    def test_fixed_place_plan_matches_direct_place_sequence_without_home(self) -> None:
        target_api, steps = plan_fixed_place(
            self.planner,
            (0.0, 0.42, 0.06),
            duration_ms=900,
        )
        self.assertEqual(target_api, (0.0, 0.42, 0.06))
        self.assertEqual([step.name for step in steps], ["place_target", "open_gripper"])
        self.assertNotIn("home_from_sorting_py", [step.name for step in steps])


if __name__ == "__main__":
    unittest.main()
