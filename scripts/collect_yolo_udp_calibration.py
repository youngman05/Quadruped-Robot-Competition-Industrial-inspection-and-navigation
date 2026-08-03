#!/usr/bin/env python3
"""Collect one stationary D455 YOLO target from the UDP output for XYZ checks."""

from __future__ import annotations

import argparse
import csv
import json
import math
import socket
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path


FIELDS = (
    "received_at",
    "sequence",
    "stamp_sec",
    "stamp_nanosec",
    "class_name",
    "confidence",
    "depth_m",
    "depth_valid_ratio",
    "x_m",
    "y_m",
    "z_m",
    "error_m",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=19002)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--class-name", choices=("red", "green", "obstacle"), required=True)
    parser.add_argument("--truth-x", type=float, required=True)
    parser.add_argument("--truth-y", type=float, required=True)
    parser.add_argument("--truth-z", type=float, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def summarize(values: list[float]) -> dict[str, float]:
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def main() -> None:
    args = parse_args()
    if args.duration <= 0:
        raise ValueError("--duration must be positive")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    prefix = datetime.now(timezone.utc).strftime("d455_xyz_%Y%m%dT%H%M%SZ")
    csv_path = args.output_dir / f"{prefix}.csv"
    jsonl_path = args.output_dir / f"{prefix}.jsonl"
    truth = (args.truth_x, args.truth_y, args.truth_z)
    rows: list[dict[str, float | int | str]] = []

    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    receiver.bind(("127.0.0.1", args.port))
    receiver.settimeout(0.25)
    deadline = time.monotonic() + args.duration
    print(f"Listening on UDP 127.0.0.1:{args.port} for {args.duration:.1f}s", flush=True)

    with csv_path.open("w", newline="", encoding="utf-8") as csv_file, jsonl_path.open("w", encoding="utf-8") as jsonl_file:
        writer = csv.DictWriter(csv_file, fieldnames=FIELDS)
        writer.writeheader()
        while time.monotonic() < deadline:
            try:
                payload, source = receiver.recvfrom(65535)
            except TimeoutError:
                continue
            received_at = time.time()
            try:
                packet = json.loads(payload)
            except json.JSONDecodeError:
                print(f"Ignoring non-JSON UDP payload from {source}", flush=True)
                continue
            jsonl_file.write(json.dumps({"received_at": received_at, "source": source, "packet": packet}) + "\n")
            jsonl_file.flush()
            for detection in packet.get("detections", []):
                if detection.get("class_name") != args.class_name or not detection.get("position_valid"):
                    continue
                position = detection.get("position_m")
                if not isinstance(position, list) or len(position) != 3:
                    continue
                error = math.dist(position, truth)
                row = {
                    "received_at": received_at,
                    "sequence": packet.get("sequence"),
                    "stamp_sec": packet.get("stamp", {}).get("sec"),
                    "stamp_nanosec": packet.get("stamp", {}).get("nanosec"),
                    "class_name": detection["class_name"],
                    "confidence": detection.get("confidence"),
                    "depth_m": detection.get("depth_m"),
                    "depth_valid_ratio": detection.get("depth_valid_ratio"),
                    "x_m": position[0],
                    "y_m": position[1],
                    "z_m": position[2],
                    "error_m": error,
                }
                rows.append(row)
                writer.writerow(row)
                csv_file.flush()

    receiver.close()
    if not rows:
        raise RuntimeError(f"No valid {args.class_name} detections were received")

    print(f"CSV: {csv_path}")
    print(f"JSONL: {jsonl_path}")
    print(f"truth camera_link: x={truth[0]:.3f}, y={truth[1]:.3f}, z={truth[2]:.3f}")
    for name in ("x_m", "y_m", "z_m", "error_m"):
        result = summarize([float(row[name]) for row in rows])
        print(
            f"{name}: n={result['count']} mean={result['mean']:.4f} median={result['median']:.4f} "
            f"std={result['stdev']:.4f} range=[{result['min']:.4f}, {result['max']:.4f}]"
        )


if __name__ == "__main__":
    main()
