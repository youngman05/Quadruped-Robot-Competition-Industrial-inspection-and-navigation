#!/usr/bin/env python3
"""Send Nav2 waypoints sequentially and wait for natural action results.

Unlike nav2_goal_cmd_vel_probe.py, this script does not cancel each goal after a
fixed sampling window. It is intended to test whether BT Navigator can complete
one NavigateToPose goal and then accept/controller-drive the next goal in the
same Nav2 session.
"""

import argparse
import csv
import json
import math
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import Twist
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Odometry
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from tf2_ros import Buffer, TransformException, TransformListener


STATUS_NAMES = {
    GoalStatus.STATUS_UNKNOWN: "UNKNOWN",
    GoalStatus.STATUS_ACCEPTED: "ACCEPTED",
    GoalStatus.STATUS_EXECUTING: "EXECUTING",
    GoalStatus.STATUS_CANCELING: "CANCELING",
    GoalStatus.STATUS_SUCCEEDED: "SUCCEEDED",
    GoalStatus.STATUS_CANCELED: "CANCELED",
    GoalStatus.STATUS_ABORTED: "ABORTED",
}


_INSPECTION_PREFIX_LEGACY = [
    ("obstacle_cross_target", 1.05, 0.75, math.pi),
    ("pos1_middle", 1.50, 3.25, math.pi / 2.0),
    ("pos1_middle_turned", 1.50, 3.25, -math.pi / 2.0),
]

_INSPECTION_PREFIX_STAGED = [
    ("obstacle_cross_target", 1.05, 0.75, math.pi),
    # Stay left until the full footprint clears the lower cabinet's upper-left
    # corner at (1.0, 2.5), then enter the middle inspection corridor.
    ("pos1_left_clear", 0.60, 2.90, math.pi / 2.0),
    ("pos1_middle", 1.50, 3.25, math.pi / 2.0),
    # Approximate the Lite3's drifting clockwise U-turn with two empirically
    # sized quarter turns, then approach the observation pose heading south.
    ("pos1_turn_quarter_1", 1.72, 3.50, 0.0),
    ("pos1_turn_quarter_2", 2.10, 3.50, -math.pi / 2.0),
    ("pos1_middle_turned", 2.10, 3.25, -math.pi / 2.0),
]

_INSPECTION_TAIL = [
    ("pos2a_upper_right", 2.60, 4.50, math.pi),
    ("pos2b_lower_right", 2.60, 2.00, math.pi),
]

_FULL_TAIL = [
    ("grab_area_approach", 3.10, 2.00, 0.0),
    ("placement_A_approach", 3.25, 4.95, math.pi / 2.0),
    ("placement_B_approach", 3.75, 4.95, math.pi / 2.0),
    ("placement_C_approach", 4.25, 4.95, math.pi / 2.0),
    ("placement_D_approach", 4.65, 4.95, math.pi / 2.0),
]


ROUTE_PRESETS = {
    # Keep the proven same-spot route unchanged as the regression baseline.
    "nav-only-full": _INSPECTION_PREFIX_LEGACY + _INSPECTION_TAIL + _FULL_TAIL,
    "nav-only-inspection": _INSPECTION_PREFIX_LEGACY + _INSPECTION_TAIL,
    # Opt-in staged-turn routes avoid the same-XY 180 deg RotateToGoal.
    "nav-only-full-staged": _INSPECTION_PREFIX_STAGED + _INSPECTION_TAIL + _FULL_TAIL,
    "nav-only-inspection-staged": _INSPECTION_PREFIX_STAGED + _INSPECTION_TAIL,
}


def yaw_to_quaternion(yaw):
    half = yaw * 0.5
    return {
        "x": 0.0,
        "y": 0.0,
        "z": math.sin(half),
        "w": math.cos(half),
    }


def yaw_from_quaternion(q):
    siny = 2.0 * (q.w * q.z + q.x * q.y)
    cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny, cosy)


def normalize_angle(value):
    while value > math.pi:
        value -= 2.0 * math.pi
    while value < -math.pi:
        value += 2.0 * math.pi
    return value


def make_output_dir(value):
    if value:
        path = Path(value).expanduser()
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path.home() / "competition_logs" / "nav2_waypoint_sequence" / stamp
    path.mkdir(parents=True, exist_ok=True)
    return path


