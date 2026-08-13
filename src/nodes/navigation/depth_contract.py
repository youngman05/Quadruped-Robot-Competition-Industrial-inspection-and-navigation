"""Versioned file contract for Docker-to-Host depth transport and control."""

from __future__ import annotations

import json
import math
import os
import threading
import time
import uuid
import zlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


PROTOCOL_VERSION = 1
CONTROL_REQUEST_FILE = "depth_control_request.json"
CONTROLLER_STATUS_FILE = "depth_controller_status.json"
FRAME_DATA_FILE = "latest_depth.raw"
FRAME_METADATA_FILE = "latest_depth.json"


class DepthContractError(ValueError):
    """Raised when shared depth state is incomplete or inconsistent."""


class DepthMode(str, Enum):
    BOOTING = "BOOTING"
    AVOIDANCE = "AVOIDANCE"
    DISABLED = "DISABLED"
    MANIPULATION = "MANIPULATION"
    FAULT = "FAULT"

    @property
    def requires_depth(self) -> bool:
        return self in (DepthMode.AVOIDANCE, DepthMode.MANIPULATION)


def parse_depth_mode(value: Any) -> DepthMode:
    if isinstance(value, DepthMode):
        return value
    try:
        return DepthMode(str(value).upper())
    except ValueError as exc:
        raise DepthContractError("unsupported depth mode: %r" % (value,)) from exc


