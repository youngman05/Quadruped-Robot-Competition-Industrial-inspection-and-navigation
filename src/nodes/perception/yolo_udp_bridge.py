#!/usr/bin/env python3
"""Bridge Docker D455 YOLO UDP detections into Host ROS base_link topics."""

from __future__ import annotations

import json
import socket
from typing import Any, Dict, List

import rclpy
from geometry_msgs.msg import Pose, PoseArray
from rclpy.duration import Duration
from rclpy.node import Node
from std_msgs.msg import String
from tf2_ros import Buffer, TransformException, TransformListener

from nodes.perception.yolo_udp_bridge_core import (
    CLASS_SCHEMA,
    MODEL_ID,
    PacketValidationError,
    packet_stamp_seconds,
    transform_point,
    validate_source_packet,
)


class YoloUdpBridge(Node):
    """Receive v1 UDP packets, transform valid XYZ to base_link, and publish ROS."""

    def __init__(self) -> None:
        super().__init__("yolo_udp_bridge_node")
        self._declare_parameters()

        self._bind_host = str(self.get_parameter("udp_bind_host").value)
        self._udp_port = int(self.get_parameter("udp_port").value)
        self._source_frame = str(self.get_parameter("source_frame").value)
        self._target_frame = str(self.get_parameter("target_frame").value)
        self._max_packet_age_s = float(self.get_parameter("max_packet_age_s").value)
        self._expected_model_id = str(self.get_parameter("expected_model_id").value)
        self._expected_class_schema = str(
            self.get_parameter("expected_class_schema").value
        )
        self._min_depth_valid_ratio = float(self.get_parameter("min_depth_valid_ratio").value)
        self._max_packets_per_poll = int(self.get_parameter("max_packets_per_poll").value)
        self._tf_timeout_s = float(self.get_parameter("tf_timeout_s").value)
        poll_period_s = float(self.get_parameter("poll_period_s").value)
        if self._udp_port <= 0 or poll_period_s <= 0 or self._max_packets_per_poll < 1:
            raise ValueError("invalid UDP bridge polling parameters")
        if self._max_packet_age_s < 0 or not 0.0 <= self._min_depth_valid_ratio <= 1.0:
            raise ValueError("invalid UDP bridge validation parameters")

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((self._bind_host, self._udp_port))
        self._socket.setblocking(False)

        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self, spin_thread=False)
        self._detections_pub = self.create_publisher(String, "/yolo/detections", 10)
        self._all_poses_pub = self.create_publisher(PoseArray, "/yolo/detection_poses", 10)
        self._cone_poses_pub = self.create_publisher(PoseArray, "/cone/detections", 10)
        self._block_poses_pub = self.create_publisher(PoseArray, "/block/detections", 10)
        self._status_pub = self.create_publisher(String, "/yolo/bridge/status", 10)
        self._last_status = ""
        self._timer = self.create_timer(poll_period_s, self._poll_udp)

        self.get_logger().info(
            f"UDP {self._bind_host}:{self._udp_port} -> {self._target_frame}; "
            f"expecting source frame {self._source_frame}"
        )
        self._publish_status("waiting_for_udp")

    def _declare_parameters(self) -> None:
        self.declare_parameter("udp_bind_host", "127.0.0.1")
        self.declare_parameter("udp_port", 19004)
        self.declare_parameter("expected_model_id", MODEL_ID)
        self.declare_parameter("expected_class_schema", CLASS_SCHEMA)
        self.declare_parameter("source_frame", "camera_link")
        self.declare_parameter("target_frame", "base_link")
        self.declare_parameter("poll_period_s", 0.05)
        self.declare_parameter("max_packets_per_poll", 4)
        self.declare_parameter("max_packet_age_s", 0.5)
        self.declare_parameter("min_depth_valid_ratio", 0.6)
        self.declare_parameter("tf_timeout_s", 0.05)

    def _poll_udp(self) -> None:
        for _ in range(self._max_packets_per_poll):
            try:
                payload, _source = self._socket.recvfrom(65_535)
            except BlockingIOError:
                return
            self._handle_payload(payload)

    def _handle_payload(self, payload: bytes) -> None:
        try:
            packet = validate_source_packet(
                json.loads(payload.decode("utf-8")),
                expected_model_id=self._expected_model_id,
                expected_class_schema=self._expected_class_schema,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, PacketValidationError) as exc:
            self.get_logger().warn(f"Dropped invalid YOLO UDP packet: {exc}", throttle_duration_sec=2.0)
            self._publish_status("invalid_packet")
            return
        if packet["frame_id"] != self._source_frame:
            self.get_logger().warn(
                f"Dropped YOLO UDP packet from unexpected frame {packet['frame_id']}",
                throttle_duration_sec=2.0,
            )
            self._publish_status("unexpected_frame")
            return
        if self._is_stale(packet):
            self._publish_status("stale_packet")
            return

        valid_detections = [
            detection for detection in packet["detections"]
            if detection["position_valid"] and detection["depth_valid_ratio"] >= self._min_depth_valid_ratio
        ]
        transform = None
        if valid_detections:
            try:
                transform = self._tf_buffer.lookup_transform(
                    self._target_frame,
                    self._source_frame,
                    rclpy.time.Time(),
                    timeout=Duration(seconds=self._tf_timeout_s),
                )
            except TransformException as exc:
                self.get_logger().warn(
                    f"Cannot transform {self._source_frame} to {self._target_frame}: {exc}",
                    throttle_duration_sec=2.0,
                )
                # Do not publish an empty result: downstream freshness watchdogs must fail safe.
                self._publish_status("waiting_for_tf")
                return

        output_detections = self._transform_detections(packet["detections"], transform)
        output_packet = {
            "schema_version": 1,
            "source_schema_version": packet["schema_version"],
            "model_id": packet["model_id"],
            "class_schema": packet["class_schema"],
            "sequence": packet["sequence"],
            "stamp": packet["stamp"],
            "frame_id": self._target_frame,
            "inference_ms": packet["inference_ms"],
            "detections": output_detections,
        }
        self._publish_packet_and_poses(output_packet)
        base_positions = [detection["position_m"] for detection in output_detections if detection["position_valid"]]
        first_position = "" if not base_positions else f" first_xyz={base_positions[0]}"
        self.get_logger().info(
            f"Published base_link detections={len(output_detections)} "
            f"valid={len(valid_detections)} sequence={packet['sequence']}{first_position}",
            throttle_duration_sec=1.0,
        )
        self._publish_status("receiving")

    def _is_stale(self, packet: Dict[str, Any]) -> bool:
        if self._max_packet_age_s == 0:
            return False
        now_s = self.get_clock().now().nanoseconds / 1_000_000_000.0
        return now_s - packet_stamp_seconds(packet) > self._max_packet_age_s

    def _transform_detections(self, detections: List[Dict[str, Any]], transform) -> List[Dict[str, Any]]:
        converted = []
        translation = rotation = None
        if transform is not None:
            trans = transform.transform.translation
            quat = transform.transform.rotation
            translation = [trans.x, trans.y, trans.z]
            rotation = [quat.x, quat.y, quat.z, quat.w]

        for detection in detections:
            output = dict(detection)
            if output["position_valid"] and output["depth_valid_ratio"] >= self._min_depth_valid_ratio:
                assert translation is not None and rotation is not None
                output["position_m"] = transform_point(output["position_m"], translation, rotation)
            else:
                output["position_valid"] = False
                output["position_m"] = None
            converted.append(output)
        return converted

    def _publish_packet_and_poses(self, packet: Dict[str, Any]) -> None:
        message = String()
        message.data = json.dumps(packet, separators=(",", ":"))
        self._detections_pub.publish(message)

        stamp = packet["stamp"]
        all_detections = [detection for detection in packet["detections"] if detection["position_valid"]]
        self._all_poses_pub.publish(self._pose_array(stamp, all_detections))
        self._cone_poses_pub.publish(self._pose_array(
            stamp, []
        ))
        self._block_poses_pub.publish(self._pose_array(
            stamp, [detection for detection in all_detections if detection["class_name"] in {"red", "green"}]
        ))

    def _pose_array(self, stamp: Dict[str, int], detections: List[Dict[str, Any]]) -> PoseArray:
        message = PoseArray()
        message.header.stamp.sec = stamp["sec"]
        message.header.stamp.nanosec = stamp["nanosec"]
        message.header.frame_id = self._target_frame
        for detection in detections:
            pose = Pose()
            pose.position.x, pose.position.y, pose.position.z = detection["position_m"]
            pose.orientation.w = 1.0
            message.poses.append(pose)
        return message

    def _publish_status(self, status: str) -> None:
        if status == self._last_status:
            return
        self._last_status = status
        message = String()
        message.data = status
        self._status_pub.publish(message)

    def destroy_node(self):
        self._socket.close()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = YoloUdpBridge()
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
