"""Priority and watchdog arbitration for Nav2 and precision velocity commands."""

from __future__ import annotations

import math
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node

from nodes.navigation.cmd_vel_arbitration import CmdVelArbitration


def _clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


class CmdVelArbiter(Node):
    """Publish one safe /cmd_vel stream with precision control taking priority."""

    def __init__(self) -> None:
        super().__init__("cmd_vel_arbiter")
        self.declare_parameter("nav_topic", "/cmd_vel_nav2")
        self.declare_parameter("precision_topic", "/cmd_vel_precision")
        self.declare_parameter("output_topic", "/cmd_vel")
        self.declare_parameter("output_rate_hz", 40.0)
        self.declare_parameter("nav_timeout_sec", 0.35)
        self.declare_parameter("precision_timeout_sec", 0.25)
        self.declare_parameter("precision_release_stop_sec", 0.50)
        self.declare_parameter("max_vx", 0.12)
        self.declare_parameter("max_vy", 0.05)
        self.declare_parameter("max_wz", 0.15)

        nav_topic = str(self.get_parameter("nav_topic").value)
        precision_topic = str(self.get_parameter("precision_topic").value)
        output_topic = str(self.get_parameter("output_topic").value)
        self._output_rate_hz = max(
            5.0,
            float(self.get_parameter("output_rate_hz").value),
        )
        self._nav_timeout = max(
            0.05,
            float(self.get_parameter("nav_timeout_sec").value),
        )
        self._precision_timeout = max(
            0.05,
            float(self.get_parameter("precision_timeout_sec").value),
        )
        self._release_stop = max(
            0.0,
            float(self.get_parameter("precision_release_stop_sec").value),
        )
        self._max_vx = abs(float(self.get_parameter("max_vx").value))
        self._max_vy = abs(float(self.get_parameter("max_vy").value))
        self._max_wz = abs(float(self.get_parameter("max_wz").value))

        self._arbitration = CmdVelArbitration(
            nav_timeout=self._nav_timeout,
            precision_timeout=self._precision_timeout,
            release_stop=self._release_stop,
        )
        self._invalid_count = 0
        self._ignored_nav_count = 0

        self._publisher = self.create_publisher(Twist, output_topic, 10)
        self._nav_subscription = self.create_subscription(
            Twist,
            nav_topic,
            self._on_nav,
            10,
        )
        self._precision_subscription = self.create_subscription(
            Twist,
            precision_topic,
            self._on_precision,
            10,
        )
        self._timer = self.create_timer(
            1.0 / self._output_rate_hz,
            self._publish_selected,
        )
        self.get_logger().info(
            "cmd_vel arbiter ready | nav=%s precision=%s output=%s rate=%.1fHz"
            % (nav_topic, precision_topic, output_topic, self._output_rate_hz)
        )

    def _sanitize(self, msg: Twist):
        values = (float(msg.linear.x), float(msg.linear.y), float(msg.angular.z))
        if not all(math.isfinite(value) for value in values):
            self._invalid_count += 1
            self.get_logger().error("rejected non-finite cmd_vel input")
            return None
        return (
            _clamp(values[0], self._max_vx),
            _clamp(values[1], self._max_vy),
            _clamp(values[2], self._max_wz),
        )

    def _on_nav(self, msg: Twist) -> None:
        # Never buffer Nav2 commands behind an active precision-control lease.
        command = self._sanitize(msg)
        if command is None:
            return
        if not self._arbitration.accept_nav(command, time.monotonic()):
            self._ignored_nav_count += 1

    def _on_precision(self, msg: Twist) -> None:
        command = self._sanitize(msg)
        if command is None:
            return
        acquired = self._arbitration.accept_precision(command, time.monotonic())
        if acquired:
            self.get_logger().info("precision cmd_vel lease acquired")

    def _publish_selected(self) -> None:
        now = time.monotonic()
        previous_mode = self._arbitration.mode
        decision = self._arbitration.select(now)
        if previous_mode == "precision" and decision.mode == "precision_release":
            self.get_logger().info("precision lease released; holding stop")

        msg = Twist()
        msg.linear.x = decision.command[0]
        msg.linear.y = decision.command[1]
        msg.angular.z = decision.command[2]
        self._publisher.publish(msg)

    def destroy_node(self) -> bool:
        stop = Twist()
        for _ in range(12):
            self._publisher.publish(stop)
            time.sleep(0.025)
        self.get_logger().info(
            "cmd_vel arbiter stopped | invalid=%d ignored_nav=%d"
            % (self._invalid_count, self._ignored_nav_count)
        )
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = CmdVelArbiter()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
