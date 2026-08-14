"""YOLO detection contract and fixed-zone placement state machine.

This module deliberately has no ROS imports. The ROS node supplies a small
runtime adapter for velocity and arm services; tests use the same contract.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Mapping, Optional, Protocol, Tuple


Point3 = Tuple[float, float, float]


@dataclass(frozen=True)
class BlockDetection:
    class_name: str
    position_m: Point3
    confidence: float


@dataclass(frozen=True)
class DetectionFrame:
    sequence: int
    stamp_s: float
    red_blocks: Tuple[BlockDetection, ...]
    green_blocks: Tuple[BlockDetection, ...]


class DetectionContractError(ValueError):
    pass


def parse_detection_frame(packet: Mapping[str, Any], min_confidence: float, min_depth_ratio: float) -> DetectionFrame:
    """Consume only the Host bridge's ``base_link`` 3-D detection contract."""

    if packet.get("frame_id") != "base_link":
        raise DetectionContractError("YOLO frame_id must be base_link")
    sequence = packet.get("sequence")
    if not isinstance(sequence, int) or sequence < 0:
        raise DetectionContractError("YOLO sequence must be a non-negative integer")
    stamp = packet.get("stamp")
    if not isinstance(stamp, Mapping):
        raise DetectionContractError("YOLO stamp must be an object")
    sec, nanosec = stamp.get("sec"), stamp.get("nanosec")
    if (not isinstance(sec, int) or not isinstance(nanosec, int) or sec < 0 or
            nanosec < 0 or nanosec >= 1_000_000_000):
        raise DetectionContractError("YOLO stamp must contain valid sec/nanosec")
    detections = packet.get("detections")
    if not isinstance(detections, list):
        raise DetectionContractError("YOLO detections must be an array")
    red: List[BlockDetection] = []
    green: List[BlockDetection] = []
    for raw in detections:
        if not isinstance(raw, Mapping):
            continue
        name = raw.get("class_name")
        if name not in {"red", "green"} or not raw.get("position_valid", False):
            continue
        confidence = raw.get("confidence")
        depth_ratio = raw.get("depth_valid_ratio")
        point = raw.get("position_m")
        if not isinstance(confidence, (int, float)) or confidence < min_confidence:
            continue
        if not isinstance(depth_ratio, (int, float)) or depth_ratio < min_depth_ratio:
            continue
        if not isinstance(point, (list, tuple)) or len(point) != 3:
            continue
        try:
            xyz = tuple(float(value) for value in point)
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(value) for value in xyz):
            continue
        block = BlockDetection(str(name), xyz, float(confidence))
        (red if name == "red" else green).append(block)
    return DetectionFrame(sequence, float(sec) + float(nanosec) / 1_000_000_000.0, tuple(red), tuple(green))


class SegmentState(str, Enum):
    IDLE = "idle"
    SETTLE = "settle"
    ALIGN_Y = "align_y"
    ALIGN_X = "align_x"
    ALIGN_YAW = "align_yaw"
    PULSE = "pulse"
    WAIT_ARM = "wait_arm"
    HOLD = "hold"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass(frozen=True)
class SegmentResult:
    success: bool
    reason: str
    alignment_success: bool = False
    grasp_success: bool = False
    place_success: bool = False
    outputs: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlaceConfig:
    settle_s: float = 1.0
    align_timeout_s: float = 30.0
    tolerance_m: float = 0.04
    yaw_tolerance_rad: float = 0.0873
    gain_xy: float = 0.5
    gain_yaw: float = 0.8
    max_speed_mps: float = 0.05
    min_speed_mps: float = 0.025
    max_yaw_rps: float = 0.20
    pulse_min_s: float = 0.15
    pulse_max_s: float = 0.40
    pulse_settle_s: float = 0.70


class ManipulationRuntime(Protocol):
    """ROS-independent dependencies used by the local state machines."""

    def now(self) -> float: ...
    def stop(self) -> None: ...
    def command(self, axis: str, speed: float) -> None: ...
    def next_detection(self) -> Optional[DetectionFrame]: ...
    def placement_error(self, zone: str) -> Tuple[float, float, float]: ...
    def start_place(self) -> bool: ...
    def place_result(self) -> Optional[bool]: ...


def _pulse(error: float, gain: float, maximum: float, minimum: float, min_s: float, max_s: float, sign: float = 1.0) -> Tuple[float, float]:
    speed = min(max(abs(float(error) * gain), minimum), maximum)
    signed_speed = math.copysign(speed * abs(sign), float(error) * sign)
    duration = min(max(abs(float(error)) / speed, min_s), max_s)
    return signed_speed, duration


