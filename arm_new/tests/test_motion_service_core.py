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
        self.target_arm_base = (0.42, 0.0, 0.15)

    def test_arm_base_to_api_axes_match_documented_convention(self) -> None:
        self.assertEqual(arm_base_to_api((0.42, 0.10, 0.06)), (-0.10, 0.42, 0.06))

    def test_grasp_target_requires_i1_xy_and_calibrated_z_range(self) -> None:
        self.assertEqual(
            validate_grasp_target(self.target_arm_base, (0.42, 0.0), 0.02, 0.15, 0.25),
            self.target_arm_base,
        )
        with self.assertRaises(MotionServiceValidationError):
            validate_grasp_target((0.45, 0.0, 0.15), (0.42, 0.0), 0.02, 0.15, 0.25)
        with self.assertRaises(MotionServiceValidationError):
            validate_grasp_target((0.42, 0.0, 0.26), (0.42, 0.0), 0.02, 0.15, 0.25)

    def test_grasp_plan_matches_face_approach_sequence_and_stays_lifted(self) -> None:
        target_api, _pose, steps = plan_face_approach_grasp(
            self.planner,
            self.target_arm_base,
            rotation_deg=0.0,
            pre_distance_m=0.05,
            lift_height_m=0.08,
        )
        names = [step.name for step in steps]
        self.assertEqual(target_api, (0.0, 0.42, 0.15))
        self.assertEqual(
            names[:4],
            [
                "pre_grasp_open_and_rotate",
                "safe_pose",
                "open_gripper_after_safe_pose",
                "pre_grasp",
            ],
        )
        self.assertEqual(dict(steps[0].servos)[1], 900)
        self.assertEqual(dict(steps[2].servos), {1: 900})
        self.assertIn("close_gripper", names)
        close_step = next(step for step in steps if step.name == "close_gripper")
        self.assertEqual(dict(close_step.servos)[1], 100)
        self.assertEqual(names[-1], "lift")
        self.assertNotIn("home_from_sorting_py", names)

    def test_fixed_place_returns_to_lift_then_descends_with_wrist_fixed(self) -> None:
        reference_api, steps = plan_fixed_place(
            self.planner,
            (0.0, 0.42, 0.15),
            grasp_lift_height_m=0.08,
            descent_m=0.02,
            pose1_duration_ms=900,
            descent_duration_ms=700,
        )
        self.assertEqual(reference_api, (0.0, 0.42, 0.15))
        self.assertEqual(
            [step.name for step in steps],
            ["place_pose_1", "place_descend_2cm", "open_gripper"],
        )
        self.assertEqual(dict(steps[-1].servos), {1: self.planner.config.open_gripper})
        self.assertEqual(steps[0].coordinate[:2], (0.0, 0.42))
        self.assertEqual(steps[1].coordinate[:2], (0.0, 0.42))
        self.assertAlmostEqual(steps[0].coordinate[2], 0.23)
        self.assertAlmostEqual(steps[1].coordinate[2], 0.21)
        self.assertEqual(dict(steps[0].servos)[3], dict(steps[1].servos)[3])
        self.assertEqual(steps[0].ik_angles["theta3"], steps[1].ik_angles["theta3"])

    def test_place_reference_is_serializable_as_a_point_payload(self) -> None:
        reference_api, _steps = plan_fixed_place(
            self.planner,
            (0.0, 0.42, 0.15),
            grasp_lift_height_m=0.08,
            descent_m=0.02,
            pose1_duration_ms=900,
            descent_duration_ms=700,
        )
        self.assertEqual(
            {"x": reference_api[0], "y": reference_api[1], "z": reference_api[2]},
            {"x": 0.0, "y": 0.42, "z": 0.15},
        )


if __name__ == "__main__":
    unittest.main()
