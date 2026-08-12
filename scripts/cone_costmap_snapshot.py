#!/usr/bin/env python3
"""Capture one Nav2 Costmap message as compact, hashable JSON evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time


def summarize_costmap(message, captured_at_ns: int) -> dict:
    data = bytes(message.data)
    histogram = {}
    for value in data:
        key = str(int(value))
        histogram[key] = histogram.get(key, 0) + 1
    metadata = message.metadata
    origin = metadata.origin
    return {
        "captured_at_ns": int(captured_at_ns),
        "header": {
            "frame_id": str(message.header.frame_id),
            "stamp_ns": (
                int(message.header.stamp.sec) * 1_000_000_000
                + int(message.header.stamp.nanosec)
            ),
        },
        "metadata": {
            "size_x": int(metadata.size_x),
            "size_y": int(metadata.size_y),
            "resolution": float(metadata.resolution),
            "origin": {
                "x": float(origin.position.x),
                "y": float(origin.position.y),
                "z": float(origin.position.z),
            },
        },
        "data_length": len(data),
        "data_sha256": hashlib.sha256(data).hexdigest(),
        "histogram": histogram,
        "lethal_count": histogram.get("254", 0),
        "inscribed_count": histogram.get("253", 0),
        "unknown_count": histogram.get("255", 0),
        "nonzero_known_count": sum(
            count
            for value, count in histogram.items()
            if value not in ("0", "255")
        ),
    }


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-sec", type=float, default=10.0)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.timeout_sec <= 0.0:
        raise SystemExit("--timeout-sec must be positive")

    import rclpy
    from nav2_msgs.msg import Costmap
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

    try:
        from rclpy.qos import HistoryPolicy
    except ImportError:
        from rclpy.qos import QoSHistoryPolicy as HistoryPolicy

    rclpy.init()
    node = rclpy.create_node("cone_costmap_snapshot")
    result = []
    qos = QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=1,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )
    node.create_subscription(Costmap, args.topic, result.append, qos)
    deadline = time.monotonic() + args.timeout_sec
    try:
        while not result and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        node.destroy_node()
        rclpy.shutdown()
    if not result:
        raise SystemExit("timed out waiting for %s" % args.topic)

    payload = summarize_costmap(result[-1], time.time_ns())
    payload["topic"] = args.topic
    atomic_write_json(args.output, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
