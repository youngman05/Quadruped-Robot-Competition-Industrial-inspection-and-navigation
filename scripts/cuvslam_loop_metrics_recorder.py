#!/usr/bin/env python3
"""Record lightweight online cuVSLAM trajectory metrics.

This script is intended to run inside the Isaac ROS Humble container. It writes
small text/JSON/CSV artifacts under /logs so a loop run can be judged without
looking at RViz. It intentionally never calls GetAllPoses; the full optimized
pose graph is queried once after the robot stops by
``cuvslam_get_all_poses_once.py``.
"""

import argparse
import csv
import json
import math
import os
import signal
import time
from pathlib import Path

import rclpy
from nav_msgs.msg import Odometry, Path as RosPath
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)


def point_distance(a, b):
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def point_to_list(p):
    return [p.x, p.y, p.z]


def quat_to_list(q):
    return [q.x, q.y, q.z, q.w]


def summarize_path(msg):
    poses = msg.poses
    summary = {
        "frame_id": msg.header.frame_id,
        "poses": len(poses),
        "path_length_m": None,
        "closure_error_m": None,
        "closure_error_ratio": None,
        "max_step_m": None,
        "first_position": None,
        "last_position": None,
    }
    if len(poses) < 2:
        return summary

    first = poses[0].pose.position
    last = poses[-1].pose.position
    total = 0.0
    max_step = 0.0
    for idx in range(1, len(poses)):
        step = point_distance(poses[idx - 1].pose.position, poses[idx].pose.position)
        total += step
        max_step = max(max_step, step)

    closure = point_distance(first, last)
    summary.update(
        {
            "path_length_m": total,
            "closure_error_m": closure,
            "closure_error_ratio": closure / total if total > 1e-9 else None,
            "max_step_m": max_step,
            "first_position": point_to_list(first),
            "last_position": point_to_list(last),
        }
    )
    return summary


