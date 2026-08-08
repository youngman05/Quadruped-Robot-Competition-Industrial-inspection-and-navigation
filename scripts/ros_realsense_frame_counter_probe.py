#!/usr/bin/env python3
"""Locate the first observable RealSense frame gap between ROS and cuVSLAM."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
import sys
import threading
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cuvslam_input_timing_probe import summarize_imu_per_frame, summarize_stream


COUNTER_KEYS = ("frame_counter", "frame_number")


def normalize_metadata_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")


def parse_counter_value(value: object) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+", value.strip())
        if match:
            return int(match.group(0))
    return None


def flatten_metadata(payload: object) -> Iterable[Tuple[str, object]]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized = normalize_metadata_key(key)
            yield normalized, value
            yield from flatten_metadata(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from flatten_metadata(value)


def parse_metadata_json(json_data: str) -> Dict[str, object]:
    payload = json.loads(json_data)
    flattened = list(flatten_metadata(payload))
    normalized_keys = sorted({key for key, _ in flattened if key})
    values = {key: value for key, value in flattened}
    selected_key = next((key for key in COUNTER_KEYS if key in values), None)
    counter = parse_counter_value(values[selected_key]) if selected_key else None
    return {
        "counter": counter,
        "counter_key": selected_key,
        "keys": normalized_keys,
    }


def frame_counter_gap_events(
    counters: Sequence[int], source_stamps_ns: Sequence[int]
) -> Dict[str, object]:
    events: List[Dict[str, object]] = []
    duplicate_count = 0
    nonmonotonic_count = 0
    missing_total = 0
    for index, (older, newer) in enumerate(zip(counters, counters[1:])):
        if newer == older:
            duplicate_count += 1
            continue
        delta = newer - older
        if delta < 0 and older > 0xF0000000 and newer < 0x0FFFFFFF:
            delta = (1 << 32) - older + newer
        elif delta < 0:
            nonmonotonic_count += 1
            continue
        missing = max(0, delta - 1)
        if not missing:
            continue
        missing_total += missing
        events.append(
            {
                "before": older,
                "after": newer,
                "missing": missing,
                "source_before_ns": source_stamps_ns[index],
                "source_after_ns": source_stamps_ns[index + 1],
            }
        )
    return {
        "sample_count": len(counters),
        "missing_total": missing_total,
        "gap_event_count": len(events),
        "duplicate_count": duplicate_count,
        "nonmonotonic_count": nonmonotonic_count,
        "events": events,
    }


def summarize_image_metadata_pair(
    image_stamps_ns: Sequence[int], metadata_stamps_ns: Sequence[int]
) -> Dict[str, object]:
    image_set = set(image_stamps_ns)
    metadata_set = set(metadata_stamps_ns)
    return {
        "image_count": len(image_stamps_ns),
        "metadata_count": len(metadata_stamps_ns),
        "exact_stamp_matches": len(image_set & metadata_set),
        "image_without_metadata": len(image_set - metadata_set),
        "metadata_without_image": len(metadata_set - image_set),
    }


def stamp_ns(message: object) -> int:
    stamp = message.header.stamp
    return int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)


def ns_as_seconds(values: Sequence[int]) -> List[float]:
    return [value / 1.0e9 for value in values]


def stream_gap_events(
    source_stamps_ns: Sequence[int],
    arrival_stamps_ns: Sequence[int],
    expected_hz: float,
    threshold_multiplier: float = 2.5,
) -> List[Dict[str, object]]:
    expected_period_ns = 1.0e9 / expected_hz
    events = []
    for index, (older, newer) in enumerate(
        zip(source_stamps_ns, source_stamps_ns[1:])
    ):
        source_delta_ns = newer - older
        if source_delta_ns <= expected_period_ns * threshold_multiplier:
            continue
        arrival_delta_ns = arrival_stamps_ns[index + 1] - arrival_stamps_ns[index]
        events.append(
            {
                "source_before_ns": older,
                "source_after_ns": newer,
                "arrival_before_ns": arrival_stamps_ns[index],
                "arrival_after_ns": arrival_stamps_ns[index + 1],
                "source_delta_ms": source_delta_ns / 1.0e6,
                "arrival_delta_ms": arrival_delta_ns / 1.0e6,
                "estimated_missing": max(
                    0, round(source_delta_ns / expected_period_ns) - 1
                ),
            }
        )
    return events


def build_report(
    streams: Dict[str, Dict[str, List[int]]],
    metadata: Dict[str, Dict[str, object]],
    expected_hz: Dict[str, float],
) -> Dict[str, object]:
    stream_summaries = {
        name: summarize_stream(
            ns_as_seconds(values["source_ns"]),
            ns_as_seconds(values["arrival_ns"]),
            expected_hz[name],
        )
        for name, values in streams.items()
    }
    metadata_summaries = {}
    for name, values in metadata.items():
        counters = values["counters"]
        counter_stamps = values["counter_source_ns"]
        metadata_summaries[name] = {
            "message_count": len(values["source_ns"]),
            "valid_counter_count": len(counters),
            "parse_error_count": len(values["parse_errors"]),
            "counter_keys": sorted(values["counter_keys"]),
            "available_keys": sorted(values["available_keys"]),
            "frame_counter": frame_counter_gap_events(counters, counter_stamps),
        }

    gate_checks = {
        "infra1_hardware_counter_continuous": (
            metadata_summaries["infra1"]["valid_counter_count"] > 0
            and metadata_summaries["infra1"]["frame_counter"]["missing_total"] == 0
            and metadata_summaries["infra1"]["frame_counter"]["nonmonotonic_count"]
            == 0
        ),
        "infra2_hardware_counter_continuous": (
            metadata_summaries["infra2"]["valid_counter_count"] > 0
            and metadata_summaries["infra2"]["frame_counter"]["missing_total"] == 0
            and metadata_summaries["infra2"]["frame_counter"]["nonmonotonic_count"]
            == 0
        ),
        "infra1_interval_within_2_5x": stream_summaries["infra1"][
            "gap_over_2_5x_count"
        ]
        == 0,
        "infra2_interval_within_2_5x": stream_summaries["infra2"][
            "gap_over_2_5x_count"
        ]
        == 0,
        "imu_has_no_clustered_gaps": stream_summaries["imu"][
            "gap_over_2_5x_count"
        ]
        == 0,
    }
    imu_per_image = summarize_imu_per_frame(
        ns_as_seconds(streams["infra1"]["source_ns"]),
        ns_as_seconds(streams["imu"]["source_ns"]),
    )
    gate_checks["every_image_interval_has_imu"] = (
        imu_per_image["frame_intervals"] > 0
        and imu_per_image["zero_sample_intervals"] == 0
    )

    report = {
        "streams": stream_summaries,
        "stream_gap_events": {
            name: stream_gap_events(
                values["source_ns"], values["arrival_ns"], expected_hz[name]
            )
            for name, values in streams.items()
        },
        "metadata": metadata_summaries,
        "image_metadata_pairing": {
            name: summarize_image_metadata_pair(
                streams[name]["source_ns"], metadata[name]["source_ns"]
            )
            for name in ("infra1", "infra2")
        },
        "imu_per_infra1_frame": imu_per_image,
        "gate_checks": gate_checks,
        "gate_passed": all(gate_checks.values()),
    }
    return report


def write_outputs(
    output_dir: Path,
    streams: Dict[str, Dict[str, List[int]]],
    metadata: Dict[str, Dict[str, object]],
    report: Dict[str, object],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "ros_frame_counter_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (output_dir / "ros_frame_counter_samples.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "category",
                "stream",
                "source_stamp_ns",
                "arrival_monotonic_ns",
                "frame_counter",
                "counter_key",
            ]
        )
        for name, values in streams.items():
            writer.writerows(
                ("message", name, source, arrival, "", "")
                for source, arrival in zip(values["source_ns"], values["arrival_ns"])
            )
        for name, values in metadata.items():
            writer.writerows(
                (
                    "metadata_counter",
                    name,
                    source,
                    arrival,
                    counter,
                    next(iter(values["counter_keys"]), ""),
                )
                for source, arrival, counter in zip(
                    values["counter_source_ns"],
                    values["counter_arrival_ns"],
                    values["counters"],
                )
            )

    lines = [f"gate_passed={report['gate_passed']}"]
    for name, summary in report["streams"].items():
        lines.append(
            f"{name}: count={summary['count']} observed_hz={summary['observed_hz']} "
            f"max_delta_ms={summary['source_delta_ms']['max']} "
            f"gaps_2_5x={summary['gap_over_2_5x_count']} status={summary['status']}"
        )
    for name, summary in report["metadata"].items():
        counter = summary["frame_counter"]
        lines.append(
            f"{name}_metadata: messages={summary['message_count']} "
            f"valid_counters={summary['valid_counter_count']} "
            f"missing={counter['missing_total']} gaps={counter['gap_event_count']} "
            f"nonmonotonic={counter['nonmonotonic_count']} "
            f"parse_errors={summary['parse_error_count']}"
        )
    lines.append(
        "imu_per_infra1_frame: "
        + json.dumps(report["imu_per_infra1_frame"], sort_keys=True)
    )
    lines.append("gate_checks: " + json.dumps(report["gate_checks"], sort_keys=True))
    (output_dir / "ros_frame_counter_report.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def read_raw_csv(
    input_csv: Path,
) -> Tuple[Dict[str, Dict[str, List[int]]], Dict[str, Dict[str, object]]]:
    streams: Dict[str, Dict[str, List[int]]] = {}
    metadata = {
        name: empty_metadata() for name in ("infra1", "infra2", "accel", "gyro")
    }
    with input_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            name = row["stream"]
            source_ns = int(row["source_stamp_ns"])
            arrival_ns = int(row["arrival_monotonic_ns"])
            if row["category"] == "message":
                values = streams.setdefault(name, empty_stream())
                values["source_ns"].append(source_ns)
                values["arrival_ns"].append(arrival_ns)
                continue
            if row["category"] != "metadata_counter":
                raise ValueError(f"unknown CSV category: {row['category']}")
            values = metadata.setdefault(name, empty_metadata())
            values["source_ns"].append(source_ns)
            values["arrival_ns"].append(arrival_ns)
            if row["frame_counter"]:
                values["counter_source_ns"].append(source_ns)
                values["counter_arrival_ns"].append(arrival_ns)
                values["counters"].append(int(row["frame_counter"]))
                counter_key = row.get("counter_key") or "unknown"
                values["counter_keys"].add(counter_key)
    return streams, metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--warmup", type=float, default=3.0)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--input-csv", type=Path)
    parser.add_argument("--infra1-topic", default="/camera/infra1/image_rect_raw")
    parser.add_argument("--infra2-topic", default="/camera/infra2/image_rect_raw")
    parser.add_argument("--imu-topic", default="/camera/imu")
    parser.add_argument("--odometry-topic", default="")
    parser.add_argument("--infra1-metadata-topic", default="/camera/infra1/metadata")
    parser.add_argument("--infra2-metadata-topic", default="/camera/infra2/metadata")
    parser.add_argument("--accel-metadata-topic", default="/camera/accel/metadata")
    parser.add_argument("--gyro-metadata-topic", default="/camera/gyro/metadata")
    parser.add_argument("--infra-hz", type=float, default=30.0)
    parser.add_argument("--imu-hz", type=float, default=200.0)
    parser.add_argument("--odometry-hz", type=float, default=30.0)
    parser.add_argument("--qos-depth", type=int, default=64)
    return parser.parse_args()


def empty_stream() -> Dict[str, List[int]]:
    return {"source_ns": [], "arrival_ns": []}


def empty_metadata() -> Dict[str, object]:
    return {
        "source_ns": [],
        "arrival_ns": [],
        "counter_source_ns": [],
        "counter_arrival_ns": [],
        "counters": [],
        "counter_keys": set(),
        "available_keys": set(),
        "parse_errors": [],
    }


def main() -> int:
    args = parse_args()
    if args.duration <= 0.0:
        raise SystemExit("--duration must be > 0")
    if args.warmup < 0.0:
        raise SystemExit("--warmup must be >= 0")
    if args.infra_hz <= 0.0 or args.imu_hz <= 0.0 or args.odometry_hz <= 0.0:
        raise SystemExit("expected rates must be > 0")
    if args.qos_depth <= 0:
        raise SystemExit("--qos-depth must be > 0")

    expected_hz = {
        "infra1": args.infra_hz,
        "infra2": args.infra_hz,
        "imu": args.imu_hz,
        "odometry": args.odometry_hz,
    }
    if args.input_csv:
        streams, metadata = read_raw_csv(args.input_csv)
        required_names = ["infra1", "infra2", "imu"]
        if args.odometry_topic:
            required_names.append("odometry")
        missing = [name for name in required_names if name not in streams]
        if missing:
            raise SystemExit(f"input CSV is missing streams: {', '.join(missing)}")
        report = build_report(streams, metadata, expected_hz)
        report["duration_s"] = args.duration
        report["warmup_s"] = args.warmup
        report["source"] = str(args.input_csv)
        write_outputs(args.output_dir, streams, metadata, report)
        print(
            (args.output_dir / "ros_frame_counter_report.txt").read_text(
                encoding="utf-8"
            )
        )
        return 0

    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from rclpy.qos import (
        DurabilityPolicy,
        HistoryPolicy,
        QoSProfile,
        ReliabilityPolicy,
    )
    from realsense2_camera_msgs.msg import Metadata
    from sensor_msgs.msg import Image, Imu

    stream_names = ["infra1", "infra2", "imu"]
    if args.odometry_topic:
        stream_names.append("odometry")
    streams = {name: empty_stream() for name in stream_names}
    metadata = {
        name: empty_metadata() for name in ("infra1", "infra2", "accel", "gyro")
    }
    capture_enabled = threading.Event()
    sensor_qos = QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=args.qos_depth,
        reliability=ReliabilityPolicy.BEST_EFFORT,
        durability=DurabilityPolicy.VOLATILE,
    )

    def stream_callback(name: str):
        def callback(message: object) -> None:
            if not capture_enabled.is_set():
                return
            streams[name]["source_ns"].append(stamp_ns(message))
            streams[name]["arrival_ns"].append(time.monotonic_ns())

        return callback

    def metadata_callback(name: str):
        def callback(message: object) -> None:
            if not capture_enabled.is_set():
                return
            arrival_ns = time.monotonic_ns()
            source_ns = stamp_ns(message)
            values = metadata[name]
            values["source_ns"].append(source_ns)
            values["arrival_ns"].append(arrival_ns)
            try:
                parsed = parse_metadata_json(message.json_data)
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                values["parse_errors"].append(str(error))
                return
            values["available_keys"].update(parsed["keys"])
            if parsed["counter_key"]:
                values["counter_keys"].add(parsed["counter_key"])
            if parsed["counter"] is not None:
                values["counter_source_ns"].append(source_ns)
                values["counter_arrival_ns"].append(arrival_ns)
                values["counters"].append(parsed["counter"])

        return callback

    rclpy.init()
    node = Node("ros_realsense_frame_counter_probe")
    callback_groups = []

    def new_callback_group() -> MutuallyExclusiveCallbackGroup:
        group = MutuallyExclusiveCallbackGroup()
        callback_groups.append(group)
        return group

    subscriptions = [
        node.create_subscription(
            Image,
            args.infra1_topic,
            stream_callback("infra1"),
            sensor_qos,
            callback_group=new_callback_group(),
        ),
        node.create_subscription(
            Image,
            args.infra2_topic,
            stream_callback("infra2"),
            sensor_qos,
            callback_group=new_callback_group(),
        ),
        node.create_subscription(
            Imu,
            args.imu_topic,
            stream_callback("imu"),
            sensor_qos,
            callback_group=new_callback_group(),
        ),
    ]
    if args.odometry_topic:
        subscriptions.append(
            node.create_subscription(
                Odometry,
                args.odometry_topic,
                stream_callback("odometry"),
                sensor_qos,
                callback_group=new_callback_group(),
            )
        )
    for name, topic in (
        ("infra1", args.infra1_metadata_topic),
        ("infra2", args.infra2_metadata_topic),
        ("accel", args.accel_metadata_topic),
        ("gyro", args.gyro_metadata_topic),
    ):
        subscriptions.append(
            node.create_subscription(
                Metadata,
                topic,
                metadata_callback(name),
                sensor_qos,
                callback_group=new_callback_group(),
            )
        )

    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    executor_thread = threading.Thread(target=executor.spin, daemon=True)
    executor_thread.start()
    try:
        time.sleep(args.warmup)
        capture_enabled.set()
        time.sleep(args.duration)
        capture_enabled.clear()
    finally:
        executor.shutdown(timeout_sec=10.0)
        executor_thread.join(timeout=10.0)
        node.destroy_node()
        rclpy.shutdown()

    report = build_report(streams, metadata, expected_hz)
    report["duration_s"] = args.duration
    report["warmup_s"] = args.warmup
    report["qos"] = {"reliability": "best_effort", "depth": args.qos_depth}
    report["topics"] = {
        "infra1": args.infra1_topic,
        "infra2": args.infra2_topic,
        "imu": args.imu_topic,
        "odometry": args.odometry_topic,
        "infra1_metadata": args.infra1_metadata_topic,
        "infra2_metadata": args.infra2_metadata_topic,
        "accel_metadata": args.accel_metadata_topic,
        "gyro_metadata": args.gyro_metadata_topic,
    }
    write_outputs(args.output_dir, streams, metadata, report)
    print((args.output_dir / "ros_frame_counter_report.txt").read_text(encoding="utf-8"))
    required_counts = [streams[name]["source_ns"] for name in stream_names]
    return 0 if all(required_counts) else 1


if __name__ == "__main__":
    raise SystemExit(main())
