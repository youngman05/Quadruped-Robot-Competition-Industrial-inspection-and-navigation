#!/usr/bin/env python3
"""Record the live map -> base_link pose trace without commanding the robot."""

import argparse
import csv
import json
import math
import time
from pathlib import Path
from types import SimpleNamespace

import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from tf2_ros import Buffer, TransformException, TransformListener
from nav_msgs.msg import Odometry


def yaw_from_quaternion(q):
    siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
    cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny_cosp, cosy_cosp)


class MapBaseLinkTrace(Node):
    def __init__(self, args):
        super().__init__("map_base_link_trace")
        self.args = args
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.samples = []
        self.leg_samples = []
        self.lookup_failures = 0
        self.latest_odom = None
        odom_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT,
        )
        self.create_subscription(
            Odometry, args.odom_topic, self.odom_callback, odom_qos
        )

    def odom_callback(self, msg):
        self.latest_odom = msg

    def lookup_pose(self, target_frame, source_frame):
        try:
            transform = self.tf_buffer.lookup_transform(
                target_frame,
                source_frame,
                Time(),
                timeout=Duration(seconds=self.args.tf_timeout),
            )
        except TransformException as exc:
            return {
                "target_frame": target_frame,
                "source_frame": source_frame,
                "ok": False,
                "error": str(exc),
            }

        translation = transform.transform.translation
        rotation = transform.transform.rotation
        return {
            "target_frame": target_frame,
            "source_frame": source_frame,
            "ok": True,
            "tf_stamp_sec": transform.header.stamp.sec,
            "tf_stamp_nanosec": transform.header.stamp.nanosec,
            "x": translation.x,
            "y": translation.y,
            "z": translation.z,
            "yaw": yaw_from_quaternion(rotation),
        }

    def capture(self):
        legs = {
            "map_to_odom": self.lookup_pose(self.args.map_frame, "odom"),
            "odom_to_base_link": self.lookup_pose("odom", self.args.base_frame),
            "map_to_base_link": self.lookup_pose(
                self.args.map_frame, self.args.base_frame
            ),
        }
        self.leg_samples.append({"host_time_unix": time.time(), "legs": legs})

        pose = legs["map_to_base_link"]
        if not pose["ok"]:
            self.lookup_failures += 1
            self.get_logger().warning("map -> base_link TF lookup failed: %s" % pose["error"])
            fallback_pose = self.map_pose_from_odom()
            if fallback_pose is not None:
                self.samples.append(fallback_pose)
            return

        pose["host_time_unix"] = time.time()
        pose["source"] = "tf"
        self.samples.append(pose)

    def map_pose_from_odom(self):
        source = "odom_subscription"
        if self.latest_odom is None:
            try:
                with open(self.args.odom_file, "r", encoding="utf-8") as handle:
                    odom = json.load(handle)
            except (OSError, ValueError):
                return None
            x = float(odom["x"])
            y = float(odom["y"])
            z = float(odom["z"])
            q = SimpleNamespace(**{
                "x": float(odom["qx"]),
                "y": float(odom["qy"]),
                "z": float(odom["qz"]),
                "w": float(odom["qw"]),
            })
            stamp_sec = 0
            stamp_nanosec = 0
            source = "odom_file_fallback"
        else:
            position = self.latest_odom.pose.pose.position
            x = position.x
            y = position.y
            z = position.z
            q = self.latest_odom.pose.pose.orientation
            stamp_sec = self.latest_odom.header.stamp.sec
            stamp_nanosec = self.latest_odom.header.stamp.nanosec

        map_yaw = self.args.map_from_odom_yaw
        cos_yaw = math.cos(map_yaw)
        sin_yaw = math.sin(map_yaw)
        return {
            "host_time_unix": time.time(),
            "tf_stamp_sec": stamp_sec,
            "tf_stamp_nanosec": stamp_nanosec,
            "x": self.args.map_from_odom_x + cos_yaw * x - sin_yaw * y,
            "y": self.args.map_from_odom_y + sin_yaw * x + cos_yaw * y,
            "z": z,
            "yaw": map_yaw + yaw_from_quaternion(q),
            "source": source,
        }

    def run(self):
        deadline = time.monotonic() + self.args.duration
        period = 1.0 / self.args.rate
        next_sample = time.monotonic()

        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
            now = time.monotonic()
            if now >= next_sample:
                self.capture()
                next_sample = now + period

        return self.write_outputs()

    def write_outputs(self):
        output_dir = Path(self.args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / "map_base_link_trace.csv"
        summary_path = output_dir / "summary.json"

        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=(
                    "host_time_unix",
                    "tf_stamp_sec",
                    "tf_stamp_nanosec",
                    "x",
                    "y",
                    "z",
                    "yaw",
                    "source",
                ),
            )
            writer.writeheader()
            writer.writerows(self.samples)

        summary = {
            "map_frame": self.args.map_frame,
            "base_frame": self.args.base_frame,
            "duration_requested_sec": self.args.duration,
            "sample_count": len(self.samples),
            "lookup_failures": self.lookup_failures,
            "csv_path": str(csv_path),
        }
        if self.leg_samples:
            summary["tf_legs_last"] = self.leg_samples[-1]
        if self.samples:
            first = self.samples[0]
            last = self.samples[-1]
            summary["start"] = first
            summary["end"] = last
            summary["delta"] = {
                "x": last["x"] - first["x"],
                "y": last["y"] - first["y"],
                "yaw": last["yaw"] - first["yaw"],
            }

        summary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        return summary


def parse_args():
    parser = argparse.ArgumentParser(
        description="Record map -> base_link poses without sending motion commands."
    )
    parser.add_argument("--duration", type=float, default=15.0)
    parser.add_argument("--rate", type=float, default=10.0)
    parser.add_argument("--tf-timeout", type=float, default=0.2)
    parser.add_argument("--map-frame", default="map")
    parser.add_argument("--base-frame", default="base_link")
    parser.add_argument("--odom-topic", default="/odom")
    parser.add_argument("--odom-file", default="/tmp/odom_latest.json")
    parser.add_argument("--map-from-odom-x", type=float, default=5.35)
    parser.add_argument("--map-from-odom-y", type=float, default=0.75)
    parser.add_argument("--map-from-odom-yaw", type=float, default=math.pi)
    parser.add_argument("--output-dir", default="nav2_live_trace")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.duration <= 0.0:
        raise SystemExit("--duration must be > 0")
    if args.rate <= 0.0:
        raise SystemExit("--rate must be > 0")
    if args.tf_timeout <= 0.0:
        raise SystemExit("--tf-timeout must be > 0")

    rclpy.init()
    node = MapBaseLinkTrace(args)
    try:
        summary = node.run()
        print(json.dumps(summary, indent=2, sort_keys=True))
        if not summary["sample_count"]:
            raise SystemExit(2)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