class Nav2WaypointSequenceProbe(Node):
    def __init__(self, args):
        super().__init__("nav2_waypoint_sequence_probe")
        self.args = args
        self.action_client = ActionClient(self, NavigateToPose, "navigate_to_pose")
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.latest_odom = None
        self.segment_cmd = None
        self.segment_cmd_samples = None
        self.segment_start_time = None
        self.segment_trace = None
        self.segments = []

        cmd_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=50,
            reliability=ReliabilityPolicy.RELIABLE,
        )
        odom_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT,
        )
        self.create_subscription(Twist, "/cmd_vel", self._cmd_callback, cmd_qos)
        self.create_subscription(Odometry, args.odom_topic, self._odom_callback, odom_qos)

    def _cmd_callback(self, msg):
        if self.segment_cmd is None:
            return
        linear_x = float(msg.linear.x)
        linear_y = float(msg.linear.y)
        linear_z = float(msg.linear.z)
        angular_x = float(msg.angular.x)
        angular_y = float(msg.angular.y)
        angular_z = float(msg.angular.z)
        now = time.time()
        self.segment_cmd["cmd_count"] += 1
        if abs(linear_x) > 1e-5 or abs(angular_z) > 1e-5:
            self.segment_cmd["nonzero_count"] += 1
        if abs(linear_x) > 1e-5:
            self.segment_cmd["linear_x_nonzero_count"] += 1
        if abs(angular_z) > 1e-5:
            self.segment_cmd["angular_z_nonzero_count"] += 1
        self.segment_cmd["max_linear_x"] = max(
            self.segment_cmd["max_linear_x"], abs(linear_x)
        )
        self.segment_cmd["max_abs_angular_z"] = max(
            self.segment_cmd["max_abs_angular_z"], abs(angular_z)
        )
        if self.segment_cmd_samples is not None:
            self.segment_cmd_samples.append(
                {
                    "segment_elapsed_sec": (
                        now - self.segment_start_time
                        if self.segment_start_time is not None
                        else 0.0
                    ),
                    "host_time_unix": now,
                    "linear_x": linear_x,
                    "linear_y": linear_y,
                    "linear_z": linear_z,
                    "angular_x": angular_x,
                    "angular_y": angular_y,
                    "angular_z": angular_z,
                }
            )

    def _odom_callback(self, msg):
        self.latest_odom = msg

    def lookup_map_pose(self, allow_fallback=True):
        try:
            transform = self.tf_buffer.lookup_transform(
                self.args.frame_id,
                self.args.base_frame,
                Time(),
                timeout=Duration(seconds=self.args.tf_timeout),
            )
        except TransformException as exc:
            if not allow_fallback:
                return {"ok": False, "error": str(exc)}
            fallback = self.map_pose_from_odom()
            if fallback is not None:
                fallback["tf_error"] = str(exc)
                return fallback
            return {"ok": False, "error": str(exc)}

        translation = transform.transform.translation
        rotation = transform.transform.rotation
        return {
            "ok": True,
            "source": "tf",
            "host_time_unix": time.time(),
            "tf_stamp_sec": int(transform.header.stamp.sec),
            "tf_stamp_nanosec": int(transform.header.stamp.nanosec),
            "x": float(translation.x),
            "y": float(translation.y),
            "z": float(translation.z),
            "yaw": float(yaw_from_quaternion(rotation)),
        }

    def wait_for_map_pose(self):
        deadline = time.monotonic() + self.args.map_tf_timeout
        last_error = None
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
            pose = self.lookup_map_pose(allow_fallback=False)
            if pose.get("ok"):
                return pose
            last_error = pose.get("error")
            time.sleep(0.1)
        return {"ok": False, "error": last_error or "map TF unavailable"}

    def map_pose_from_odom(self):
        source = "odom_subscription"
        if self.latest_odom is None:
            try:
                with open(self.args.odom_file, "r", encoding="utf-8") as handle:
                    odom = json.load(handle)
            except (OSError, ValueError, KeyError):
                return None
            x = float(odom["x"])
            y = float(odom["y"])
            z = float(odom["z"])
            q = SimpleNamespace(
                x=float(odom["qx"]),
                y=float(odom["qy"]),
                z=float(odom["qz"]),
                w=float(odom["qw"]),
            )
            stamp_sec = 0
            stamp_nanosec = 0
            source = "odom_file_fallback"
        else:
            position = self.latest_odom.pose.pose.position
            x = float(position.x)
            y = float(position.y)
            z = float(position.z)
            q = self.latest_odom.pose.pose.orientation
            stamp_sec = int(self.latest_odom.header.stamp.sec)
            stamp_nanosec = int(self.latest_odom.header.stamp.nanosec)

        map_yaw = self.args.map_from_odom_yaw
        cos_yaw = math.cos(map_yaw)
        sin_yaw = math.sin(map_yaw)
        return {
            "ok": True,
            "source": source,
            "host_time_unix": time.time(),
            "tf_stamp_sec": stamp_sec,
            "tf_stamp_nanosec": stamp_nanosec,
            "x": self.args.map_from_odom_x + cos_yaw * x - sin_yaw * y,
            "y": self.args.map_from_odom_y + sin_yaw * x + cos_yaw * y,
            "z": z,
            "yaw": float(normalize_angle(map_yaw + yaw_from_quaternion(q))),
        }

    def capture_trace_sample(self, segment_index):
        if self.segment_trace is None:
            return
        pose = self.lookup_map_pose()
        pose["segment_index"] = segment_index
        self.segment_trace.append(pose)

    def build_goal_from_pose(self, x, y, yaw):
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose.header.frame_id = self.args.frame_id
        goal_msg.pose.header.stamp = self.get_clock().now().to_msg()
        goal_msg.pose.pose.position.x = float(x)
        goal_msg.pose.pose.position.y = float(y)
        goal_msg.pose.pose.position.z = 0.0
        q = yaw_to_quaternion(float(yaw))
        goal_msg.pose.pose.orientation.x = q["x"]
        goal_msg.pose.pose.orientation.y = q["y"]
        goal_msg.pose.pose.orientation.z = q["z"]
        goal_msg.pose.pose.orientation.w = q["w"]
        goal_msg.behavior_tree = self.args.behavior_tree
        return goal_msg

    def run(self):
        if not self.action_client.wait_for_server(timeout_sec=self.args.server_timeout):
            return {
                "ok": False,
                "error": "navigate_to_pose server unavailable",
                "segments": [],
            }

        goals = self.resolve_goals()
        for index, goal in enumerate(goals, start=1):
            segment = self.run_segment(index, goal)
            self.segments.append(segment)
            if self.args.stop_on_failure and not segment.get("succeeded"):
                break
            if index < len(goals) and self.args.inter_goal_pause > 0.0:
                self.spin_for(self.args.inter_goal_pause)

        return {
            "ok": bool(self.segments)
            and all(segment.get("succeeded") for segment in self.segments),
            "frame_id": self.args.frame_id,
            "base_frame": self.args.base_frame,
            "behavior_tree": self.args.behavior_tree or None,
            "segments": self.segments,
        }

    def resolve_goals(self):
        if self.args.route_preset:
            return [
                {
                    "x": x,
                    "y": y,
                    "yaw": yaw,
                    "source": "route_preset",
                    "preset": self.args.route_preset,
                    "label": label,
                }
                for label, x, y, yaw in ROUTE_PRESETS[self.args.route_preset]
            ]

        if self.args.goal:
            return [
                {"x": values[0], "y": values[1], "yaw": values[2], "source": "absolute"}
                for values in self.args.goal
            ]

        return [
            {"source": "forward_distance", "distance": distance}
            for distance in self.args.forward_distances
        ]

    def resolve_segment_goal(self, goal):
        if goal["source"] in ("absolute", "route_preset"):
            return goal

        pose = self.wait_for_map_pose()
        if not pose.get("ok"):
            raise RuntimeError("cannot resolve current map pose: %s" % pose.get("error"))
        yaw = self.args.target_yaw if self.args.target_yaw is not None else pose["yaw"]
        distance = goal["distance"]
        return {
            "x": pose["x"] + distance * math.cos(yaw),
            "y": pose["y"] + distance * math.sin(yaw),
            "yaw": yaw,
            "source": "forward_distance",
            "distance": distance,
            "start_pose_used": pose,
        }

    def run_segment(self, index, goal):
        self.segment_cmd = {
            "cmd_count": 0,
            "nonzero_count": 0,
            "linear_x_nonzero_count": 0,
            "angular_z_nonzero_count": 0,
            "max_linear_x": 0.0,
            "max_abs_angular_z": 0.0,
        }
        self.segment_cmd_samples = []
        self.segment_start_time = time.time()
        self.segment_trace = []
        goal = self.resolve_segment_goal(goal)
        start_pose = self.wait_for_map_pose()
        if not start_pose.get("ok"):
            raise RuntimeError("cannot capture start map pose: %s" % start_pose.get("error"))
        goal_msg = self.build_goal_from_pose(goal["x"], goal["y"], goal["yaw"])

        send_future = self.action_client.send_goal_async(goal_msg)
        rclpy.spin_until_future_complete(self, send_future, timeout_sec=self.args.server_timeout)
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            end_pose = self.lookup_map_pose()
            return {
                "index": index,
                "accepted": False,
                "succeeded": False,
                "error": "goal rejected",
                "goal": goal,
                "start_pose": start_pose,
                "end_pose": end_pose,
                "cmd_vel": self.segment_cmd,
                "cmd_vel_samples": self.segment_cmd_samples,
                "trace": self.segment_trace,
            }

        result_future = goal_handle.get_result_async()
        deadline = time.monotonic() + self.args.goal_timeout
        next_trace = time.monotonic()
        timed_out = False
        while rclpy.ok() and not result_future.done():
            rclpy.spin_once(self, timeout_sec=0.05)
            now = time.monotonic()
            if now >= next_trace:
                self.capture_trace_sample(index)
                next_trace = now + (1.0 / self.args.trace_rate)
            if now >= deadline:
                timed_out = True
                break

        canceled = False
        if timed_out and self.args.cancel_on_timeout:
            cancel_future = goal_handle.cancel_goal_async()
            rclpy.spin_until_future_complete(self, cancel_future, timeout_sec=2.0)
            canceled = True
            self.spin_for(self.args.post_cancel_spin)

        action_status = None
        status_name = "TIMEOUT"
        if result_future.done():
            result = result_future.result()
            action_status = int(result.status)
            status_name = STATUS_NAMES.get(action_status, str(action_status))

        end_pose = self.lookup_map_pose()
        delta = self.pose_delta(start_pose, end_pose)
        segment = {
            "index": index,
            "accepted": True,
            "succeeded": action_status == GoalStatus.STATUS_SUCCEEDED,
            "timed_out": timed_out,
            "canceled": canceled,
            "action_status": action_status,
            "action_status_name": status_name,
            "goal": goal,
            "start_pose": start_pose,
            "end_pose": end_pose,
            "delta": delta,
            "cmd_vel": self.segment_cmd,
            "cmd_vel_samples": self.segment_cmd_samples,
            "trace": self.segment_trace,
        }
        self.segment_cmd = None
        self.segment_cmd_samples = None
        self.segment_start_time = None
        self.segment_trace = None
        return segment

    def spin_for(self, seconds):
        deadline = time.monotonic() + seconds
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)

    @staticmethod
    def pose_delta(start_pose, end_pose):
        if not start_pose.get("ok") or not end_pose.get("ok"):
            return None
        return {
            "x": end_pose["x"] - start_pose["x"],
            "y": end_pose["y"] - start_pose["y"],
            "z": end_pose["z"] - start_pose["z"],
            "xy": math.hypot(end_pose["x"] - start_pose["x"], end_pose["y"] - start_pose["y"]),
            "yaw": normalize_angle(end_pose["yaw"] - start_pose["yaw"]),
        }