def _required_int(data: Dict[str, Any], key: str, minimum: int = 0) -> int:
    try:
        value = int(data[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise DepthContractError("%s must be an integer" % key) from exc
    if value < minimum:
        raise DepthContractError("%s must be >= %d" % (key, minimum))
    return value


def _required_float(data: Dict[str, Any], key: str, minimum: float = 0.0) -> float:
    try:
        value = float(data[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise DepthContractError("%s must be numeric" % key) from exc
    if not math.isfinite(value) or value < minimum:
        raise DepthContractError("%s must be >= %s" % (key, minimum))
    return value


def _required_bool(data: Dict[str, Any], key: str) -> bool:
    try:
        value = data[key]
    except KeyError as exc:
        raise DepthContractError("%s must be a boolean" % key) from exc
    if not isinstance(value, bool):
        raise DepthContractError("%s must be a boolean" % key)
    return value


def _required_string(data: Dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DepthContractError("%s must be a non-empty string" % key)
    return value


def monotonic_age_sec(
    stamp_ns: int,
    now_ns: Optional[int] = None,
    label: str = "monotonic timestamp",
) -> float:
    """Return a same-host monotonic age and reject stale-boot/future values."""
    try:
        stamp_ns = int(stamp_ns)
        now_ns = time.monotonic_ns() if now_ns is None else int(now_ns)
    except (TypeError, ValueError) as exc:
        raise DepthContractError("%s must be an integer" % label) from exc
    if stamp_ns <= 0:
        raise DepthContractError("%s must be positive" % label)
    age_ns = now_ns - stamp_ns
    if age_ns < 0:
        raise DepthContractError("%s is from the future or a previous boot" % label)
    return age_ns / 1e9


def new_control_request(
    mode: DepthMode,
    request_id: Optional[str] = None,
    created_monotonic_ns: Optional[int] = None,
) -> Dict[str, Any]:
    mode = parse_depth_mode(mode)
    if mode in (DepthMode.BOOTING, DepthMode.FAULT):
        raise DepthContractError("mission cannot request mode %s" % mode.value)
    return {
        "version": PROTOCOL_VERSION,
        "request_id": request_id or uuid.uuid4().hex,
        "requested_mode": mode.value,
        "created_monotonic_ns": int(
            time.monotonic_ns()
            if created_monotonic_ns is None
            else created_monotonic_ns
        ),
    }


def validate_control_request(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise DepthContractError("control request must be an object")
    if data.get("version") != PROTOCOL_VERSION:
        raise DepthContractError("unsupported control request version")
    request_id = data.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        raise DepthContractError("request_id must be a non-empty string")
    mode = parse_depth_mode(data.get("requested_mode"))
    if mode in (DepthMode.BOOTING, DepthMode.FAULT):
        raise DepthContractError("invalid requested mode %s" % mode.value)
    created_ns = _required_int(data, "created_monotonic_ns", minimum=0)
    return {
        "version": PROTOCOL_VERSION,
        "request_id": request_id,
        "requested_mode": mode.value,
        "created_monotonic_ns": created_ns,
    }


def new_controller_status(
    mode: DepthMode,
    stream_id: str,
    ack_request_id: str = "",
    healthy: bool = True,
    depth_enabled: Optional[bool] = None,
    strategy: str = "consumer_only",
    sequence: int = 0,
    updated_monotonic_ns: Optional[int] = None,
    message: str = "",
) -> Dict[str, Any]:
    mode = parse_depth_mode(mode)
    if not isinstance(stream_id, str) or not stream_id.strip():
        raise DepthContractError("stream_id must be a non-empty string")
    if depth_enabled is None:
        depth_enabled = mode.requires_depth
    return {
        "version": PROTOCOL_VERSION,
        "stream_id": str(stream_id),
        "mode": mode.value,
        "ack_request_id": str(ack_request_id),
        "healthy": bool(healthy),
        "depth_enabled": bool(depth_enabled),
        "strategy": str(strategy),
        "sequence": int(sequence),
        "updated_monotonic_ns": int(
            time.monotonic_ns()
            if updated_monotonic_ns is None
            else updated_monotonic_ns
        ),
        "message": str(message),
    }


def validate_controller_status(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise DepthContractError("controller status must be an object")
    if data.get("version") != PROTOCOL_VERSION:
        raise DepthContractError("unsupported controller status version")
    mode = parse_depth_mode(data.get("mode"))
    ack_request_id = data.get("ack_request_id", "")
    if not isinstance(ack_request_id, str):
        raise DepthContractError("ack_request_id must be a string")
    strategy = data.get("strategy", "")
    if not isinstance(strategy, str) or not strategy:
        raise DepthContractError("strategy must be a non-empty string")
    result = {
        "version": PROTOCOL_VERSION,
        "stream_id": _required_string(data, "stream_id"),
        "mode": mode.value,
        "ack_request_id": ack_request_id,
        "healthy": _required_bool(data, "healthy"),
        "depth_enabled": _required_bool(data, "depth_enabled"),
        "strategy": strategy,
        "sequence": _required_int(data, "sequence", minimum=0),
        "updated_monotonic_ns": _required_int(
            data, "updated_monotonic_ns", minimum=0
        ),
        "message": str(data.get("message", "")),
    }
    for key in (
        "localization_check_enabled",
        "localization_ready",
        "localization_reason",
        "localization_samples",
        "localization_ages_sec",
    ):
        if key in data:
            result[key] = data[key]
    return result


def validate_camera_info(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise DepthContractError("camera_info must be an object")
    result = {
        "width": _required_int(data, "width", minimum=1),
        "height": _required_int(data, "height", minimum=1),
        "distortion_model": str(data.get("distortion_model", "plumb_bob")),
        "d": [float(value) for value in data.get("d", [])],
        "k": [float(value) for value in data.get("k", [])],
        "r": [float(value) for value in data.get("r", [])],
        "p": [float(value) for value in data.get("p", [])],
        "binning_x": int(data.get("binning_x", 0)),
        "binning_y": int(data.get("binning_y", 0)),
        "roi": dict(data.get("roi", {})),
    }
    for key, expected in (("k", 9), ("r", 9), ("p", 12)):
        if len(result[key]) != expected:
            raise DepthContractError("camera_info.%s must contain %d values" % (key, expected))
    for key in ("d", "k", "r", "p"):
        if not all(math.isfinite(value) for value in result[key]):
            raise DepthContractError("camera_info.%s must contain finite values" % key)
    return result


@dataclass(frozen=True)
class DepthFrameMetadata:
    stream_id: str
    sequence: int
    source_stamp_ns: int
    monotonic_stamp_ns: int
    width: int
    height: int
    step: int
    encoding: str
    is_bigendian: bool
    frame_id: str
    depth_scale: float
    byte_size: int
    crc32: int
    mode: DepthMode
    camera_info: Dict[str, Any]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DepthFrameMetadata":
        if not isinstance(data, dict):
            raise DepthContractError("frame metadata must be an object")
        if data.get("version") != PROTOCOL_VERSION:
            raise DepthContractError("unsupported frame metadata version")
        encoding = str(data.get("encoding", ""))
        if encoding not in ("16UC1", "mono16"):
            raise DepthContractError("unsupported depth encoding: %s" % encoding)
        frame_id = data.get("frame_id")
        if not isinstance(frame_id, str) or not frame_id:
            raise DepthContractError("frame_id must be a non-empty string")
        metadata = cls(
            stream_id=_required_string(data, "stream_id"),
            sequence=_required_int(data, "sequence", minimum=1),
            source_stamp_ns=_required_int(data, "source_stamp_ns", minimum=1),
            monotonic_stamp_ns=_required_int(data, "monotonic_stamp_ns", minimum=1),
            width=_required_int(data, "width", minimum=1),
            height=_required_int(data, "height", minimum=1),
            step=_required_int(data, "step", minimum=1),
            encoding=encoding,
            is_bigendian=_required_bool(data, "is_bigendian"),
            frame_id=frame_id,
            depth_scale=_required_float(data, "depth_scale", minimum=1e-12),
            byte_size=_required_int(data, "byte_size", minimum=1),
            crc32=_required_int(data, "crc32", minimum=0),
            mode=parse_depth_mode(data.get("mode")),
            camera_info=validate_camera_info(data.get("camera_info", {})),
        )
        if not metadata.mode.requires_depth:
            raise DepthContractError("frame cannot be published in mode %s" % metadata.mode.value)
        if metadata.step < metadata.width * 2:
            raise DepthContractError("frame step is too small for uint16 depth")
        if metadata.byte_size != metadata.height * metadata.step:
            raise DepthContractError("frame byte_size does not match height * step")
        if metadata.camera_info["width"] != metadata.width:
            raise DepthContractError("camera_info width does not match frame")
        if metadata.camera_info["height"] != metadata.height:
            raise DepthContractError("camera_info height does not match frame")
        return metadata

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": PROTOCOL_VERSION,
            "stream_id": self.stream_id,
            "sequence": self.sequence,
            "source_stamp_ns": self.source_stamp_ns,
            "monotonic_stamp_ns": self.monotonic_stamp_ns,
            "width": self.width,
            "height": self.height,
            "step": self.step,
            "encoding": self.encoding,
            "is_bigendian": self.is_bigendian,
            "frame_id": self.frame_id,
            "depth_scale": self.depth_scale,
            "byte_size": self.byte_size,
            "crc32": self.crc32,
            "mode": self.mode.value,
            "camera_info": self.camera_info,
        }


def build_frame_metadata(
    raw: bytes,
    stream_id: str,
    sequence: int,
    source_stamp_ns: int,
    width: int,
    height: int,
    step: int,
    frame_id: str,
    depth_scale: float,
    camera_info: Dict[str, Any],
    mode: DepthMode,
    monotonic_stamp_ns: Optional[int] = None,
    encoding: str = "16UC1",
    is_bigendian: bool = False,
) -> DepthFrameMetadata:
    data = {
        "version": PROTOCOL_VERSION,
        "stream_id": str(stream_id),
        "sequence": int(sequence),
        "source_stamp_ns": int(source_stamp_ns),
        "monotonic_stamp_ns": int(
            time.monotonic_ns()
            if monotonic_stamp_ns is None
            else monotonic_stamp_ns
        ),
        "width": int(width),
        "height": int(height),
        "step": int(step),
        "encoding": encoding,
        "is_bigendian": bool(is_bigendian),
        "frame_id": frame_id,
        "depth_scale": float(depth_scale),
        "byte_size": len(raw),
        "crc32": zlib.crc32(raw) & 0xFFFFFFFF,
        "mode": parse_depth_mode(mode).value,
        "camera_info": camera_info,
    }
    return DepthFrameMetadata.from_dict(data)


def _temporary_path(path: Path) -> Path:
    suffix = ".tmp-%d-%d" % (os.getpid(), threading.get_ident())
    return path.with_name(path.name + suffix)


def write_atomic_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_path(path)
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(str(temporary), str(path))


def write_atomic_json(path: Path, data: Dict[str, Any]) -> None:
    payload = (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    write_atomic_bytes(path, payload)


def read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DepthContractError("cannot read %s: %s" % (path, exc)) from exc


def read_frame_snapshot(directory: Path, max_attempts: int = 3) -> Tuple[DepthFrameMetadata, bytes]:
    directory = Path(directory)
    metadata_path = directory / FRAME_METADATA_FILE
    data_path = directory / FRAME_DATA_FILE
    last_error: Optional[Exception] = None
    for _ in range(max(1, int(max_attempts))):
        try:
            first = DepthFrameMetadata.from_dict(read_json(metadata_path))
            raw = data_path.read_bytes()
            second = DepthFrameMetadata.from_dict(read_json(metadata_path))
            if first.sequence != second.sequence or first.crc32 != second.crc32:
                raise DepthContractError("frame metadata changed during read")
            if len(raw) != second.byte_size:
                raise DepthContractError("frame byte count does not match metadata")
            if (zlib.crc32(raw) & 0xFFFFFFFF) != second.crc32:
                raise DepthContractError("frame CRC mismatch")
            return second, raw
        except (OSError, DepthContractError) as exc:
            last_error = exc
    raise DepthContractError("unable to read a consistent depth frame: %s" % last_error)
