#!/usr/bin/env python3
"""Save the latest ROS D455 color frame when S is pressed in the terminal."""

from __future__ import annotations

import argparse
import select
import sys
import termios
import tty
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image


class D455FrameCapture(Node):
    def __init__(self, topic: str) -> None:
        super().__init__("d455_frame_capture")
        self.latest: Optional[Image] = None
        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
        )
        self.create_subscription(Image, topic, self._on_image, qos)

    def _on_image(self, message: Image) -> None:
        self.latest = message


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Press S to save the latest D455 ROS color frame; Q quits")
    parser.add_argument("--topic", default="/camera/color/image_raw")
    parser.add_argument("--output-dir", type=Path, default=Path("captures/d455_frames"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not sys.stdin.isatty():
        print("run this script in an interactive terminal", file=sys.stderr)
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    bridge = CvBridge()
    rclpy.init()
    node = D455FrameCapture(args.topic)
    original_terminal = termios.tcgetattr(sys.stdin.fileno())
    tty.setcbreak(sys.stdin.fileno())
    print("Waiting for {}. Press S to save, Q to quit.".format(args.topic))
    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.05)
            readable, _, _ = select.select([sys.stdin], [], [], 0.0)
            if not readable:
                continue
            key = sys.stdin.read(1).lower()
            if key == "q":
                break
            if key != "s":
                continue
            if node.latest is None:
                print("No frame received yet.")
                continue
            image = bridge.imgmsg_to_cv2(node.latest, desired_encoding="bgr8")
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = args.output_dir / "d455_{}.png".format(stamp)
            if cv2.imwrite(str(path), image):
                print("Saved {} ({}x{}).".format(path, image.shape[1], image.shape[0]))
            else:
                print("Failed to save {}.".format(path), file=sys.stderr)
    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, original_terminal)
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