def write_outputs(summary, output_dir):
    summary_path = output_dir / "summary.json"
    trace_path = output_dir / "trace.csv"
    cmd_vel_path = output_dir / "cmd_vel.csv"

    fieldnames = (
        "segment_index",
        "host_time_unix",
        "source",
        "ok",
        "x",
        "y",
        "z",
        "yaw",
        "tf_stamp_sec",
        "tf_stamp_nanosec",
        "error",
    )
    with trace_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for segment in summary["segments"]:
            for sample in segment.get("trace", []):
                writer.writerow(sample)

    cmd_fieldnames = (
        "segment_index",
        "sample_index",
        "segment_elapsed_sec",
        "host_time_unix",
        "linear_x",
        "linear_y",
        "linear_z",
        "angular_x",
        "angular_y",
        "angular_z",
    )
    with cmd_vel_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=cmd_fieldnames, extrasaction="ignore")
        writer.writeheader()
        for segment in summary["segments"]:
            samples = segment.pop("cmd_vel_samples", [])
            segment["cmd_vel_sample_count"] = len(samples)
            for sample_index, sample in enumerate(samples, start=1):
                row = dict(sample)
                row["segment_index"] = segment["index"]
                row["sample_index"] = sample_index
                writer.writerow(row)

    summary["summary_path"] = str(summary_path)
    summary["trace_path"] = str(trace_path)
    summary["cmd_vel_path"] = str(cmd_vel_path)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run sequential NavigateToPose goals without per-goal sample cancel."
    )
    parser.add_argument(
        "--goal",
        nargs=3,
        type=float,
        action="append",
        metavar=("X", "Y", "YAW"),
        help="Absolute map goal. Repeat for multiple waypoints.",
    )
    parser.add_argument(
        "--forward-distances",
        nargs="+",
        type=float,
        help="Generate goals forward from the current map->base_link pose.",
    )
    parser.add_argument(
        "--route-preset",
        choices=sorted(ROUTE_PRESETS),
        help="Run a built-in absolute waypoint sequence.",
    )
    parser.add_argument("--target-yaw", type=float, default=None)
    parser.add_argument("--frame-id", default="map")
    parser.add_argument("--base-frame", default="base_link")
    parser.add_argument("--odom-topic", default="/odom")
    parser.add_argument("--odom-file", default="/tmp/odom_latest.json")
    parser.add_argument("--map-from-odom-x", type=float, default=5.35)
    parser.add_argument("--map-from-odom-y", type=float, default=0.75)
    parser.add_argument("--map-from-odom-yaw", type=float, default=math.pi)
    parser.add_argument("--server-timeout", type=float, default=20.0)
    parser.add_argument("--goal-timeout", type=float, default=45.0)
    parser.add_argument("--map-tf-timeout", type=float, default=20.0)
    parser.add_argument("--trace-rate", type=float, default=5.0)
    parser.add_argument("--tf-timeout", type=float, default=0.2)
    parser.add_argument("--inter-goal-pause", type=float, default=2.0)
    parser.add_argument("--post-cancel-spin", type=float, default=1.0)
    parser.add_argument(
        "--behavior-tree",
        default="",
        help="Optional NavigateToPose behavior-tree XML path for every goal.",
    )
    parser.add_argument("--cancel-on-timeout", action="store_true", default=True)
    parser.add_argument("--no-cancel-on-timeout", dest="cancel_on_timeout", action="store_false")
    parser.add_argument("--stop-on-failure", action="store_true", default=True)
    parser.add_argument("--continue-on-failure", dest="stop_on_failure", action="store_false")
    parser.add_argument("--output-dir", default=None)
    return parser.parse_args()


