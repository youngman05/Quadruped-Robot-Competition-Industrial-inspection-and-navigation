"""Pure fail-closed velocity policy for depth-required mission modes."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

from nodes.navigation.depth_contract import DepthMode, parse_depth_mode


Command3 = Tuple[float, float, float]
ZERO_COMMAND: Command3 = (0.0, 0.0, 0.0)


def is_fresh_monotonic(stamp: Optional[float], now: float, max_age_sec: float) -> bool:
    if stamp is None:
        return False
    age = float(now) - float(stamp)
    return math.isfinite(age) and 0.0 <= age <= float(max_age_sec)


def costmap_confirms_depth_generation(
    mode_started_time: float,
    last_pointcloud_time: Optional[float],
    source_stamp_ns: Optional[int],
    costmap_stamp_ns: int,
) -> bool:
    """Confirm a new-mode cloud exists and the costmap stamp is not older."""
    if last_pointcloud_time is None or source_stamp_ns is None:
        return False
    return bool(
        math.isfinite(float(last_pointcloud_time))
        and float(last_pointcloud_time) >= float(mode_started_time)
        and int(source_stamp_ns) > 0
        and int(costmap_stamp_ns) >= int(source_stamp_ns)
    )


@dataclass(frozen=True)
class DepthReadiness:
    controller_mode: DepthMode
    request_acknowledged: bool
    controller_healthy: bool
    last_frame_time: Optional[float]
    last_pointcloud_time: Optional[float]
    last_tf_time: Optional[float]
    costmap_ready: bool


@dataclass(frozen=True)
class DepthGateDecision:
    command: Command3
    allowed: bool
    reason: str


class DepthSafetyPolicy:
    def __init__(self, max_data_age_sec: float = 0.5) -> None:
        self.max_data_age_sec = max(0.05, float(max_data_age_sec))

    def evaluate(
        self,
        command: Command3,
        requested_mode: DepthMode,
        readiness: DepthReadiness,
        now: float,
    ) -> DepthGateDecision:
        requested_mode = parse_depth_mode(requested_mode)
        if not all(math.isfinite(float(value)) for value in command):
            return DepthGateDecision(ZERO_COMMAND, False, "non-finite velocity command")
        if requested_mode == DepthMode.DISABLED:
            if readiness.controller_mode != DepthMode.DISABLED:
                return DepthGateDecision(ZERO_COMMAND, False, "controller mode mismatch")
            if not readiness.request_acknowledged:
                return DepthGateDecision(ZERO_COMMAND, False, "depth request is not acknowledged")
            if not readiness.controller_healthy:
                return DepthGateDecision(ZERO_COMMAND, False, "depth controller is unhealthy")
            return DepthGateDecision(tuple(float(value) for value in command), True, "depth disabled")
        if not requested_mode.requires_depth:
            return DepthGateDecision(ZERO_COMMAND, False, "mission depth mode is not operational")
        if readiness.controller_mode != requested_mode:
            return DepthGateDecision(ZERO_COMMAND, False, "controller mode mismatch")
        if not readiness.request_acknowledged:
            return DepthGateDecision(ZERO_COMMAND, False, "depth request is not acknowledged")
        if not readiness.controller_healthy:
            return DepthGateDecision(ZERO_COMMAND, False, "depth controller is unhealthy")
        for label, stamp in (
            ("depth frame", readiness.last_frame_time),
            ("point cloud", readiness.last_pointcloud_time),
            ("optical TF", readiness.last_tf_time),
        ):
            if not is_fresh_monotonic(stamp, now, self.max_data_age_sec):
                return DepthGateDecision(ZERO_COMMAND, False, "%s is stale" % label)
        if not readiness.costmap_ready:
            return DepthGateDecision(ZERO_COMMAND, False, "dynamic costmap is not ready")
        return DepthGateDecision(tuple(float(value) for value in command), True, "ready")
