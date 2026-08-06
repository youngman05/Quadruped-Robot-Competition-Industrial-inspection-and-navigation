#!/usr/bin/env python3
"""Export cuVSLAM rectified SLAM pose without touching the VO bridge contract."""

import argparse
import json
import socket
import time

try:
    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.qos import QoSProfile, ReliabilityPolicy

    try:
        from rclpy.qos import HistoryPolicy
    except ImportError:
        from rclpy.qos import QoSHistoryPolicy as HistoryPolicy
except ImportError:  # Allows the payload contract to be tested off-robot.
    rclpy = None
    Odometry = object
    QoSProfile = ReliabilityPolicy = HistoryPolicy = None


def odometry_to_payload(message, sequence, receive_time=None):
    pose = message.pose.pose
    twist = message.twist.twist
    source_frame = str(message.header.frame_id or "").strip()
    return {
        "bridge_kind": "slam_pose",
        "seq": int(sequence),
        "stamp": {
            "sec": int(message.header.stamp.sec),
            "nanosec": int(message.header.stamp.nanosec),
        },
        "source_frame_id": source_frame,
        "frame_id": "vslam_map",
        "child_frame_id": str(message.child_frame_id or "").strip(),
        "receive_time": float(time.time() if receive_time is None else receive_time),
        "tracking_ok": True,
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
        "pose_covariance": [float(value) for value in message.pose.covariance],
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
        "twist_covariance": [float(value) for value in message.twist.covariance],
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", default="/visual_slam/vis/slam_odometry")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=19002)
    parser.add_argument("--qos-depth", type=int, default=10)
    parser.add_argument("--qos-reliability", choices=("best_effort", "reliable"), default="reliable")
    parser.add_argument("--log-every", type=int, default=300)
    return parser.parse_args()


def main():
    if rclpy is None:
        raise RuntimeError("cuvslam_slam_pose_udp_exporter requires ROS 2 rclpy")
    args = parse_args()
    rclpy.init()
    node = rclpy.create_node("cuvslam_slam_pose_udp_exporter")
    qos = QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=args.qos_depth,
        reliability=(
            ReliabilityPolicy.RELIABLE
            if args.qos_reliability == "reliable"
            else ReliabilityPolicy.BEST_EFFORT
        ),
    )
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = (args.host, args.port)
    count = 0

    def callback(message):
        nonlocal count
        count += 1
        payload = odometry_to_payload(message, count)
        sock.sendto(json.dumps(payload, separators=(",", ":")).encode("utf-8"), target)
        if args.log_every > 0 and count % args.log_every == 1:
            stamp = payload["stamp"]
            node.get_logger().info(
                "sent %d SLAM pose packets to %s:%d stamp=%d.%09d source_frame=%s"
                % (count, args.host, args.port, stamp["sec"], stamp["nanosec"], payload["source_frame_id"])
            )

    node.create_subscription(Odometry, args.topic, callback, qos)
    node.get_logger().info("exporting %s as vslam_map to udp://%s:%d" % (args.topic, args.host, args.port))
    try:
        rclpy.spin(node)
    finally:
        sock.close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
