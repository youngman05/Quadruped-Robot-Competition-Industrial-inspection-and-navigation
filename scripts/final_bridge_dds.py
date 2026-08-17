#!/usr/bin/env python3
"""Bridge cuVSLAM odometry directly over DDS to host /odom.

This is the same frame/pose policy as final_bridge.py, but it subscribes to
``/visual_slam/tracking/odometry`` directly instead of running a Docker UDP
exporter and receiving datagrams on the host.
"""

from __future__ import annotations

import argparse
import json
import math
import time

import rclpy
from geometry_msgs.msg import TransformStamped
from nav_msgs.msg import Odometry
from rclpy.qos import QoSProfile, ReliabilityPolicy
from tf2_ros import TransformBroadcaster

try:
    from rclpy.qos import HistoryPolicy
except ImportError:
    from rclpy.qos import QoSHistoryPolicy as HistoryPolicy

import final_bridge as fb


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-topic",
        default="/visual_slam/tracking/odometry",
        help="DDS topic published by cuVSLAM inside the Docker container.",
    )
    parser.add_argument("--qos-depth", type=int, default=1)
    parser.add_argument("--stale-drop-ms", type=float, default=1000.0)
    parser.add_argument("--log-every", type=int, default=300)
    parser.add_argument("--camera-frame", default="camera_link")
    parser.add_argument("--base-frame", default="base_link")
    parser.add_argument("--odom-frame", default="odom")
    parser.add_argument(
        "--transform-camera-pose-to-base",
        dest="transform_camera_pose_to_base",
        action="store_true",
        default=True,
    )
    parser.add_argument(
        "--no-transform-camera-pose-to-base",
        dest="transform_camera_pose_to_base",
        action="store_false",
    )
    parser.add_argument("--base-to-camera-x", type=float, default=0.080)
    parser.add_argument("--base-to-camera-y", type=float, default=0.000)
    parser.add_argument("--base-to-camera-z", type=float, default=0.493)
    parser.add_argument("--base-to-camera-roll", type=float, default=0.0)
    parser.add_argument("--base-to-camera-pitch", type=float, default=0.523599)
    parser.add_argument("--base-to-camera-yaw", type=float, default=0.0)
    parser.add_argument(
        "--camera-world-rebase",
        choices=("camera_start", "base_start"),
        default="camera_start",
    )
    parser.add_argument(
        "--planarize-output",
        action="store_true",
    )
    return parser.parse_args()


def odometry_to_payload(msg: Odometry):
    return {
        "stamp": {
            "sec": int(msg.header.stamp.sec),
            "nanosec": int(msg.header.stamp.nanosec),
        },
        "frame_id": str(msg.header.frame_id),
        "child_frame_id": str(msg.child_frame_id),
        "pose": {
            "position": {
                "x": float(msg.pose.pose.position.x),
                "y": float(msg.pose.pose.position.y),
                "z": float(msg.pose.pose.position.z),
            },
            "orientation": {
                "x": float(msg.pose.pose.orientation.x),
                "y": float(msg.pose.pose.orientation.y),
                "z": float(msg.pose.pose.orientation.z),
                "w": float(msg.pose.pose.orientation.w),
            },
        },
        "pose_covariance": list(msg.pose.covariance),
        "twist": {
            "linear": {
                "x": float(msg.twist.twist.linear.x),
                "y": float(msg.twist.twist.linear.y),
                "z": float(msg.twist.twist.linear.z),
            },
            "angular": {
                "x": float(msg.twist.twist.angular.x),
                "y": float(msg.twist.twist.angular.y),
                "z": float(msg.twist.twist.angular.z),
            },
        },
        "twist_covariance": list(msg.twist.covariance),
    }


def write_latest_file(msg: Odometry, stamp_source: str, source_child: str, transform_mode: str):
    try:
        with open("/tmp/odom_latest.json", "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "x": float(msg.pose.pose.position.x),
                    "y": float(msg.pose.pose.position.y),
                    "z": float(msg.pose.pose.position.z),
                    "qx": float(msg.pose.pose.orientation.x),
                    "qy": float(msg.pose.pose.orientation.y),
                    "qz": float(msg.pose.pose.orientation.z),
                    "qw": float(msg.pose.pose.orientation.w),
                    "stamp": stamp_source,
                    "source_child_frame_id": source_child,
                    "transform_mode": transform_mode,
                },
                handle,
            )
    except Exception:
        pass


def main():
    args = parse_args()
    rclpy.init()
    qos = QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=max(1, int(args.qos_depth)),
        reliability=ReliabilityPolicy.BEST_EFFORT,
    )
    node = rclpy.create_node("final_bridge_dds")
    pub = node.create_publisher(Odometry, "/odom", qos)
    tf_broadcaster = TransformBroadcaster(node)
    transform_config = fb.make_transform_config(args)

    node.get_logger().info(
        "DDS odom bridge ready | input=%s | camera=%s base=%s "
        "world_rebase=%s planarize=%s"
        % (
            args.input_topic,
            transform_config["camera_frame"],
            transform_config["base_frame"],
            transform_config["camera_world_rebase"],
            transform_config["planarize_output"],
        )
    )

    state = {
        "count": 0,
        "dropped_stale": 0,
        "dropped_invalid": 0,
        "self_verified": 0,
    }

    def self_cb(msg: Odometry):
        state["self_verified"] += 1

    node.create_subscription(Odometry, "/odom", self_cb, qos)

    def on_odometry(msg: Odometry):
        payload = odometry_to_payload(msg)
        source_time = fb.payload_stamp_seconds(payload)
        now_s = node.get_clock().now().nanoseconds / 1e9
        latency_ms = None
        if source_time is not None:
            latency_ms = (now_s - source_time) * 1000.0
            if args.stale_drop_ms > 0 and latency_ms > args.stale_drop_ms:
                state["dropped_stale"] += 1
                if (
                    args.log_every > 0
                    and state["dropped_stale"] % args.log_every == 1
                ):
                    node.get_logger().warn(
                        "dropped stale DDS odom latency=%.2f ms > %.2f ms"
                        % (latency_ms, args.stale_drop_ms)
                    )
                return

        out = Odometry()
        try:
            stamp_source, source_child, transform_mode = fb.fill_odometry(
                out, payload, node, transform_config
            )
        except ValueError as exc:
            state["dropped_invalid"] += 1
            node.get_logger().warn(
                "dropping DDS odom packet: %s" % exc,
                throttle_duration_sec=2.0,
            )
            return

        pub.publish(out)
        transform = TransformStamped()
        fb.fill_transform(transform, out)
        tf_broadcaster.sendTransform(transform)
        state["count"] += 1
        write_latest_file(out, stamp_source, source_child, transform_mode)

        if args.log_every > 0 and state["count"] % args.log_every == 1:
            latency_text = "nan" if latency_ms is None else "%.2f ms" % latency_ms
            node.get_logger().info(
                "bridged %d DDS msgs | latency=%s | stale=%d invalid=%d "
                "self_verified=%d | source_child=%s mode=%s"
                % (
                    state["count"],
                    latency_text,
                    state["dropped_stale"],
                    state["dropped_invalid"],
                    state["self_verified"],
                    source_child,
                    transform_mode,
                )
            )

    node.create_subscription(Odometry, args.input_topic, on_odometry, qos)
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
