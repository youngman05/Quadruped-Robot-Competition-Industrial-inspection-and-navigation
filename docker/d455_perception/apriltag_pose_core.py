"""AprilTag 36h11 pose estimation with no ROS dependency."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

import cv2
import numpy as np


# OpenCV marker axes are +X right, +Y up, +Z out of the printed face.
# Project tag axes are +X out of the face, +Y right, +Z up.
_MARKER_FROM_TAG = np.array(
    [[0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0]],
    dtype=np.float64,
)


@dataclass(frozen=True)
class TagPose:
    tag_id: int
    position_m: Tuple[float, float, float]
    rotation: np.ndarray
    reprojection_error_px: float


def quaternion_xyzw(rotation: np.ndarray) -> Tuple[float, float, float, float]:
    matrix = np.asarray(rotation, dtype=np.float64).reshape(3, 3)
    trace = float(np.trace(matrix))
    if trace > 0.0:
        scale = 2.0 * np.sqrt(trace + 1.0)
        result = np.array([
            (matrix[2, 1] - matrix[1, 2]) / scale,
            (matrix[0, 2] - matrix[2, 0]) / scale,
            (matrix[1, 0] - matrix[0, 1]) / scale,
            0.25 * scale,
        ])
    else:
        index = int(np.argmax(np.diag(matrix)))
        if index == 0:
            scale = 2.0 * np.sqrt(1.0 + matrix[0, 0] - matrix[1, 1] - matrix[2, 2])
            result = np.array([
                0.25 * scale,
                (matrix[0, 1] + matrix[1, 0]) / scale,
                (matrix[0, 2] + matrix[2, 0]) / scale,
                (matrix[2, 1] - matrix[1, 2]) / scale,
            ])
        elif index == 1:
            scale = 2.0 * np.sqrt(1.0 + matrix[1, 1] - matrix[0, 0] - matrix[2, 2])
            result = np.array([
                (matrix[0, 1] + matrix[1, 0]) / scale,
                0.25 * scale,
                (matrix[1, 2] + matrix[2, 1]) / scale,
                (matrix[0, 2] - matrix[2, 0]) / scale,
            ])
        else:
            scale = 2.0 * np.sqrt(1.0 + matrix[2, 2] - matrix[0, 0] - matrix[1, 1])
            result = np.array([
                (matrix[0, 2] + matrix[2, 0]) / scale,
                (matrix[1, 2] + matrix[2, 1]) / scale,
                0.25 * scale,
                (matrix[1, 0] - matrix[0, 1]) / scale,
            ])
    result /= np.linalg.norm(result)
    return tuple(float(value) for value in result)


class AprilTagPoseDetector:
    def __init__(
        self,
        tag_size_m: float,
        expected_tag_ids: Iterable[int] = (0, 1, 2, 3),
        max_reprojection_error_px: float = 3.0,
    ) -> None:
        if tag_size_m <= 0.0:
            raise ValueError("tag_size_m must be positive")
        if max_reprojection_error_px <= 0.0:
            raise ValueError("max_reprojection_error_px must be positive")
        self.tag_size_m = float(tag_size_m)
        self.expected_tag_ids = frozenset(int(tag_id) for tag_id in expected_tag_ids)
        self.max_reprojection_error_px = float(max_reprojection_error_px)
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
        parameters = cv2.aruco.DetectorParameters()
        parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        self._detector = cv2.aruco.ArucoDetector(dictionary, parameters)
        half = self.tag_size_m / 2.0
        self._object_corners = np.array(
            [[-half, half, 0.0], [half, half, 0.0], [half, -half, 0.0], [-half, -half, 0.0]],
            dtype=np.float64,
        )

    def detect(
        self,
        image_bgr: np.ndarray,
        camera_matrix: Sequence[float],
        distortion: Sequence[float],
    ) -> List[TagPose]:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        corners, ids, _rejected = self._detector.detectMarkers(gray)
        if ids is None:
            return []
        camera_matrix = np.asarray(camera_matrix, dtype=np.float64).reshape(3, 3)
        distortion = np.asarray(distortion, dtype=np.float64).reshape(-1)
        detections = []
        for raw_corners, raw_id in zip(corners, ids.reshape(-1)):
            tag_id = int(raw_id)
            if tag_id not in self.expected_tag_ids:
                continue
            image_corners = np.asarray(raw_corners, dtype=np.float64).reshape(4, 2)
            success, rotation_vector, translation = cv2.solvePnP(
                self._object_corners,
                image_corners,
                camera_matrix,
                distortion,
                flags=cv2.SOLVEPNP_IPPE_SQUARE,
            )
            if not success:
                continue
            rotation_vector = np.asarray(rotation_vector, dtype=np.float64).reshape(3)
            translation = np.asarray(translation, dtype=np.float64).reshape(3)
            if (
                not np.all(np.isfinite(rotation_vector))
                or not np.all(np.isfinite(translation))
                or translation[2] <= 0.0
            ):
                continue
            projected, _ = cv2.projectPoints(
                self._object_corners,
                rotation_vector,
                translation,
                camera_matrix,
                distortion,
            )
            residual = projected.reshape(4, 2) - image_corners
            error = float(np.sqrt(np.mean(np.sum(residual * residual, axis=1))))
            if error > self.max_reprojection_error_px:
                continue
            marker_rotation, _ = cv2.Rodrigues(rotation_vector)
            detections.append(
                TagPose(
                    tag_id,
                    tuple(float(value) for value in translation),
                    marker_rotation @ _MARKER_FROM_TAG,
                    error,
                )
            )
        return sorted(detections, key=lambda pose: pose.tag_id)


def transform_pose(pose: TagPose, target_from_source) -> TagPose:
    position = target_from_source.rotation @ np.asarray(pose.position_m) + target_from_source.translation
    return TagPose(
        pose.tag_id,
        tuple(float(value) for value in position),
        target_from_source.rotation @ pose.rotation,
        pose.reprojection_error_px,
    )
