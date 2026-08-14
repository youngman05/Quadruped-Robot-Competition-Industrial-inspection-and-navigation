#!/usr/bin/env python3
"""Run the supervised local I0 -> I2 QR-alignment acceptance test.

Xavier's Fast DDS setup does not reliably discover the static TF / UDP bridge
when they run in separate processes.  Keep these runtime nodes in one process
for this hardware test.  The robot remains stopped until /task/start_route is
called; Ctrl-C publishes a final zero Twist through CmdVelBridge.
"""

from __future__ import annotations

import json
import math
import threading
from pathlib import Path

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from std_msgs.msg import String
from std_srvs.srv import Trigger

from nodes.decision.competition_manager import CompetitionManager
from nodes.navigation.cmd_vel_bridge import CmdVelBridge
from nodes.perception.lite3_qr_pose_publisher import Lite3QrPosePublisher


class TestMonitor(Node):
    """Keep test evidence in the same DDS process as the production nodes."""

    def __init__(self, manager: CompetitionManager) -> None:
        super().__init__("pick_i0_to_i2_test_monitor")
        self._manager = manager
        self._start_requested = threading.Event()
        self._started = False
        self.create_subscription(String, "/task/route_status", self._on_status, 10)
        self.create_subscription(PoseStamped, "/box/qr_pose", self._on_qr, 10)
        self.create_timer(0.1, self._start_when_requested)
        threading.Thread(target=self._wait_for_enter, daemon=True).start()

    def _wait_for_enter(self) -> None:
        try:
            input("QR preflight is running. Clear the area, then press Enter to start I0 -> I2: ")
        except EOFError:
            self.get_logger().error("No interactive terminal; route start was not requested")
            return
        self._start_requested.set()

    def _start_when_requested(self) -> None:
        if self._started or not self._start_requested.is_set():
            return
        self._started = True
        response = self._manager._on_start(Trigger.Request(), Trigger.Response())
        self.get_logger().info(
            "START_RESULT success={} message={}".format(response.success, response.message)
        )

    def _on_status(self, message: String) -> None:
        try:
            status = json.loads(message.data)
        except json.JSONDecodeError:
            self.get_logger().info("ROUTE_STATUS {}".format(message.data))
            return
        self.get_logger().info(
            "ROUTE_STATUS state={} step={} reason={}".format(
                status.get("state", ""), status.get("current_step", ""), status.get("reason", "")
            )
        )

    def _on_qr(self, message: PoseStamped) -> None:
        q = message.pose.orientation
        yaw_deg = math.degrees(math.atan2(
            2.0 * (q.w * q.z + q.x * q.y),
            1.0 - 2.0 * (q.y * q.y + q.z * q.z),
        ))
        p = message.pose.position
        self.get_logger().info(
            "QR_POSE xyz=[{:.3f},{:.3f},{:.3f}] yaw_deg={:.2f}".format(
                p.x, p.y, p.z, yaw_deg
            ),
            throttle_duration_sec=1.0,
        )


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    qr_params = root / "configs" / "camera" / "lite3_front_qr.yaml"
    route_params = root / "configs" / "ros" / "competition_route_params.yaml"
    rclpy.init(args=[
        "--ros-args",
        "--params-file", str(qr_params),
        "--params-file", str(route_params),
    ])
    qr = Lite3QrPosePublisher()
    manager = CompetitionManager()
    manager.set_parameters([
        Parameter("route_mode", value="segment"),
        Parameter("segment_name", value="pick_i0_to_i2"),
        Parameter("enable_route_execution", value=True),
    ])
    nodes = [qr, manager, CmdVelBridge(), TestMonitor(manager)]
    executor = MultiThreadedExecutor()
    for node in nodes:
        executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        for node in reversed(nodes):
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
