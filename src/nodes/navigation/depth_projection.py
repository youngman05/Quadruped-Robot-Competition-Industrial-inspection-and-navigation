"""Pure uint16 depth-to-optical-pointcloud projection helpers."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Tuple

from nodes.navigation.depth_contract import DepthContractError, DepthFrameMetadata


@dataclass(frozen=True)
class ProjectionConfig:
    decimation: int = 4
    min_range_m: float = 0.20
    max_range_m: float = 3.00
    crop_left: float = 0.0
    crop_right: float = 1.0
    crop_top: float = 0.0
    crop_bottom: float = 1.0

    def validate(self) -> "ProjectionConfig":
        if self.decimation < 1:
            raise DepthContractError("decimation must be >= 1")
        if self.min_range_m <= 0.0 or self.max_range_m <= self.min_range_m:
            raise DepthContractError("invalid pointcloud range limits")
        if not (
            0.0 <= self.crop_left < self.crop_right <= 1.0
            and 0.0 <= self.crop_top < self.crop_bottom <= 1.0
        ):
            raise DepthContractError("invalid pointcloud crop fractions")
        return self


def project_depth_points(
    raw: bytes,
    metadata: DepthFrameMetadata,
    config: ProjectionConfig,
) -> Tuple[bytes, int]:
    """Return packed little-endian XYZ float32 points in the optical frame."""
    config = config.validate()
    if len(raw) != metadata.byte_size:
        raise DepthContractError("raw depth size does not match metadata")
    k = metadata.camera_info["k"]
    fx, fy, cx, cy = float(k[0]), float(k[4]), float(k[2]), float(k[5])
    if not all(math.isfinite(value) and value != 0.0 for value in (fx, fy)):
        raise DepthContractError("camera intrinsics require finite non-zero fx/fy")

    x0 = int(metadata.width * config.crop_left)
    x1 = int(metadata.width * config.crop_right)
    y0 = int(metadata.height * config.crop_top)
    y1 = int(metadata.height * config.crop_bottom)
    unpack = ">H" if metadata.is_bigendian else "<H"
    points = bytearray()
    count = 0
    for v in range(y0, y1, config.decimation):
        row_offset = v * metadata.step
        for u in range(x0, x1, config.decimation):
            depth_units = struct.unpack_from(unpack, raw, row_offset + u * 2)[0]
            if depth_units == 0:
                continue
            z = float(depth_units) * metadata.depth_scale
            if z < config.min_range_m or z > config.max_range_m:
                continue
            x = (float(u) - cx) * z / fx
            y = (float(v) - cy) * z / fy
            points.extend(struct.pack("<fff", x, y, z))
            count += 1
    return bytes(points), count