class LoopMetricsRecorder(Node):
    def __init__(
        self,
        log_dir,
        interval,
        path_dump_interval,
        mount_mode,
        expected_base_frame,
        enable_path_topics,
        odom_csv_hz,
    ):
        super().__init__("cuvslam_loop_metrics_recorder")
        self.log_dir = Path(log_dir)
        self.interval = interval
        self.path_dump_interval = path_dump_interval
        self.mount_mode = mount_mode
        self.expected_base_frame = expected_base_frame
        self.path_topics_enabled = enable_path_topics
        self.odom_csv_interval = 1.0 / odom_csv_hz if odom_csv_hz > 0.0 else 0.0
        self.last_odom_csv_stamp = None
        self.latest_paths = {}
        self.latest_odom = None
        self.first_odom = None
        self.prev_odom_position = None
        self.odom_path_length_m = 0.0
        self.odom_count = 0
        self.odom_csv_count = 0
        self.start_time = time.time()
        self.last_summary_time = 0.0
        self.last_path_dump_time = 0.0

        self.odom_csv_path = self.log_dir / "odometry_samples.csv"
        self.odom_csv_file = self.odom_csv_path.open("w", newline="", encoding="utf-8")
        self.odom_writer = csv.writer(self.odom_csv_file)
        self.odom_writer.writerow(
            [
                "elapsed_s",
                "stamp_sec",
                "frame_id",
                "child_frame_id",
                "x",
                "y",
                "z",
                "qx",
                "qy",
                "qz",
                "qw",
            ]
        )

        if self.path_topics_enabled:
            path_qos = QoSProfile(
                history=HistoryPolicy.KEEP_LAST,
                depth=1,
                reliability=ReliabilityPolicy.BEST_EFFORT,
                durability=DurabilityPolicy.VOLATILE,
            )
            self.create_subscription(
                RosPath,
                "/visual_slam/tracking/slam_path",
                lambda msg: self._path_callback("slam_path", msg),
                path_qos,
            )
            self.create_subscription(
                RosPath,
                "/visual_slam/tracking/vo_path",
                lambda msg: self._path_callback("vo_path", msg),
                path_qos,
            )
        self.create_subscription(
            Odometry,
            "/visual_slam/tracking/odometry",
            self._odom_callback,
            50,
        )

    def _path_callback(self, name, msg):
        self.latest_paths[name] = msg

    def _odom_callback(self, msg):
        self.latest_odom = msg
        if self.first_odom is None:
            self.first_odom = msg
        pos = msg.pose.pose.position
        if self.prev_odom_position is not None:
            self.odom_path_length_m += point_distance(self.prev_odom_position, pos)
        self.prev_odom_position = pos
        self.odom_count += 1

        q = msg.pose.pose.orientation
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec / 1e9
        should_write_csv = (
            self.last_odom_csv_stamp is None
            or stamp < self.last_odom_csv_stamp
            or stamp - self.last_odom_csv_stamp >= self.odom_csv_interval
        )
        if should_write_csv:
            self.odom_writer.writerow(
                [
                    f"{time.time() - self.start_time:.3f}",
                    f"{stamp:.9f}",
                    msg.header.frame_id,
                    msg.child_frame_id,
                    f"{pos.x:.6f}",
                    f"{pos.y:.6f}",
                    f"{pos.z:.6f}",
                    f"{q.x:.8f}",
                    f"{q.y:.8f}",
                    f"{q.z:.8f}",
                    f"{q.w:.8f}",
                ]
            )
            self.last_odom_csv_stamp = stamp
            self.odom_csv_count += 1
            if self.odom_csv_count % 50 == 0:
                self.odom_csv_file.flush()

    def maybe_write_outputs(self, force=False):
        now = time.time()
        if force or now - self.last_summary_time >= self.interval:
            self.write_summary()
            self.last_summary_time = now
        if force or now - self.last_path_dump_time >= self.path_dump_interval:
            self.write_path_csvs()
            self.last_path_dump_time = now

    def make_summary(self):
        elapsed = time.time() - self.start_time
        paths = {name: summarize_path(msg) for name, msg in self.latest_paths.items()}
        odom_summary = {
            "samples": self.odom_count,
            "frame_id": None,
            "child_frame_id": None,
            "path_length_m": self.odom_path_length_m,
            "first_position": None,
            "last_position": None,
            "closure_error_m": None,
            "closure_error_ratio": None,
        }
        if self.first_odom is not None and self.latest_odom is not None:
            first = self.first_odom.pose.pose.position
            last = self.latest_odom.pose.pose.position
            closure = point_distance(first, last)
            odom_summary.update(
                {
                    "frame_id": self.latest_odom.header.frame_id,
                    "child_frame_id": self.latest_odom.child_frame_id,
                    "first_position": point_to_list(first),
                    "last_position": point_to_list(last),
                    "closure_error_m": closure,
                    "closure_error_ratio": closure / self.odom_path_length_m
                    if self.odom_path_length_m > 1e-9
                    else None,
                }
            )

        base_frame_match = (
            odom_summary["child_frame_id"] == self.expected_base_frame
        )
        return {
            "elapsed_s": elapsed,
            "generated_at_unix": time.time(),
            "mount_mode": self.mount_mode,
            "expected_base_frame": self.expected_base_frame,
            "base_frame_match": base_frame_match,
            "robot_base_ready": self.mount_mode == "robot" and base_frame_match,
            "all_poses": {
                "service_status": "disabled_online",
                "query_tool": "cuvslam_get_all_poses_once.py",
            },
            "path_topics_enabled": self.path_topics_enabled,
            "paths": paths,
            "odometry": odom_summary,
            "interpretation": self.interpret(
                paths, odom_summary, self.path_topics_enabled
            ),
        }

    @staticmethod
    def interpret(paths, odom_summary, path_topics_enabled=True):
        if not path_topics_enabled:
            return "online_path_topics_disabled: use one-shot GetAllPoses after stop"
        slam = paths.get("slam_path") or {}
        closure = slam.get("closure_error_m")
        length = slam.get("path_length_m")
        if closure is None or length is None:
            return "insufficient_data: waiting for slam_path with at least two poses"
        if length < 5.0:
            return "insufficient_motion: path length is too short for a loop judgement"
        if closure < 0.2:
            return "good_loop_closure: closure error below 0.2 m"
        if closure < 0.5:
            return "usable_but_note_drift: closure error between 0.2 m and 0.5 m"
        return "poor_loop_closure: closure error above 0.5 m"

    def write_summary(self):
        data = self.make_summary()
        json_path = self.log_dir / "loop_metrics_latest.json"
        tmp_json = json_path.with_suffix(".json.tmp")
        tmp_json.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp_json.replace(json_path)

        text_path = self.log_dir / "loop_metrics_latest.txt"
        lines = [
            "cuVSLAM loop metrics",
            f"elapsed_s: {data['elapsed_s']:.1f}",
            f"interpretation: {data['interpretation']}",
            f"mount_mode: {data['mount_mode']}",
            f"expected_base_frame: {data['expected_base_frame']}",
            f"base_frame_match: {data['base_frame_match']}",
            f"robot_base_ready: {data['robot_base_ready']}",
            f"path_topics_enabled: {data['path_topics_enabled']}",
            "all_poses_service: disabled_online",
            "",
            "odometry:",
        ]
        odom = data["odometry"]
        lines.extend(
            [
                f"  samples: {odom['samples']}",
                f"  frame_id: {odom['frame_id']}",
                f"  child_frame_id: {odom['child_frame_id']}",
                f"  path_length_m: {odom['path_length_m']:.3f}",
                f"  closure_error_m: {format_optional(odom['closure_error_m'])}",
                f"  closure_error_ratio: {format_optional(odom['closure_error_ratio'])}",
                f"  first_position: {format_list(odom['first_position'])}",
                f"  last_position: {format_list(odom['last_position'])}",
            ]
        )

        for name in ("slam_path", "vo_path"):
            item = data["paths"].get(name, {})
            lines.extend(
                [
                    "",
                    f"{name}:",
                    f"  poses: {item.get('poses')}",
                    f"  frame_id: {item.get('frame_id')}",
                    f"  path_length_m: {format_optional(item.get('path_length_m'))}",
                    f"  closure_error_m: {format_optional(item.get('closure_error_m'))}",
                    f"  closure_error_ratio: {format_optional(item.get('closure_error_ratio'))}",
                    f"  max_step_m: {format_optional(item.get('max_step_m'))}",
                    f"  first_position: {format_list(item.get('first_position'))}",
                    f"  last_position: {format_list(item.get('last_position'))}",
                ]
            )

        tmp_text = text_path.with_suffix(".txt.tmp")
        tmp_text.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp_text.replace(text_path)

    def write_path_csvs(self):
        for name, msg in self.latest_paths.items():
            csv_path = self.log_dir / f"{name}_latest.csv"
            tmp_path = csv_path.with_suffix(".csv.tmp")
            with tmp_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["index", "x", "y", "z", "qx", "qy", "qz", "qw"])
                for idx, pose_stamped in enumerate(msg.poses):
                    p = pose_stamped.pose.position
                    q = pose_stamped.pose.orientation
                    writer.writerow(
                        [
                            idx,
                            f"{p.x:.6f}",
                            f"{p.y:.6f}",
                            f"{p.z:.6f}",
                            f"{q.x:.8f}",
                            f"{q.y:.8f}",
                            f"{q.z:.8f}",
                            f"{q.w:.8f}",
                        ]
                    )
            tmp_path.replace(csv_path)

    def close(self):
        self.maybe_write_outputs(force=True)
        self.odom_csv_file.flush()
        self.odom_csv_file.close()


