"""Pure RGB-D geometry helpers for the Docker D455 YOLO node.

This module deliberately has no ROS dependency so its depth filtering and
deprojection behavior can be tested in the WSL ``gauge_env`` environment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np


@dataclass(frozen=True)
class CameraIntrinsics:
    """Pinhole intrinsics for the color image receiving aligned depth."""

    fx: float
    fy: float
    cx: float
    cy: float

    def __post_init__(self) -> None:
        if self.fx <= 0 or self.fy <= 0:
            raise ValueError("fx and fy must be positive")


@dataclass(frozen=True)
class DepthEstimate:
    """Robust depth estimate for one segmentation mask."""

    depth_m: Optional[float]
    center_px: Tuple[int, int]
    mask_area_px: int
    valid_pixels: int
    valid_ratio: float

    @property
    def valid(self) -> bool:
        return self.depth_m is not None


def estimate_mask_depth(
    depth_mm: np.ndarray,
    mask: np.ndarray,
    *,
    min_depth_m: float = 0.2,
    max_depth_m: float = 4.0,
    trim_fraction: float = 0.1,
    erosion_iterations: int = 2,
    min_valid_pixels: int = 20,
) -> DepthEstimate:
    """Estimate target depth from valid pixels inside an instance mask.

    The D455 provides depth in millimeters. Erosion and percentile trimming
    reduce contamination from background pixels along object boundaries.
    """

    if depth_mm.ndim != 2 or mask.ndim != 2:
        raise ValueError("depth and mask must both be two-dimensional")
    if depth_mm.shape != mask.shape:
        raise ValueError("aligned depth and mask must have identical shapes")
    if min_depth_m <= 0 or max_depth_m <= min_depth_m:
        raise ValueError("invalid depth range")
    if not 0.0 <= trim_fraction < 0.5:
        raise ValueError("trim_fraction must be in [0, 0.5)")
    if erosion_iterations < 0 or min_valid_pixels < 1:
        raise ValueError("erosion_iterations and min_valid_pixels are invalid")

    binary_mask = mask.astype(bool).astype(np.uint8)
    original_area = int(binary_mask.sum())
    if original_area == 0:
        return DepthEstimate(None, (0, 0), 0, 0, 0.0)

    if erosion_iterations:
        kernel = np.ones((3, 3), dtype=np.uint8)
        sample_mask = cv2.erode(
            binary_mask,
            kernel,
            iterations=erosion_iterations,
        ).astype(bool)
        # Very small masks can disappear after erosion; sample the original
        # mask rather than turning a valid small detection into an empty one.
        if not sample_mask.any():
            sample_mask = binary_mask.astype(bool)
    else:
        sample_mask = binary_mask.astype(bool)

    ys, xs = np.nonzero(sample_mask)
    center_px = (int(np.median(xs)), int(np.median(ys)))
    values = depth_mm[sample_mask].astype(np.float64)
    min_mm = min_depth_m * 1000.0
    max_mm = max_depth_m * 1000.0
    values = values[(values >= min_mm) & (values <= max_mm)]
    valid_pixels = int(values.size)
    valid_ratio = valid_pixels / int(sample_mask.sum())

    if valid_pixels < min_valid_pixels:
        return DepthEstimate(
            None,
            center_px,
            original_area,
            valid_pixels,
            float(valid_ratio),
        )

    values.sort()
    trim_count = int(valid_pixels * trim_fraction)
    if trim_count and valid_pixels - 2 * trim_count >= min_valid_pixels:
        values = values[trim_count:-trim_count]

    return DepthEstimate(
        float(np.median(values) / 1000.0),
        center_px,
        original_area,
        valid_pixels,
        float(valid_ratio),
    )


def deproject_pixel(
    center_px: Tuple[int, int],
    depth_m: float,
    intrinsics: CameraIntrinsics,
) -> Tuple[float, float, float]:
    """Deproject a color pixel into ``camera_color_optical_frame``."""

    if depth_m <= 0:
        raise ValueError("depth_m must be positive")
    u, v = center_px
    x = (float(u) - intrinsics.cx) * depth_m / intrinsics.fx
    y = (float(v) - intrinsics.cy) * depth_m / intrinsics.fy
    return x, y, depth_m


@dataclass(frozen=True)
class RigidTransform:
    """Rigid transform using ``p_target = R @ p_source + t``."""

    rotation: np.ndarray
    translation: np.ndarray

    def __post_init__(self) -> None:
        rotation = np.asarray(self.rotation, dtype=np.float64)
        translation = np.asarray(self.translation, dtype=np.float64)
        if rotation.shape != (3, 3):
            raise ValueError("rotation must have shape (3, 3)")
        if translation.shape != (3,):
            raise ValueError("translation must have shape (3,)")
        if not np.all(np.isfinite(rotation)) or not np.all(np.isfinite(translation)):
            raise ValueError("transform values must be finite")
        object.__setattr__(self, "rotation", rotation)
        object.__setattr__(self, "translation", translation)

    @classmethod
    def identity(cls) -> "RigidTransform":
        return cls(np.eye(3, dtype=np.float64), np.zeros(3, dtype=np.float64))

    def apply(self, points: np.ndarray) -> np.ndarray:
        """Apply the transform to an ``(N, 3)`` point array."""

        points = np.asarray(points, dtype=np.float64)
        if points.ndim != 2 or points.shape[1] != 3:
            raise ValueError("points must have shape (N, 3)")
        return points @ self.rotation.T + self.translation


@dataclass(frozen=True)
class SparseProjectionEstimate:
    """Robust 3-D estimate obtained by projecting raw depth into a color mask."""

    position_m: Optional[Tuple[float, float, float]]
    depth_m: Optional[float]
    center_px: Tuple[int, int]
    mask_area_px: int
    valid_pixels: int
    valid_ratio: float

    @property
    def valid(self) -> bool:
        return self.position_m is not None


@dataclass(frozen=True)
class ProjectedDepthPoints:
    """Raw D455 depth points projected once into color-image pixels."""

    image_shape: Tuple[int, int]
    projected_u: np.ndarray
    projected_v: np.ndarray
    points_color: np.ndarray


def project_raw_depth_to_color(
    depth_mm: np.ndarray,
    color_shape: Tuple[int, int],
    depth_intrinsics: CameraIntrinsics,
    color_intrinsics: CameraIntrinsics,
    depth_to_color: RigidTransform,
    *,
    min_depth_m: float = 0.2,
    max_depth_m: float = 4.0,
    depth_scale_m: float = 0.001,
) -> ProjectedDepthPoints:
    """Project valid raw-depth pixels into the corresponding color image.

    This operation is independent of an instance mask. It is intentionally
    performed once per RGB-D frame and reused by every YOLO detection.
    """

    if depth_mm.ndim != 2:
        raise ValueError("depth must be two-dimensional")
    if len(color_shape) != 2 or color_shape[0] <= 0 or color_shape[1] <= 0:
        raise ValueError("color_shape must contain positive height and width")
    if min_depth_m <= 0 or max_depth_m <= min_depth_m or depth_scale_m <= 0:
        raise ValueError("invalid depth projection parameters")

    height, width = int(color_shape[0]), int(color_shape[1])
    empty = lambda: ProjectedDepthPoints(
        (height, width),
        np.empty(0, dtype=np.int32),
        np.empty(0, dtype=np.int32),
        np.empty((0, 3), dtype=np.float64),
    )
    depth_m = depth_mm.astype(np.float64) * depth_scale_m
    valid_depth = (depth_m >= min_depth_m) & (depth_m <= max_depth_m)
    rows, cols = np.nonzero(valid_depth)
    if rows.size == 0:
        return empty()

    z = depth_m[rows, cols]
    points_depth = np.column_stack((
        (cols - depth_intrinsics.cx) * z / depth_intrinsics.fx,
        (rows - depth_intrinsics.cy) * z / depth_intrinsics.fy,
        z,
    ))
    points_color = depth_to_color.apply(points_depth)
    points_color = points_color[points_color[:, 2] > 0]
    if points_color.size == 0:
        return empty()

    projected_u = np.rint(
        points_color[:, 0] * color_intrinsics.fx / points_color[:, 2]
        + color_intrinsics.cx
    ).astype(np.int32)
    projected_v = np.rint(
        points_color[:, 1] * color_intrinsics.fy / points_color[:, 2]
        + color_intrinsics.cy
    ).astype(np.int32)
    in_bounds = (
        (projected_u >= 0)
        & (projected_u < width)
        & (projected_v >= 0)
        & (projected_v < height)
    )
    return ProjectedDepthPoints(
        (height, width),
        projected_u[in_bounds],
        projected_v[in_bounds],
        points_color[in_bounds],
    )


def estimate_mask_3d_from_projected_depth(
    projection: ProjectedDepthPoints,
    color_mask: np.ndarray,
    *,
    trim_fraction: float = 0.1,
    erosion_iterations: int = 2,
    min_valid_pixels: int = 20,
) -> SparseProjectionEstimate:
    """Estimate one target from a color mask and preprojected depth points."""

    if color_mask.ndim != 2:
        raise ValueError("color_mask must be two-dimensional")
    if color_mask.shape != projection.image_shape:
        raise ValueError("color_mask shape must match projected color image")
    if not 0.0 <= trim_fraction < 0.5:
        raise ValueError("trim_fraction must be in [0, 0.5)")
    if erosion_iterations < 0 or min_valid_pixels < 1:
        raise ValueError("invalid mask projection parameters")

    binary_mask = color_mask.astype(bool).astype(np.uint8)
    original_area = int(binary_mask.sum())
    if original_area == 0 or projection.points_color.size == 0:
        return SparseProjectionEstimate(None, None, (0, 0), original_area, 0, 0.0)

    if erosion_iterations:
        kernel = np.ones((3, 3), dtype=np.uint8)
        sample_mask = cv2.erode(binary_mask, kernel, iterations=erosion_iterations)
        if not sample_mask.any():
            sample_mask = binary_mask
    else:
        sample_mask = binary_mask

    inside_mask = sample_mask[projection.projected_v, projection.projected_u].astype(bool)
    projected_u = projection.projected_u[inside_mask]
    projected_v = projection.projected_v[inside_mask]
    points_color = projection.points_color[inside_mask]
    valid_pixels = int(points_color.shape[0])
    covered_pixels = np.unique(np.column_stack((projected_u, projected_v)), axis=0).shape[0]
    valid_ratio = covered_pixels / int(sample_mask.sum())
    if valid_pixels < min_valid_pixels:
        center = (0, 0) if valid_pixels == 0 else (
            int(np.median(projected_u)), int(np.median(projected_v))
        )
        return SparseProjectionEstimate(
            None, None, center, original_area, valid_pixels, float(valid_ratio)
        )

    # Trim both optical-Z tails to reduce background spill at mask boundaries.
    points_color = points_color[np.argsort(points_color[:, 2])]
    trim_count = int(valid_pixels * trim_fraction)
    if trim_count and valid_pixels - 2 * trim_count >= min_valid_pixels:
        points_color = points_color[trim_count:-trim_count]

    position = tuple(float(value) for value in np.median(points_color, axis=0))
    center = (int(np.median(projected_u)), int(np.median(projected_v)))
    return SparseProjectionEstimate(
        position,
        position[2],
        center,
        original_area,
        valid_pixels,
        float(valid_ratio),
    )


def estimate_mask_3d_from_raw_depth(
    depth_mm: np.ndarray,
    color_mask: np.ndarray,
    depth_intrinsics: CameraIntrinsics,
    color_intrinsics: CameraIntrinsics,
    depth_to_color: RigidTransform,
    *,
    min_depth_m: float = 0.2,
    max_depth_m: float = 4.0,
    trim_fraction: float = 0.1,
    erosion_iterations: int = 2,
    min_valid_pixels: int = 20,
    depth_scale_m: float = 0.001,
) -> SparseProjectionEstimate:
    """Estimate one color-mask target from an unaligned D455 depth image.

    Raw depth pixels are deprojected in ``camera_depth_optical_frame``,
    transformed to ``camera_color_optical_frame``, and projected into the
    color mask. The returned position is in the color optical frame. The ROS
    adapter applies the static ``color optical -> camera_link`` transform.
    """

    if depth_mm.ndim != 2 or color_mask.ndim != 2:
        raise ValueError("depth and color_mask must both be two-dimensional")
    if min_depth_m <= 0 or max_depth_m <= min_depth_m:
        raise ValueError("invalid depth range")
    if not 0.0 <= trim_fraction < 0.5:
        raise ValueError("trim_fraction must be in [0, 0.5)")
    if erosion_iterations < 0 or min_valid_pixels < 1 or depth_scale_m <= 0:
        raise ValueError("invalid projection parameters")

    projection = project_raw_depth_to_color(
        depth_mm,
        color_mask.shape,
        depth_intrinsics,
        color_intrinsics,
        depth_to_color,
        min_depth_m=min_depth_m,
        max_depth_m=max_depth_m,
        depth_scale_m=depth_scale_m,
    )
    return estimate_mask_3d_from_projected_depth(
        projection,
        color_mask,
        trim_fraction=trim_fraction,
        erosion_iterations=erosion_iterations,
        min_valid_pixels=min_valid_pixels,
    )
