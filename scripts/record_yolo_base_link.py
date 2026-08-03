#!/usr/bin/env python3
"""Record Host bridge YOLO detections against a known base_link target point."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


REQUIRED_PACKET_KEYS = {
    "schema_version", "source_schema_version", "sequence", "stamp", "frame_id",
    "inference_ms", "detections",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-x", type=float, required=True, help="base_link X truth in metres")
    parser.add_argument("--expected-y", type=float, required=True, help="base_link Y truth in metres")
    parser.add_argument("--expected-z", type=float, required=True, help="base_link Z truth in metres")
    parser.add_argument("--target-class", choices=("red", "green", "obstacle"), required=True)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--topic", default="/yolo/detections")
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/yolo_xyz_calibration"))
    args = parser.parse_args()
    if args.samples < 1 or args.timeout <= 0:
        parser.error("--samples must be positive and --timeout must be greater than zero")
    if not 0.0 <= args.min_confidence <= 1.0:
        parser.error("--min-confidence must be in [0, 1]")
    return args


def percentile(values: Iterable[float], fraction: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower, upper = math.floor(index), math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


class BaseLinkRecorder(Node):
    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__("yolo_base_link_calibration_recorder")
        self._args = args
        self._truth = (args.expected_x, args.expected_y, args.expected_z)
        self.records: list[Dict[str, Any]] = []
        self.skipped: Dict[str, int] = {}
        self.create_subscription(String, args.topic, self._callback, 10)

    def _callback(self, message: String) -> None:
        if len(self.records) >= self._args.samples:
            return
        try:
            packet = json.loads(message.data)
        except json.JSONDecodeError:
            self._skip("invalid_json")
            return
        detection, reason = self._select_detection(packet)
        if detection is None:
            self._skip(reason or "invalid_packet")
            return

        x, y, z = (float(value) for value in detection["position_m"])
        dx, dy, dz = x - self._truth[0], y - self._truth[1], z - self._truth[2]
        self.records.append({
            "host_received_unix_s": time.time(),
            "sequence": packet["sequence"],
            "source_sec": packet["stamp"]["sec"],
            "source_nanosec": packet["stamp"]["nanosec"],
            "inference_ms": packet["inference_ms"],
            "class_name": detection["class_name"],
            "confidence": detection["confidence"],
            "depth_m": detection["depth_m"],
            "depth_valid_ratio": detection["depth_valid_ratio"],
            "measured_x_m": x,
            "measured_y_m": y,
            "measured_z_m": z,
            "expected_x_m": self._truth[0],
            "expected_y_m": self._truth[1],
            "expected_z_m": self._truth[2],
            "error_x_m": dx,
            "error_y_m": dy,
            "error_z_m": dz,
            "error_norm_m": math.sqrt(dx * dx + dy * dy + dz * dz),
        })
        self.get_logger().info(
            f"accepted {len(self.records):02d}/{self._args.samples}: "
            f"base_link=({x:.3f}, {y:.3f}, {z:.3f}) m"
        )

    def _select_detection(self, packet: Any) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        if not isinstance(packet, dict) or set(packet) != REQUIRED_PACKET_KEYS:
            return None, "invalid_packet"
        if packet["schema_version"] != 1 or packet["source_schema_version"] != 1:
            return None, "unsupported_schema"
        if packet["frame_id"] != "base_link" or not isinstance(packet["detections"], list):
            return None, "wrong_frame"
        candidates = []
        for detection in packet["detections"]:
            if not isinstance(detection, dict):
                continue
            if detection.get("class_name") != self._args.target_class:
                continue
            if not detection.get("position_valid") or detection.get("confidence", 0.0) < self._args.min_confidence:
                continue
            position = detection.get("position_m")
            if not isinstance(position, list) or len(position) != 3:
                continue
            if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in position):
                continue
            candidates.append(detection)
        if len(candidates) == 1:
            return candidates[0], None
        return None, "no_valid_target" if not candidates else "ambiguous_target"

    def _skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1


def main() -> int:
    args = parse_args()
    rclpy.init()
    recorder = BaseLinkRecorder(args)
    deadline = time.monotonic() + args.timeout
    print(
        f"Listening on {args.topic}; target={args.target_class}; "
        f"truth=({args.expected_x:.3f}, {args.expected_y:.3f}, {args.expected_z:.3f}) m; "
        f"need={args.samples}",
        flush=True,
    )
    try:
        while rclpy.ok() and len(recorder.records) < args.samples and time.monotonic() < deadline:
            rclpy.spin_once(recorder, timeout_sec=0.25)
    finally:
        recorder.destroy_node()
        rclpy.shutdown()

    if not recorder.records:
        raise RuntimeError(f"No valid samples recorded; skipped={recorder.skipped}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = args.output_dir / f"yolo_base_link_{args.target_class}_{timestamp}.csv"
    with output_path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=list(recorder.records[0]))
        writer.writeheader()
        writer.writerows(recorder.records)

    norms = [record["error_norm_m"] for record in recorder.records]
    axis_errors = [[record[f"error_{axis}_m"] for record in recorder.records] for axis in "xyz"]
    print(f"CSV: {output_path}")
    print(f"valid={len(recorder.records)}/{args.samples}; skipped={recorder.skipped}")
    print(f"error norm (m): mean={statistics.fmean(norms):.4f} p95={percentile(norms, 0.95):.4f} max={max(norms):.4f}")
    print(
        "axis bias (m): "
        f"x={statistics.fmean(axis_errors[0]):+.4f} "
        f"y={statistics.fmean(axis_errors[1]):+.4f} "
        f"z={statistics.fmean(axis_errors[2]):+.4f}"
    )
    print(
        "axis stdev (m): "
        f"x={statistics.pstdev(axis_errors[0]):.4f} "
        f"y={statistics.pstdev(axis_errors[1]):.4f} "
        f"z={statistics.pstdev(axis_errors[2]):.4f}"
    )
    return 0 if len(recorder.records) == args.samples else 2


if __name__ == "__main__":
    raise SystemExit(main())
