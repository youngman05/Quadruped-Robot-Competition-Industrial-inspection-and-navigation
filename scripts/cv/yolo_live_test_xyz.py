#!/usr/bin/env python3
"""Validate YOLO Raw-Depth 3-D coordinates from an existing RealSense ROS node.

Unlike yolo_live_test.py, this script never opens D455. Start the Docker
RealSense node first, then run this script in the same ROS 2 environment.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from collections import deque
import rclpy
from pathlib import Path
from typing import Deque, Optional, Tuple

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PERCEPTION_DIR = ROOT / "docker" / "d455_perception"
sys.path.insert(0, str(PERCEPTION_DIR))

from d455_yolo_3d_core import CameraIntrinsics, RigidTransform
from d455_yolo_3d_pipeline import Yolo3DConfig, Yolo3DPipeline


DEFAULT_MODEL = ROOT / "src" / "cv" / "depth_detector" / "projects" / "combined" / "model" / "best.pt"


def parse_args() -> Tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(description="D455 ROS Raw Depth -> YOLO 3-D validation")
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--device", default="0")
    parser.add_argument("--max-fps", type=float, default=5.0)
    parser.add_argument("--no-gui", action="store_true")
    return parser.parse_known_args()


def stamp_ns(message) -> int:
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


class YoloLiveTestXyz:
    def __init__(self, args: argparse.Namespace) -> None:
        import rclpy
        from cv_bridge import CvBridge
        from rclpy.duration import Duration
        from rclpy.node import Node
        from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
        from sensor_msgs.msg import CameraInfo, Image
        from tf2_ros import Buffer, TransformListener

        class NodeImpl(Node):
            pass

        self._node = NodeImpl("yolo_live_test_xyz")
        self._duration = Duration
        self._bridge = CvBridge()
        self._lock = threading.Lock()
        self._latest_color: Optional[Image] = None
        self._depth_frames: Deque[Image] = deque(maxlen=4)
        self._color_intrinsics: Optional[CameraIntrinsics] = None
        self._depth_intrinsics: Optional[CameraIntrinsics] = None
        self._depth_to_color: Optional[RigidTransform] = None
        self._color_to_link: Optional[RigidTransform] = None
        self._last_processed_stamp = -1
        self._warmed_up = False
        self._show_gui = not args.no_gui
        self._last_report_at = 0.0

        self._color_frame = "camera_color_optical_frame"
        self._depth_frame = "camera_depth_optical_frame"
        self._output_frame = "camera_link"
        self._max_pair_delta_ns = 30_000_000

        config = Yolo3DConfig(device=args.device)
        self._pipeline = Yolo3DPipeline(args.model, config)
        self._node.get_logger().info(f"Model ready: {self._pipeline.class_names}")

        sensor_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
        )
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self._node, spin_thread=True)
        self._node.create_subscription(Image, "/camera/color/image_raw", self._on_color, sensor_qos)
        self._node.create_subscription(Image, "/camera/depth/image_rect_raw", self._on_depth, sensor_qos)
        self._node.create_subscription(CameraInfo, "/camera/color/camera_info", self._on_color_info, sensor_qos)
        self._node.create_subscription(CameraInfo, "/camera/depth/camera_info", self._on_depth_info, sensor_qos)
        self._node.create_timer(1.0 / args.max_fps, self._process_latest)

    @property
    def node(self):
        return self._node

    def _on_color(self, message) -> None:
        with self._lock:
            self._latest_color = message

    def _on_depth(self, message) -> None:
        with self._lock:
            self._depth_frames.append(message)

    def _on_color_info(self, message) -> None:
        self._color_intrinsics = CameraIntrinsics(message.k[0], message.k[4], message.k[2], message.k[5])
        self._color_frame = message.header.frame_id or self._color_frame

    def _on_depth_info(self, message) -> None:
        self._depth_intrinsics = CameraIntrinsics(message.k[0], message.k[4], message.k[2], message.k[5])
        self._depth_frame = message.header.frame_id or self._depth_frame

    def _resolve_static_transforms(self) -> bool:
        if self._depth_to_color is not None and self._color_to_link is not None:
            return True
        try:
            timeout = self._duration(seconds=0.1)
            if self._depth_to_color is None:
                transform = self._tf_buffer.lookup_transform(
                    self._color_frame, self._depth_frame, rclpy.time.Time(), timeout=timeout
                )
                self._depth_to_color = transform_to_rigid(transform)
            if self._color_to_link is None:
                transform = self._tf_buffer.lookup_transform(
                    self._output_frame, self._color_frame, rclpy.time.Time(), timeout=timeout
                )
                self._color_to_link = transform_to_rigid(transform)
            return True
        except Exception as exc:
            self._node.get_logger().warn(f"Waiting for RealSense TF: {exc}", throttle_duration_sec=5.0)
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
            self._node.get_logger().warn(
                f"No depth within 30 ms of RGB; nearest is {delta_ns / 1e6:.1f} ms",
                throttle_duration_sec=2.0,
            )
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
                raise ValueError(f"Expected 16UC1 depth, received {depth.dtype}")
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
                self._color_to_link,
            )
            infer_ms = (time.perf_counter() - start) * 1000.0
            self._last_processed_stamp = stamp_ns(color_message)
            self._report(detections, infer_ms, delta_ns)
            if self._show_gui:
                cv2.imshow("YOLO Raw Depth XYZ [Q to quit]", self._annotate(color, detections, infer_ms, delta_ns))
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    import rclpy
                    rclpy.shutdown()
        except Exception as exc:
            self._node.get_logger().error(f"3-D validation error: {exc}", throttle_duration_sec=2.0)

    def _report(self, detections, infer_ms: float, delta_ns: int) -> None:
        now = time.monotonic()
        if now - self._last_report_at < 0.5:
            return
        self._last_report_at = now
        lines = []
        for detection in detections:
            if detection.position_valid:
                x, y, z = detection.position_m
                lines.append(f"{detection.class_name} xyz=({x:.3f}, {y:.3f}, {z:.3f})")
            else:
                lines.append(f"{detection.class_name} invalid depth ratio={detection.depth_valid_ratio:.2f}")
        self._node.get_logger().info(
            f"infer={infer_ms:.1f}ms rgb-depth={delta_ns / 1e6:.1f}ms " + "; ".join(lines or ["no detections"])
        )

    @staticmethod
    def _annotate(image: np.ndarray, detections, infer_ms: float, delta_ns: int) -> np.ndarray:
        annotated = image.copy()
        colors = {0: (0, 0, 255), 1: (0, 255, 0), 2: (0, 165, 255)}
        overlay = annotated.copy()
        for detection in detections:
            color = colors.get(detection.class_id, (255, 255, 255))
            overlay[detection.mask] = color
            x1, y1, x2, y2 = detection.bbox
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            if detection.position_valid:
                x, y, z = detection.position_m
                text = f"{detection.class_name} {x:.2f},{y:.2f},{z:.2f}m"
            else:
                text = f"{detection.class_name} depth invalid"
            cv2.putText(annotated, text, (x1, max(18, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 2)
        cv2.addWeighted(overlay, 0.35, annotated, 0.65, 0, annotated)
        cv2.putText(
            annotated,
            f"infer {infer_ms:.0f} ms | RGB-Depth {delta_ns / 1e6:.1f} ms",
            (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2,
        )
        return annotated


def main() -> None:
    args, ros_args = parse_args()
    if args.max_fps <= 0:
        raise ValueError("--max-fps must be positive")
    import rclpy
    from rclpy.executors import MultiThreadedExecutor

    rclpy.init(args=ros_args)
    app = YoloLiveTestXyz(args)
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(app.node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        app.node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
