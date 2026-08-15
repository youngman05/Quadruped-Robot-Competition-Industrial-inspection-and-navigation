"""Validation and rigid-pose helpers for the AprilTag UDP bridge."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, Sequence, Tuple

import yaml


PACKET_KEYS = {
    "schema_version",
    "sequence",
    "stamp",
    "frame_id",
    "detections",
    "detection_ms",
}


class PacketValidationError(ValueError):
    pass


def load_static_extrinsic(
    config_path: Path, parent_frame: str, child_frame: str
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float, float]]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if "static_transforms" in config:
        for transform in config["static_transforms"]:
            if (
                transform.get("publish", False)
                and transform.get("parent_frame") == parent_frame
                and transform.get("child_frame") == child_frame
            ):
                translation = tuple(float(value) for value in transform["translation_m"])
                rotation = tuple(float(value) for value in transform["rotation_xyzw"])
                return translation, rotation
    elif (
        config.get("parent_frame") == parent_frame
        and config.get("child_frame") == child_frame
    ):
        translation_data = config["translation_m"]
        rpy = config["rotation_rpy_rad"]
        translation = tuple(float(translation_data[key]) for key in ("x", "y", "z"))
        rotation = quaternion_from_rpy(
            float(rpy["roll"]), float(rpy["pitch"]), float(rpy["yaw"])
        )
        return translation, rotation
    raise ValueError(
        "static extrinsic {} -> {} not found in {}".format(
            parent_frame, child_frame, config_path
        )
    )


def quaternion_from_rpy(roll: float, pitch: float, yaw: float) -> Tuple[float, float, float, float]:
    cr, sr = math.cos(roll / 2.0), math.sin(roll / 2.0)
    cp, sp = math.cos(pitch / 2.0), math.sin(pitch / 2.0)
    cy, sy = math.cos(yaw / 2.0), math.sin(yaw / 2.0)
    return (
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    )


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _vector(value: Any, size: int, name: str) -> None:
    if not isinstance(value, list) or len(value) != size or not all(_number(item) for item in value):
        raise PacketValidationError("{} must contain {} finite numbers".format(name, size))


def validate_packet(packet: Any) -> Dict[str, Any]:
    if not isinstance(packet, dict) or set(packet) != PACKET_KEYS:
        raise PacketValidationError("unexpected packet keys")
    if packet["schema_version"] != 1:
        raise PacketValidationError("unsupported schema_version")
    if not isinstance(packet["sequence"], int) or isinstance(packet["sequence"], bool) or packet["sequence"] < 0:
        raise PacketValidationError("invalid sequence")
    if not isinstance(packet["frame_id"], str) or not packet["frame_id"]:
        raise PacketValidationError("invalid frame_id")
    stamp = packet["stamp"]
    if (
        not isinstance(stamp, dict)
        or set(stamp) != {"sec", "nanosec"}
        or not isinstance(stamp["sec"], int)
        or not isinstance(stamp["nanosec"], int)
        or stamp["sec"] < 0
        or not 0 <= stamp["nanosec"] < 1_000_000_000
    ):
        raise PacketValidationError("invalid stamp")
    detections = packet["detections"]
    if not isinstance(detections, list):
        raise PacketValidationError("detections must be a list")
    seen_ids = set()
    for detection in detections:
        if not isinstance(detection, dict) or set(detection) != {
            "tag_id", "position_m", "orientation_xyzw", "reprojection_error_px"
        }:
            raise PacketValidationError("invalid detection fields")
        tag_id = detection["tag_id"]
        if not isinstance(tag_id, int) or isinstance(tag_id, bool) or tag_id < 0 or tag_id in seen_ids:
            raise PacketValidationError("invalid or duplicate tag_id")
        seen_ids.add(tag_id)
        _vector(detection["position_m"], 3, "position_m")
        _vector(detection["orientation_xyzw"], 4, "orientation_xyzw")
        if sum(float(value) ** 2 for value in detection["orientation_xyzw"]) < 1e-12:
            raise PacketValidationError("orientation quaternion is zero")
        if not _number(detection["reprojection_error_px"]) or detection["reprojection_error_px"] < 0:
            raise PacketValidationError("invalid reprojection_error_px")
    if not _number(packet["detection_ms"]) or packet["detection_ms"] < 0:
        raise PacketValidationError("invalid detection_ms")
    return packet


def quaternion_multiply(left: Sequence[float], right: Sequence[float]) -> Tuple[float, float, float, float]:
    lx, ly, lz, lw = (float(value) for value in left)
    rx, ry, rz, rw = (float(value) for value in right)
    result = (
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
        lw * rw - lx * rx - ly * ry - lz * rz,
    )
    norm = math.sqrt(sum(value * value for value in result))
    return tuple(value / norm for value in result)


def transform_pose(
    position: Sequence[float],
    orientation_xyzw: Sequence[float],
    translation: Sequence[float],
    rotation_xyzw: Sequence[float],
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float, float]]:
    from nodes.perception.yolo_udp_bridge_core import transform_point

    transformed_position = transform_point(position, translation, rotation_xyzw)
    transformed_orientation = quaternion_multiply(rotation_xyzw, orientation_xyzw)
    return tuple(transformed_position), transformed_orientation


def stamp_seconds(packet: Dict[str, Any]) -> float:
    return float(packet["stamp"]["sec"]) + float(packet["stamp"]["nanosec"]) / 1e9
