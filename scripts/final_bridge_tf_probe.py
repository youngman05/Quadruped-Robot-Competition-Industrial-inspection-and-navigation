#!/usr/bin/env python3
"""Verify final_bridge /odom and TF visibility with synthetic UDP data."""

import argparse
import json
import socket
import time

import rclpy
from nav_msgs.msg import Odometry
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from tf2_ros import Buffer, TransformException, TransformListener


class FinalBridgeTfProbe(Node):
    def __init__(self, args):
        super().__init__("final_bridge_tf_probe")
        self.args = args
        self.odom_count = 0
        self.tf_success_count = 0
        self.last_transform = None
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT,
        )
        self.create_subscription(Odometry, args.odom_topic, self.odom_callback, qos)

    def odom_callback(self, _msg):
        self.odom_count += 1

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        deadline = time.monotonic() + self.args.duration
        next_send = time.monotonic()
        sequence = 0
        try:
            while rclpy.ok() and time.monotonic() < deadline:
                now = time.monotonic()
                if now >= next_send:
                    self.send_payload(sock, sequence)
                    sequence += 1
                    next_send = now + 1.0 / self.args.send_rate
                rclpy.spin_once(self, timeout_sec=0.02)
                self.capture_transform()
        finally:
            sock.close()

        return {
            "udp_sent": sequence,
            "odom_received": self.odom_count,
            "tf_success_count": self.tf_success_count,
            "last_transform": self.last_transform,
        }

    def send_payload(self, sock, sequence):
        now_ns = time.time_ns()
        payload = {
            "frame_id": "odom",
            "child_frame_id": "base_link",
            "stamp": {
                "sec": now_ns // 1_000_000_000,
                "nanosec": now_ns % 1_000_000_000,
            },
            "pose": {
                "position": {"x": sequence * 0.001, "y": 0.0, "z": 0.0},
                "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
            },
            "twist": {
                "linear": {"x": 0.02, "y": 0.0, "z": 0.0},
                "angular": {"x": 0.0, "y": 0.0, "z": 0.0},
            },
        }
        sock.sendto(
            json.dumps(payload).encode("utf-8"),
            (self.args.host, self.args.port),
        )

    def capture_transform(self):
        try:
            transform = self.tf_buffer.lookup_transform(
                self.args.odom_frame,
                self.args.base_frame,
                Time(),
                timeout=Duration(seconds=0.02),
            )
        except TransformException:
            return

        self.tf_success_count += 1
        translation = transform.transform.translation
        self.last_transform = {
            "x": translation.x,
            "y": translation.y,
            "z": translation.z,
            "stamp_sec": transform.header.stamp.sec,
            "stamp_nanosec": transform.header.stamp.nanosec,
        }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=19002)
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--send-rate", type=float, default=30.0)
    parser.add_argument("--odom-topic", default="/odom")
    parser.add_argument("--odom-frame", default="odom")
    parser.add_argument("--base-frame", default="base_link")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.duration <= 0.0:
        raise SystemExit("--duration must be > 0")
    if args.send_rate <= 0.0:
        raise SystemExit("--send-rate must be > 0")

    rclpy.init()
    node = FinalBridgeTfProbe(args)
    try:
        result = node.run()
        print(json.dumps(result, indent=2, sort_keys=True))
        if result["odom_received"] == 0 or result["tf_success_count"] == 0:
            raise SystemExit(2)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
