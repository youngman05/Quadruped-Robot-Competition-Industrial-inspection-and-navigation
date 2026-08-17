#!/usr/bin/env python3
"""Capture one left and one right D455 IR image and save them as PNG."""

from __future__ import annotations

import time

import cv2
import rclpy
from cv_bridge import CvBridge
from sensor_msgs.msg import Image


def main() -> None:
    rclpy.init()
    node = rclpy.create_node("capture_ir_pair")
    bridge = CvBridge()
    latest = {}

    def make_callback(topic: str):
        def callback(msg: Image) -> None:
            try:
                image = bridge.imgmsg_to_cv2(msg, "passthrough")
                if image.dtype == "uint16":
                    image = cv2.normalize(
                        image, None, 0, 255, cv2.NORM_MINMAX
                    ).astype("uint8")
                if len(image.shape) == 3:
                    image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                latest[topic] = image
            except Exception as exc:  # noqa: BLE001
                node.get_logger().error("convert %s failed: %s" % (topic, exc))

        return callback

    node.create_subscription(
        Image,
        "/camera/infra1/image_rect_raw",
        make_callback("left"),
        10,
    )
    node.create_subscription(
        Image,
        "/camera/infra2/image_rect_raw",
        make_callback("right"),
        10,
    )

    deadline = time.time() + 10.0
    while rclpy.ok() and time.time() < deadline:
        rclpy.spin_once(node, timeout_sec=0.2)
        if "left" in latest and "right" in latest:
            break

    for side in ("left", "right"):
        if side in latest:
            path = "/tmp/ir_%s.png" % side
            cv2.imwrite(path, latest[side])
            print("%s=%s" % (side, path))
        else:
            print("%s=missing" % side)

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
