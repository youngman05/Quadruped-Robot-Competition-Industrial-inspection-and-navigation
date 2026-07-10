#!/usr/bin/env python3
"""Export cuVSLAM Odometry from Docker to the host over localhost UDP."""
import argparse
import json
import socket

import rclpy
from nav_msgs.msg import Odometry
from rclpy.qos import QoSProfile, ReliabilityPolicy

try:
    from rclpy.qos import HistoryPolicy
except ImportError:
    from rclpy.qos import QoSHistoryPolicy as HistoryPolicy


def covariance_to_list(values):
    return [float(value) for value in values]


def odometry_to_payload(msg):
    pose = msg.pose.pose
    twist = msg.twist.twist
    return {
        "stamp": {
            "sec": int(msg.header.stamp.sec),
            "nanosec": int(msg.header.stamp.nanosec),
        },
        "frame_id": msg.header.frame_id,
        "child_frame_id": msg.child_frame_id,
        "pose": {
            "position": {
                "x": float(pose.position.x),
                "y": float(pose.position.y),
                "z": float(pose.position.z),
            },
            "orientation": {
                "x": float(pose.orientation.x),
                "y": float(pose.orientation.y),
                "z": float(pose.orientation.z),
                "w": float(pose.orientation.w),
            },
        },
        "pose_covariance": covariance_to_list(msg.pose.covariance),
        "twist": {
            "linear": {
                "x": float(twist.linear.x),
                "y": float(twist.linear.y),
                "z": float(twist.linear.z),
            },
            "angular": {
                "x": float(twist.angular.x),
                "y": float(twist.angular.y),
                "z": float(twist.angular.z),
            },
        },
        "twist_covariance": covariance_to_list(msg.twist.covariance),
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", default="/visual_slam/tracking/odometry")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=19001)
    parser.add_argument("--qos-depth", type=int, default=1)
    parser.add_argument("--log-every", type=int, default=300)
    return parser.parse_args()


def main():
    args = parse_args()
    rclpy.init()
    node = rclpy.create_node("cuvslam_odometry_udp_exporter")
    qos = QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=args.qos_depth,
        reliability=ReliabilityPolicy.BEST_EFFORT,
    )
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = (args.host, args.port)
    count = 0

    def callback(msg):
        nonlocal count
        count += 1
        payload = odometry_to_payload(msg)
        payload["seq"] = count
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        sock.sendto(data, target)
        if args.log_every > 0 and count % args.log_every == 1:
            stamp = payload["stamp"]
            node.get_logger().info(
                f"sent {count} odom UDP packets to {args.host}:{args.port} "
                f"stamp={stamp['sec']}.{stamp['nanosec']:09d}"
            )

    node.create_subscription(Odometry, args.topic, callback, qos)
    node.get_logger().info(
        f"exporting {args.topic} to udp://{args.host}:{args.port}"
    )
    try:
        rclpy.spin(node)
    finally:
        sock.close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