def validate_args(args):
    goal_sources = [bool(args.goal), bool(args.forward_distances), bool(args.route_preset)]
    if sum(goal_sources) != 1:
        raise SystemExit("Provide exactly one of --goal, --forward-distances, or --route-preset")
    if args.goal_timeout <= 0.0:
        raise SystemExit("--goal-timeout must be > 0")
    if args.trace_rate <= 0.0:
        raise SystemExit("--trace-rate must be > 0")
    if args.server_timeout <= 0.0:
        raise SystemExit("--server-timeout must be > 0")
    if args.map_tf_timeout <= 0.0:
        raise SystemExit("--map-tf-timeout must be > 0")
    if args.tf_timeout <= 0.0:
        raise SystemExit("--tf-timeout must be > 0")


def main():
    args = parse_args()
    validate_args(args)
    output_dir = make_output_dir(args.output_dir)

    rclpy.init()
    node = Nav2WaypointSequenceProbe(args)
    try:
        try:
            summary = node.run()
        except RuntimeError as exc:
            summary = {"ok": False, "error": str(exc), "segments": []}
        summary = write_outputs(summary, output_dir)
        print(json.dumps(summary, indent=2, sort_keys=True))
        if not summary.get("ok"):
            raise SystemExit(2)
    finally:
        node.action_client.destroy()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
