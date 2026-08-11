"""Fail-closed velocity gate driven by validated cone scan health."""

from __future__ import annotations

import json
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

from nodes.navigation.cone_scan_safety import (
    ZERO_COMMAND,
    ConeScanHealthTracker,
)

try:
    from rclpy.qos import HistoryPolicy
except ImportError:
    from rclpy.qos import QoSHistoryPolicy as HistoryPolicy


class ConeScanSafetyGate(Node):
    def __init__(self) -> None:
        super().__init__("cone_scan_safety_gate")
        self.declare_parameter("input_topic", "/cmd_vel_selected")
        self.declare_parameter("output_topic", "/cmd_vel")
        self.declare_parameter("health_topic", "/cone_obstacle/health")
        self.declare_parameter("status_topic", "/cone_obstacle/safety_gate_status")
        self.declare_parameter("output_rate_hz", 40.0)
        self.declare_parameter("status_rate_hz", 5.0)
        self.declare_parameter("command_timeout_sec", 0.35)
        self.declare_parameter("health_timeout_sec", 0.25)
        self.declare_parameter("required_consecutive_frames", 3)

        output_rate = max(5.0, float(self.get_parameter("output_rate_hz").value))
        status_rate = max(1.0, float(self.get_parameter("status_rate_hz").value))
        self._status_divisor = max(1, int(round(output_rate / status_rate)))
        self._tick = 0
        self._command_timeout = max(
            0.05, float(self.get_parameter("command_timeout_sec").value)
        )
        self._command = ZERO_COMMAND
        self._command_time = None
        self._tracker = ConeScanHealthTracker(
            required_consecutive=int(
                self.get_parameter("required_consecutive_frames").value
            ),
            max_age_sec=float(self.get_parameter("health_timeout_sec").value),
        )

        self._publisher = self.create_publisher(
            Twist, str(self.get_parameter("output_topic").value), 10
        )
        self._status_publisher = self.create_publisher(
            String, str(self.get_parameter("status_topic").value), 10
        )
        self.create_subscription(
            Twist,
            str(self.get_parameter("input_topic").value),
            self._on_command,
            10,
        )
        health_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
        )
        self.create_subscription(
            String,
            str(self.get_parameter("health_topic").value),
            self._on_health,
            health_qos,
        )
        self.create_timer(1.0 / output_rate, self._publish)
        self.get_logger().info(
            "cone scan safety gate ready | timeout=%.3fs required_frames=%d"
            % (self._tracker.max_age_sec, self._tracker.required_consecutive)
        )

    def _on_command(self, msg: Twist) -> None:
        self._command = (
            float(msg.linear.x),
            float(msg.linear.y),
            float(msg.angular.z),
        )
        self._command_time = time.monotonic()

    def _on_health(self, msg: String) -> None:
        now = time.monotonic()
        try:
            data = json.loads(msg.data)
            self._tracker.observe(
                stream_id=str(data.get("stream_id", "")),
                sequence=int(data.get("sequence", 0)),
                healthy=bool(data.get("healthy", False)),
                now=now,
                reason=str(data.get("reason", "")),
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self._tracker.observe("", 0, False, now, "invalid health JSON: %s" % exc)

    def _publish(self) -> None:
        now = time.monotonic()
        decision = self._tracker.evaluate(
            self._command,
            self._command_time,
            now,
            self._command_timeout,
        )
        output = Twist()
        output.linear.x, output.linear.y, output.angular.z = decision.command
        self._publisher.publish(output)
        self._tick += 1
        if self._tick % self._status_divisor == 0:
            status = String()
            status.data = json.dumps(
                {
                    "allowed": decision.allowed,
                    "reason": decision.reason,
                    "stream_id": self._tracker.stream_id,
                    "sequence": self._tracker.last_sequence,
                    "consecutive_healthy": self._tracker.consecutive,
                    "required_consecutive": self._tracker.required_consecutive,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            self._status_publisher.publish(status)

    def destroy_node(self) -> bool:
        stop = Twist()
        for _ in range(3):
            self._publisher.publish(stop)
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ConeScanSafetyGate()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