class _BaseExecutor:
    def __init__(self, runtime: ManipulationRuntime) -> None:
        self.runtime = runtime
        self.state = SegmentState.IDLE
        self._entered_s = runtime.now()
        self._result: Optional[SegmentResult] = None
        self._pulse_axis = ""
        self._pulse_speed = 0.0
        self._pulse_until_s = 0.0
        self._resume_state = SegmentState.IDLE

    @property
    def running(self) -> bool:
        return self.state not in {SegmentState.IDLE, SegmentState.SUCCESS, SegmentState.FAILED}

    def result(self) -> Optional[SegmentResult]:
        return self._result

    def cancel(self, reason: str) -> SegmentResult:
        self.runtime.stop()
        return self._finish(False, reason)

    def _set_state(self, state: SegmentState) -> None:
        self.state = state
        self._entered_s = self.runtime.now()

    def _elapsed(self) -> float:
        return self.runtime.now() - self._entered_s

    def _finish(self, success: bool, reason: str, **flags: Any) -> SegmentResult:
        self.runtime.stop()
        self.state = SegmentState.SUCCESS if success else SegmentState.FAILED
        self._result = SegmentResult(success=success, reason=reason, **flags)
        return self._result

    def _start_pulse(self, axis: str, speed: float, duration_s: float, resume: SegmentState) -> None:
        self._pulse_axis = axis
        self._pulse_speed = speed
        self._pulse_until_s = self.runtime.now() + duration_s
        self._resume_state = resume
        self._set_state(SegmentState.PULSE)

    def _tick_pulse(self, settle_s: float) -> None:
        if self.runtime.now() < self._pulse_until_s:
            self.runtime.command(self._pulse_axis, self._pulse_speed)
            return
        self.runtime.stop()
        self._set_state(SegmentState.SETTLE)
        self._pulse_until_s = self.runtime.now() + settle_s

    def _tick_pulse_settle(self) -> bool:
        self.runtime.stop()
        if self.runtime.now() < self._pulse_until_s:
            return False
        self._set_state(self._resume_state)
        return True


class PlaceOneExecutor(_BaseExecutor):
    """J0 -> J1 map/TF correction and one fixed placement request."""

    def __init__(self, runtime: ManipulationRuntime, zone: str, config: PlaceConfig = PlaceConfig()) -> None:
        super().__init__(runtime)
        self.zone = str(zone).upper()
        self.config = config
        self._align_started_s: Optional[float] = None

    def start(self) -> None:
        if self.zone not in {"A", "B", "C", "D"}:
            raise RuntimeError("place executor requires zone A/B/C/D")
        self._set_state(SegmentState.SETTLE)

    def tick(self) -> Optional[SegmentResult]:
        if self._result is not None:
            return self._result
        if self.state == SegmentState.SETTLE:
            self.runtime.stop()
            if self._pulse_until_s:
                self._tick_pulse_settle()
                return None
            if self._elapsed() >= self.config.settle_s:
                self._align_started_s = self.runtime.now()
                self._set_state(SegmentState.ALIGN_Y)
            return None
        if self.state in {SegmentState.ALIGN_Y, SegmentState.ALIGN_X, SegmentState.ALIGN_YAW}:
            return self._tick_align()
        if self.state == SegmentState.PULSE:
            self._tick_pulse(self.config.pulse_settle_s)
            return None
        if self.state == SegmentState.WAIT_ARM:
            result = self.runtime.place_result()
            if result is False:
                return self._finish(False, "place service failed")
            if result is True:
                return self._finish(True, "fixed place completed", place_success=True, outputs={"zone": self.zone})
        return None

    def _tick_align(self) -> Optional[SegmentResult]:
        if (self._align_started_s is not None and
                self.runtime.now() - self._align_started_s > self.config.align_timeout_s):
            return self._finish(False, "J1 alignment timed out")
        error_x, error_y, error_yaw = self.runtime.placement_error(self.zone)
        if self.state == SegmentState.ALIGN_Y:
            axis, error, tolerance, resume = "y", error_y, self.config.tolerance_m, SegmentState.ALIGN_X
            gain, maximum = self.config.gain_xy, self.config.max_speed_mps
        elif self.state == SegmentState.ALIGN_X:
            axis, error, tolerance, resume = "x", error_x, self.config.tolerance_m, SegmentState.ALIGN_YAW
            gain, maximum = self.config.gain_xy, self.config.max_speed_mps
        else:
            axis, error, tolerance, resume = "yaw", error_yaw, self.config.yaw_tolerance_rad, SegmentState.WAIT_ARM
            gain, maximum = self.config.gain_yaw, self.config.max_yaw_rps
        if abs(error) <= tolerance:
            if resume == SegmentState.WAIT_ARM:
                if not self.runtime.start_place():
                    return self._finish(False, "place service rejected")
            self._set_state(resume)
            return None
        speed, duration = _pulse(error, gain, maximum, min(self.config.min_speed_mps, maximum),
                                 self.config.pulse_min_s, self.config.pulse_max_s)
        self._start_pulse(axis, speed, duration, self.state)
        return None