def format_optional(value):
    if value is None:
        return "n/a"
    return f"{value:.4f}"


def format_list(value):
    if value is None:
        return "n/a"
    return "(" + ", ".join(f"{item:.3f}" for item in value) + ")"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-dir", default="/logs")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--path-dump-interval", type=float, default=15.0)
    parser.add_argument("--odom-csv-hz", type=float, default=10.0)
    parser.add_argument("--mount-mode", choices=("bench", "robot"), default="bench")
    parser.add_argument("--expected-base-frame", default="camera_link")
    parser.add_argument(
        "--disable-all-poses-service",
        action="store_true",
        help="Compatibility flag; online recorder never calls GetAllPoses.",
    )
    parser.add_argument(
        "--disable-path-topics",
        action="store_true",
        help="Do not subscribe to rolling 1024-pose Path topics.",
    )
    args = parser.parse_args()

    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    Path("/tmp/cuvslam_loop_metrics_recorder.pid").write_text(
        str(os.getpid()), encoding="utf-8"
    )

    rclpy.init()
    node = LoopMetricsRecorder(
        log_dir,
        args.interval,
        args.path_dump_interval,
        args.mount_mode,
        args.expected_base_frame,
        not args.disable_path_topics,
        args.odom_csv_hz,
    )
    stopping = {"value": False}

    def handle_signal(signum, frame):
        stopping["value"] = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        while rclpy.ok() and not stopping["value"]:
            rclpy.spin_once(node, timeout_sec=0.2)
            node.maybe_write_outputs()
    finally:
        node.close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
