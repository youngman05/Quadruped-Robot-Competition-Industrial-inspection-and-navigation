"""ROS-independent acknowledgement state machine for staged depth modes."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from nodes.navigation.depth_contract import (
    DepthContractError,
    DepthMode,
    new_control_request,
    parse_depth_mode,
    validate_controller_status,
)


@dataclass(frozen=True)
class DepthModeReadiness:
    ready: bool
    mode: DepthMode
    pending: bool
    reason: str


class DepthModeCoordinator:
    """Require a stopped robot and an explicit matching controller ACK."""

    def __init__(self, transition_timeout_sec: float = 8.0) -> None:
        self.transition_timeout_ns = int(max(0.1, transition_timeout_sec) * 1e9)
        self.current_mode = DepthMode.BOOTING
        self.desired_mode = DepthMode.BOOTING
        self.pending_request: Optional[Dict[str, Any]] = None
        self.last_status: Optional[Dict[str, Any]] = None

    def request(
        self,
        mode: DepthMode,
        robot_stopped: bool,
        now_ns: Optional[int] = None,
        request_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        mode = parse_depth_mode(mode)
        if not robot_stopped:
            raise DepthContractError("depth mode transitions require a stopped robot")
        if self.pending_request is None and self.current_mode == mode:
            return None
        request = new_control_request(
            mode,
            request_id=request_id,
            created_monotonic_ns=time.monotonic_ns() if now_ns is None else now_ns,
        )
        self.desired_mode = mode
        self.pending_request = request
        return dict(request)

    def observe_status(self, data: Dict[str, Any]) -> None:
        status = validate_controller_status(data)
        self.last_status = status
        if self.pending_request is None:
            if self.current_mode not in (DepthMode.BOOTING, DepthMode.FAULT):
                actual_mode = parse_depth_mode(status["mode"])
                expected_depth = self.current_mode.requires_depth
                if (
                    not status["healthy"]
                    or actual_mode != self.current_mode
                    or status["depth_enabled"] != expected_depth
                ):
                    self.current_mode = DepthMode.FAULT
            return
        if status["ack_request_id"] != self.pending_request["request_id"]:
            return
        actual_mode = parse_depth_mode(status["mode"])
        expected_depth = self.desired_mode.requires_depth
        if actual_mode != self.desired_mode:
            return
        if not status["healthy"] or status["depth_enabled"] != expected_depth:
            return
        self.current_mode = actual_mode
        self.pending_request = None

    def readiness(self, now_ns: Optional[int] = None) -> DepthModeReadiness:
        now_ns = time.monotonic_ns() if now_ns is None else int(now_ns)
        if self.pending_request is not None:
            age_ns = now_ns - self.pending_request["created_monotonic_ns"]
            if age_ns > self.transition_timeout_ns:
                return DepthModeReadiness(
                    False,
                    DepthMode.FAULT,
                    True,
                    "depth mode transition timed out",
                )
            return DepthModeReadiness(
                False,
                self.desired_mode,
                True,
                "waiting for matching depth controller acknowledgement",
            )
        if self.current_mode in (DepthMode.BOOTING, DepthMode.FAULT):
            return DepthModeReadiness(
                False,
                self.current_mode,
                False,
                "depth controller is not in an operational mode",
            )
        return DepthModeReadiness(True, self.current_mode, False, "ready")
