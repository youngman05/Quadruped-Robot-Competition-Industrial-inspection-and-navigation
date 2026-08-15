"""Pure validation and geometry helpers for the D455 YOLO UDP bridge."""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Sequence, Tuple


PACKET_KEYS = {
    "schema_version", "model_id", "class_schema", "sequence", "stamp",
    "frame_id", "inference_ms", "detections",
}
DETECTION_KEYS = {
    "class_id", "class_name", "confidence", "bbox", "center_px", "mask_area_px",
    "depth_m", "depth_valid_ratio", "position_valid", "position_m",
}
MODEL_ID = "gauge-ad-3ed76de7-v1"
CLASS_SCHEMA = "competition-ad-red-green-v1"
CLASS_NAMES = frozenset({"A", "B", "C", "D", "red", "green"})


class PacketValidationError(ValueError):
    """Raised when a UDP payload does not satisfy the v1 source contract."""


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _require_vector(values: Any, size: int, field: str) -> None:
    if not isinstance(values, list) or len(values) != size or not all(_is_finite_number(value) for value in values):
        raise PacketValidationError(f"{field} must contain {size} finite numeric values")


def validate_source_packet(
    packet: Any,
    *,
    expected_model_id: str = MODEL_ID,
    expected_class_schema: str = CLASS_SCHEMA,
) -> Dict[str, Any]:
    """Validate the Docker D455 YOLO v1 packet without external dependencies."""

    if not isinstance(packet, dict) or set(packet) != PACKET_KEYS:
        raise PacketValidationError("unexpected packet keys")
    if packet["schema_version"] != 1:
        raise PacketValidationError("unsupported schema_version")
    if packet["model_id"] != expected_model_id:
        raise PacketValidationError("unexpected model_id")
    if packet["class_schema"] != expected_class_schema:
        raise PacketValidationError("unexpected class_schema")
    if not _is_integer(packet["sequence"]) or packet["sequence"] < 0:
        raise PacketValidationError("invalid sequence")
    if not isinstance(packet["frame_id"], str) or not packet["frame_id"]:
        raise PacketValidationError("invalid frame_id")
    if not _is_finite_number(packet["inference_ms"]) or packet["inference_ms"] < 0:
        raise PacketValidationError("invalid inference_ms")

    stamp = packet["stamp"]
    if not isinstance(stamp, dict) or set(stamp) != {"sec", "nanosec"}:
        raise PacketValidationError("invalid stamp keys")
    if not _is_integer(stamp["sec"]) or stamp["sec"] < 0:
        raise PacketValidationError("invalid stamp seconds")
    if not _is_integer(stamp["nanosec"]) or not 0 <= stamp["nanosec"] < 1_000_000_000:
        raise PacketValidationError("invalid stamp nanoseconds")

    detections = packet["detections"]
    if not isinstance(detections, list):
        raise PacketValidationError("detections must be a list")
    for detection in detections:
        _validate_detection(detection)
    return packet


def _validate_detection(detection: Any) -> None:
    if not isinstance(detection, dict) or set(detection) != DETECTION_KEYS:
        raise PacketValidationError("unexpected detection keys")
    class_id = detection["class_id"]
    if not _is_integer(class_id) or class_id < 0:
        raise PacketValidationError("invalid class_id")
    if detection["class_name"] not in CLASS_NAMES:
        raise PacketValidationError("invalid class_name")
    if not _is_finite_number(detection["confidence"]) or not 0.0 <= detection["confidence"] <= 1.0:
        raise PacketValidationError("invalid confidence")
    if not isinstance(detection["bbox"], list) or len(detection["bbox"]) != 4 or not all(_is_integer(value) for value in detection["bbox"]):
        raise PacketValidationError("invalid bbox")
    if not isinstance(detection["center_px"], list) or len(detection["center_px"]) != 2 or not all(_is_integer(value) for value in detection["center_px"]):
        raise PacketValidationError("invalid center_px")
    if not _is_integer(detection["mask_area_px"]) or detection["mask_area_px"] < 0:
        raise PacketValidationError("invalid mask_area_px")
    if detection["depth_m"] is not None and (not _is_finite_number(detection["depth_m"]) or detection["depth_m"] <= 0):
        raise PacketValidationError("invalid depth_m")
    if not _is_finite_number(detection["depth_valid_ratio"]) or not 0.0 <= detection["depth_valid_ratio"] <= 1.0:
        raise PacketValidationError("invalid depth_valid_ratio")
    if not isinstance(detection["position_valid"], bool):
        raise PacketValidationError("invalid position_valid")
    if detection["position_valid"]:
        _require_vector(detection["position_m"], 3, "position_m")
    elif detection["position_m"] is not None:
        raise PacketValidationError("invalid detection must have null position_m")


def transform_point(
    point: Sequence[float],
    translation: Sequence[float],
    rotation_xyzw: Sequence[float],
) -> List[float]:
    """Apply a TF transform: ``p_target = R * p_source + t``."""

    if len(point) != 3 or len(translation) != 3 or len(rotation_xyzw) != 4:
        raise ValueError("point, translation, and rotation must be 3, 3, and 4 values")
    if not all(_is_finite_number(value) for value in (*point, *translation, *rotation_xyzw)):
        raise ValueError("transform values must be finite")

    x, y, z, w = (float(value) for value in rotation_xyzw)
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm == 0.0:
        raise ValueError("rotation quaternion must be non-zero")
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    px, py, pz = (float(value) for value in point)

    # Quaternion-vector multiplication without constructing a matrix.
    tx = 2.0 * (y * pz - z * py)
    ty = 2.0 * (z * px - x * pz)
    tz = 2.0 * (x * py - y * px)
    rx = px + w * tx + (y * tz - z * ty)
    ry = py + w * ty + (z * tx - x * tz)
    rz = pz + w * tz + (x * ty - y * tx)
    return [rx + float(translation[0]), ry + float(translation[1]), rz + float(translation[2])]


def packet_stamp_seconds(packet: Dict[str, Any]) -> float:
    stamp = packet["stamp"]
    return float(stamp["sec"]) + float(stamp["nanosec"]) / 1_000_000_000.0
