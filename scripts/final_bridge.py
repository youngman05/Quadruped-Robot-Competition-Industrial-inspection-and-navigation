#!/usr/bin/env python3
"""
Odom bridge: Docker cuVSLAM → Host /odom via shared JSON file.

Docker runs odom_relay_docker.py which writes latest_odom.json
to the shared filesystem. This script reads it and publishes
/odom + TF on the host. No DDS cross-version, no docker exec zombies.
"""
import json
import math
import os
import time
from pathlib import Path

import rclpy
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformBroadcaster
from rclpy.qos import QoSProfile, ReliabilityPolicy

RELAY_FILE = Path.home() / "workspaces/isaac_ros-dev/camera_frames/latest_odom.json"
PUBLISH_RATE = 30.0  # Hz (match cuVSLAM odom rate)


rclpy.init()
be = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
node = rclpy.create_node("final_bridge")
pub = node.create_publisher(Odometry, "/odom", be)
tf_br = TransformBroadcaster(node)

# Self-verification
verify_count = [0]
def self_cb(msg):
    verify_count[0] += 1
node.create_subscription(Odometry, "/odom", self_cb, be)

node.get_logger().info(f"Reading odom from {RELAY_FILE}")

# Track file modification to avoid re-reading stale data
last_mtime = 0
bridged = 0

while rclpy.ok():
    rclpy.spin_once(node, timeout_sec=1.0 / PUBLISH_RATE)

    if not RELAY_FILE.exists():
        continue

    mtime = os.stat(str(RELAY_FILE)).st_mtime
    if mtime == last_mtime:
        continue
    last_mtime = mtime

    try:
        with open(RELAY_FILE, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        continue

    x = data.get("x", 0.0)
    y = data.get("y", 0.0)
    z = data.get("z", 0.0)
    qx = data.get("qx", 0.0)
    qy = data.get("qy", 0.0)
    qz = data.get("qz", 0.0)
    qw = data.get("qw", 1.0)

    now = node.get_clock().now().to_msg()

    msg = Odometry()
    msg.header.stamp = now
    msg.header.frame_id = "odom"
    msg.child_frame_id = "base_link"
    msg.pose.pose.position.x = x
    msg.pose.pose.position.y = y
    msg.pose.pose.position.z = z
    msg.pose.pose.orientation.x = qx
    msg.pose.pose.orientation.y = qy
    msg.pose.pose.orientation.z = qz
    msg.pose.pose.orientation.w = qw
    pub.publish(msg)

    t = TransformStamped()
    t.header.stamp = now
    t.header.frame_id = "odom"
    t.child_frame_id = "base_link"
    t.transform.translation.x = x
    t.transform.translation.y = y
    t.transform.translation.z = z
    t.transform.rotation.x = qx
    t.transform.rotation.y = qy
    t.transform.rotation.z = qz
    t.transform.rotation.w = qw
    tf_br.sendTransform(t)

    bridged += 1
    if bridged % 300 == 1:
        node.get_logger().info(
            f"bridged {bridged} msgs | self-verify: {verify_count[0]}"
        )

node.get_logger().info(f"DONE: {bridged} bridged, {verify_count[0]} self-verified")
rclpy.shutdown()
