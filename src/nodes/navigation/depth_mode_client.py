"""Small ROS adapter around the pure depth-mode acknowledgement state machine."""

from __future__ import annotations

import json
import time

from std_msgs.msg import String

from nodes.navigation.depth_contract import DepthMode
from nodes.navigation.depth_mode import DepthModeCoordinator


class DepthModeClient:
    def __init__(
        self,
        node,
        request_topic: str = "/depth/mode_request",
        status_topic: str = "/depth/mode_status",
        safety_status_topic: str = "/depth/safety_gate_status",
        transition_timeout_sec: float = 8.0,
        safety_status_timeout_sec: float = 0.5,
    ) -> None:
        self._node = node
        self._coordinator = DepthModeCoordinator(transition_timeout_sec)
        self._publisher = node.create_publisher(String, request_topic, 10)
        self._subscription = node.create_subscription(
            String,
            status_topic,
            self._on_status,
            10,
        )
        self._safety_subscription = node.create_subscription(
            String,
            safety_status_topic,
            self._on_safety_status,
            10,
        )
        self.last_status_error = ""
        self.safety_status_timeout_sec = max(0.1, float(safety_status_timeout_sec))
        self.safety_ready = False
        self.safety_mode = DepthMode.BOOTING
        self.active_request_id = ""
        self.safety_request_id = ""
        self.safety_reason = "waiting for depth safety gate status"
        self.safety_status_time = float("-inf")

    @property
    def current_mode(self) -> DepthMode:
        return self._coordinator.current_mode

    def begin_transition(self, mode: DepthMode, robot_stopped: bool = True):
        request = self._coordinator.request(mode, robot_stopped=robot_stopped)
        if request is None:
            return None
        self.active_request_id = request["request_id"]
        self.safety_request_id = ""
        self.safety_ready = False
        self.safety_status_time = float("-inf")
        msg = String()
        msg.data = json.dumps(request, sort_keys=True)
        self._publisher.publish(msg)
        return request

    def readiness(self):
        return self._coordinator.readiness()

    def end_to_end_ready(self, mode: DepthMode) -> bool:
        readiness = self.readiness()
        return bool(
            readiness.ready
            and readiness.mode == mode
            and self.safety_ready
            and self.safety_mode == mode
            and self.safety_request_id == self.active_request_id
            and bool(self.active_request_id)
            and time.monotonic() - self.safety_status_time
            <= self.safety_status_timeout_sec
        )

    def end_to_end_reason(self, mode: DepthMode) -> str:
        readiness = self.readiness()
        if not readiness.ready or readiness.mode != mode:
            return readiness.reason
        if time.monotonic() - self.safety_status_time > self.safety_status_timeout_sec:
            return "depth safety gate status is stale"
        if self.safety_mode != mode:
            return "depth safety gate mode mismatch"
        if not self.active_request_id:
            return "no active depth request"
        if self.safety_request_id != self.active_request_id:
            return "depth safety gate request mismatch"
        return self.safety_reason

    def _on_status(self, msg: String) -> None:
        try:
            self._coordinator.observe_status(json.loads(msg.data))
            self.last_status_error = ""
        except Exception as exc:  # noqa: BLE001
            self.last_status_error = str(exc)

    def _on_safety_status(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
            self.safety_mode = DepthMode(str(data.get("mode", "")).upper())
            self.safety_request_id = str(data.get("active_request_id", ""))
            self.safety_ready = bool(data.get("allowed", False))
            self.safety_reason = str(data.get("reason", "unknown"))
            self.safety_status_time = time.monotonic()
        except Exception as exc:  # noqa: BLE001
            self.safety_mode = DepthMode.FAULT
            self.safety_request_id = ""
            self.safety_ready = False
            self.safety_reason = "invalid safety gate status: %s" % exc
            self.safety_status_time = time.monotonic()
