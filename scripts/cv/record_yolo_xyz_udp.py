#!/usr/bin/env python3
"""Record D455 YOLO 3-D UDP detections against a known camera_link point."""

from __future__ import annotations

import argparse
import csv
import json
import math
import socket
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REQUIRED_PACKET_KEYS = {
    "schema_version", "sequence", "stamp", "frame_id", "inference_ms", "detections",
}
REQUIRED_DETECTION_KEYS = {
    "class_id", "class_name", "confidence", "bbox", "center_px", "mask_area_px",
    "depth_m", "depth_valid_ratio", "position_valid", "position_m",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record /d455_object_yolo_3d UDP positions for one known target."
    )
    parser.add_argument("--expected-x", type=float, required=True, help="camera_link X truth, metres")
    parser.add_argument("--expected-y", type=float, required=True, help="camera_link Y truth, metres")
    parser.add_argument("--expected-z", type=float, required=True, help="camera_link Z truth, metres")
    parser.add_argument("--target-class", choices=("red", "green", "obstacle"), default="obstacle")
    parser.add_argument("--samples", type=int, default=30, help="valid samples to record")
    parser.add_argument("--timeout", type=float, default=60.0, help="maximum recording time in seconds")
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--bind-host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=19002)
    parser.add_argument("--output", type=Path, default=None, help="CSV destination")
    args = parser.parse_args()
    if args.samples <= 0 or args.timeout <= 0:
        parser.error("--samples and --timeout must be positive")
    if not 0.0 <= args.min_confidence <= 1.0:
        parser.error("--min-confidence must be in [0, 1]")
    return args


def percentile(values: Iterable[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot calculate a percentile of no values")
    index = (len(ordered) - 1) * fraction
    lower, upper = math.floor(index), math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def select_detection(packet: Any, target_class: str, min_confidence: float) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(packet, dict) or set(packet) != REQUIRED_PACKET_KEYS:
        return None, "invalid_packet"
    if packet["schema_version"] != 1 or packet["frame_id"] != "camera_link":
        return None, "unsupported_packet"
    detections = packet["detections"]
    if not isinstance(detections, list):
        return None, "invalid_detections"
    candidates = []
    for detection in detections:
        if not isinstance(detection, dict) or set(detection) != REQUIRED_DETECTION_KEYS:
            continue
        if detection["class_name"] != target_class or not detection["position_valid"]:
            continue
        position = detection["position_m"]
        if not isinstance(position, list) or len(position) != 3:
            continue
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in position):
            continue
        confidence = detection["confidence"]
        if not isinstance(confidence, (int, float)) or confidence < min_confidence:
            continue
        candidates.append(detection)
    if not candidates:
        return None, "no_valid_target"
    if len(candidates) != 1:
        return None, "ambiguous_target"
    return candidates[0], None


def output_path(args: argparse.Namespace) -> Path:
    if args.output is not None:
        return args.output
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(f"yolo_xyz_{args.target_class}_{timestamp}.csv")


def main() -> int:
    args = parse_args()
    expected = (args.expected_x, args.expected_y, args.expected_z)
    destination = output_path(args)
    destination.parent.mkdir(parents=True, exist_ok=True)
    skipped: dict[str, int] = {}
    records: list[dict[str, Any]] = []

    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    receiver.bind((args.bind_host, args.port))
    receiver.settimeout(min(1.0, args.timeout))
    print(
        f"Listening on {args.bind_host}:{args.port}; target={args.target_class}; "
        f"truth=({expected[0]:.3f}, {expected[1]:.3f}, {expected[2]:.3f}) m; "
        f"need={args.samples}",
        flush=True,
    )

    deadline = time.monotonic() + args.timeout
    try:
        while len(records) < args.samples and time.monotonic() < deadline:
            try:
                payload, _ = receiver.recvfrom(65535)
                packet = json.loads(payload.decode("utf-8"))
            except socket.timeout:
                continue
            except (UnicodeDecodeError, json.JSONDecodeError):
                skipped["invalid_json"] = skipped.get("invalid_json", 0) + 1
                continue
            detection, reason = select_detection(packet, args.target_class, args.min_confidence)
            if detection is None:
                assert reason is not None
                skipped[reason] = skipped.get(reason, 0) + 1
                continue

            x, y, z = (float(value) for value in detection["position_m"])
            dx, dy, dz = x - expected[0], y - expected[1], z - expected[2]
            records.append({
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
                "expected_x_m": expected[0],
                "expected_y_m": expected[1],
                "expected_z_m": expected[2],
                "error_x_m": dx,
                "error_y_m": dy,
                "error_z_m": dz,
                "error_norm_m": math.sqrt(dx * dx + dy * dy + dz * dz),
            })
            print(f"accepted {len(records):02d}/{args.samples}: xyz=({x:.3f}, {y:.3f}, {z:.3f}) m", flush=True)
    finally:
        receiver.close()

    if not records:
        print(f"No valid samples recorded; skipped={skipped}", file=sys.stderr)
        return 1

    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)

    norms = [record["error_norm_m"] for record in records]
    axis_errors = [[record[f"error_{axis}_m"] for record in records] for axis in "xyz"]
    print(f"CSV: {destination}")
    print(f"valid={len(records)}/{args.samples}; skipped={skipped}")
    print(
        "error norm (m): "
        f"mean={statistics.fmean(norms):.4f} p95={percentile(norms, 0.95):.4f} max={max(norms):.4f}"
    )
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
    return 0 if len(records) == args.samples else 2


if __name__ == "__main__":
    raise SystemExit(main())
