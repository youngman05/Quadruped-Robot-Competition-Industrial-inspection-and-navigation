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

