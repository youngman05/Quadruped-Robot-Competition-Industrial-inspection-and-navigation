#!/usr/bin/env python3
"""Interactively record named map-frame waypoints without commanding the robot."""

import argparse
import math
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.time import Time
from tf2_ros import Buffer, TransformException, TransformListener

from nodes.navigation.waypoint_calibration import (
    DEFAULT_CALIBRATION_ORDER,
    WaypointCalibrationError,
    estimate_stable_pose,
    load_waypoint_document,
    new_waypoint_document,
    upsert_waypoint,
    validate_waypoint_name,
    write_waypoint_document,
)


class WaypointCalibrationRecorder(Node):
    def __init__(self, args):
        super().__init__("waypoint_calibration_recorder")
        self.args = args
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

    def lookup_sample(self):
        try:
            transform = self.tf_buffer.lookup_transform(
                self.args.frame_id,
                self.args.base_frame,
                Time(),
                timeout=Duration(seconds=self.args.tf_timeout),
            )
        except TransformException:
            return None

        stamp = transform.header.stamp
        stamp_ns = int(stamp.sec) * 1000000000 + int(stamp.nanosec)
        now_ns = self.get_clock().now().nanoseconds
        tf_age = max(0.0, (now_ns - stamp_ns) / 1e9) if stamp_ns else 0.0
        if tf_age > self.args.max_tf_age:
            return None

        translation = transform.transform.translation
        rotation = transform.transform.rotation
        siny = 2.0 * (rotation.w * rotation.z + rotation.x * rotation.y)
        cosy = 1.0 - 2.0 * (rotation.y * rotation.y + rotation.z * rotation.z)
        return {
            "x": float(translation.x),
            "y": float(translation.y),
            "yaw": math.atan2(siny, cosy),
            "tf_age": tf_age,
        }

    def collect_samples(self):
        deadline = time.monotonic() + self.args.sample_duration
        period = 1.0 / self.args.sample_rate
        next_sample = time.monotonic()
        samples = []
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=min(0.05, period))
            now = time.monotonic()
            if now < next_sample:
                continue
            sample = self.lookup_sample()
            if sample is not None:
                samples.append(sample)
            next_sample = max(next_sample + period, now)
        return samples


def load_or_create_document(path, frame_id, map_id):
    if path.exists():
        document = load_waypoint_document(path)
        if document["frame_id"] != frame_id:
            raise WaypointCalibrationError(
                "existing file frame_id=%s, requested frame_id=%s"
                % (document["frame_id"], frame_id)
            )
        if map_id:
            existing = document.get("map_id", "")
            if existing and existing != map_id:
                raise WaypointCalibrationError(
                    "existing map_id=%s, requested map_id=%s" % (existing, map_id)
                )
            document["map_id"] = map_id
        return document
    return new_waypoint_document(frame_id=frame_id, map_id=map_id)


def make_session_backup(path):
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = path.parent / "calibration_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / ("%s.backup_%s%s" % (path.stem, stamp, path.suffix))
    shutil.copy2(str(path), str(backup))
    return backup


def next_missing_index(order, document):
    captured = document["waypoints"]
    for index, name in enumerate(order):
        if name not in captured:
            return index
    return 0


def print_status(order, document):
    captured = document["waypoints"]
    print("\nCalibration status:")
    for index, name in enumerate(order, start=1):
        marker = "captured" if name in captured else "pending"
        print("  %2d. %-30s %s" % (index, name, marker))


def confirm(prompt):
    return input(prompt).strip().lower() in ("y", "yes")


def capture_waypoint(node, document, output_path, name):
    validate_waypoint_name(name)
    print(
        "Sampling %s for %.1fs. Keep the robot fully stopped."
        % (name, node.args.sample_duration)
    )
    samples = node.collect_samples()
    try:
        estimate = estimate_stable_pose(
            samples,
            min_samples=node.args.min_samples,
            max_xy_deviation=node.args.max_xy_deviation,
            max_yaw_deviation=node.args.max_yaw_deviation,
        )
    except WaypointCalibrationError as exc:
        print("Rejected: %s" % exc)
        return False

    print(
        "Candidate %s: x=%.4f y=%.4f yaw=%.3frad (%.2fdeg) "
        "samples=%d max_xy=%.4fm max_yaw=%.3fdeg"
        % (
            name,
            estimate["x"],
            estimate["y"],
            estimate["yaw"],
            estimate["yaw_deg"],
            estimate["sample_count"],
            estimate["max_xy_deviation"],
            estimate["max_yaw_deviation_deg"],
        )
    )
    if not confirm("Accept and save this waypoint? [y/N] "):
        print("Discarded.")
        return False

    upsert_waypoint(document, name, estimate)
    write_waypoint_document(output_path, document)
    print("Saved %s to %s" % (name, output_path))
    return True


