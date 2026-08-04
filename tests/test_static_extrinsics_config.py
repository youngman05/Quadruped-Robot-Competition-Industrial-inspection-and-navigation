"""Regression tests for the project-owned static camera extrinsic."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs" / "transforms" / "static_extrinsics.yaml"
SCHEMA_PATH = ROOT / "configs" / "transforms" / "static_extrinsics.schema.json"


def rotation_from_xyzw(quaternion: list[float]) -> np.ndarray:
    x, y, z, w = quaternion
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


class StaticExtrinsicsConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

    def test_schema_is_valid_json(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["$id"], "https://quadruped.local/schemas/static-extrinsics-v1.json")

    def test_camera_transform_is_the_single_published_static_transform(self) -> None:
        transforms = self.config["static_transforms"]
        self.assertEqual(len(transforms), 1)
        transform = transforms[0]
        self.assertTrue(transform["publish"])
        self.assertEqual(transform["parent_frame"], "base_link")
        self.assertEqual(transform["child_frame"], "camera_link")
        self.assertEqual(transform["status"], "calibrated")

    def test_calibrated_camera_transform_is_a_proper_rigid_transform(self) -> None:
        transform = self.config["static_transforms"][0]
        rotation = rotation_from_xyzw(transform["rotation_xyzw"])
        translation = np.array(transform["translation_m"])

        np.testing.assert_allclose(rotation @ rotation.T, np.eye(3), atol=1e-6)
        self.assertAlmostEqual(float(np.linalg.det(rotation)), 1.0, places=6)
        np.testing.assert_allclose(translation, [0.231724440, 0.077561412, 0.503275873], atol=1e-9)

    def test_calibration_template_uses_base_link_truth(self) -> None:
        template = yaml.safe_load(
            (ROOT / "configs" / "calibration" / "yolo_xyz_test_points.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(template["convention"]["truth_frame"], "base_link")
        self.assertEqual(template["test_points"], [])


if __name__ == "__main__":
    unittest.main()
