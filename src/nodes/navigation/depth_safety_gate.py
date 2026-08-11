"""Fail-closed ROS velocity gate for depth-required mission modes."""

from __future__ import annotations

import json
import math
import time

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import OccupancyGrid
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.time import Time
from std_msgs.msg import String
from tf2_ros import Buffer, TransformException, TransformListener

from nodes.navigation.depth_contract import DepthMode, parse_depth_mode
from nodes.navigation.depth_safety import (
    ZERO_COMMAND,
    DepthReadiness,
    DepthSafetyPolicy,
    costmap_confirms_depth_generation,
    is_fresh_monotonic,
)


class DepthSafetyGate(Node):
    def __init__(self) -> None:
        super().__init__("depth_safety_gate")
        self.declare_parameter("input_topic", "/cmd_vel_selected")
        self.declare_parameter("output_topic", "/cmd_vel")
        self.declare_parameter("pipeline_status_topic", "/depth/pipeline_status")
        self.declare_parameter("local_costmap_topic", "/local_costmap/costmap_raw")
        self.declare_parameter("status_topic", "/depth/safety_gate_status")
        self.declare_parameter("output_rate_hz", 40.0)
        self.declare_parameter("command_timeout_sec", 0.35)
        self.declare_parameter("max_data_age_sec", 0.60)
        self.declare_parameter("pipeline_status_timeout_sec", 0.50)
        self.declare_parameter("costmap_max_age_sec", 1.0)
        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("optical_frame", "camera_depth_optical_frame")

        self._command_timeout = max(0.05, float(self.get_parameter("command_timeout_sec").value))
        self._costmap_max_age = max(0.1, float(self.get_parameter("costmap_max_age_sec").value))
        self._pipeline_status_timeout = max(
            0.1,
            float(self.get_parameter("pipeline_status_timeout_sec").value),
        )
        self._base_frame = str(self.get_parameter("base_frame").value)
        self._optical_frame = str(self.get_parameter("optical_frame").value)
        self._policy = DepthSafetyPolicy(float(self.get_parameter("max_data_age_sec").value))
        self._command = ZERO_COMMAND
        self._command_time = float("-inf")
        self._mode = DepthMode.BOOTING
        self._controller_mode = DepthMode.BOOTING
        self._acknowledged = False
        self._controller_healthy = False
        self._last_frame_time = None
        self._last_pointcloud_time = None
        self._last_source_stamp_ns = None
        self._last_tf_time = None
        self._last_costmap_time = None
        self._last_pipeline_status_time = float("-inf")
        self._active_request_id = ""
        self._controller_stream_id = ""
        self._pipeline_generation = None
        self._mode_started_time = float("inf")
        self._costmap_generation_confirmed = False
        self._last_reason = "booting"

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
        self.create_subscription(
            String,
            str(self.get_parameter("pipeline_status_topic").value),
            self._on_pipeline_status,
            10,
        )
        self.create_subscription(
            OccupancyGrid,
            str(self.get_parameter("local_costmap_topic").value),
            self._on_costmap,
            5,
        )
        self._tf_buffer = Buffer(cache_time=Duration(seconds=3.0))
        self._tf_listener = TransformListener(self._tf_buffer, self)
        rate = max(5.0, float(self.get_parameter("output_rate_hz").value))
        self.create_timer(1.0 / rate, self._publish)
        self.get_logger().info("depth safety gate ready")

    def _on_command(self, msg: Twist) -> None:
        values = (float(msg.linear.x), float(msg.linear.y), float(msg.angular.z))
        self._command = values
        self._command_time = time.monotonic()

    def _on_pipeline_status(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
            now = time.monotonic()
            requested_mode = parse_depth_mode(
                data.get("requested_mode", data.get("mode"))
            )
            active_request_id = str(data.get("active_request_id", ""))
            controller_stream_id = str(data.get("controller_stream_id", ""))
            generation = (
                active_request_id,
                controller_stream_id,
                requested_mode.value,
            )
            if generation != self._pipeline_generation:
                self._pipeline_generation = generation
                self._mode_started_time = now
                self._costmap_generation_confirmed = False
                self._last_costmap_time = None
            self._mode = requested_mode
            self._controller_mode = parse_depth_mode(data.get("mode"))
            self._active_request_id = active_request_id
            self._controller_stream_id = controller_stream_id
            self._acknowledged = bool(data.get("acknowledged", False))
            self._controller_healthy = bool(data.get("controller_healthy", False))
            self._last_frame_time = data.get("last_frame_time")
            self._last_pointcloud_time = data.get("last_pointcloud_time")
            self._last_source_stamp_ns = data.get("last_source_stamp_ns")
            self._last_pipeline_status_time = now
        except Exception as exc:  # noqa: BLE001
            self._mode = DepthMode.FAULT
            self._controller_mode = DepthMode.FAULT
            self._acknowledged = False
            self._controller_healthy = False
            self._last_reason = "invalid pipeline status: %s" % exc

    def _on_costmap(self, msg: OccupancyGrid) -> None:
        now = time.monotonic()
        self._last_costmap_time = now
        costmap_stamp_ns = (
            int(msg.header.stamp.sec) * 1_000_000_000
            + int(msg.header.stamp.nanosec)
        )
        if (
            self._mode.requires_depth
            and self._acknowledged
            and costmap_confirms_depth_generation(
                self._mode_started_time,
                self._last_pointcloud_time,
                self._last_source_stamp_ns,
                costmap_stamp_ns,
            )
        ):
            self._costmap_generation_confirmed = True

    def _update_tf_health(self, now: float) -> None:
        try:
            self._tf_buffer.lookup_transform(
                self._base_frame,
                self._optical_frame,
                Time(),
                timeout=Duration(seconds=0.02),
            )
            self._last_tf_time = now
        except TransformException:
            pass

    def _publish(self) -> None:
        now = time.monotonic()
        self._update_tf_health(now)
        command = self._command
        if now - self._command_time > self._command_timeout:
            command = ZERO_COMMAND
        costmap_ready = bool(
            self._costmap_generation_confirmed
            and is_fresh_monotonic(
                self._last_costmap_time,
                now,
                self._costmap_max_age,
            )
        )
        pipeline_status_fresh = is_fresh_monotonic(
            self._last_pipeline_status_time,
            now,
            self._pipeline_status_timeout,
        )
        readiness = DepthReadiness(
            controller_mode=self._controller_mode,
            request_acknowledged=self._acknowledged and pipeline_status_fresh,
            controller_healthy=self._controller_healthy and pipeline_status_fresh,
            last_frame_time=self._last_frame_time,
            last_pointcloud_time=self._last_pointcloud_time,
            last_tf_time=self._last_tf_time,
            costmap_ready=costmap_ready,
        )
        decision = self._policy.evaluate(command, self._mode, readiness, now)
        output = Twist()
        output.linear.x, output.linear.y, output.angular.z = decision.command
        self._publisher.publish(output)
        self._last_reason = decision.reason
        status = String()
        status.data = json.dumps(
            {
                "allowed": decision.allowed,
                "mode": self._mode.value,
                "active_request_id": self._active_request_id,
                "controller_stream_id": self._controller_stream_id,
                "reason": decision.reason,
                "costmap_ready": costmap_ready,
                "costmap_generation_confirmed": self._costmap_generation_confirmed,
                "pipeline_status_fresh": pipeline_status_fresh,
            },
            sort_keys=True,
        )
        self._status_publisher.publish(status)

    def destroy_node(self) -> bool:
        stop = Twist()
        for _ in range(12):
            self._publisher.publish(stop)
            time.sleep(0.025)
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = DepthSafetyGate()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
