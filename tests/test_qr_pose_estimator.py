"""Numerical tests for the OpenCV QR pose convention."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cv.qr_pose.estimator import (
    detect_qr_pose,
    quaternion_xyzw_from_rotation,
    rotation_from_quaternion_xyzw,
    solve_qr_pose,
)


class FakeDetector:
    def __init__(self, payload, corners):
        self._payload = payload
        self._corners = corners

    def detectAndDecode(self, _frame):
        return self._payload, self._corners, None


class QrPoseEstimatorTest(unittest.TestCase):
    def test_ippe_pose_uses_outward_right_up_qr_axes(self):
        side = 0.15
        half = side / 2.0
        camera_matrix = np.array([
            [900.0, 0.0, 640.0],
            [0.0, 900.0, 360.0],
            [0.0, 0.0, 1.0],
        ])
        object_points = np.array([
            [-half, half, 0.0],
            [half, half, 0.0],
            [half, -half, 0.0],
            [-half, -half, 0.0],
        ])
        marker_rotation = cv2.Rodrigues(np.array([0.08, -0.04, 0.02]))[0] @ np.diag([1.0, -1.0, -1.0])
        rotation_vector = cv2.Rodrigues(marker_rotation)[0]
        translation = np.array([0.03, -0.02, 0.85])
        corners, _ = cv2.projectPoints(
            object_points, rotation_vector, translation, camera_matrix, np.zeros(5)
        )

        pose = solve_qr_pose(corners, camera_matrix, np.zeros(5), side)
        expected_qr_rotation = marker_rotation @ np.array([
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
            [1.0, 0.0, 0.0],
        ])
        np.testing.assert_allclose(pose.position_m, translation, atol=1e-6)
        np.testing.assert_allclose(pose.rotation, expected_qr_rotation, atol=1e-6)

    def test_quaternion_rotation_round_trip(self):
        rotation = cv2.Rodrigues(np.array([0.3, -0.2, 0.1]))[0]
        quaternion = quaternion_xyzw_from_rotation(rotation)
        recovered = rotation_from_quaternion_xyzw(quaternion)
        np.testing.assert_allclose(recovered, rotation, atol=1e-12)

    def test_fisheye_corners_are_rectified_before_ippe_pose_solving(self):
        side = 0.15
        half = side / 2.0
        matrix = np.array([
            [420.0, 0.0, 640.0],
            [0.0, 418.0, 360.0],
            [0.0, 0.0, 1.0],
        ])
        distortion = np.array([-0.08, 0.012, -0.002, 0.0005])
        object_points = np.array([
            [-half, half, 0.0],
            [half, half, 0.0],
            [half, -half, 0.0],
            [-half, -half, 0.0],
        ], dtype=np.float64).reshape(-1, 1, 3)
        marker_rotation = cv2.Rodrigues(np.array([0.04, -0.08, 0.02]))[0] @ np.diag([1.0, -1.0, -1.0])
        rotation_vector = cv2.Rodrigues(marker_rotation)[0]
        translation = np.array([0.06, -0.04, 0.90])
        corners, _ = cv2.fisheye.projectPoints(
            object_points, rotation_vector, translation, matrix, distortion
        )

        pose = solve_qr_pose(corners, matrix, distortion, side, distortion_model="fisheye")
        np.testing.assert_allclose(pose.position_m, translation, atol=1e-5)

    def test_unverified_corners_require_matching_payload(self):
        corners = np.array([[[10.0, 10.0], [20.0, 10.0], [20.0, 20.0], [10.0, 20.0]]])
        detector = FakeDetector("", corners)
        matrix = np.array([[100.0, 0.0, 15.0], [0.0, 100.0, 15.0], [0.0, 0.0, 1.0]])
        self.assertIsNone(detect_qr_pose(np.zeros((2, 2, 3)), matrix, np.zeros(5), 0.15, "box", detector))

    def test_verified_corners_can_continue_without_redecode(self):
        corners = np.array([[[10.0, 10.0], [20.0, 10.0], [20.0, 20.0], [10.0, 20.0]]])
        detector = FakeDetector("", corners)
        matrix = np.array([[100.0, 0.0, 15.0], [0.0, 100.0, 15.0], [0.0, 0.0, 1.0]])
        pose = detect_qr_pose(
            np.zeros((2, 2, 3)), matrix, np.zeros(5), 0.15, "box", detector,
            allow_unverified_corners=True,
        )
        self.assertIsNotNone(pose)


if __name__ == "__main__":
    unittest.main()
