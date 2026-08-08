#!/usr/bin/env python3
"""Measure raw D455 accel/gyro timing through librealsense callbacks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import threading
import time
from typing import Dict, List, Set


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cuvslam_input_timing_probe import (  # noqa: E402
    summarize_imu_per_frame,
    summarize_stereo_sync,
    summarize_stream,
)


def trim_startup_timestamp_resets(
    stream: Dict[str, List[float]], reset_threshold_s: float = 60.0
) -> tuple:
    source = stream["source"]
    reset_after = [
        index + 1
        for index, (older, newer) in enumerate(zip(source, source[1:]))
        if newer <= older or newer - older > reset_threshold_s
    ]
    start = reset_after[-1] if reset_after else 0
    return (
        {key: list(values[start:]) for key, values in stream.items()},
        len(reset_after),
        start,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--warmup", type=float, default=3.0)
    parser.add_argument("--rate", type=int, default=200)
    parser.add_argument("--infrared-fps", type=int, default=0)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=360)
    parser.add_argument("--runtime-pm-path", type=Path)
    parser.add_argument("--runtime-pm-interval", type=float, default=0.5)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def frame_number_gap_events(stream: Dict[str, List[float]]) -> List[Dict[str, object]]:
    events: List[Dict[str, object]] = []
    numbers = stream["frame_numbers"]
    for index, (older, newer) in enumerate(zip(numbers, numbers[1:])):
        missing = int(newer - older - 1)
        if missing <= 0:
            continue
        events.append(
            {
                "before": int(older),
                "after": int(newer),
                "missing": missing,
                "source_before_s": stream["source"][index],
                "source_after_s": stream["source"][index + 1],
                "arrival_before_s": stream["arrival"][index],
                "arrival_after_s": stream["arrival"][index + 1],
            }
        )
    return events


def read_runtime_pm(power_path: Path, elapsed_s: float) -> Dict[str, object]:
    return {
        "elapsed_s": elapsed_s,
        "control": (power_path / "control").read_text(encoding="ascii").strip(),
        "runtime_status": (power_path / "runtime_status")
        .read_text(encoding="ascii")
        .strip(),
        "runtime_active_time": int(
            (power_path / "runtime_active_time").read_text(encoding="ascii").strip()
        ),
        "runtime_suspended_time": int(
            (power_path / "runtime_suspended_time")
            .read_text(encoding="ascii")
            .strip()
        ),
    }


def summarize_runtime_pm(samples: List[Dict[str, object]]) -> Dict[str, object]:
    status_counts: Dict[str, int] = {}
    transitions: List[Dict[str, object]] = []
    previous = None
    for sample in samples:
        status = str(sample["runtime_status"])
        status_counts[status] = status_counts.get(status, 0) + 1
        if status != previous:
            transitions.append({"elapsed_s": sample["elapsed_s"], "status": status})
            previous = status
    return {
        "sample_count": len(samples),
        "status_counts": status_counts,
        "transitions": transitions,
        "start": samples[0] if samples else None,
        "end": samples[-1] if samples else None,
    }


def main() -> int:
    args = parse_args()
    if args.duration <= 0.0:
        raise SystemExit("--duration must be > 0")
    if args.warmup < 0.0:
        raise SystemExit("--warmup must be >= 0")
    if args.rate <= 0:
        raise SystemExit("--rate must be > 0")
    if args.infrared_fps not in {0, 15, 30, 60, 90}:
        raise SystemExit("--infrared-fps must be one of 0, 15, 30, 60, 90")
    if args.width <= 0 or args.height <= 0:
        raise SystemExit("--width and --height must be > 0")
    if args.runtime_pm_interval <= 0.0:
        raise SystemExit("--runtime-pm-interval must be > 0")
    if args.runtime_pm_path and not args.runtime_pm_path.is_dir():
        raise SystemExit(f"runtime PM path not found: {args.runtime_pm_path}")

    import pyrealsense2 as rs

    context = rs.context()
    devices = list(context.query_devices())
    if not devices:
        raise SystemExit("No RealSense device found")
    device = devices[0]
    device_info = {
        "name": device.get_info(rs.camera_info.name),
        "serial": device.get_info(rs.camera_info.serial_number),
        "firmware": device.get_info(rs.camera_info.firmware_version),
        "usb": device.get_info(rs.camera_info.usb_type_descriptor),
    }

    capture_enabled = threading.Event()
    notifications: List[Dict[str, object]] = []
    notification_lock = threading.Lock()

    def notification_callback(notification) -> None:
        with notification_lock:
            notifications.append(
                {
                    "description": str(notification.get_description()),
                    "severity": str(notification.get_severity()),
                    "timestamp_ms": float(notification.get_timestamp()),
                    "serialized_data": str(notification.get_serialized_data()),
                    "phase": (
                        "measurement" if capture_enabled.is_set() else "startup"
                    ),
                }
            )

    for sensor in device.query_sensors():
        try:
            sensor.set_notifications_callback(notification_callback)
        except RuntimeError:
            pass

    samples = {
        "accel": {"source": [], "arrival": [], "frame_numbers": []},
        "gyro": {"source": [], "arrival": [], "frame_numbers": []},
    }
    if args.infrared_fps:
        samples.update(
            {
                "infrared_1": {"source": [], "arrival": [], "frame_numbers": []},
                "infrared_2": {"source": [], "arrival": [], "frame_numbers": []},
            }
        )
    seen: Dict[str, Set[int]] = {"accel": set(), "gyro": set()}
    if args.infrared_fps:
        seen.update({"infrared_1": set(), "infrared_2": set()})
    sample_lock = threading.Lock()

    def handle_sample(sample, arrival: float) -> None:
        stream_type = sample.get_profile().stream_type()
        if stream_type == rs.stream.accel:
            name = "accel"
        elif stream_type == rs.stream.gyro:
            name = "gyro"
        elif stream_type == rs.stream.infrared:
            stream_index = sample.get_profile().stream_index()
            if stream_index not in {1, 2}:
                return
            name = f"infrared_{stream_index}"
        else:
            return
        frame_number = int(sample.get_frame_number())
        with sample_lock:
            if frame_number in seen[name]:
                return
            seen[name].add(frame_number)
            samples[name]["source"].append(float(sample.get_timestamp()) / 1000.0)
            samples[name]["arrival"].append(arrival)
            samples[name]["frame_numbers"].append(frame_number)

    def frame_callback(frame) -> None:
        if not capture_enabled.is_set():
            return
        arrival = time.monotonic()
        try:
            if frame.is_frameset():
                for sample in frame.as_frameset():
                    handle_sample(sample, arrival)
            else:
                handle_sample(frame, arrival)
        except RuntimeError:
            return

    pipeline = rs.pipeline(context)
    config = rs.config()
    config.enable_stream(rs.stream.accel, rs.format.motion_xyz32f, args.rate)
    config.enable_stream(rs.stream.gyro, rs.format.motion_xyz32f, args.rate)
    if args.infrared_fps:
        config.enable_stream(
            rs.stream.infrared,
            1,
            args.width,
            args.height,
            rs.format.y8,
            args.infrared_fps,
        )
        config.enable_stream(
            rs.stream.infrared,
            2,
            args.width,
            args.height,
            rs.format.y8,
            args.infrared_fps,
        )
    pipeline.start(config, frame_callback)
    runtime_pm_samples: List[Dict[str, object]] = []
    try:
        if args.warmup:
            time.sleep(args.warmup)
        started_at = time.monotonic()
        next_runtime_pm_sample = started_at
        capture_enabled.set()
        deadline = started_at + args.duration
        while time.monotonic() < deadline:
            now = time.monotonic()
            if args.runtime_pm_path and now >= next_runtime_pm_sample:
                runtime_pm_samples.append(
                    read_runtime_pm(args.runtime_pm_path, now - started_at)
                )
                next_runtime_pm_sample = now + args.runtime_pm_interval
            time.sleep(0.05)
        if args.runtime_pm_path:
            runtime_pm_samples.append(
                read_runtime_pm(args.runtime_pm_path, time.monotonic() - started_at)
            )
    finally:
        capture_enabled.clear()
        pipeline.stop()

    with sample_lock:
        snapshot = {
            name: {key: list(values) for key, values in stream.items()}
            for name, stream in samples.items()
        }
    cleaned = {}
    timestamp_resets = {}
    discarded_startup_samples = {}
    for name, stream in snapshot.items():
        cleaned[name], timestamp_resets[name], discarded_startup_samples[name] = (
            trim_startup_timestamp_resets(stream)
        )
    expected_hz = {"accel": float(args.rate), "gyro": float(args.rate)}
    if args.infrared_fps:
        expected_hz.update(
            {
                "infrared_1": float(args.infrared_fps),
                "infrared_2": float(args.infrared_fps),
            }
        )
    report = {
        "duration_s": args.duration,
        "warmup_s": args.warmup,
        "device": device_info,
        "streams": {
            name: summarize_stream(
                stream["source"], stream["arrival"], expected_hz[name]
            )
            for name, stream in cleaned.items()
        },
        "frame_number_gaps": {
            name: sum(
                max(0, newer - older - 1)
                for older, newer in zip(
                    stream["frame_numbers"], stream["frame_numbers"][1:]
                )
            )
            for name, stream in cleaned.items()
        },
        "frame_number_gap_events": {
            name: frame_number_gap_events(stream)
            for name, stream in cleaned.items()
        },
        "timestamp_resets": timestamp_resets,
        "discarded_startup_samples": discarded_startup_samples,
        "notifications": notifications,
    }
    if args.runtime_pm_path:
        report["runtime_pm"] = summarize_runtime_pm(runtime_pm_samples)
    if args.infrared_fps:
        report["infrared_profile"] = {
            "width": args.width,
            "height": args.height,
            "fps": args.infrared_fps,
        }
        report["stereo_sync"] = summarize_stereo_sync(
            cleaned["infrared_1"]["source"],
            cleaned["infrared_2"]["source"],
        )
        report["imu_per_infrared_frame"] = {
            name: summarize_imu_per_frame(
                cleaned["infrared_1"]["source"], cleaned[name]["source"]
            )
            for name in ("accel", "gyro")
        }
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if all(item["count"] > 0 for item in report["streams"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
