"""ROS2 node: D455 gauge status detection via YOLO."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String

_ROOT = Path(__file__).resolve().parents[3]
_SRC = str(_ROOT / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from cv.gauge_detector import GaugeDetector
from cv.realsense_camera import RealsenseCamera


class GaugeStatusNode(Node):
    """Read D455 RGB, run YOLO detection, publish status."""

    def __init__(self) -> None:
        super().__init__("gauge_status_node")

        self.declare_parameter("interval_sec", 0.5)
        self.declare_parameter("status_topic", "/gauge/status")
        self.declare_parameter("detected_topic", "/gauge/detected")

        interval = float(self.get_parameter("interval_sec").value)
        status_topic = str(self.get_parameter("status_topic").value)
        detected_topic = str(self.get_parameter("detected_topic").value)

        self._status_pub = self.create_publisher(String, status_topic, 10)
        self._detected_pub = self.create_publisher(Bool, detected_topic, 10)

        self._detector = GaugeDetector()
        self._camera = RealsenseCamera.for_gauge()
        self._camera.start(warmup_frames=30)

        self.get_logger().info(f"Gauge status node ready. Publishing to {status_topic}")
        self._timer = self.create_timer(interval, self._process_frame)

    def _process_frame(self) -> None:
        try:
            image = self._camera.get_color_image()
            if image is None:
                return

            result = self._detector.detect(image)

            letter = result.best_letter
            gauge = result.best_gauge

            payload = {
                "detected": letter is not None,
                "area": letter.label if letter else None,
                "letter_conf": round(letter.conf, 4) if letter else None,
                "color": gauge.color if gauge else None,
                "gauge_conf": round(gauge.conf, 4) if gauge else None,
            }

            self._status_pub.publish(String(data=json.dumps(payload)))
            self._detected_pub.publish(Bool(data=letter is not None))

        except Exception as exc:
            self.get_logger().error(f"Processing error: {exc}")

    def destroy_node(self) -> bool:
        try:
            self._camera.stop()
        except Exception:
            pass
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = GaugeStatusNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
