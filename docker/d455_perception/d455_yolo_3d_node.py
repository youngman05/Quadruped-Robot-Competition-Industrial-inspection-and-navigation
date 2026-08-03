#!/usr/bin/env python3
"""Docker ROS 2 node: RealSense RGB + raw depth -> camera_link XYZ UDP."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from collections import deque
from pathlib import Path
from typing import Deque, Optional

import numpy as np
import rclpy
from cv_bridge import CvBridge
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup, ReentrantCallbackGroup
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CameraInfo, Image
from tf2_ros import Buffer, TransformListener

from d455_yolo_3d_core import CameraIntrinsics, RigidTransform
from d455_yolo_3d_pipeline import Yolo3DConfig, Yolo3DPipeline


def stamp_ns(message: Image) -> int:
    return int(message.header.stamp.sec) * 1_000_000_000 + int(message.header.stamp.nanosec)


def transform_to_rigid(transform) -> RigidTransform:
    quaternion = transform.transform.rotation
    x, y, z, w = quaternion.x, quaternion.y, quaternion.z, quaternion.w
    rotation = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])
    translation = transform.transform.translation
    return RigidTransform(rotation, np.array([translation.x, translation.y, translation.z]))


class D455Yolo3DNode(Node):
    """Low-latency segmentation node with raw-depth sparse 3-D projection."""

    def __init__(self) -> None:
        super().__init__("d455_object_yolo_3d")
        self._declare_parameters()

        self._color_topic = str(self.get_parameter("color_topic").value)
        self._depth_topic = str(self.get_parameter("depth_topic").value)
        self._color_info_topic = str(self.get_parameter("color_info_topic").value)
        self._depth_info_topic = str(self.get_parameter("depth_info_topic").value)
        self._color_frame = str(self.get_parameter("color_optical_frame").value)
        self._depth_frame = str(self.get_parameter("depth_optical_frame").value)
        self._output_frame = str(self.get_parameter("output_frame").value)
        self._max_pair_delta_ns = int(float(self.get_parameter("max_rgb_depth_delta_ms").value) * 1e6)
        self._heartbeat_hz = float(self.get_parameter("heartbeat_hz").value)
        if self._max_pair_delta_ns < 0 or self._heartbeat_hz <= 0:
            raise ValueError("max_rgb_depth_delta_ms and heartbeat_hz must be positive")

        config = Yolo3DConfig(
            confidence=float(self.get_parameter("confidence").value),
            iou=float(self.get_parameter("iou").value),
            image_size=int(self.get_parameter("image_size").value),
            device=str(self.get_parameter("device").value),
            min_depth_m=float(self.get_parameter("min_depth_m").value),
            max_depth_m=float(self.get_parameter("max_depth_m").value),
            trim_fraction=float(self.get_parameter("trim_fraction").value),
            mask_erosion_iterations=int(self.get_parameter("mask_erosion_iterations").value),
            min_valid_pixels=int(self.get_parameter("min_valid_pixels").value),
            min_valid_ratio=float(self.get_parameter("min_valid_ratio").value),
        )
        model_path = str(self.get_parameter("model_path").value)
        self.get_logger().info(f"Loading YOLO model: {model_path}")
        self._pipeline = Yolo3DPipeline(model_path, config)
        self.get_logger().info(f"YOLO model ready: {self._pipeline.class_names}")

        self._bridge = CvBridge()
        self._lock = threading.Lock()
        self._latest_color: Optional[Image] = None
        self._depth_frames: Deque[Image] = deque(maxlen=4)
        self._color_intrinsics: Optional[CameraIntrinsics] = None
        self._depth_intrinsics: Optional[CameraIntrinsics] = None
        self._depth_to_color: Optional[RigidTransform] = None
        self._color_to_output: Optional[RigidTransform] = None
        self._last_processed_stamp = -1
        self._warmed_up = False
        self._sequence = 0
        self._last_udp_send_at = 0.0

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp_target = (
            str(self.get_parameter("udp_host").value),
            int(self.get_parameter("udp_port").value),
        )

        sensor_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
        )
        self._subscription_group = ReentrantCallbackGroup()
        self._inference_group = MutuallyExclusiveCallbackGroup()
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self, spin_thread=False)
        self.create_subscription(Image, self._color_topic, self._on_color, sensor_qos, callback_group=self._subscription_group)
        self.create_subscription(Image, self._depth_topic, self._on_depth, sensor_qos, callback_group=self._subscription_group)
        self.create_subscription(CameraInfo, self._color_info_topic, self._on_color_info, sensor_qos, callback_group=self._subscription_group)
        self.create_subscription(CameraInfo, self._depth_info_topic, self._on_depth_info, sensor_qos, callback_group=self._subscription_group)
        max_fps = float(self.get_parameter("max_fps").value)
        if max_fps <= 0:
            raise ValueError("max_fps must be positive")
        self.create_timer(1.0 / max_fps, self._process_latest, callback_group=self._inference_group)
        self.create_timer(1.0 / self._heartbeat_hz, self._heartbeat, callback_group=self._subscription_group)
        self.get_logger().info(
            f"Subscribed RGB={self._color_topic}, depth={self._depth_topic}; UDP={self._udp_target[0]}:{self._udp_target[1]}"
        )

    def _declare_parameters(self) -> None:
        model_default = os.environ.get("YOLO_MODEL_PATH", "/opt/quadruped/perception/models/red_green_obstacle.pt")
        self.declare_parameter("model_path", model_default)
        self.declare_parameter("device", "0")
        self.declare_parameter("image_size", 640)
        self.declare_parameter("confidence", 0.5)
        self.declare_parameter("iou", 0.5)
        self.declare_parameter("max_fps", 5.0)
        self.declare_parameter("color_topic", "/camera/color/image_raw")
        self.declare_parameter("depth_topic", "/camera/depth/image_rect_raw")
        self.declare_parameter("color_info_topic", "/camera/color/camera_info")
        self.declare_parameter("depth_info_topic", "/camera/depth/camera_info")
        self.declare_parameter("color_optical_frame", "camera_color_optical_frame")
        self.declare_parameter("depth_optical_frame", "camera_depth_optical_frame")
        self.declare_parameter("output_frame", "camera_link")
        self.declare_parameter("max_rgb_depth_delta_ms", 30.0)
        self.declare_parameter("min_depth_m", 0.2)
        self.declare_parameter("max_depth_m", 4.0)
        self.declare_parameter("trim_fraction", 0.1)
        self.declare_parameter("mask_erosion_iterations", 2)
        self.declare_parameter("min_valid_pixels", 20)
        self.declare_parameter("min_valid_ratio", 0.6)
        self.declare_parameter("udp_host", "127.0.0.1")
        self.declare_parameter("udp_port", 19002)
        self.declare_parameter("heartbeat_hz", 1.0)

    def _on_color(self, message: Image) -> None:
        with self._lock:
            self._latest_color = message

    def _on_depth(self, message: Image) -> None:
        with self._lock:
            self._depth_frames.append(message)

    def _on_color_info(self, message: CameraInfo) -> None:
        self._color_intrinsics = CameraIntrinsics(message.k[0], message.k[4], message.k[2], message.k[5])
        self._color_frame = message.header.frame_id or self._color_frame

    def _on_depth_info(self, message: CameraInfo) -> None:
        self._depth_intrinsics = CameraIntrinsics(message.k[0], message.k[4], message.k[2], message.k[5])
        self._depth_frame = message.header.frame_id or self._depth_frame

    def _resolve_static_transforms(self) -> bool:
        if self._depth_to_color is not None and self._color_to_output is not None:
            return True
        try:
            timeout = Duration(seconds=0.1)
            if self._depth_to_color is None:
                transform = self._tf_buffer.lookup_transform(
                    self._color_frame, self._depth_frame, rclpy.time.Time(), timeout=timeout
                )
                self._depth_to_color = transform_to_rigid(transform)
            if self._color_to_output is None:
                transform = self._tf_buffer.lookup_transform(
                    self._output_frame, self._color_frame, rclpy.time.Time(), timeout=timeout
                )
                self._color_to_output = transform_to_rigid(transform)
            return True
        except Exception as exc:
            self.get_logger().warn(f"Waiting for static RealSense TF: {exc}", throttle_duration_sec=5.0)
            return False

    def _select_pair(self):
        with self._lock:
            color = self._latest_color
            depth_frames = tuple(self._depth_frames)
        if color is None or not depth_frames:
            return None
        color_stamp = stamp_ns(color)
        if color_stamp <= self._last_processed_stamp:
            return None
        depth = min(depth_frames, key=lambda item: abs(stamp_ns(item) - color_stamp))
        delta_ns = abs(stamp_ns(depth) - color_stamp)
        if delta_ns > self._max_pair_delta_ns:
            self.get_logger().warn(
                f"Dropping RGB frame: nearest depth is {delta_ns / 1e6:.1f} ms away",
                throttle_duration_sec=2.0,
            )
            self._last_processed_stamp = color_stamp
            return None
        return color, depth, delta_ns

    def _process_latest(self) -> None:
        if self._color_intrinsics is None or self._depth_intrinsics is None:
            return
        if not self._resolve_static_transforms():
            return
        pair = self._select_pair()
        if pair is None:
            return
        color_message, depth_message, delta_ns = pair
        try:
            color = self._bridge.imgmsg_to_cv2(color_message, desired_encoding="bgr8")
            depth = self._bridge.imgmsg_to_cv2(depth_message, desired_encoding="passthrough")
            if depth.dtype != np.uint16:
                raise ValueError(f"Expected 16UC1 raw depth; received {depth.dtype}")
            if not self._warmed_up:
                self._pipeline.warmup(color.shape)
                self._warmed_up = True
            start = time.perf_counter()
            detections = self._pipeline.infer(
                color,
                depth,
                self._depth_intrinsics,
                self._color_intrinsics,
                self._depth_to_color,
                self._color_to_output,
            )
            inference_ms = (time.perf_counter() - start) * 1000.0
            self._last_processed_stamp = stamp_ns(color_message)
            self._send_packet(color_message, inference_ms, [item.packet_dict() for item in detections])
            self.get_logger().info(
                f"infer={inference_ms:.1f}ms detections={len(detections)} rgb-depth={delta_ns / 1e6:.1f}ms",
                throttle_duration_sec=1.0,
            )
        except Exception as exc:
            self.get_logger().error(f"YOLO 3-D processing error: {exc}", throttle_duration_sec=2.0)

    def _heartbeat(self) -> None:
        if time.monotonic() - self._last_udp_send_at < 1.0 / self._heartbeat_hz:
            return
        self._send_packet(None, 0.0, [])

    def _send_packet(self, source_message: Optional[Image], inference_ms: float, detections) -> None:
        if source_message is None:
            now = self.get_clock().now().to_msg()
            sec, nanosec = int(now.sec), int(now.nanosec)
        else:
            sec = int(source_message.header.stamp.sec)
            nanosec = int(source_message.header.stamp.nanosec)
        packet = {
            "schema_version": 1,
            "sequence": self._sequence,
            "stamp": {"sec": sec, "nanosec": nanosec},
            "frame_id": self._output_frame,
            "inference_ms": round(float(inference_ms), 3),
            "detections": detections,
        }
        self._sequence += 1
        try:
            self._socket.sendto(json.dumps(packet, separators=(",", ":")).encode("utf-8"), self._udp_target)
            self._last_udp_send_at = time.monotonic()
        except OSError as exc:
            self.get_logger().error(f"UDP send failed: {exc}", throttle_duration_sec=2.0)

    def destroy_node(self):
        self._socket.close()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = D455Yolo3DNode()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
