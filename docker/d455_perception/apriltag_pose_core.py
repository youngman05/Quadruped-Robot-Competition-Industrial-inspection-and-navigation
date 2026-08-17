"""AprilTag 36h11 pose estimation with no ROS dependency."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

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


@dataclass(frozen=True)
class PoseCandidate:
    rotation: np.ndarray
    translation: np.ndarray
    reprojection_error_px: float


def rotation_distance_rad(left: np.ndarray, right: np.ndarray) -> float:
    relative = np.asarray(left, dtype=np.float64).reshape(3, 3).T @ np.asarray(
        right, dtype=np.float64
    ).reshape(3, 3)
    cosine = min(1.0, max(-1.0, (float(np.trace(relative)) - 1.0) / 2.0))
    return float(np.arccos(cosine))


def select_pose_candidate(
    candidates: Sequence[PoseCandidate],
    previous_rotation: Optional[np.ndarray],
) -> PoseCandidate:
    if not candidates:
        raise ValueError("at least one pose candidate is required")
    if previous_rotation is None:
        return min(candidates, key=lambda item: item.reprojection_error_px)
    return min(
        candidates,
        key=lambda item: (
            rotation_distance_rad(previous_rotation, item.rotation),
            item.reprojection_error_px,
        ),
    )


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
        pose_history_max_missed_frames: int = 5,
    ) -> None:
        if tag_size_m <= 0.0:
            raise ValueError("tag_size_m must be positive")
        if max_reprojection_error_px <= 0.0:
            raise ValueError("max_reprojection_error_px must be positive")
        if pose_history_max_missed_frames < 0:
            raise ValueError("pose_history_max_missed_frames must be non-negative")
        self.tag_size_m = float(tag_size_m)
        self.expected_tag_ids = frozenset(int(tag_id) for tag_id in expected_tag_ids)
        self.max_reprojection_error_px = float(max_reprojection_error_px)
        self.pose_history_max_missed_frames = int(pose_history_max_missed_frames)
        self._previous_rotations = {}
        self._missed_frames = {}
        self._dictionary = cv2.aruco.getPredefinedDictionary(
            cv2.aruco.DICT_APRILTAG_36h11
        )
        if hasattr(cv2.aruco, "DetectorParameters"):
            parameters = cv2.aruco.DetectorParameters()
        else:
            parameters = cv2.aruco.DetectorParameters_create()
        parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        self._parameters = parameters
        self._detector = (
            cv2.aruco.ArucoDetector(self._dictionary, parameters)
            if hasattr(cv2.aruco, "ArucoDetector")
            else None
        )
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
        if self._detector is not None:
            corners, ids, _rejected = self._detector.detectMarkers(gray)
        else:
            corners, ids, _rejected = cv2.aruco.detectMarkers(
                gray,
                self._dictionary,
                parameters=self._parameters,
            )
        if ids is None:
            self._update_missed_histories(())
            return []
        camera_matrix = np.asarray(camera_matrix, dtype=np.float64).reshape(3, 3)
        distortion = np.asarray(distortion, dtype=np.float64).reshape(-1)
        detections = []
        seen_ids = set()
        for raw_corners, raw_id in zip(corners, ids.reshape(-1)):
            tag_id = int(raw_id)
            if tag_id not in self.expected_tag_ids:
                continue
            image_corners = np.asarray(raw_corners, dtype=np.float64).reshape(4, 2)
            # OpenCV 4.2 Python binding has a known bug: when reprojectionError
            # is omitted, it is allocated as CV_8U and solvePnPGeneric raises.
            # Explicitly provide a float64 output array to keep the detector alive.
            reprojection_error = np.empty((1,), dtype=np.float64)
            result = cv2.solvePnPGeneric(
                self._object_corners,
                image_corners,
                camera_matrix,
                distortion,
                flags=cv2.SOLVEPNP_IPPE_SQUARE,
                reprojectionError=reprojection_error,
            )
            if not result[0]:
                continue
            candidates = []
            for rotation_vector, translation in zip(result[1], result[2]):
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
                candidates.append(
                    PoseCandidate(
                        marker_rotation @ _MARKER_FROM_TAG,
                        translation,
                        error,
                    )
                )
            if not candidates:
                continue
            selected = select_pose_candidate(
                candidates,
                self._previous_rotations.get(tag_id),
            )
            seen_ids.add(tag_id)
            self._previous_rotations[tag_id] = selected.rotation
            self._missed_frames[tag_id] = 0
            detections.append(
                TagPose(
                    tag_id,
                    tuple(float(value) for value in selected.translation),
                    selected.rotation,
                    selected.reprojection_error_px,
                )
            )
        self._update_missed_histories(seen_ids)
        return sorted(detections, key=lambda pose: pose.tag_id)

    def _update_missed_histories(self, seen_ids: Iterable[int]) -> None:
        seen = set(int(tag_id) for tag_id in seen_ids)
        for tag_id in list(self._previous_rotations):
            if tag_id in seen:
                self._missed_frames[tag_id] = 0
                continue
            missed = self._missed_frames.get(tag_id, 0) + 1
            if missed > self.pose_history_max_missed_frames:
                self._previous_rotations.pop(tag_id, None)
                self._missed_frames.pop(tag_id, None)
            else:
                self._missed_frames[tag_id] = missed


def transform_pose(pose: TagPose, target_from_source) -> TagPose:
    position = target_from_source.rotation @ np.asarray(pose.position_m) + target_from_source.translation
    return TagPose(
        pose.tag_id,
        tuple(float(value) for value in position),
        target_from_source.rotation @ pose.rotation,
        pose.reprojection_error_px,
    )
