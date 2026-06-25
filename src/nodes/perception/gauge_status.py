#!/usr/bin/env python3
"""ROS2 node that publishes D455 OpenCV gauge recognition status."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
import sys

import cv2
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import Bool, String

ROOT = Path(__file__).resolve().parents[3]  # perception → nodes → src → root

# ── CV detection + validation ──────────────────────
_GAUGE_DIR = ROOT / "src" / "cv" / "gauge_detector"
if str(_GAUGE_DIR) not in sys.path:
    sys.path.insert(0, str(_GAUGE_DIR))

from gauge_detector import detect_gauge  # noqa: E402
from live_validation import (  # noqa: E402
    GaugeStabilityTracker,    GaugeValidationConfig,
    is_valid_gauge_result,
    make_status_payload,
)

# ── Camera wrapper ─────────────────────────────────
_SRC = ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cv.realsense_camera import RealsenseCamera  # noqa: E402


class GaugeStatusNode(Node):
    """Read D455 RGB frames, run OpenCV gauge detection, and publish status."""

    def __init__(self) -> None:
        super().__init__("gauge_status_node")

        self.declare_parameter("width", 640)
        self.declare_parameter("height", 480)
        self.declare_parameter("fps", 30)
        self.declare_parameter("interval_sec", 0.5)
        self.declare_parameter("frame_id", "d455_color_optical_frame")
        self.declare_parameter("status_topic", "/gauge/status")
        self.declare_parameter("detected_topic", "/gauge/detected")
        self.declare_parameter("publish_invalid", True)
        self.declare_parameter("verbose_invalid", False)
        self.declare_parameter("debug_dir", "")
        self.declare_parameter("min_color_ratio", 0.04)
        self.declare_parameter("min_direction_score", 100)
        self.declare_parameter("min_zone_pixels", 300)
        self.declare_parameter("max_zone_fraction", 0.62)
        self.declare_parameter("min_direction_margin", 2.0)
        self.declare_parameter("stable_frame_count", 3)

        self._width = int(self.get_parameter("width").value)
        self._height = int(self.get_parameter("height").value)
        self._fps = int(self.get_parameter("fps").value)
        self._interval_sec = float(self.get_parameter("interval_sec").value)
        self._frame_id = str(self.get_parameter("frame_id").value)
        status_topic = str(self.get_parameter("status_topic").value)
        detected_topic = str(self.get_parameter("detected_topic").value)
        self._publish_invalid = bool(self.get_parameter("publish_invalid").value)
        self._verbose_invalid = bool(self.get_parameter("verbose_invalid").value)
        debug_dir_value = str(self.get_parameter("debug_dir").value)
        self._debug_dir = Path(debug_dir_value) if debug_dir_value else None
        if self._debug_dir:
            self._debug_dir.mkdir(parents=True, exist_ok=True)

        self._validation_config = GaugeValidationConfig(
            min_color_ratio=float(self.get_parameter("min_color_ratio").value),
            min_direction_score=int(self.get_parameter("min_direction_score").value),
            min_zone_pixels=int(self.get_parameter("min_zone_pixels").value),
            max_zone_fraction=float(self.get_parameter("max_zone_fraction").value),
            min_direction_margin=float(self.get_parameter("min_direction_margin").value),
        )
        self._stability_tracker = GaugeStabilityTracker(
            required_count=int(self.get_parameter("stable_frame_count").value)
        )

        self._status_pub = self.create_publisher(String, status_topic, 10)
        self._detected_pub = self.create_publisher(Bool, detected_topic, 10)
        self._tmp_path = Path(tempfile.gettempdir()) / "d455_gauge_ros_frame.jpg"
        self._frame_count = 0

        # 使用 RealsenseCamera 封装替代裸 pyrealsense2 管线
        self._camera = RealsenseCamera.for_gauge(width=self._width, height=self._height)
        self._camera.start(warmup_frames=30)
        self.get_logger().info(
            f"D455 started: {self._camera.device_name}, serial={self._camera.serial}"
        )
        self.get_logger().info(f"Publishing gauge status on {status_topic}")

        self._timer = self.create_timer(self._interval_sec, self._process_frame)

    def destroy_node(self) -> bool:
        try:
            self._camera.stop()
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warning(f"Failed to stop D455 camera cleanly: {exc}")
        # 清理临时图片
        try:
            self._tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return super().destroy_node()

    def _process_frame(self) -> None:
        try:
            image = self._camera.get_color_image()
            if image is None:
                self._publish_status(None, False, "no_color_frame")
                return

            cv2.imwrite(str(self._tmp_path), image)

            debug_out = None
            if self._debug_dir:
                debug_out = str(self._debug_dir / f"gauge_ros_{self._frame_count:04d}_debug.jpg")

            result = detect_gauge(str(self._tmp_path), debug=bool(debug_out), debug_out=debug_out)
            valid, reason = is_valid_gauge_result(result, self._validation_config)
            self._publish_status(result, valid, reason)
            self._frame_count += 1
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f"Gauge processing failed: {exc}")
            self._publish_status(None, False, "processing_exception")

    def _publish_status(self, result, valid: bool, reason: str) -> None:
        stability = self._stability_tracker.update(result, valid)
        if not valid and not self._publish_invalid:
            return
        if not valid and self._verbose_invalid:
            self.get_logger().info(f"Invalid gauge result: {reason}")

        stamp = self.get_clock().now().to_msg()
        payload = make_status_payload(
            result=result,
            valid=valid,
            reason=reason,
            frame_id=self._frame_id,
            stamp_sec=stamp.sec,
            stamp_nanosec=stamp.nanosec,
            stability=stability,
        )

        status_msg = String()
        status_msg.data = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        self._status_pub.publish(status_msg)

        detected_msg = Bool()
        detected_msg.data = bool(valid)
        self._detected_pub.publish(detected_msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = GaugeStatusNode()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
