#!/usr/bin/env python3
"""Runs inside Docker: subscribes /camera/depth/image_rect_raw, writes numpy to shared dir."""
import rclpy, os, struct, time
from sensor_msgs.msg import Image

OUT_DIR = "/workspaces/isaac_ros-dev/camera_frames"
os.makedirs(OUT_DIR, exist_ok=True)
LATEST_DEPTH = os.path.join(OUT_DIR, "latest_depth.raw")
LATEST_META = os.path.join(OUT_DIR, "latest_depth_meta.txt")

count = 0
w = h = 0


def callback(msg):
    global count, w, h
    w, h = msg.width, msg.height
    tmp = LATEST_DEPTH + ".tmp"
    with open(tmp, "wb") as f:
        f.write(msg.data)  # raw uint16
    os.rename(tmp, LATEST_DEPTH)
    with open(LATEST_META, "w") as f:
        f.write(f"{msg.width} {msg.height} {msg.header.stamp.sec}.{msg.header.stamp.nanosec:09d}")
    count += 1
    if count % 50 == 1:
        print(f"Depth {count} frames ({w}x{h})", flush=True)


rclpy.init()
node = rclpy.create_node("depth_relay")
node.create_subscription(Image, "/camera/depth/image_rect_raw", callback, 10)
node.get_logger().info(f"Writing depth to {LATEST_DEPTH}")
rclpy.spin(node)
