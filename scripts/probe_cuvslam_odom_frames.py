#!/usr/bin/env python3
"""Probe cuVSLAM Odometry frame ids for integration tests."""

import argparse
import json
import time

import rclpy
from nav_msgs.msg import Odometry
from rclpy.qos import QoSProfile, ReliabilityPolicy


DEFAULT_TOPICS = (
    "/visual_slam/tracking/odometry",
    "/visual_slam/vis/slam_odometry",
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--topic", action="append", dest="topics")
    args = parser.parse_args()

    topics = tuple(args.topics or DEFAULT_TOPICS)
    samples = {}

    rclpy.init()
    node = rclpy.create_node("cuvslam_odom_frame_probe")
    qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)

    def make_callback(topic):
        def callback(msg):
            samples[topic] = {
                "header_frame_id": msg.header.frame_id,
                "child_frame_id": msg.child_frame_id,
                "stamp": {
                    "sec": msg.header.stamp.sec,
                    "nanosec": msg.header.stamp.nanosec,
                },
                "position": {
                    "x": msg.pose.pose.position.x,
                    "y": msg.pose.pose.position.y,
                    "z": msg.pose.pose.position.z,
                },
                "linear": {
                    "x": msg.twist.twist.linear.x,
                    "y": msg.twist.twist.linear.y,
                    "z": msg.twist.twist.linear.z,
                },
                "angular": {
                    "x": msg.twist.twist.angular.x,
                    "y": msg.twist.twist.angular.y,
                    "z": msg.twist.twist.angular.z,
                },
            }

        return callback

    subscriptions = [
        node.create_subscription(Odometry, topic, make_callback(topic), qos)
        for topic in topics
    ]

    deadline = time.time() + args.timeout
    try:
        while rclpy.ok() and time.time() < deadline and len(samples) < len(topics):
            rclpy.spin_once(node, timeout_sec=0.2)
    finally:
        for subscription in subscriptions:
            node.destroy_subscription(subscription)
        node.destroy_node()
        rclpy.shutdown()

    print(json.dumps(samples, indent=2, sort_keys=True))
    missing = [topic for topic in topics if topic not in samples]
    if missing:
        print("missing_topics=" + ",".join(missing))
        raise SystemExit(3)


if __name__ == "__main__":
    main()
