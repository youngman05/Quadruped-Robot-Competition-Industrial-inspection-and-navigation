"""Unit tests for Docker-independent D455 depth geometry."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "docker" / "d455_perception" / "d455_yolo_3d_core.py"
SPEC = importlib.util.spec_from_file_location("d455_yolo_3d_core", CORE_PATH)
CORE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = CORE
SPEC.loader.exec_module(CORE)


class DepthGeometryTest(unittest.TestCase):
    def test_constant_depth_mask(self) -> None:
        depth = np.full((20, 30), 1250, dtype=np.uint16)
        mask = np.zeros_like(depth, dtype=bool)
        mask[4:16, 5:25] = True

        estimate = CORE.estimate_mask_depth(
            depth,
            mask,
            erosion_iterations=1,
            min_valid_pixels=10,
        )

        self.assertTrue(estimate.valid)
        self.assertAlmostEqual(estimate.depth_m, 1.25)
        self.assertEqual(estimate.center_px, (14, 9))
        self.assertEqual(estimate.mask_area_px, 240)
        self.assertAlmostEqual(estimate.valid_ratio, 1.0)

    def test_invalid_and_outlier_depths_are_rejected(self) -> None:
        depth = np.full((20, 20), 1000, dtype=np.uint16)
        mask = np.ones_like(depth, dtype=bool)
        depth.flat[:40] = 0
        depth.flat[40:60] = 5000
        depth.flat[60:80] = 3000

        estimate = CORE.estimate_mask_depth(
            depth,
            mask,
            erosion_iterations=0,
            trim_fraction=0.1,
            min_valid_pixels=20,
        )

        self.assertTrue(estimate.valid)
        self.assertAlmostEqual(estimate.depth_m, 1.0)
        self.assertEqual(estimate.valid_pixels, 340)
        self.assertAlmostEqual(estimate.valid_ratio, 0.85)

    def test_insufficient_depth_is_marked_invalid(self) -> None:
        depth = np.zeros((10, 10), dtype=np.uint16)
        mask = np.ones_like(depth, dtype=bool)
        depth[4, 4] = 800

        estimate = CORE.estimate_mask_depth(
            depth,
            mask,
            erosion_iterations=0,
            min_valid_pixels=2,
        )

        self.assertFalse(estimate.valid)
        self.assertIsNone(estimate.depth_m)
        self.assertEqual(estimate.valid_pixels, 1)

    def test_deprojection_at_principal_point(self) -> None:
        intrinsics = CORE.CameraIntrinsics(600.0, 600.0, 320.0, 240.0)
        point = CORE.deproject_pixel((320, 240), 2.0, intrinsics)
        self.assertEqual(point, (0.0, 0.0, 2.0))

    def test_deprojection_off_center(self) -> None:
        intrinsics = CORE.CameraIntrinsics(600.0, 600.0, 320.0, 240.0)
        x, y, z = CORE.deproject_pixel((380, 210), 2.0, intrinsics)
        self.assertAlmostEqual(x, 0.2)
        self.assertAlmostEqual(y, -0.1)
        self.assertEqual(z, 2.0)

    def test_mismatched_shapes_raise(self) -> None:
        with self.assertRaises(ValueError):
            CORE.estimate_mask_depth(
                np.zeros((10, 10), dtype=np.uint16),
                np.zeros((8, 10), dtype=bool),
            )


    def test_raw_depth_identity_projection(self) -> None:
        depth = np.full((8, 10), 1000, dtype=np.uint16)
        mask = np.zeros((8, 10), dtype=bool)
        mask[2:6, 3:7] = True
        intrinsics = CORE.CameraIntrinsics(100.0, 100.0, 4.5, 3.5)

        estimate = CORE.estimate_mask_3d_from_raw_depth(
            depth,
            mask,
            intrinsics,
            intrinsics,
            CORE.RigidTransform.identity(),
            erosion_iterations=0,
            min_valid_pixels=4,
        )

        self.assertTrue(estimate.valid)
        self.assertEqual(estimate.center_px, (4, 3))
        self.assertAlmostEqual(estimate.depth_m, 1.0)
        self.assertAlmostEqual(estimate.position_m[0], 0.0)
        self.assertAlmostEqual(estimate.position_m[1], 0.0)
        self.assertEqual(estimate.valid_pixels, 16)

    def test_raw_depth_projection_applies_extrinsics(self) -> None:
        depth = np.full((5, 5), 1000, dtype=np.uint16)
        mask = np.zeros((5, 5), dtype=bool)
        # +0.1 m in color X shifts the principal depth pixel one pixel right.
        mask[2, 3] = True
        intrinsics = CORE.CameraIntrinsics(10.0, 10.0, 2.0, 2.0)
        transform = CORE.RigidTransform(np.eye(3), np.array([0.1, 0.0, 0.0]))

        estimate = CORE.estimate_mask_3d_from_raw_depth(
            depth,
            mask,
            intrinsics,
            intrinsics,
            transform,
            erosion_iterations=0,
            min_valid_pixels=1,
        )

        self.assertTrue(estimate.valid)
        self.assertEqual(estimate.center_px, (3, 2))
        self.assertAlmostEqual(estimate.position_m[0], 0.1)
        self.assertAlmostEqual(estimate.position_m[2], 1.0)

    def test_raw_depth_projection_marks_empty_overlap_invalid(self) -> None:
        depth = np.full((5, 5), 1000, dtype=np.uint16)
        mask = np.zeros((5, 5), dtype=bool)
        mask[0, 0] = True
        intrinsics = CORE.CameraIntrinsics(10.0, 10.0, 2.0, 2.0)

        estimate = CORE.estimate_mask_3d_from_raw_depth(
            depth,
            mask,
            intrinsics,
            intrinsics,
            CORE.RigidTransform.identity(),
            erosion_iterations=0,
            min_valid_pixels=2,
        )

        self.assertFalse(estimate.valid)
        self.assertIsNone(estimate.position_m)
        self.assertEqual(estimate.valid_pixels, 1)


if __name__ == "__main__":
    unittest.main()
