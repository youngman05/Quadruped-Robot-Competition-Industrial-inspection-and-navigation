"""Tests for AprilTag IPPE ambiguity resolution and pose helpers."""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "docker" / "d455_perception" / "apriltag_pose_core.py"
SPEC = importlib.util.spec_from_file_location("apriltag_pose_core", CORE_PATH)
CORE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = CORE
SPEC.loader.exec_module(CORE)


def rotation(y_degrees: float) -> np.ndarray:
    vector = np.array([0.0, np.deg2rad(y_degrees), 0.0], dtype=np.float64)
    return cv2.Rodrigues(vector)[0]


class PoseCandidateSelectionTest(unittest.TestCase):
    def candidate(self, y_degrees: float, error: float) -> CORE.PoseCandidate:
        return CORE.PoseCandidate(
            rotation(y_degrees),
            np.array([0.0, 0.0, 1.0], dtype=np.float64),
            error,
        )

    def test_first_frame_uses_lowest_reprojection_error(self) -> None:
        lower_error = self.candidate(25.0, 0.1)
        higher_error = self.candidate(-25.0, 0.2)
        selected = CORE.select_pose_candidate([higher_error, lower_error], None)
        self.assertIs(selected, lower_error)

    def test_history_prevents_planar_solution_flip(self) -> None:
        previous = rotation(24.0)
        continuous = self.candidate(25.0, 0.2)
        flipped = self.candidate(-25.0, 0.1)
        selected = CORE.select_pose_candidate([flipped, continuous], previous)
        self.assertIs(selected, continuous)

    def test_rotation_distance_is_sign_independent_and_symmetric(self) -> None:
        left = rotation(-20.0)
        right = rotation(30.0)
        expected = np.deg2rad(50.0)
        self.assertAlmostEqual(CORE.rotation_distance_rad(left, right), expected)
        self.assertAlmostEqual(CORE.rotation_distance_rad(right, left), expected)

    def test_missed_frames_expire_pose_history(self) -> None:
        detector = CORE.AprilTagPoseDetector(
            0.072,
            pose_history_max_missed_frames=2,
        )
        detector._previous_rotations[0] = rotation(10.0)
        detector._missed_frames[0] = 0
        detector._update_missed_histories(())
        detector._update_missed_histories(())
        self.assertIn(0, detector._previous_rotations)
        detector._update_missed_histories(())
        self.assertNotIn(0, detector._previous_rotations)

    def test_opencv_42_uses_legacy_aruco_api(self) -> None:
        calls = []

        class LegacyAruco:
            DICT_APRILTAG_36h11 = 20
            CORNER_REFINE_SUBPIX = 1

            @staticmethod
            def getPredefinedDictionary(dictionary_id):
                calls.append(("dictionary", dictionary_id))
                return "april-tag-dictionary"

            @staticmethod
            def DetectorParameters_create():
                calls.append(("parameters",))
                return types.SimpleNamespace(cornerRefinementMethod=None)

            @staticmethod
            def detectMarkers(image, dictionary, parameters=None):
                calls.append(("detect", dictionary, parameters.cornerRefinementMethod))
                return [], None, []

        with mock.patch.object(CORE.cv2, "aruco", LegacyAruco):
            detector = CORE.AprilTagPoseDetector(0.1, [0, 1])
            detections = detector.detect(
                np.zeros((8, 8, 3), dtype=np.uint8),
                np.eye(3),
                np.zeros(5),
            )

        self.assertEqual(detections, [])
        self.assertIsNone(detector._detector)
        self.assertEqual(calls[0], ("dictionary", 20))
        self.assertEqual(calls[1], ("parameters",))
        self.assertEqual(calls[2][:2], ("detect", "april-tag-dictionary"))
        self.assertEqual(calls[2][2], 1)

    def test_quaternion_is_unit_length(self) -> None:
        quaternion = CORE.quaternion_xyzw(rotation(42.0))
        self.assertAlmostEqual(sum(value * value for value in quaternion), 1.0)


if __name__ == "__main__":
    unittest.main()
