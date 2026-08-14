#!/usr/bin/env python3
"""Publish Docker D455 AprilTag UDP poses in base_link."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import rclpy
from ament_index_python.packages import get_package_share_directory
from rclpy.node import Node
from std_msgs.msg import String

from nodes.perception.apriltag_udp_bridge_core import (
    PacketValidationError,
    load_static_extrinsic,
    stamp_seconds,
    transform_pose,
    validate_packet,
)


class AprilTagUdpBridge(Node):
    def __init__(self) -> None:
        super().__init__("apriltag_udp_bridge_node")
        self._declare_parameters()
        self._bind_host = str(self.get_parameter("udp_bind_host").value)
        self._port = int(self.get_parameter("udp_port").value)
        self._source_frame = str(self.get_parameter("source_frame").value)
        self._target_frame = str(self.get_parameter("target_frame").value)
        self._max_age_s = float(self.get_parameter("max_packet_age_s").value)
        config_path = str(self.get_parameter("extrinsics_config").value)
        if not config_path:
            config_path = str(
                Path(get_package_share_directory("quadruped_robot_competition"))
                / "configs"
                / "transforms"
                / "static_extrinsics.yaml"
            )
        self._translation, self._rotation = load_static_extrinsic(
            Path(config_path), self._target_frame, self._source_frame
        )
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind((self._bind_host, self._port))
        self._socket.setblocking(False)
        self._publisher = self.create_publisher(
            String, str(self.get_parameter("detections_topic").value), 10
        )
        self._timer = self.create_timer(
            float(self.get_parameter("poll_period_s").value), self._poll
        )
        self.get_logger().info(
            "AprilTag UDP {}:{}: {} -> {}".format(
                self._bind_host, self._port, self._source_frame, self._target_frame
            )
        )

    def _declare_parameters(self) -> None:
        self.declare_parameter("udp_bind_host", "127.0.0.1")
        self.declare_parameter("udp_port", 19003)
        self.declare_parameter("source_frame", "camera_link")
        self.declare_parameter("target_frame", "base_link")
        self.declare_parameter("detections_topic", "/apriltag/detections_base")
        self.declare_parameter("poll_period_s", 0.01)
        self.declare_parameter("max_packet_age_s", 0.5)
        self.declare_parameter("extrinsics_config", "")

    def _poll(self) -> None:
        payload = None
        try:
            while True:
                payload, _source = self._socket.recvfrom(16384)
        except BlockingIOError:
            pass
        if payload is None:
            return
        try:
            packet = validate_packet(json.loads(payload.decode("utf-8")))
            if packet["frame_id"] != self._source_frame:
                return
            now_s = self.get_clock().now().nanoseconds / 1e9
            if now_s - stamp_seconds(packet) > self._max_age_s:
                return
        except (UnicodeDecodeError, json.JSONDecodeError, PacketValidationError) as exc:
            self.get_logger().warn("Dropped AprilTag packet: {}".format(exc), throttle_duration_sec=2.0)
            return
        detections = []
        for detection in packet["detections"]:
            position, orientation = transform_pose(
                detection["position_m"],
                detection["orientation_xyzw"],
                self._translation,
                self._rotation,
            )
            detections.append({
                "tag_id": detection["tag_id"],
                "position_m": list(position),
                "orientation_xyzw": list(orientation),
                "reprojection_error_px": detection["reprojection_error_px"],
            })
        output = {
            "schema_version": 1,
            "sequence": packet["sequence"],
            "stamp": packet["stamp"],
            "frame_id": self._target_frame,
            "detections": detections,
            "detection_ms": packet["detection_ms"],
        }
        message = String()
        message.data = json.dumps(output, separators=(",", ":"))
        self._publisher.publish(message)
        self.get_logger().info(
            "Published tags={} in {}".format(
                [item["tag_id"] for item in detections], self._target_frame
            ),
            throttle_duration_sec=1.0,
        )

    def destroy_node(self):
        self._socket.close()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = AprilTagUdpBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
