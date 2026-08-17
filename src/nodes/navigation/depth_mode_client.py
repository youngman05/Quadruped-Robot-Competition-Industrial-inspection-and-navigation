"""Small ROS adapter around the pure depth-mode acknowledgement state machine."""

from __future__ import annotations

import json
import time
from typing import Optional

from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

from nodes.navigation.depth_contract import DepthMode, new_control_request
from nodes.navigation.depth_mode import DepthModeCoordinator


class DepthModeClient:
    REQUEST_REPUBLISH_INTERVAL_SEC = 0.5

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
        request_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._publisher = node.create_publisher(String, request_topic, request_qos)
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
        self.cone_layer_baseline_ready = False
        self.cone_layer_baseline_reason = "waiting for cone layer applied status"
        self._active_request = None
        self._active_request_payload = ""
        self._next_republish_at = float("-inf")

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
        self._active_request = dict(request)
        self._active_request_payload = json.dumps(request, sort_keys=True)
        msg.data = self._active_request_payload
        self._publisher.publish(msg)
        self._next_republish_at = (
            time.monotonic() + self.REQUEST_REPUBLISH_INTERVAL_SEC
        )
        return request

    def republish_active_request(
        self,
        mode: Optional[DepthMode] = None,
        now: Optional[float] = None,
    ) -> bool:
        """Republish the unchanged request while its end-to-end ACK is pending."""
        if self._active_request is None or not self._active_request_payload:
            return False
        if mode is None:
            mode = DepthMode(self._active_request["requested_mode"])
        if self.end_to_end_ready(mode):
            return False
        now = time.monotonic() if now is None else float(now)
        if now < self._next_republish_at:
            return False
        msg = String()
        msg.data = self._active_request_payload
        self._publisher.publish(msg)
        self._next_republish_at = now + self.REQUEST_REPUBLISH_INTERVAL_SEC
        return True

    def direct_disable(self) -> None:
        """Publish a one-shot DISABLED request and stop consuming depth status.

        This is intentionally a fire-and-forget path used after the cone
        avoidance area has been completed. TaskManager no longer waits for the
        Docker controller acknowledgement or the safety-gate status, and no
        later mission milestone may re-enable depth.
        """
        request = new_control_request(DepthMode.DISABLED)
        self.active_request_id = request["request_id"]
        self.safety_request_id = request["request_id"]
        self.safety_ready = True
        self.safety_mode = DepthMode.DISABLED
        self.safety_status_time = time.monotonic()
        self._coordinator.current_mode = DepthMode.DISABLED
        self._coordinator.desired_mode = DepthMode.DISABLED
        self._coordinator.pending_request = None
        self._active_request = dict(request)
        self._active_request_payload = json.dumps(request, sort_keys=True)
        msg = String()
        msg.data = self._active_request_payload
        self._publisher.publish(msg)
        self.close_depth_subscriptions()

    def close_depth_subscriptions(self) -> None:
        """Permanently stop TaskManager-side depth status subscriptions."""
        for subscription in (self._subscription, self._safety_subscription):
            if subscription is not None:
                self._node.destroy_subscription(subscription)
        self._subscription = None
        self._safety_subscription = None

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
            self.cone_layer_baseline_ready = bool(
                data.get("layer_baseline_ready", False)
            )
            self.cone_layer_baseline_reason = str(
                data.get(
                    "layer_baseline_reason",
                    "waiting for cone layer applied status",
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.safety_mode = DepthMode.FAULT
            self.safety_request_id = ""
            self.safety_ready = False
            self.safety_reason = "invalid safety gate status: %s" % exc
            self.safety_status_time = time.monotonic()
            self.cone_layer_baseline_ready = False
            self.cone_layer_baseline_reason = self.safety_reason
