#!/usr/bin/env python3
"""Measure cuVSLAM input timing without publishing commands or calling services."""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
from pathlib import Path
import statistics
import time
from typing import Dict, List, Optional, Sequence


def percentile(values: Sequence[float], percent: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    rank = (len(ordered) - 1) * percent / 100.0
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _deltas(values: Sequence[float]) -> List[float]:
    return [newer - older for older, newer in zip(values, values[1:])]


def summarize_stream(
    source_stamps: Sequence[float],
    arrival_stamps: Sequence[float],
    expected_hz: float,
) -> Dict[str, object]:
    source_deltas = _deltas(source_stamps)
    arrival_deltas = _deltas(arrival_stamps)
    positive_source_deltas = [delta for delta in source_deltas if delta > 0.0]
    expected_period = 1.0 / expected_hz
    source_span = (
        source_stamps[-1] - source_stamps[0] if len(source_stamps) >= 2 else 0.0
    )
    observed_hz = (
        (len(source_stamps) - 1) / source_span if source_span > 0.0 else None
    )
    estimated_missing = sum(
        max(0, round(delta / expected_period) - 1) for delta in positive_source_deltas
    )

    status = "insufficient_data"
    if observed_hz is not None:
        status = "ok"
        if observed_hz < expected_hz * 0.90:
            status = "degraded_rate"
        if any(delta > expected_period * 2.5 for delta in positive_source_deltas):
            status = "clustered_gaps"

    def milliseconds(value: Optional[float]) -> Optional[float]:
        return None if value is None else value * 1000.0

    return {
        "count": len(source_stamps),
        "expected_hz": expected_hz,
        "observed_hz": observed_hz,
        "source_span_s": source_span,
        "source_delta_ms": {
            "p50": milliseconds(percentile(positive_source_deltas, 50.0)),
            "p95": milliseconds(percentile(positive_source_deltas, 95.0)),
            "p99": milliseconds(percentile(positive_source_deltas, 99.0)),
            "max": milliseconds(max(positive_source_deltas, default=None)),
        },
        "arrival_delta_ms": {
            "p50": milliseconds(percentile(arrival_deltas, 50.0)),
            "p95": milliseconds(percentile(arrival_deltas, 95.0)),
            "p99": milliseconds(percentile(arrival_deltas, 99.0)),
            "max": milliseconds(max(arrival_deltas, default=None)),
        },
        "nonmonotonic_source_count": sum(delta <= 0.0 for delta in source_deltas),
        "gap_over_1_5x_count": sum(
            delta > expected_period * 1.5 for delta in positive_source_deltas
        ),
        "gap_over_2_5x_count": sum(
            delta > expected_period * 2.5 for delta in positive_source_deltas
        ),
        "estimated_missing_samples": estimated_missing,
        "status": status,
    }


def summarize_stereo_sync(
    left_stamps: Sequence[float], right_stamps: Sequence[float]
) -> Dict[str, object]:
    ordered_right = sorted(right_stamps)
    nearest_ms: List[float] = []
    for stamp in left_stamps:
        index = bisect.bisect_left(ordered_right, stamp)
        candidates = ordered_right[max(0, index - 1) : index + 1]
        if candidates:
            nearest_ms.append(min(abs(stamp - value) for value in candidates) * 1000.0)
    return {
        "left_count": len(left_stamps),
        "right_count": len(right_stamps),
        "paired_left_count": len(nearest_ms),
        "nearest_delta_ms": {
            "p50": percentile(nearest_ms, 50.0),
            "p95": percentile(nearest_ms, 95.0),
            "max": max(nearest_ms, default=None),
        },
        "within_0_5ms_ratio": (
            sum(delta <= 0.5 for delta in nearest_ms) / len(nearest_ms)
            if nearest_ms
            else None
        ),
        "within_2ms_ratio": (
            sum(delta <= 2.0 for delta in nearest_ms) / len(nearest_ms)
            if nearest_ms
            else None
        ),
    }


def summarize_imu_per_frame(
    image_stamps: Sequence[float], imu_stamps: Sequence[float]
) -> Dict[str, object]:
    ordered_imu = sorted(imu_stamps)
    counts = [
        bisect.bisect_right(ordered_imu, newer)
        - bisect.bisect_right(ordered_imu, older)
        for older, newer in zip(image_stamps, image_stamps[1:])
        if newer > older
    ]
    return {
        "frame_intervals": len(counts),
        "samples_per_frame": {
            "min": min(counts, default=None),
            "p05": percentile(counts, 5.0),
            "median": statistics.median(counts) if counts else None,
            "p95": percentile(counts, 95.0),
            "max": max(counts, default=None),
        },
        "zero_sample_intervals": sum(count == 0 for count in counts),
    }


def build_report(
    samples: Dict[str, Dict[str, List[float]]], expected_hz: Dict[str, float]
) -> Dict[str, object]:
    streams = {
        name: summarize_stream(
            values["source"], values["arrival"], expected_hz[name]
        )
        for name, values in samples.items()
    }
    return {
        "streams": streams,
        "stereo_sync": summarize_stereo_sync(
            samples["infra1"]["source"], samples["infra2"]["source"]
        ),
        "imu_per_infra1_frame": summarize_imu_per_frame(
            samples["infra1"]["source"], samples["imu"]["source"]
        ),
    }


def write_outputs(
    output_dir: Path,
    samples: Dict[str, Dict[str, List[float]]],
    report: Dict[str, object],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "input_timing_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (output_dir / "input_timing_samples.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(["stream", "source_stamp_s", "arrival_monotonic_s"])
        for name, values in samples.items():
            writer.writerows(
                (name, source, arrival)
                for source, arrival in zip(values["source"], values["arrival"])
            )

    lines = []
    for name, summary in report["streams"].items():
        delta = summary["source_delta_ms"]
        lines.append(
            f"{name}: count={summary['count']} observed_hz={summary['observed_hz']} "
            f"p95_delta_ms={delta['p95']} max_delta_ms={delta['max']} "
            f"gaps_2_5x={summary['gap_over_2_5x_count']} "
            f"estimated_missing={summary['estimated_missing_samples']} "
            f"status={summary['status']}"
        )
    stereo = report["stereo_sync"]
    imu = report["imu_per_infra1_frame"]
    lines.append(f"stereo_sync: {json.dumps(stereo, sort_keys=True)}")
    lines.append(f"imu_per_infra1_frame: {json.dumps(imu, sort_keys=True)}")
    (output_dir / "input_timing_report.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--output-dir", type=Path, default=Path("/logs/input_timing"))
    parser.add_argument("--infra1-topic", default="/camera/infra1/camera_info")
    parser.add_argument("--infra2-topic", default="/camera/infra2/camera_info")
    parser.add_argument("--imu-topic", default="/camera/imu")
    parser.add_argument("--odometry-topic", default="/visual_slam/tracking/odometry")
    parser.add_argument("--infra-hz", type=float, default=60.0)
    parser.add_argument("--imu-hz", type=float, default=200.0)
    parser.add_argument("--odometry-hz", type=float, default=60.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.duration <= 0.0:
        raise SystemExit("--duration must be > 0")

    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.node import Node
    from rclpy.qos import (
        DurabilityPolicy,
        HistoryPolicy,
        QoSProfile,
        ReliabilityPolicy,
    )
    from sensor_msgs.msg import CameraInfo, Imu

    samples = {
        name: {"source": [], "arrival": []}
        for name in ("infra1", "infra2", "imu", "odometry")
    }
    node = None
    sensor_qos = QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=100,
        reliability=ReliabilityPolicy.BEST_EFFORT,
        durability=DurabilityPolicy.VOLATILE,
    )

    def callback_for(name: str):
        def callback(message) -> None:
            samples[name]["source"].append(
                float(message.header.stamp.sec)
                + float(message.header.stamp.nanosec) / 1.0e9
            )
            samples[name]["arrival"].append(time.monotonic())

        return callback

    rclpy.init()
    try:
        node = Node("cuvslam_input_timing_probe")
        subscriptions = [
            node.create_subscription(
                CameraInfo, args.infra1_topic, callback_for("infra1"), sensor_qos
            ),
            node.create_subscription(
                CameraInfo, args.infra2_topic, callback_for("infra2"), sensor_qos
            ),
            node.create_subscription(
                Imu, args.imu_topic, callback_for("imu"), sensor_qos
            ),
            node.create_subscription(
                Odometry,
                args.odometry_topic,
                callback_for("odometry"),
                sensor_qos,
            ),
        ]
        deadline = time.monotonic() + args.duration
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
        if not subscriptions:
            raise RuntimeError("subscriptions were not created")
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()

    expected_hz = {
        "infra1": args.infra_hz,
        "infra2": args.infra_hz,
        "imu": args.imu_hz,
        "odometry": args.odometry_hz,
    }
    report = build_report(samples, expected_hz)
    report["duration_s"] = args.duration
    report["topics"] = {
        "infra1": args.infra1_topic,
        "infra2": args.infra2_topic,
        "imu": args.imu_topic,
        "odometry": args.odometry_topic,
    }
    write_outputs(args.output_dir, samples, report)
    print((args.output_dir / "input_timing_report.txt").read_text(encoding="utf-8"))
    return 0 if all(item["count"] > 0 for item in report["streams"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
