import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pick_place_calibration_gate import (  # noqa: E402
    CalibrationGateError,
    validate_calibration,
)


def task_document(
    *,
    enable_i2=False,
    enable_place_vision=False,
    duplicate_i2=False,
    grasp_x=0.42,
    place_distance=0.0,
    service_timeout=30.0,
):
    targets = {}
    tag_ids = [0, 1]
    tag_size_m = 0.0
    if enable_i2:
        targets = {
            "0": [0.10, 0.00, 0.00],
            "1": [0.20, 0.01, 0.10],
        }
        if duplicate_i2:
            targets["1"] = list(targets["0"])
        tag_size_m = 0.1
    return {
        "task_manager_node": {
            "ros__parameters": {
                "manipulation_preset": "competition_v1",
                "manipulation_model_id": "gauge-ad-3ed76de7-v1",
                "manipulation_class_schema": "competition-ad-yellow-red-green-v1",
                "abnormal_zone_fallback_order": ["A", "B", "C", "D"],
                "enable_pick_i2_alignment": enable_i2,
                "enable_place_vision_alignment": enable_place_vision,
                "pick_red_tag_ids": tag_ids,
                "pick_i2_targets_json": json.dumps(targets),
                "apriltag_tag_size_m": tag_size_m,
                "grasp_target_arm_base": [grasp_x, 0.0, 0.20],
                "place_target_distance_m": place_distance,
                "placement_color_width_px": 640,
                "placement_color_height_px": 360,
                "placement_camera_pitch_deg": 30.0,
                "placement_box_width_m": 0.50,
                "arm_service_timeout_sec": service_timeout,
            }
        }
    }


def arm_document(*, enable_motion=False, max_sequence_sec=20.0):
    return {
        "arm_motion_node": {
            "ros__parameters": {
                "arm_preset": "competition_v1",
                "enable_motion": enable_motion,
                "transform_calibrated": False,
                "require_tf_in_preflight": False,
                "grasp_reference_configured": True,
                "place_target_configured": True,
                "grasp_reference_arm_base": [0.42, 0.0],
                "grasp_reference_xy_tolerance_m": 0.02,
                "grasp_z_min_m": 0.15,
                "grasp_z_max_m": 0.25,
                "place_reference_grasp_arm": [0.0, 0.42, 0.20],
                "grasp_open_gripper_pulse": 400,
                "gripper_open_pulse": 400,
                "gripper_close_pulse": 256,
                "grasp_pre_distance": 0.05,
                "grasp_lift_height": 0.08,
                "grasp_duration_scale": 2.0,
                "grasp_include_home": False,
                "grasp_approach_steps": 8,
                "grasp_approach_step_duration_ms": 180,
                "place_pose_1_duration_ms": 1200,
                "place_descent_m": 0.02,
                "place_descent_duration_ms": 800,
                "place_duration_scale": 1.0,
                "place_include_home": False,
                "max_arm_sequence_sec": max_sequence_sec,
            }
        }
    }


class PickPlaceCalibrationGateTests(unittest.TestCase):
    def _write(self, directory, name, document):
        path = Path(directory) / name
        path.write_text(yaml.safe_dump(document), encoding="utf-8")
        return path

    def _validate(self, task, arm):
        with tempfile.TemporaryDirectory() as directory:
            task_path = self._write(directory, "task.yaml", task)
            arm_path = self._write(directory, "arm.yaml", arm)
            return validate_calibration(task_path, arm_path)

    def test_repository_defaults_are_rejected(self):
        with self.assertRaises(CalibrationGateError):
            validate_calibration(
                ROOT / "configs" / "manipulation" / "pick_place.yaml",
                ROOT / "arm_new" / "config" / "arm_motion_params.yaml",
            )

    def test_fixed_competition_preset_passes_without_visual_alignment(self):
        result = self._validate(task_document(), arm_document())
        self.assertEqual(result["arm_preset"], "competition_v1")
        self.assertFalse(result["enable_pick_i2_alignment"])
        self.assertFalse(result["enable_place_vision_alignment"])
        self.assertEqual(result["tag_ids"], [0, 1])
        self.assertEqual(result["i2_target_count"], 0)
        self.assertEqual(result["place_target_distance_m"], 0.0)
        self.assertEqual(result["max_arm_sequence_sec"], 20.0)

    def test_i2_alignment_is_optional_but_validated_when_enabled(self):
        result = self._validate(
            task_document(enable_i2=True),
            arm_document(),
        )
        self.assertTrue(result["enable_pick_i2_alignment"])
        self.assertEqual(result["tag_ids"], [0, 1])
        self.assertEqual(result["i2_target_count"], 2)
        self.assertEqual(result["tag_size_m"], 0.1)

        duplicated = self._validate(
            task_document(enable_i2=True, duplicate_i2=True),
            arm_document(),
        )
        self.assertEqual(duplicated["i2_target_count"], 2)

    def test_disabled_i2_keeps_two_ids_but_rejects_active_targets(self):
        task = task_document()
        params = task["task_manager_node"]["ros__parameters"]
        params["pick_i2_targets_json"] = json.dumps({"0": [0.1, 0.0, 0.0]})
        with self.assertRaisesRegex(CalibrationGateError, "disabled I2"):
            self._validate(task, arm_document())

    def test_exactly_two_distinct_pickup_tag_ids_are_required(self):
        for tag_ids in ([], [0], [0, 0], [0, 1, 2]):
            task = task_document()
            task["task_manager_node"]["ros__parameters"]["pick_red_tag_ids"] = tag_ids
            with self.subTest(tag_ids=tag_ids):
                with self.assertRaisesRegex(CalibrationGateError, "exactly two"):
                    self._validate(task, arm_document())

    def test_fallback_order_must_cover_abcd_once(self):
        task = task_document()
        task["task_manager_node"]["ros__parameters"][
            "abnormal_zone_fallback_order"
        ] = ["A", "A", "B", "C"]
        with self.assertRaisesRegex(CalibrationGateError, "permutation"):
            self._validate(task, arm_document())

    def test_place_vision_alignment_is_optional_but_requires_distance(self):
        result = self._validate(
            task_document(enable_place_vision=True, place_distance=0.45),
            arm_document(),
        )
        self.assertTrue(result["enable_place_vision_alignment"])
        self.assertEqual(result["place_target_distance_m"], 0.45)

        with self.assertRaisesRegex(CalibrationGateError, "must be positive"):
            self._validate(
                task_document(enable_place_vision=True),
                arm_document(),
            )

    def test_motion_authorization_is_not_stored_in_the_preset(self):
        with self.assertRaisesRegex(CalibrationGateError, "authorization is separate"):
            self._validate(task_document(), arm_document(enable_motion=True))

    def test_service_timeout_covers_the_maximum_arm_sequence(self):
        with self.assertRaisesRegex(
            CalibrationGateError,
            "arm_service_timeout_sec must be >= max_arm_sequence_sec",
        ):
            self._validate(
                task_document(service_timeout=19.9),
                arm_document(max_sequence_sec=20.0),
            )

    def test_task_and_arm_grasp_references_must_agree(self):
        with self.assertRaisesRegex(CalibrationGateError, "XY preset tolerance"):
            self._validate(task_document(grasp_x=0.50), arm_document())


if __name__ == "__main__":
    unittest.main()
