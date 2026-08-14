"""OpenCV-only pose estimation for the box-centre QR marker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np


@dataclass(frozen=True)
class QrPose:
    payload: str
    position_m: Tuple[float, float, float]
    rotation: np.ndarray
    corners_px: np.ndarray


# IPPE marker axes are X right, Y up, Z out of the printed face.  The project
# qr_link axes are X out of the face, Y right, Z up.
_MARKER_FROM_QR = np.array([
    [0.0, 1.0, 0.0],
    [0.0, 0.0, 1.0],
    [1.0, 0.0, 0.0],
], dtype=np.float64)


def solve_qr_pose(
    corners_px: np.ndarray,
    camera_matrix: np.ndarray,
    distortion: np.ndarray,
    side_m: float,
    payload: str = "",
    distortion_model: str = "pinhole",
) -> QrPose:
    """Solve qr_link in an OpenCV optical camera frame."""

    corners = np.asarray(corners_px, dtype=np.float64).reshape(4, 2)
    matrix = np.asarray(camera_matrix, dtype=np.float64).reshape(3, 3)
    coefficients = np.asarray(distortion, dtype=np.float64).reshape(-1)
    model = str(distortion_model).strip().lower()
    if model == "fisheye":
        # IPPE solvePnP accepts pinhole distortion only. Preserve detection on
        # the raw frame, then rectify just the QR corners for pose solving.
        corners = cv2.fisheye.undistortPoints(
            corners.reshape(-1, 1, 2), matrix, coefficients, P=matrix
        ).reshape(4, 2)
        coefficients = np.zeros(5, dtype=np.float64)
    elif model not in {"pinhole", "plumb_bob"}:
        raise ValueError("unsupported QR distortion model: {}".format(distortion_model))
    half = float(side_m) / 2.0
    object_points = np.array([
        [-half, half, 0.0],
        [half, half, 0.0],
        [half, -half, 0.0],
        [-half, -half, 0.0],
    ], dtype=np.float64)
    solved, rotation_vector, translation_vector = cv2.solvePnP(
        object_points,
        corners,
        matrix,
        coefficients,
        flags=cv2.SOLVEPNP_IPPE_SQUARE,
    )
    if not solved:
        raise ValueError("QR pose could not be solved")
    marker_rotation, _ = cv2.Rodrigues(rotation_vector)
    qr_rotation = marker_rotation @ _MARKER_FROM_QR
    position = tuple(float(value) for value in translation_vector.reshape(3))
    return QrPose(payload, position, qr_rotation, corners)


def detect_qr_pose(
    frame_bgr: np.ndarray,
    camera_matrix: np.ndarray,
    distortion: np.ndarray,
    side_m: float,
    expected_payload: str,
    detector=None,
    allow_unverified_corners: bool = False,
    distortion_model: str = "pinhole",
) -> Optional[QrPose]:
    """Return the expected marker pose, optionally from already-verified corners."""

    qr_detector = detector or cv2.QRCodeDetector()
    payload, corners, _straight = qr_detector.detectAndDecode(frame_bgr)
    if corners is None or (payload != expected_payload and not allow_unverified_corners):
        return None
    return solve_qr_pose(
        corners, camera_matrix, distortion, side_m, payload, distortion_model
    )


def rotation_from_quaternion_xyzw(quaternion) -> np.ndarray:
    x, y, z, w = (float(value) for value in quaternion)
    return np.array([
        [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
        [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
        [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
    ], dtype=np.float64)


def quaternion_xyzw_from_rotation(rotation: np.ndarray) -> Tuple[float, float, float, float]:
    matrix = np.asarray(rotation, dtype=np.float64).reshape(3, 3)
    trace = float(np.trace(matrix))
    if trace > 0.0:
        scale = 2.0 * np.sqrt(trace + 1.0)
        quaternion = np.array([
            (matrix[2, 1] - matrix[1, 2]) / scale,
            (matrix[0, 2] - matrix[2, 0]) / scale,
            (matrix[1, 0] - matrix[0, 1]) / scale,
            0.25 * scale,
        ])
    else:
        index = int(np.argmax(np.diag(matrix)))
        if index == 0:
            scale = 2.0 * np.sqrt(1.0 + matrix[0, 0] - matrix[1, 1] - matrix[2, 2])
            quaternion = np.array([
                0.25 * scale,
                (matrix[0, 1] + matrix[1, 0]) / scale,
                (matrix[0, 2] + matrix[2, 0]) / scale,
                (matrix[2, 1] - matrix[1, 2]) / scale,
            ])
        elif index == 1:
            scale = 2.0 * np.sqrt(1.0 + matrix[1, 1] - matrix[0, 0] - matrix[2, 2])
            quaternion = np.array([
                (matrix[0, 1] + matrix[1, 0]) / scale,
                0.25 * scale,
                (matrix[1, 2] + matrix[2, 1]) / scale,
                (matrix[0, 2] - matrix[2, 0]) / scale,
            ])
        else:
            scale = 2.0 * np.sqrt(1.0 + matrix[2, 2] - matrix[0, 0] - matrix[1, 1])
            quaternion = np.array([
                (matrix[0, 2] + matrix[2, 0]) / scale,
                (matrix[1, 2] + matrix[2, 1]) / scale,
                0.25 * scale,
                (matrix[1, 0] - matrix[0, 1]) / scale,
            ])
    quaternion /= np.linalg.norm(quaternion)
    return tuple(float(value) for value in quaternion)


def compose_pose(
    parent_from_source_rotation: np.ndarray,
    parent_from_source_translation,
    source_pose: QrPose,
) -> QrPose:
    """Transform a QR pose from source coordinates into parent coordinates."""

    rotation = np.asarray(parent_from_source_rotation, dtype=np.float64).reshape(3, 3)
    translation = np.asarray(parent_from_source_translation, dtype=np.float64).reshape(3)
    source_position = np.asarray(source_pose.position_m, dtype=np.float64)
    parent_position = rotation @ source_position + translation
    return QrPose(
        source_pose.payload,
        tuple(float(value) for value in parent_position),
        rotation @ source_pose.rotation,
        source_pose.corners_px,
    )
