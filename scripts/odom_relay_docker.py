#!/usr/bin/env python3
"""
Runs INSIDE Docker: subscribes to /visual_slam/tracking/odometry,
writes latest pose as JSON to a shared file on the host filesystem.

Replaces: docker exec + stdbuf ros2 topic echo pipeline
Advantage: no DDS cross-version issues, no zombie processes,
           atomic writes, JSON easier to parse than YAML.
"""
import json
import os
import rclpy
from nav_msgs.msg import Odometry

OUT_DIR = "/workspaces/isaac_ros-dev/camera_frames"
OUT_FILE = os.path.join(OUT_DIR, "latest_odom.json")
TMP_FILE = OUT_FILE + ".tmp"

count = 0

def callback(msg: Odometry):
    global count
    p = msg.pose.pose
    q = p.orientation
    data = {
        "x": p.position.x,
        "y": p.position.y,
        "z": p.position.z,
        "qx": q.x,
        "qy": q.y,
        "qz": q.z,
        "qw": q.w,
    }
    # Atomic write
    with open(TMP_FILE, "w") as f:
        json.dump(data, f)
    os.rename(TMP_FILE, OUT_FILE)
    count += 1
    if count % 100 == 1:
        print(f"Odom {count} frames", flush=True)


rclpy.init()
node = rclpy.create_node("odom_relay")
node.create_subscription(Odometry, "/visual_slam/tracking/odometry", callback, 10)
node.get_logger().info(f"Writing odometry to {OUT_FILE}")
rclpy.spin(node)
