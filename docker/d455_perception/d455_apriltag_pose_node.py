#!/usr/bin/env python3
"""Docker ROS node: D455 AprilTag pose in camera_link -> Host UDP."""

from __future__ import annotations

import json
import os
import socket
import time
from typing import Optional

import numpy as np
import rclpy
from cv_bridge import CvBridge
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CameraInfo, Image
from tf2_ros import Buffer, TransformListener

from apriltag_pose_core import AprilTagPoseDetector, quaternion_xyzw, transform_pose
from d455_yolo_3d_core import RigidTransform


def _rigid_from_transform(transform) -> RigidTransform:
    quaternion = transform.transform.rotation
    x, y, z, w = quaternion.x, quaternion.y, quaternion.z, quaternion.w
    rotation = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])
    translation = transform.transform.translation
    return RigidTransform(rotation, np.array([translation.x, translation.y, translation.z]))


class D455AprilTagPoseNode(Node):
    def __init__(self) -> None:
        super().__init__("d455_apriltag_pose")
        self._declare_parameters()
        self._color_topic = str(self.get_parameter("color_topic").value)
        self._info_topic = str(self.get_parameter("camera_info_topic").value)
        self._color_frame = str(self.get_parameter("color_optical_frame").value)
        self._output_frame = str(self.get_parameter("output_frame").value)
        self._detector = AprilTagPoseDetector(
            float(self.get_parameter("tag_size_m").value),
            self.get_parameter("tag_ids").value,
            float(self.get_parameter("max_reprojection_error_px").value),
            int(self.get_parameter("pose_history_max_missed_frames").value),
        )
        self._udp_target = (
            str(self.get_parameter("udp_host").value),
            int(self.get_parameter("udp_port").value),
        )
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._bridge = CvBridge()
        self._camera_matrix: Optional[np.ndarray] = None
        self._distortion = np.zeros(5, dtype=np.float64)
        self._latest_image: Optional[Image] = None
        self._last_stamp_ns = -1
        self._sequence = 0
        self._output_from_color = None
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self, spin_thread=False)
        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
        )
        self.create_subscription(Image, self._color_topic, self._on_image, qos)
        self.create_subscription(CameraInfo, self._info_topic, self._on_info, qos)
        self.create_timer(1.0 / float(self.get_parameter("process_rate_hz").value), self._process_latest)
        self.get_logger().info(
            "AprilTag IDs {}: {} -> {} UDP {}:{}".format(
                sorted(self._detector.expected_tag_ids),
                self._color_topic,
                self._output_frame,
                *self._udp_target,
            )
        )

    def _declare_parameters(self) -> None:
        tag_ids_default = json.loads(os.environ.get("APRILTAG_TAG_IDS", "[0,1,2,3]"))
        tag_size_default = float(os.environ.get("APRILTAG_TAG_SIZE_M", "0.100"))
        self.declare_parameter("color_topic", "/camera/color/image_raw")
        self.declare_parameter("camera_info_topic", "/camera/color/camera_info")
        self.declare_parameter("color_optical_frame", "camera_color_optical_frame")
        self.declare_parameter("output_frame", "camera_link")
        self.declare_parameter("tag_ids", tag_ids_default)
        # Printed black AprilTag square side length. The white quiet zone is excluded.
        self.declare_parameter("tag_size_m", tag_size_default)
        self.declare_parameter("max_reprojection_error_px", 3.0)
        self.declare_parameter("pose_history_max_missed_frames", 5)
        self.declare_parameter("process_rate_hz", 10.0)
        self.declare_parameter("udp_host", "127.0.0.1")
        self.declare_parameter("udp_port", 19003)

    def _on_image(self, message: Image) -> None:
        self._latest_image = message

    def _on_info(self, message: CameraInfo) -> None:
        self._camera_matrix = np.asarray(message.k, dtype=np.float64).reshape(3, 3)
        self._distortion = np.asarray(message.d, dtype=np.float64)
        self._color_frame = message.header.frame_id or self._color_frame

    def _resolve_transform(self) -> bool:
        if self._output_from_color is not None:
            return True
        try:
            transform = self._tf_buffer.lookup_transform(
                self._output_frame,
                self._color_frame,
                rclpy.time.Time(),
                timeout=Duration(seconds=0.1),
            )
            self._output_from_color = _rigid_from_transform(transform)
            return True
        except Exception as exc:
            self.get_logger().warn("Waiting for RealSense TF: {}".format(exc), throttle_duration_sec=5.0)
            return False

    def _process_latest(self) -> None:
        message = self._latest_image
        if message is None or self._camera_matrix is None or not self._resolve_transform():
            return
        stamp_ns = int(message.header.stamp.sec) * 1_000_000_000 + int(message.header.stamp.nanosec)
        if stamp_ns <= self._last_stamp_ns:
            return
        self._last_stamp_ns = stamp_ns
        started = time.perf_counter()
        image = self._bridge.imgmsg_to_cv2(message, desired_encoding="bgr8")
        poses = self._detector.detect(image, self._camera_matrix, self._distortion)
        if not poses:
            return
        poses = [transform_pose(pose, self._output_from_color) for pose in poses]
        packet = {
            "schema_version": 1,
            "sequence": self._sequence,
            "stamp": {"sec": int(message.header.stamp.sec), "nanosec": int(message.header.stamp.nanosec)},
            "frame_id": self._output_frame,
            "detections": [
                {
                    "tag_id": pose.tag_id,
                    "position_m": list(pose.position_m),
                    "orientation_xyzw": list(quaternion_xyzw(pose.rotation)),
                    "reprojection_error_px": pose.reprojection_error_px,
                }
                for pose in poses
            ],
            "detection_ms": (time.perf_counter() - started) * 1000.0,
        }
        self._socket.sendto(
            json.dumps(packet, separators=(",", ":")).encode("utf-8"),
            self._udp_target,
        )
        self._sequence += 1
        self.get_logger().info(
            "tags={} detection_ms={:.1f}".format(
                [pose.tag_id for pose in poses], packet["detection_ms"]
            ),
            throttle_duration_sec=1.0,
        )

    def destroy_node(self):
        self._socket.close()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = D455AprilTagPoseNode()
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
