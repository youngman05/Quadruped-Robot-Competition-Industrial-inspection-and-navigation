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


def task_document(*, duplicate_i2=False, grasp_x=0.42):
    targets = {
        "0": [0.10, 0.00, 0.00],
        "1": [0.20, 0.00, 0.10],
        "2": [0.30, 0.01, 0.20],
        "3": [0.40, 0.02, 0.30],
    }
    if duplicate_i2:
        targets["3"] = list(targets["2"])
    return {
        "task_manager_node": {
            "ros__parameters": {
                "pick_red_tag_ids": [0, 1],
                "pick_i2_targets_json": json.dumps(targets),
                "grasp_target_arm_base": [grasp_x, 0.0, 0.20],
                "place_target_distance_m": 0.45,
            }
        }
    }


def arm_document():
    return {
        "arm_motion_node": {
            "ros__parameters": {
                "enable_motion": True,
                "transform_calibrated": True,
                "grasp_reference_configured": True,
                "place_target_configured": True,
                "require_tf_in_preflight": True,
                "grasp_reference_arm_base": [0.42, 0.0],
                "grasp_reference_xy_tolerance_m": 0.02,
                "grasp_z_min_m": 0.15,
                "grasp_z_max_m": 0.25,
                "place_reference_grasp_arm": [0.0, 0.42, 0.20],
            }
        }
    }


class PickPlaceCalibrationGateTests(unittest.TestCase):
    def _write(self, directory, name, document):
        path = Path(directory) / name
        path.write_text(yaml.safe_dump(document), encoding="utf-8")
        return path

    def test_repository_defaults_are_rejected(self):
        with self.assertRaises(CalibrationGateError):
            validate_calibration(
                ROOT / "configs" / "manipulation" / "pick_place.yaml",
                ROOT / "arm_new" / "config" / "arm_motion_params.yaml",
                "[0,1,2,3]",
                "0.100",
            )

    def test_complete_distinct_calibration_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            task_path = self._write(directory, "task.yaml", task_document())
            arm_path = self._write(directory, "arm.yaml", arm_document())
            result = validate_calibration(
                task_path,
                arm_path,
                "[0,1,2,3]",
                "0.100",
            )
        self.assertEqual(result["i2_target_count"], 4)
        self.assertEqual(result["red_tag_ids"], [0, 1])

    def test_duplicate_i2_targets_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            task_path = self._write(
                directory, "task.yaml", task_document(duplicate_i2=True)
            )
            arm_path = self._write(directory, "arm.yaml", arm_document())
            with self.assertRaisesRegex(CalibrationGateError, "duplicated"):
                validate_calibration(
                    task_path,
                    arm_path,
                    "[0,1,2,3]",
                    "0.100",
                )

    def test_task_and_arm_grasp_references_must_agree(self):
        with tempfile.TemporaryDirectory() as directory:
            task_path = self._write(
                directory, "task.yaml", task_document(grasp_x=0.50)
            )
            arm_path = self._write(directory, "arm.yaml", arm_document())
            with self.assertRaisesRegex(CalibrationGateError, "XY reference"):
                validate_calibration(
                    task_path,
                    arm_path,
                    "[0,1,2,3]",
                    "0.100",
                )


if __name__ == "__main__":
    unittest.main()
