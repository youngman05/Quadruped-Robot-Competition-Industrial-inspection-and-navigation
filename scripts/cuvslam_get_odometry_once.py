#!/usr/bin/env python3
"""Capture one cuVSLAM tracking odometry sample or compare two captures."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path


def normalize_angle(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def quaternion_to_yaw(x, y, z, w):
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm < 1.0e-12:
        raise ValueError("odometry quaternion norm is zero")
    x, y, z, w = (value / norm for value in (x, y, z, w))
    return math.atan2(
        2.0 * (w * z + x * y),
        1.0 - 2.0 * (y * y + z * z),
    )


def odometry_to_document(message, topic, captured_at_unix=None):
    position = message.pose.pose.position
    orientation = message.pose.pose.orientation
    stamp = message.header.stamp
    yaw = quaternion_to_yaw(
        float(orientation.x),
        float(orientation.y),
        float(orientation.z),
        float(orientation.w),
    )
    return {
        "captured_at_unix": float(
            time.time() if captured_at_unix is None else captured_at_unix
        ),
        "topic": str(topic),
        "frame_id": str(message.header.frame_id),
        "child_frame_id": str(message.child_frame_id),
        "header_stamp_sec": float(stamp.sec) + float(stamp.nanosec) / 1.0e9,
        "position": {
            "x": float(position.x),
            "y": float(position.y),
            "z": float(position.z),
        },
        "orientation": {
            "x": float(orientation.x),
            "y": float(orientation.y),
            "z": float(orientation.z),
            "w": float(orientation.w),
        },
        "yaw_rad": yaw,
        "yaw_deg": math.degrees(yaw),
    }


def compare_documents(start, end):
    if start.get("topic") != end.get("topic"):
        raise ValueError("capture topics do not match")
    if start.get("frame_id") != end.get("frame_id"):
        raise ValueError("capture frame_id values do not match")
    if start.get("child_frame_id") != end.get("child_frame_id"):
        raise ValueError("capture child_frame_id values do not match")

    start_position = start["position"]
    end_position = end["position"]
    dx = float(end_position["x"]) - float(start_position["x"])
    dy = float(end_position["y"]) - float(start_position["y"])
    dz = float(end_position["z"]) - float(start_position["z"])
    dyaw = normalize_angle(float(end["yaw_rad"]) - float(start["yaw_rad"]))
    return {
        "topic": start["topic"],
        "frame_id": start["frame_id"],
        "child_frame_id": start["child_frame_id"],
        "start_header_stamp_sec": float(start["header_stamp_sec"]),
        "end_header_stamp_sec": float(end["header_stamp_sec"]),
        "elapsed_header_sec": (
            float(end["header_stamp_sec"]) - float(start["header_stamp_sec"])
        ),
        "dx_m": dx,
        "dy_m": dy,
        "dz_m": dz,
        "xy_drift_m": math.hypot(dx, dy),
        "yaw_drift_rad": dyaw,
        "yaw_drift_deg": math.degrees(dyaw),
    }


def write_json(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def capture_odometry(topic, timeout):
    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.qos import QoSProfile, ReliabilityPolicy

    rclpy.init()
    node = rclpy.create_node("cuvslam_get_odometry_once")
    result = []

    def callback(message):
        if not result:
            result.append(odometry_to_document(message, topic))

    qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
    subscription = node.create_subscription(Odometry, topic, callback, qos)
    deadline = time.monotonic() + timeout
    try:
        while rclpy.ok() and not result and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        node.destroy_subscription(subscription)
        node.destroy_node()
        rclpy.shutdown()

    if not result:
        raise RuntimeError(
            "timed out waiting for one odometry sample on {}".format(topic)
        )
    return result[0]


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture")
    capture.add_argument(
        "--topic", default="/visual_slam/tracking/odometry"
    )
    capture.add_argument("--timeout", type=float, default=5.0)
    capture.add_argument("--output", required=True)

    compare = subparsers.add_parser("compare")
    compare.add_argument("--start", required=True)
    compare.add_argument("--end", required=True)
    compare.add_argument("--output", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "capture":
            if not math.isfinite(args.timeout) or args.timeout <= 0.0:
                raise ValueError("--timeout must be a finite positive number")
            document = capture_odometry(args.topic, args.timeout)
        else:
            start = json.loads(Path(args.start).read_text(encoding="utf-8"))
            end = json.loads(Path(args.end).read_text(encoding="utf-8"))
            document = compare_documents(start, end)
        write_json(args.output, document)
        print(json.dumps(document, sort_keys=True))
        return 0
    except (
        ImportError,
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
    ) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