def run_interactive(node, document, output_path, order):
    index = next_missing_index(order, document)
    print("This process only reads TF. It never publishes cmd_vel.")
    print("Commands: Enter=capture current, list, goto NAME, skip, finish, quit")
    print_status(order, document)

    while rclpy.ok():
        name = order[index]
        existing = " (recapture)" if name in document["waypoints"] else ""
        command = input("\n[%d/%d] %s%s > " % (index + 1, len(order), name, existing)).strip()
        if not command:
            if capture_waypoint(node, document, output_path, name):
                index = (index + 1) % len(order)
            continue
        if command == "list":
            print_status(order, document)
            continue
        if command == "skip":
            index = (index + 1) % len(order)
            continue
        if command.startswith("goto "):
            target = command[5:].strip()
            if target not in order:
                print("Unknown waypoint: %s" % target)
                continue
            index = order.index(target)
            continue
        if command == "finish":
            missing = [item for item in order if item not in document["waypoints"]]
            if missing:
                print("Cannot finish; missing: %s" % ", ".join(missing))
                continue
            document.setdefault("calibration", {})["status"] = "complete"
            write_waypoint_document(output_path, document)
            print("Calibration complete: %s" % output_path)
            return 0
        if command in ("quit", "q"):
            print("Calibration left in progress: %s" % output_path)
            return 0
        print("Unknown command.")
    return 1


def parse_args():
    parser = argparse.ArgumentParser(
        description="Record stable map-frame waypoints while the robot is driven by remote control."
    )
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "configs" / "navigation" / "waypoints_real.yaml"),
    )
    parser.add_argument(
        "--map-id",
        required=True,
        help="Stable identifier for the exact map and field layout used by this calibration.",
    )
    parser.add_argument("--frame-id", default="map")
    parser.add_argument("--base-frame", default="base_link")
    parser.add_argument("--sample-duration", type=float, default=3.0)
    parser.add_argument("--sample-rate", type=float, default=10.0)
    parser.add_argument("--tf-timeout", type=float, default=0.20)
    parser.add_argument("--max-tf-age", type=float, default=0.20)
    parser.add_argument("--min-samples", type=int, default=20)
    parser.add_argument("--max-xy-deviation", type=float, default=0.04)
    parser.add_argument("--max-yaw-deviation", type=float, default=0.06)
    parser.add_argument(
        "--waypoint",
        action="append",
        dest="waypoints",
        help="Override the default calibration order. Repeat for each name.",
    )
    return parser.parse_args()


def validate_args(args):
    positive = {
        "--sample-duration": args.sample_duration,
        "--sample-rate": args.sample_rate,
        "--tf-timeout": args.tf_timeout,
        "--max-tf-age": args.max_tf_age,
        "--max-xy-deviation": args.max_xy_deviation,
        "--max-yaw-deviation": args.max_yaw_deviation,
    }
    for name, value in positive.items():
        if not math.isfinite(value) or value <= 0.0:
            raise SystemExit("%s must be > 0" % name)
    if args.min_samples < 2:
        raise SystemExit("--min-samples must be >= 2")
    order = tuple(args.waypoints or DEFAULT_CALIBRATION_ORDER)
    if not order:
        raise SystemExit("at least one waypoint is required")
    for name in order:
        validate_waypoint_name(name)
    if len(set(order)) != len(order):
        raise SystemExit("waypoint names in the calibration order must be unique")
    return order


def main():
    args = parse_args()
    try:
        order = validate_args(args)
        output_path = Path(args.output).expanduser().resolve()
        document = load_or_create_document(
            output_path,
            frame_id=args.frame_id,
            map_id=args.map_id,
        )
        backup = make_session_backup(output_path)
        if backup is not None:
            print("Session backup: %s" % backup)
    except WaypointCalibrationError as exc:
        raise SystemExit(str(exc))

    rclpy.init()
    node = WaypointCalibrationRecorder(args)
    try:
        return run_interactive(node, document, output_path, order)
    except (EOFError, KeyboardInterrupt):
        print("\nCalibration interrupted; accepted points remain saved.")
        return 130
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
