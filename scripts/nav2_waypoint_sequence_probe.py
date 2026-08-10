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
import threading
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
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from std_msgs.msg import String
from tf2_ros import Buffer, TransformException, TransformListener

from nodes.navigation.se2_pose_control import (
    Se2ControllerConfig,
    Se2PoseController,
    YawOnlyController,
    YawOnlyControllerConfig,
)
from nodes.navigation.waypoint_calibration import (
    WaypointCalibrationError,
    describe_waypoint_route,
    load_waypoint_document,
    resolve_waypoint_route,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]

STATUS_NAMES = {
    GoalStatus.STATUS_UNKNOWN: "UNKNOWN",
    GoalStatus.STATUS_ACCEPTED: "ACCEPTED",
    GoalStatus.STATUS_EXECUTING: "EXECUTING",
    GoalStatus.STATUS_CANCELING: "CANCELING",
    GoalStatus.STATUS_SUCCEEDED: "SUCCEEDED",
    GoalStatus.STATUS_CANCELED: "CANCELED",
    GoalStatus.STATUS_ABORTED: "ABORTED",
}

NO_RECOVERY_REPLANNING_BT = (
    "/opt/ros/foxy/share/nav2_bt_navigator/behavior_trees/"
    "navigate_w_replanning_time.xml"
)
TERMINAL_NO_REPLANNING_BT = str(
    PROJECT_ROOT
    / "configs"
    / "navigation"
    / "navigate_terminal_no_replanning.xml"
)


_INSPECTION_PREFIX_LEGACY = [
    ("obstacle_cross_target", 1.05, 0.75, math.pi),
    ("pos1_middle", 1.50, 3.25, math.pi / 2.0),
    ("pos1_middle_turned", 1.50, 3.25, -math.pi / 2.0),
]

_INSPECTION_PREFIX_TAKEOVER = [
    ("obstacle_cross_target", 1.05, 0.75, math.pi),
    {
        "kind": "nav2_yaw_takeover",
        "label": "pos1_middle_turned",
        "approach_label": "pos1_middle",
        "approach_x": 1.50,
        "approach_y": 3.25,
        "approach_yaw": math.pi / 2.0,
        "takeover_radius": 0.22,
        "target_yaw": -math.pi / 2.0,
        "direction": "clockwise",
        "anchor_bounds": [1.25, 1.75, 3.03, 3.47],
        "control_bounds": [1.10, 1.90, 3.00, 3.50],
    },
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

_INSPECTION_PREFIX_SE2 = [
    ("obstacle_cross_target", 1.05, 0.75, math.pi),
    ("pos1_left_clear", 0.60, 2.90, math.pi / 2.0),
    ("pos1_middle", 1.50, 3.25, math.pi / 2.0),
    {
        "kind": "se2_pose",
        "label": "pos1_middle_turned",
        "target_x": 1.50,
        "target_y": 3.25,
        "target_yaw": -math.pi / 2.0,
        "direction": "clockwise",
        # The controller refuses to start outside this known-clear corridor.
        "anchor_bounds": [1.25, 1.75, 3.05, 3.36],
        # Keeps the 0.70 x 0.50m footprint inside the 2.5m..4.0m corridor.
        "control_bounds": [1.10, 1.90, 3.00, 3.50],
    },
]

# Same-stack recovery after Nav2's approach goal drifts left while trying to
# satisfy terminal yaw.  The y bounds keep the padded footprint inside the
# 1.5m open band between the two inspection cabinets at every orientation.
_INSPECTION_SE2_CORRIDOR_RECOVERY = [
    {
        "kind": "se2_pose",
        "label": "pos1_middle_turned_corridor_recovery",
        "target_x": 1.50,
        "target_y": 3.25,
        "target_yaw": -math.pi / 2.0,
        "direction": "clockwise",
        "anchor_bounds": [0.95, 1.30, 3.10, 3.35],
        "control_bounds": [0.90, 1.90, 3.10, 3.40],
    },
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
    # Production routes transfer the final approach to strict yaw-only control.
    "nav-only-full": _INSPECTION_PREFIX_TAKEOVER + _INSPECTION_TAIL + _FULL_TAIL,
    "nav-only-inspection": _INSPECTION_PREFIX_TAKEOVER + _INSPECTION_TAIL,
    "nav-only-turn-validation": _INSPECTION_PREFIX_TAKEOVER,
    # Preserve the old same-XY DWB turn only for explicit regression comparison.
    "nav-only-full-dwb-baseline": _INSPECTION_PREFIX_LEGACY + _INSPECTION_TAIL + _FULL_TAIL,
    "nav-only-inspection-dwb-baseline": _INSPECTION_PREFIX_LEGACY + _INSPECTION_TAIL,
    # Opt-in staged-turn routes avoid the same-XY 180 deg RotateToGoal.
    "nav-only-full-staged": _INSPECTION_PREFIX_STAGED + _INSPECTION_TAIL + _FULL_TAIL,
    "nav-only-inspection-staged": _INSPECTION_PREFIX_STAGED + _INSPECTION_TAIL,
    # Use cuVSLAM feedback to refine XY and yaw together through the U-turn.
    "nav-only-full-se2": _INSPECTION_PREFIX_SE2 + _INSPECTION_TAIL + _FULL_TAIL,
    "nav-only-inspection-se2": _INSPECTION_PREFIX_SE2 + _INSPECTION_TAIL,
    # Resume after the three proven Nav2 approach segments without driving back
    # to the start when an SE(2) safety gate stops a live run.
    "nav-only-full-se2-resume": _INSPECTION_PREFIX_SE2[3:] + _INSPECTION_TAIL + _FULL_TAIL,
    "nav-only-inspection-se2-resume": _INSPECTION_PREFIX_SE2[3:] + _INSPECTION_TAIL,
    "nav-only-full-se2-recover": _INSPECTION_SE2_CORRIDOR_RECOVERY + _INSPECTION_TAIL + _FULL_TAIL,
    "nav-only-inspection-se2-recover": _INSPECTION_SE2_CORRIDOR_RECOVERY + _INSPECTION_TAIL,
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


def describe_route_preset(name):
    steps = []
    for index, step in enumerate(ROUTE_PRESETS[name], start=1):
        if isinstance(step, dict):
            description = dict(step)
            description["index"] = index
            steps.append(description)
            continue
        label, x, y, yaw = step
        steps.append(
            {
                "index": index,
                "kind": "nav2",
                "label": label,
                "x": x,
                "y": y,
                "yaw": yaw,
            }
        )
    return {"route_preset": name, "steps": steps}


class Nav2WaypointSequenceProbe(Node):
    def __init__(self, args):
        super().__init__("nav2_waypoint_sequence_probe")
        self.args = args
        self.action_client = ActionClient(self, NavigateToPose, "navigate_to_pose")
        # TF and odometry have dedicated executors so high-rate callbacks cannot
        # starve the proximity or yaw-only safety checks on the main node.
        self.tf_node = rclpy.create_node("nav2_waypoint_sequence_tf_listener")
        self.odom_node = rclpy.create_node("nav2_waypoint_sequence_odom_listener")
        self.tf_buffer = Buffer()
        self.tf_listener = None
        self.odom_executor = SingleThreadedExecutor()
        self.odom_thread = None
        self.latest_odom = None
        self.latest_output_cmd = None
        self.arbiter_mode = None
        self.arbiter_mode_time = float("-inf")
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
        self.odom_node.create_subscription(
            Odometry, args.odom_topic, self._odom_callback, odom_qos
        )
        self.odom_executor.add_node(self.odom_node)
        self.odom_thread = threading.Thread(
            target=self.odom_executor.spin,
            name="nav2-waypoint-odom-listener",
            daemon=True,
        )
        self.odom_thread.start()
        self.tf_listener = TransformListener(
            self.tf_buffer,
            self.tf_node,
            spin_thread=True,
        )
        self.create_subscription(
            Twist, args.cmd_vel_topic, self._cmd_callback, cmd_qos
        )
        self.create_subscription(
            String,
            args.arbiter_status_topic,
            self._arbiter_mode_callback,
            10,
        )
        self.precision_cmd_pub = self.create_publisher(
            Twist,
            args.se2_cmd_topic,
            cmd_qos,
        )

    def shutdown_background_listeners(self):
        listener = self.tf_listener
        if listener is not None:
            executor = getattr(listener, "executor", None)
            if executor is not None:
                executor.shutdown()
            thread = getattr(listener, "dedicated_listener_thread", None)
            if thread is not None and thread.is_alive():
                thread.join(timeout=2.0)
            self.tf_listener = None
            del listener

        if self.tf_node is not None:
            self.tf_node.destroy_node()
            self.tf_node = None

        odom_executor = self.odom_executor
        odom_node = self.odom_node
        if odom_executor is not None:
            odom_executor.shutdown()
        if self.odom_thread is not None and self.odom_thread.is_alive():
            self.odom_thread.join(timeout=2.0)
        self.odom_thread = None
        if odom_executor is not None and odom_node is not None:
            odom_executor.remove_node(odom_node)
        self.odom_executor = None
        if odom_node is not None:
            odom_node.destroy_node()
            self.odom_node = None

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
        self.latest_output_cmd = {
            "monotonic_time": time.monotonic(),
            "linear_x": linear_x,
            "linear_y": linear_y,
            "angular_z": angular_z,
        }
        self.segment_cmd["cmd_count"] += 1
        if abs(linear_x) > 1e-5 or abs(linear_y) > 1e-5 or abs(angular_z) > 1e-5:
            self.segment_cmd["nonzero_count"] += 1
        if abs(linear_x) > 1e-5:
            self.segment_cmd["linear_x_nonzero_count"] += 1
        if abs(linear_y) > 1e-5:
            self.segment_cmd["linear_y_nonzero_count"] += 1
        if abs(angular_z) > 1e-5:
            self.segment_cmd["angular_z_nonzero_count"] += 1
        self.segment_cmd["max_linear_x"] = max(
            self.segment_cmd["max_linear_x"], abs(linear_x)
        )
        self.segment_cmd["max_abs_linear_y"] = max(
            self.segment_cmd["max_abs_linear_y"], abs(linear_y)
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

    def _arbiter_mode_callback(self, msg):
        self.arbiter_mode = str(msg.data)
        self.arbiter_mode_time = time.monotonic()

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
        stamp_sec = int(transform.header.stamp.sec)
        stamp_nanosec = int(transform.header.stamp.nanosec)
        stamp_float = stamp_sec + stamp_nanosec * 1e-9
        now_ros = self.get_clock().now().nanoseconds * 1e-9
        return {
            "ok": True,
            "source": "tf",
            "host_time_unix": time.time(),
            "tf_stamp_sec": stamp_sec,
            "tf_stamp_nanosec": stamp_nanosec,
            "tf_age_sec": max(0.0, now_ros - stamp_float) if stamp_float > 0.0 else None,
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

    def build_goal_from_pose(self, x, y, yaw, behavior_tree=None):
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
        goal_msg.behavior_tree = (
            self.args.behavior_tree if behavior_tree is None else behavior_tree
        )
        return goal_msg

    def run(self):
        goals = self.resolve_goals()
        needs_nav2 = any(
            goal.get("kind", "nav2") in ("nav2", "nav2_yaw_takeover")
            for goal in goals
        )
        if needs_nav2 and not self.action_client.wait_for_server(
            timeout_sec=self.args.server_timeout
        ):
            return {
                "ok": False,
                "error": "navigate_to_pose server unavailable",
                "segments": [],
            }

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
            "terminal_behavior_tree": (
                self.args.terminal_behavior_tree
                if self.args.terminal_replan_stop
                else None
            ),
            "segments": self.segments,
        }

    def resolve_goals(self):
        if self.args.waypoint_route:
            return resolve_waypoint_route(
                self.args.waypoint_document,
                self.args.waypoint_route,
                expected_frame=self.args.frame_id,
            )

        if self.args.route_preset:
            goals = []
            for step in ROUTE_PRESETS[self.args.route_preset]:
                if isinstance(step, dict):
                    goal = dict(step)
                    goal["source"] = "route_preset"
                    goal["preset"] = self.args.route_preset
                    goals.append(goal)
                    continue
                label, x, y, yaw = step
                goals.append(
                    {
                        "kind": "nav2",
                        "x": x,
                        "y": y,
                        "yaw": yaw,
                        "source": "route_preset",
                        "preset": self.args.route_preset,
                        "label": label,
                    }
                )
            return goals

        if self.args.goal:
            return [
                {
                    "kind": "nav2",
                    "x": values[0],
                    "y": values[1],
                    "yaw": values[2],
                    "source": "absolute",
                }
                for values in self.args.goal
            ]

        if self.args.se2_goal:
            return [
                {
                    "kind": "se2_pose",
                    "target_x": values[0],
                    "target_y": values[1],
                    "target_yaw": values[2],
                    "direction": self.args.se2_direction,
                    "source": "se2_absolute",
                    "label": "se2_goal_%d" % index,
                }
                for index, values in enumerate(self.args.se2_goal, start=1)
            ]

        return [
            {"kind": "nav2", "source": "forward_distance", "distance": distance}
            for distance in self.args.forward_distances
        ]

    def resolve_segment_goal(self, goal):
        if goal["source"] in ("absolute", "route_preset", "waypoint_file"):
            return goal

        pose = self.wait_for_map_pose()
        if not pose.get("ok"):
            raise RuntimeError("cannot resolve current map pose: %s" % pose.get("error"))
        yaw = self.args.target_yaw if self.args.target_yaw is not None else pose["yaw"]
        distance = goal["distance"]
        return {
            "kind": "nav2",
            "x": pose["x"] + distance * math.cos(yaw),
            "y": pose["y"] + distance * math.sin(yaw),
            "yaw": yaw,
            "source": "forward_distance",
            "distance": distance,
            "start_pose_used": pose,
        }

    def run_segment(self, index, goal):
        if goal.get("kind", "nav2") == "nav2_yaw_takeover":
            return self.run_nav2_yaw_takeover_segment(index, goal)
        if goal.get("kind", "nav2") in ("se2_hold_turn", "se2_pose"):
            return self.run_se2_hold_turn_segment(index, goal)
        return self.run_nav2_segment(index, goal)

    def _begin_segment_logging(self):
        self.segment_cmd = {
            "cmd_count": 0,
            "nonzero_count": 0,
            "linear_x_nonzero_count": 0,
            "linear_y_nonzero_count": 0,
            "angular_z_nonzero_count": 0,
            "max_linear_x": 0.0,
            "max_abs_linear_y": 0.0,
            "max_abs_angular_z": 0.0,
        }
        self.segment_cmd_samples = []
        self.segment_start_time = time.time()
        self.segment_trace = []

    def _clear_segment_logging(self):
        self.segment_cmd = None
        self.segment_cmd_samples = None
        self.segment_start_time = None
        self.segment_trace = None

    def _publish_precision_command(self, vx, vy, wz):
        msg = Twist()
        msg.linear.x = float(vx)
        msg.linear.y = float(vy) * self.args.se2_vy_sign
        msg.angular.z = float(wz)
        self.precision_cmd_pub.publish(msg)

    def _spin_until_monotonic(self, deadline):
        while rclpy.ok():
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                return
            rclpy.spin_once(self, timeout_sec=min(0.02, remaining))

    def _hold_precision_stop(self, seconds):
        period = 1.0 / self.args.se2_rate
        deadline = time.monotonic() + max(0.0, seconds)
        next_tick = time.monotonic()
        while rclpy.ok() and time.monotonic() < deadline:
            self._publish_precision_command(0.0, 0.0, 0.0)
            next_tick = max(next_tick + period, time.monotonic())
            self._spin_until_monotonic(min(next_tick, deadline))

    @staticmethod
    def _output_command_is_zero(command):
        return command is not None and all(
            abs(command[name]) <= 1e-5
            for name in ("linear_x", "linear_y", "angular_z")
        )

    def _wait_future(self, future, timeout):
        deadline = time.monotonic() + max(0.0, timeout)
        while rclpy.ok() and not future.done() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.02)
        return future.done()

    def _send_nav2_goal(self, goal, behavior_tree):
        goal_msg = self.build_goal_from_pose(
            goal["x"],
            goal["y"],
            goal["yaw"],
            behavior_tree=behavior_tree,
        )
        send_future = self.action_client.send_goal_async(goal_msg)
        if not self._wait_future(send_future, self.args.server_timeout):
            return None, None, "goal send timed out"
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            return goal_handle, None, "goal rejected"
        return goal_handle, goal_handle.get_result_async(), None

    def _cancel_nav2_goal(self, goal_handle, result_future, timeout):
        if result_future.done():
            return int(result_future.result().status), None

        cancel_future = goal_handle.cancel_goal_async()
        if not self._wait_future(cancel_future, timeout):
            return None, "Nav2 cancel request timed out"

        response = cancel_future.result()
        return_code = getattr(response, "return_code", None)
        cancel_accepted = return_code == 0 or bool(
            getattr(response, "goals_canceling", [])
        )
        if not self._wait_future(result_future, timeout):
            return None, "Nav2 goal stayed active after cancel request"

        status = int(result_future.result().status)
        if not cancel_accepted and status not in (
            GoalStatus.STATUS_SUCCEEDED,
            GoalStatus.STATUS_CANCELED,
            GoalStatus.STATUS_ABORTED,
        ):
            return status, "Nav2 cancel request was rejected"
        return status, None

    def _wait_for_output_zero(self):
        started = time.monotonic()
        deadline = started + self.args.terminal_zero_timeout
        zero_started = None
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.02)
            now = time.monotonic()
            command = self.latest_output_cmd
            command_is_current = (
                command is not None and command["monotonic_time"] >= started
            )
            if command_is_current and self._output_command_is_zero(command):
                if zero_started is None:
                    zero_started = now
                elif now - zero_started >= self.args.terminal_zero_confirm_time:
                    return None
            else:
                zero_started = None
        return "final cmd_vel did not remain zero before terminal goal"

    def _capture_nav2_trace_sample(self, segment_index, goal, phase):
        pose = self.lookup_map_pose(allow_fallback=False)
        trace_sample = dict(pose)
        trace_sample.update(
            {
                "segment_index": segment_index,
                "segment_kind": "nav2",
                "handover_phase": phase,
                "control_mode": phase,
                "target_x": goal["x"],
                "target_y": goal["y"],
                "target_yaw": goal["yaw"],
            }
        )
        if pose.get("ok"):
            trace_sample["position_error"] = math.hypot(
                pose["x"] - goal["x"],
                pose["y"] - goal["y"],
            )
            trace_sample["error_yaw"] = normalize_angle(goal["yaw"] - pose["yaw"])
        self.segment_trace.append(trace_sample)
        return trace_sample

    def _acquire_precision_zero_lease(self):
        if self.precision_cmd_pub.get_subscription_count() < 1:
            return "no subscriber on %s; cmd_vel arbiter is not active" % (
                self.args.se2_cmd_topic,
            )

        started = time.monotonic()
        deadline = started + self.args.se2_takeover_stop
        zero_started = None
        period = 1.0 / self.args.se2_rate
        next_tick = started
        while rclpy.ok() and time.monotonic() < deadline:
            self._publish_precision_command(0.0, 0.0, 0.0)
            now = time.monotonic()
            command = self.latest_output_cmd
            command_is_current = (
                command is not None and command["monotonic_time"] >= started
            )
            if (
                self.arbiter_mode == "precision"
                and self.arbiter_mode_time >= started
                and command_is_current
                and self._output_command_is_zero(command)
            ):
                if zero_started is None:
                    zero_started = now
                elif now - zero_started >= self.args.takeover_zero_confirm_time:
                    return None
            else:
                zero_started = None
            next_tick = max(next_tick + period, time.monotonic())
            self._spin_until_monotonic(min(next_tick, deadline))

        if self.arbiter_mode != "precision":
            return "precision lease was not confirmed on %s" % (
                self.args.arbiter_status_topic,
            )
        return "final cmd_vel did not remain zero during precision takeover"

    def _wait_future_with_precision_stop(self, future, timeout):
        deadline = time.monotonic() + max(0.0, timeout)
        period = 1.0 / self.args.se2_rate
        next_tick = time.monotonic()
        while rclpy.ok() and not future.done() and time.monotonic() < deadline:
            self._publish_precision_command(0.0, 0.0, 0.0)
            next_tick = max(next_tick + period, time.monotonic())
            self._spin_until_monotonic(min(next_tick, deadline))
        return future.done()

    def _cancel_nav2_under_precision_lease(self, goal_handle, result_future):
        if result_future.done():
            result = result_future.result()
            return True, False, int(result.status), None

        cancel_future = goal_handle.cancel_goal_async()
        if not self._wait_future_with_precision_stop(
            cancel_future, self.args.takeover_cancel_timeout
        ):
            return False, True, None, "Nav2 cancel request timed out"

        response = cancel_future.result()
        return_code = getattr(response, "return_code", None)
        cancel_accepted = return_code == 0 or bool(
            getattr(response, "goals_canceling", [])
        )
        if not self._wait_future_with_precision_stop(
            result_future, self.args.takeover_cancel_timeout
        ):
            return False, True, None, "Nav2 goal stayed active after cancel request"

        result = result_future.result()
        status = int(result.status)
        if not cancel_accepted and status not in (
            GoalStatus.STATUS_SUCCEEDED,
            GoalStatus.STATUS_CANCELED,
            GoalStatus.STATUS_ABORTED,
        ):
            return False, True, status, "Nav2 cancel request was rejected"
        return True, True, status, None

    def _wait_for_precision_release(self):
        started = time.monotonic()
        deadline = started + self.args.takeover_release_timeout
        zero_started = None
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.02)
            now = time.monotonic()
            command = self.latest_output_cmd
            if (
                self.arbiter_mode == "idle"
                and self.arbiter_mode_time >= started
                and command is not None
                and command["monotonic_time"] >= started
                and self._output_command_is_zero(command)
            ):
                if zero_started is None:
                    zero_started = now
                elif now - zero_started >= self.args.takeover_zero_confirm_time:
                    return None
            else:
                zero_started = None
        return "precision lease did not return to confirmed idle/zero state"

    def _validate_se2_pose(self, pose, previous_pose=None, anchor_pose=None):
        if not pose.get("ok"):
            return "map TF unavailable: %s" % pose.get("error", "unknown error")
        values = (pose.get("x"), pose.get("y"), pose.get("yaw"))
        if not all(value is not None and math.isfinite(value) for value in values):
            return "map TF contains NaN/Inf"
        tf_age = pose.get("tf_age_sec")
        if tf_age is None:
            return "map TF has no usable timestamp"
        if tf_age > self.args.se2_tf_max_age:
            return "map TF is stale (age %.3fs)" % tf_age
        if previous_pose is not None:
            jump_xy = math.hypot(
                pose["x"] - previous_pose["x"],
                pose["y"] - previous_pose["y"],
            )
            jump_yaw = abs(normalize_angle(pose["yaw"] - previous_pose["yaw"]))
            if jump_xy > self.args.se2_max_tf_jump_xy:
                return "map TF position jump %.3fm" % jump_xy
            if jump_yaw > self.args.se2_max_tf_jump_yaw:
                return "map TF yaw jump %.3frad" % jump_yaw
        if anchor_pose is not None:
            anchor_error = math.hypot(
                pose["x"] - anchor_pose["x"],
                pose["y"] - anchor_pose["y"],
            )
            if anchor_error > self.args.se2_max_anchor_error:
                return "left SE2 safety radius (%.3fm)" % anchor_error
        return None

    def _wait_for_stable_se2_anchor(self):
        period = 1.0 / self.args.se2_rate
        deadline = time.monotonic() + self.args.se2_tf_settle_timeout
        previous_pose = None
        last_stamp = None
        stable_count = 0
        last_error = "no fresh TF samples"
        next_tick = time.monotonic()
        while rclpy.ok() and time.monotonic() < deadline:
            self._publish_precision_command(0.0, 0.0, 0.0)
            pose = self.lookup_map_pose(allow_fallback=False)
            error = self._validate_se2_pose(pose, previous_pose=previous_pose)
            stamp = (pose.get("tf_stamp_sec"), pose.get("tf_stamp_nanosec"))
            if error is not None:
                stable_count = 0
                previous_pose = None
                last_error = error
            elif stamp != last_stamp:
                stable_count += 1
                previous_pose = pose
                last_stamp = stamp
                if stable_count >= self.args.se2_stable_tf_samples:
                    return pose, None
            next_tick = max(next_tick + period, time.monotonic())
            self._spin_until_monotonic(min(next_tick, deadline))
        return None, "stable map TF unavailable: %s" % last_error

    def run_nav2_yaw_takeover_segment(self, index, goal):
        """Approach a pose with Nav2, then atomically hand over to yaw-only."""
        self._begin_segment_logging()
        approach_x = float(goal["approach_x"])
        approach_y = float(goal["approach_y"])
        approach_yaw = float(goal["approach_yaw"])
        takeover_radius = float(
            goal.get("takeover_radius", self.args.takeover_radius)
        )
        start_pose = self.wait_for_map_pose()
        goal_handle = None
        result_future = None
        takeover_pose = None
        anchor_pose = None
        action_status = None
        canceled = False
        cancel_requested = False
        precision_attempted = False
        precision_acquired = False
        release_confirmed = False
        succeeded = False
        timed_out = False
        error = None
        takeover_distance = None
        cancel_error = None
        settle_started = None
        last_pose = None
        last_stamp = None
        last_stamp_change_time = None
        stale_started = None
        last_progress_time = None
        best_yaw_error = None
        linear_x_baseline = None
        linear_y_baseline = None

        try:
            if not start_pose.get("ok"):
                error = "cannot capture start map pose: %s" % start_pose.get("error")
            elif not self.action_client.wait_for_server(
                timeout_sec=self.args.server_timeout
            ):
                error = "navigate_to_pose server unavailable"
            else:
                goal_msg = self.build_goal_from_pose(
                    approach_x, approach_y, approach_yaw
                )
                send_future = self.action_client.send_goal_async(goal_msg)
                rclpy.spin_until_future_complete(
                    self, send_future, timeout_sec=self.args.server_timeout
                )
                goal_handle = send_future.result()
                if goal_handle is None or not goal_handle.accepted:
                    error = "approach goal rejected"
                else:
                    result_future = goal_handle.get_result_async()
                    deadline = time.monotonic() + self.args.goal_timeout
                    next_trace = time.monotonic()
                    while rclpy.ok() and not result_future.done():
                        rclpy.spin_once(self, timeout_sec=0.05)
                        now = time.monotonic()
                        pose = self.lookup_map_pose(allow_fallback=False)
                        if now >= next_trace:
                            trace_sample = dict(pose)
                            trace_sample.update(
                                {
                                    "segment_index": index,
                                    "segment_kind": "nav2_yaw_takeover",
                                    "handover_phase": "nav2_approach",
                                    "control_mode": "nav2_approach",
                                    "target_x": approach_x,
                                    "target_y": approach_y,
                                    "target_yaw": approach_yaw,
                                    "arbiter_mode": self.arbiter_mode,
                                }
                            )
                            if pose.get("ok"):
                                trace_sample["approach_distance"] = math.hypot(
                                    pose["x"] - approach_x,
                                    pose["y"] - approach_y,
                                )
                                trace_sample["position_error"] = trace_sample[
                                    "approach_distance"
                                ]
                            self.segment_trace.append(trace_sample)
                            next_trace = now + (1.0 / self.args.trace_rate)

                        if pose.get("ok") and pose.get("tf_age_sec") is not None:
                            if pose["tf_age_sec"] <= self.args.se2_tf_max_age:
                                takeover_distance = math.hypot(
                                    pose["x"] - approach_x,
                                    pose["y"] - approach_y,
                                )
                                if takeover_distance <= takeover_radius:
                                    takeover_pose = pose
                                    break
                        if now >= deadline:
                            timed_out = True
                            error = "Nav2 approach timeout before proximity takeover"
                            break

                    if takeover_pose is None and result_future.done():
                        result = result_future.result()
                        action_status = int(result.status)
                        final_pose = self.lookup_map_pose(allow_fallback=False)
                        if (
                            final_pose.get("ok")
                            and final_pose.get("tf_age_sec") is not None
                            and final_pose["tf_age_sec"] <= self.args.se2_tf_max_age
                        ):
                            takeover_distance = math.hypot(
                                final_pose["x"] - approach_x,
                                final_pose["y"] - approach_y,
                            )
                            if takeover_distance <= takeover_radius:
                                takeover_pose = final_pose
                        if takeover_pose is None and error is None:
                            error = (
                                "Nav2 approach finished before entering takeover radius "
                                "(status=%s, distance=%s)"
                                % (
                                    STATUS_NAMES.get(action_status, action_status),
                                    "%.3f" % takeover_distance
                                    if takeover_distance is not None
                                    else "unknown",
                                )
                            )

                    if takeover_pose is None and not result_future.done():
                        cancel_requested = True
                        cancel_future = goal_handle.cancel_goal_async()
                        rclpy.spin_until_future_complete(
                            self,
                            cancel_future,
                            timeout_sec=self.args.takeover_cancel_timeout,
                        )
                        if cancel_future.done():
                            canceled = True
                        else:
                            cancel_error = "approach timeout cancel request timed out"
                        self.spin_for(self.args.post_cancel_spin)

                    if takeover_pose is not None and error is None:
                        precision_attempted = True
                        error = self._acquire_precision_zero_lease()
                        precision_acquired = error is None
                        cancel_requested = True
                        (
                            terminal_confirmed,
                            _cancel_attempted,
                            action_status,
                            cancel_error,
                        ) = self._cancel_nav2_under_precision_lease(
                            goal_handle, result_future
                        )
                        canceled = action_status == GoalStatus.STATUS_CANCELED
                        if not terminal_confirmed and cancel_error is not None:
                            error = cancel_error if error is None else "%s; %s" % (
                                error,
                                cancel_error,
                            )

                    if precision_acquired and error is None:
                        anchor_pose, error = self._wait_for_stable_se2_anchor()
                        if anchor_pose is not None:
                            anchor_trace = dict(anchor_pose)
                            anchor_trace.update(
                                {
                                    "segment_index": index,
                                    "segment_kind": "nav2_yaw_takeover",
                                    "handover_phase": "post_cancel_anchor",
                                    "control_mode": "precision_zero",
                                    "target_x": anchor_pose["x"],
                                    "target_y": anchor_pose["y"],
                                    "target_yaw": goal["target_yaw"],
                                    "position_error": 0.0,
                                    "command_vx": 0.0,
                                    "command_vy": 0.0,
                                    "command_wz": 0.0,
                                    "arbiter_mode": self.arbiter_mode,
                                }
                            )
                            self.segment_trace.append(anchor_trace)

                    if error is None and anchor_pose is not None:
                        bounds = goal.get("anchor_bounds")
                        if bounds is not None:
                            min_x, max_x, min_y, max_y = bounds
                            if not (
                                min_x <= anchor_pose["x"] <= max_x
                                and min_y <= anchor_pose["y"] <= max_y
                            ):
                                error = (
                                    "yaw-only anchor outside safe bounds: "
                                    "(%.3f, %.3f) not in [%.2f, %.2f]x[%.2f, %.2f]"
                                    % (
                                        anchor_pose["x"],
                                        anchor_pose["y"],
                                        min_x,
                                        max_x,
                                        min_y,
                                        max_y,
                                    )
                                )

                    if error is None and anchor_pose is not None:
                        controller = YawOnlyController(
                            YawOnlyControllerConfig(
                                ktheta=self.args.yaw_only_ktheta,
                                coarse_max_wz=self.args.yaw_only_max_wz,
                                fine_max_wz=self.args.yaw_only_fine_max_wz,
                                fine_yaw_error=self.args.yaw_only_fine_yaw_error,
                                yaw_tolerance=self.args.yaw_only_tolerance,
                                max_angular_accel=self.args.yaw_only_max_angular_accel,
                            )
                        )
                        controller.start(
                            start_yaw=anchor_pose["yaw"],
                            target_yaw=goal["target_yaw"],
                            direction=goal.get("direction", "shortest"),
                        )
                        control_started = time.monotonic()
                        last_control_time = control_started
                        last_progress_time = control_started
                        last_stamp_change_time = control_started
                        period = 1.0 / self.args.se2_rate
                        next_tick = control_started
                        linear_x_baseline = self.segment_cmd[
                            "linear_x_nonzero_count"
                        ]
                        linear_y_baseline = self.segment_cmd[
                            "linear_y_nonzero_count"
                        ]
                        while rclpy.ok():
                            cycle_started = time.monotonic()
                            if (
                                cycle_started - control_started
                                >= self.args.yaw_only_timeout
                            ):
                                timed_out = True
                                error = "yaw-only control timeout"
                                break
                            if (
                                self.segment_cmd["linear_x_nonzero_count"]
                                > linear_x_baseline
                                or self.segment_cmd["linear_y_nonzero_count"]
                                > linear_y_baseline
                            ):
                                error = (
                                    "nonzero linear velocity observed during "
                                    "yaw-only precision lease"
                                )
                                break

                            pose = self.lookup_map_pose(allow_fallback=False)
                            pose_error = self._validate_se2_pose(
                                pose,
                                previous_pose=last_pose,
                                anchor_pose=anchor_pose,
                            )
                            if pose_error is not None:
                                if (
                                    not pose.get("ok")
                                    or "stale" in pose_error
                                    or "timestamp" in pose_error
                                ):
                                    if stale_started is None:
                                        stale_started = cycle_started
                                    controller.hold()
                                    self._publish_precision_command(0.0, 0.0, 0.0)
                                    if (
                                        cycle_started - stale_started
                                        > self.args.yaw_only_tf_hold_timeout
                                    ):
                                        error = "yaw-only TF unavailable: %s" % pose_error
                                        break
                                    next_tick = max(
                                        next_tick + period, time.monotonic()
                                    )
                                    self._spin_until_monotonic(next_tick)
                                    continue
                                error = pose_error
                                break
                            stale_started = None

                            control_bounds = goal.get("control_bounds")
                            if control_bounds is not None:
                                min_x, max_x, min_y, max_y = control_bounds
                                if not (
                                    min_x <= pose["x"] <= max_x
                                    and min_y <= pose["y"] <= max_y
                                ):
                                    error = (
                                        "yaw-only pose left the prevalidated clear corridor"
                                    )
                                    break

                            stamp = (pose["tf_stamp_sec"], pose["tf_stamp_nanosec"])
                            if stamp != last_stamp:
                                last_stamp = stamp
                                last_stamp_change_time = cycle_started
                            elif (
                                cycle_started - last_stamp_change_time
                                > self.args.yaw_only_tf_hold_timeout
                            ):
                                error = "map TF timestamp stopped advancing"
                                break

                            dt = max(1e-3, cycle_started - last_control_time)
                            output = controller.compute(pose["yaw"], dt)
                            self._publish_precision_command(0.0, 0.0, output.wz)
                            trace_sample = dict(pose)
                            trace_sample.update(
                                {
                                    "segment_index": index,
                                    "segment_kind": "nav2_yaw_takeover",
                                    "handover_phase": "yaw_only",
                                    "control_mode": output.mode,
                                    "target_x": anchor_pose["x"],
                                    "target_y": anchor_pose["y"],
                                    "target_yaw": goal["target_yaw"],
                                    "error_yaw": output.error_yaw,
                                    "position_error": math.hypot(
                                        pose["x"] - anchor_pose["x"],
                                        pose["y"] - anchor_pose["y"],
                                    ),
                                    "command_vx": 0.0,
                                    "command_vy": 0.0,
                                    "command_wz": output.wz,
                                    "arbiter_mode": self.arbiter_mode,
                                }
                            )
                            self.segment_trace.append(trace_sample)

                            yaw_error = abs(output.error_yaw)
                            if (
                                best_yaw_error is None
                                or yaw_error
                                <= best_yaw_error - self.args.yaw_only_progress_delta
                            ):
                                best_yaw_error = yaw_error
                                last_progress_time = cycle_started
                            elif (
                                not output.reached
                                and cycle_started - last_progress_time
                                > self.args.yaw_only_progress_timeout
                            ):
                                error = "yaw-only controller made no measurable progress"
                                break

                            if output.reached:
                                if settle_started is None:
                                    settle_started = cycle_started
                                elif (
                                    cycle_started - settle_started
                                    >= self.args.se2_settle_time
                                ):
                                    succeeded = True
                                    break
                            else:
                                settle_started = None

                            last_pose = pose
                            last_control_time = cycle_started
                            next_tick = max(next_tick + period, time.monotonic())
                            self._spin_until_monotonic(next_tick)

        finally:
            if precision_attempted:
                self._hold_precision_stop(self.args.se2_release_stop)
                release_error = self._wait_for_precision_release()
                release_confirmed = release_error is None
                if error is None and release_error is not None:
                    error = release_error

        end_pose = self.lookup_map_pose()
        segment = {
            "index": index,
            "kind": "nav2_yaw_takeover",
            "accepted": goal_handle is not None and goal_handle.accepted,
            "succeeded": succeeded and error is None,
            "timed_out": timed_out,
            "canceled": canceled,
            "action_status": action_status,
            "action_status_name": (
                "TAKEOVER_SUCCEEDED" if succeeded and error is None else "TAKEOVER_ABORTED"
            ),
            "nav2_action_status_name": STATUS_NAMES.get(action_status, action_status),
            "error": error,
            "goal": {
                "approach_label": goal.get("approach_label"),
                "approach_x": approach_x,
                "approach_y": approach_y,
                "approach_yaw": approach_yaw,
                "takeover_radius": takeover_radius,
                "target_yaw": goal["target_yaw"],
                "direction": goal.get("direction", "shortest"),
            },
            "start_pose": start_pose,
            "end_pose": end_pose,
            "delta": self.pose_delta(start_pose, end_pose),
            "cmd_vel": self.segment_cmd,
            "cmd_vel_samples": self.segment_cmd_samples,
            "trace": self.segment_trace,
            "takeover": {
                "triggered": takeover_pose is not None,
                "trigger_pose": takeover_pose,
                "trigger_distance": takeover_distance,
                "precision_acquired": precision_acquired,
                "anchor_pose": anchor_pose,
                "turn_delta": self.pose_delta(anchor_pose, end_pose)
                if anchor_pose is not None
                else None,
                "cancel_requested": cancel_requested,
                "cancel_error": cancel_error,
                "release_confirmed": release_confirmed,
                "yaw_linear_x_nonzero_count": max(
                    0,
                    self.segment_cmd["linear_x_nonzero_count"]
                    - (
                        self.segment_cmd["linear_x_nonzero_count"]
                        if linear_x_baseline is None
                        else linear_x_baseline
                    ),
                ),
                "yaw_linear_y_nonzero_count": max(
                    0,
                    self.segment_cmd["linear_y_nonzero_count"]
                    - (
                        self.segment_cmd["linear_y_nonzero_count"]
                        if linear_y_baseline is None
                        else linear_y_baseline
                    ),
                ),
            },
        }
        self._clear_segment_logging()
        return segment

    def run_se2_hold_turn_segment(self, index, goal):
        self._begin_segment_logging()
        start_pose = self.wait_for_map_pose()
        error = None
        succeeded = False
        timed_out = False
        anchor_pose = None
        target = dict(goal)
        settle_started = None
        best_cost = None
        last_progress_time = None
        last_pose = None
        last_stamp = None
        last_stamp_change_time = None

        try:
            if not start_pose.get("ok"):
                error = "cannot capture start map pose: %s" % start_pose.get("error")
            else:
                self._hold_precision_stop(self.args.se2_takeover_stop)
                if self.precision_cmd_pub.get_subscription_count() < 1:
                    error = "no subscriber on %s; cmd_vel arbiter is not active" % (
                        self.args.se2_cmd_topic,
                    )
                else:
                    anchor_pose, error = self._wait_for_stable_se2_anchor()

            if error is None:
                bounds = goal.get("anchor_bounds")
                if bounds is not None:
                    min_x, max_x, min_y, max_y = bounds
                    if not (
                        min_x <= anchor_pose["x"] <= max_x
                        and min_y <= anchor_pose["y"] <= max_y
                    ):
                        error = (
                            "SE2 anchor outside safe bounds: "
                            "(%.3f, %.3f) not in [%.2f, %.2f]x[%.2f, %.2f]"
                            % (
                                anchor_pose["x"],
                                anchor_pose["y"],
                                min_x,
                                max_x,
                                min_y,
                                max_y,
                            )
                        )

            if error is None:
                target_x = float(goal.get("target_x", anchor_pose["x"]))
                target_y = float(goal.get("target_y", anchor_pose["y"]))
                target.update(
                    {
                        "x": target_x,
                        "y": target_y,
                        "yaw": float(goal["target_yaw"]),
                        "anchor_pose": anchor_pose,
                    }
                )
                config = Se2ControllerConfig(
                    kx=self.args.se2_kx,
                    ky=self.args.se2_ky,
                    ktheta=self.args.se2_ktheta,
                    coarse_max_vx=self.args.se2_max_vx,
                    coarse_max_vy=self.args.se2_max_vy,
                    coarse_max_wz=self.args.se2_max_wz,
                    fine_max_vx=self.args.se2_fine_max_vx,
                    fine_max_vy=self.args.se2_fine_max_vy,
                    fine_max_wz=self.args.se2_fine_max_wz,
                    fine_position_radius=self.args.se2_fine_position_radius,
                    fine_yaw_error=self.args.se2_fine_yaw_error,
                    position_tolerance=self.args.se2_position_tolerance,
                    yaw_tolerance=self.args.se2_yaw_tolerance,
                    max_linear_accel=self.args.se2_max_linear_accel,
                    max_angular_accel=self.args.se2_max_angular_accel,
                )
                controller = Se2PoseController(config)
                controller.start(
                    target_x=target_x,
                    target_y=target_y,
                    start_yaw=anchor_pose["yaw"],
                    target_yaw=goal["target_yaw"],
                    direction=goal.get("direction", "shortest"),
                )

                control_started = time.monotonic()
                last_control_time = control_started
                last_progress_time = control_started
                last_stamp_change_time = control_started
                period = 1.0 / self.args.se2_rate
                next_tick = control_started
                while rclpy.ok():
                    cycle_started = time.monotonic()
                    if cycle_started - control_started >= self.args.se2_timeout:
                        timed_out = True
                        error = "SE2 control timeout"
                        break

                    pose = self.lookup_map_pose(allow_fallback=False)
                    pose_error = self._validate_se2_pose(
                        pose,
                        previous_pose=last_pose,
                        anchor_pose=anchor_pose,
                    )
                    if pose_error is not None:
                        error = pose_error
                        break
                    control_bounds = goal.get("control_bounds")
                    if control_bounds is not None:
                        min_x, max_x, min_y, max_y = control_bounds
                        if not (
                            min_x <= pose["x"] <= max_x
                            and min_y <= pose["y"] <= max_y
                        ):
                            error = "SE2 pose left the prevalidated clear corridor"
                            break

                    stamp = (pose["tf_stamp_sec"], pose["tf_stamp_nanosec"])
                    if stamp != last_stamp:
                        last_stamp = stamp
                        last_stamp_change_time = cycle_started
                    elif cycle_started - last_stamp_change_time > self.args.se2_tf_freeze_timeout:
                        error = "map TF timestamp stopped advancing"
                        break

                    dt = max(1e-3, cycle_started - last_control_time)
                    output = controller.compute(pose["x"], pose["y"], pose["yaw"], dt)
                    command_vy = output.vy * self.args.se2_vy_sign
                    self._publish_precision_command(output.vx, output.vy, output.wz)
                    trace_sample = dict(pose)
                    trace_sample.update(
                        {
                            "segment_index": index,
                            "segment_kind": goal.get("kind", "se2_pose"),
                            "control_mode": output.mode,
                            "target_x": target_x,
                            "target_y": target_y,
                            "target_yaw": goal["target_yaw"],
                            "error_x_body": output.error_x_body,
                            "error_y_body": output.error_y_body,
                            "error_yaw": output.error_yaw,
                            "position_error": output.position_error,
                            "command_vx": output.vx,
                            "command_vy": command_vy,
                            "command_wz": output.wz,
                        }
                    )
                    self.segment_trace.append(trace_sample)

                    cost = output.position_error + 0.25 * abs(output.error_yaw)
                    if best_cost is None or cost <= best_cost - self.args.se2_progress_delta:
                        best_cost = cost
                        last_progress_time = cycle_started
                    elif (
                        not output.reached
                        and cycle_started - last_progress_time > self.args.se2_progress_timeout
                    ):
                        error = "SE2 controller made no measurable progress"
                        break

                    if output.reached:
                        if settle_started is None:
                            settle_started = cycle_started
                        elif cycle_started - settle_started >= self.args.se2_settle_time:
                            succeeded = True
                            break
                    else:
                        settle_started = None

                    last_pose = pose
                    last_control_time = cycle_started
                    next_tick = max(next_tick + period, time.monotonic())
                    self._spin_until_monotonic(next_tick)

                if not rclpy.ok() and not succeeded and error is None:
                    error = "ROS shutdown during SE2 control"
        finally:
            self._hold_precision_stop(self.args.se2_release_stop)

        end_pose = self.lookup_map_pose()
        segment = {
            "index": index,
            "kind": goal.get("kind", "se2_pose"),
            "accepted": anchor_pose is not None,
            "succeeded": succeeded,
            "timed_out": timed_out,
            "canceled": False,
            "action_status": None,
            "action_status_name": "SE2_SUCCEEDED" if succeeded else "SE2_ABORTED",
            "error": error,
            "goal": target,
            "start_pose": start_pose,
            "end_pose": end_pose,
            "delta": self.pose_delta(start_pose, end_pose),
            "cmd_vel": self.segment_cmd,
            "cmd_vel_samples": self.segment_cmd_samples,
            "trace": self.segment_trace,
        }
        self._clear_segment_logging()
        return segment

    def run_nav2_segment(self, index, goal):
        self._begin_segment_logging()
        goal = self.resolve_segment_goal(goal)
        start_pose = self.wait_for_map_pose()
        if not start_pose.get("ok"):
            raise RuntimeError("cannot capture start map pose: %s" % start_pose.get("error"))

        terminal_enabled = bool(
            self.args.terminal_replan_stop and self.args.terminal_behavior_tree
        )
        start_distance = math.hypot(
            start_pose["x"] - goal["x"],
            start_pose["y"] - goal["y"],
        )
        started_in_terminal_radius = bool(
            terminal_enabled
            and start_distance <= self.args.terminal_replan_stop_radius
        )
        terminal_started = started_in_terminal_radius
        current_phase = (
            "terminal_no_replanning"
            if terminal_started
            else "periodic_replanning"
        )
        current_behavior_tree = (
            self.args.terminal_behavior_tree
            if terminal_started
            else self.args.behavior_tree
        )
        goal_handle, result_future, error = self._send_nav2_goal(
            goal,
            current_behavior_tree,
        )
        if error is not None:
            end_pose = self.lookup_map_pose()
            segment = {
                "index": index,
                "kind": "nav2",
                "accepted": False,
                "succeeded": False,
                "error": error,
                "goal": goal,
                "start_pose": start_pose,
                "end_pose": end_pose,
                "cmd_vel": self.segment_cmd,
                "cmd_vel_samples": self.segment_cmd_samples,
                "trace": self.segment_trace,
                "terminal_handover": {
                    "enabled": terminal_enabled,
                    "started_in_terminal_radius": started_in_terminal_radius,
                    "triggered": False,
                    "stop_radius": self.args.terminal_replan_stop_radius,
                    "periodic_behavior_tree": self.args.behavior_tree or None,
                    "terminal_behavior_tree": (
                        self.args.terminal_behavior_tree if terminal_enabled else None
                    ),
                },
            }
            self._clear_segment_logging()
            return segment

        deadline = time.monotonic() + self.args.goal_timeout
        next_trace = time.monotonic()
        timed_out = False
        canceled = False
        handover_triggered = False
        handover_trigger_pose = None
        handover_trigger_distance = None
        handover_cancel_requested = False
        handover_zero_confirmed = False
        periodic_action_status = None
        terminal_accepted = terminal_started
        action_status = None

        while rclpy.ok():
            if result_future.done():
                action_status = int(result_future.result().status)
                break
            rclpy.spin_once(self, timeout_sec=0.05)
            now = time.monotonic()
            if now >= next_trace:
                trace_sample = self._capture_nav2_trace_sample(
                    index,
                    goal,
                    current_phase,
                )
                next_trace = now + (1.0 / self.args.trace_rate)
                tf_age = trace_sample.get("tf_age_sec")
                pose_is_fresh = (
                    trace_sample.get("ok")
                    and tf_age is not None
                    and tf_age <= self.args.terminal_tf_max_age
                )
                if (
                    terminal_enabled
                    and not terminal_started
                    and pose_is_fresh
                    and trace_sample["position_error"]
                    <= self.args.terminal_replan_stop_radius
                ):
                    handover_triggered = True
                    handover_trigger_pose = dict(trace_sample)
                    handover_trigger_distance = trace_sample["position_error"]
                    handover_cancel_requested = True
                    periodic_action_status, cancel_error = self._cancel_nav2_goal(
                        goal_handle,
                        result_future,
                        self.args.terminal_cancel_timeout,
                    )
                    if cancel_error is not None:
                        error = cancel_error
                        break
                    if periodic_action_status == GoalStatus.STATUS_SUCCEEDED:
                        action_status = periodic_action_status
                        break
                    if periodic_action_status != GoalStatus.STATUS_CANCELED:
                        error = "periodic Nav2 goal ended during terminal handover: %s" % (
                            STATUS_NAMES.get(
                                periodic_action_status,
                                periodic_action_status,
                            )
                        )
                        break

                    zero_error = self._wait_for_output_zero()
                    if zero_error is not None:
                        error = zero_error
                        break
                    handover_zero_confirmed = True

                    goal_handle, result_future, send_error = self._send_nav2_goal(
                        goal,
                        self.args.terminal_behavior_tree,
                    )
                    terminal_accepted = send_error is None
                    if send_error is not None:
                        error = send_error
                        break
                    terminal_started = True
                    current_phase = "terminal_no_replanning"
                    current_behavior_tree = self.args.terminal_behavior_tree
                    continue
            if now >= deadline:
                timed_out = True
                break

        should_cancel_active = (
            not result_future.done()
            and (
                error is not None
                or (timed_out and self.args.cancel_on_timeout)
            )
        )
        if should_cancel_active:
            action_status, cancel_error = self._cancel_nav2_goal(
                goal_handle,
                result_future,
                self.args.terminal_cancel_timeout,
            )
            canceled = action_status == GoalStatus.STATUS_CANCELED
            if cancel_error is not None:
                error = cancel_error if error is None else "%s; %s" % (
                    error,
                    cancel_error,
                )
            self.spin_for(self.args.post_cancel_spin)

        status_name = "TIMEOUT"
        if action_status is None and result_future.done():
            result = result_future.result()
            action_status = int(result.status)
        if action_status is not None:
            status_name = STATUS_NAMES.get(action_status, str(action_status))
        elif error is not None:
            status_name = "HANDOVER_FAILED"

        end_pose = self.lookup_map_pose()
        delta = self.pose_delta(start_pose, end_pose)
        segment = {
            "index": index,
            "kind": "nav2",
            "accepted": True,
            "succeeded": (
                error is None and action_status == GoalStatus.STATUS_SUCCEEDED
            ),
            "timed_out": timed_out,
            "canceled": canceled,
            "action_status": action_status,
            "action_status_name": status_name,
            "error": error,
            "goal": goal,
            "start_pose": start_pose,
            "end_pose": end_pose,
            "delta": delta,
            "cmd_vel": self.segment_cmd,
            "cmd_vel_samples": self.segment_cmd_samples,
            "trace": self.segment_trace,
            "terminal_handover": {
                "enabled": terminal_enabled,
                "started_in_terminal_radius": started_in_terminal_radius,
                "triggered": handover_triggered,
                "trigger_pose": handover_trigger_pose,
                "trigger_distance": handover_trigger_distance,
                "stop_radius": self.args.terminal_replan_stop_radius,
                "cancel_requested": handover_cancel_requested,
                "periodic_action_status": periodic_action_status,
                "periodic_action_status_name": (
                    STATUS_NAMES.get(periodic_action_status, periodic_action_status)
                    if periodic_action_status is not None
                    else None
                ),
                "zero_confirmed": handover_zero_confirmed,
                "terminal_started": terminal_started,
                "terminal_accepted": terminal_accepted,
                "periodic_behavior_tree": self.args.behavior_tree or None,
                "terminal_behavior_tree": (
                    self.args.terminal_behavior_tree if terminal_enabled else None
                ),
            },
        }
        self._clear_segment_logging()
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
        "tf_age_sec",
        "segment_kind",
        "handover_phase",
        "control_mode",
        "arbiter_mode",
        "approach_distance",
        "target_x",
        "target_y",
        "target_yaw",
        "error_x_body",
        "error_y_body",
        "error_yaw",
        "position_error",
        "command_vx",
        "command_vy",
        "command_wz",
        "tf_error",
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
        "--se2-goal",
        nargs=3,
        type=float,
        action="append",
        metavar=("X", "Y", "YAW"),
        help="Low-speed precision goal within the configured anchor safety radius.",
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
    parser.add_argument(
        "--waypoint-file",
        help="Field-calibrated waypoint YAML/JSON file.",
    )
    parser.add_argument(
        "--waypoint-route",
        help="Named route from --waypoint-file; exclusive with built-in goal sources.",
    )
    parser.add_argument(
        "--allow-preview-route",
        action="store_true",
        help=(
            "Explicitly allow the legacy-PGM preview file for a controlled trial; "
            "never use this in a calibrated competition run."
        ),
    )
    parser.add_argument(
        "--describe-route",
        action="store_true",
        help="Print the selected built-in or calibrated route and exit without initializing ROS.",
    )
    parser.add_argument("--target-yaw", type=float, default=None)
    parser.add_argument("--frame-id", default="map")
    parser.add_argument("--base-frame", default="base_link")
    parser.add_argument("--odom-topic", default="/odom")
    parser.add_argument("--cmd-vel-topic", default="/cmd_vel")
    parser.add_argument(
        "--arbiter-status-topic",
        default="/cmd_vel_arbiter/mode",
    )
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
    se2 = parser.add_argument_group("SE(2) precision-control options")
    se2.add_argument(
        "--se2-cmd-topic",
        default="/cmd_vel_precision",
        help="Precision input of cmd_vel_arbiter (its output remains /cmd_vel).",
    )
    se2.add_argument("--se2-rate", type=float, default=10.0)
    se2.add_argument(
        "--se2-direction",
        choices=("shortest", "clockwise", "counterclockwise"),
        default="shortest",
    )
    se2.add_argument("--se2-timeout", type=float, default=40.0)
    se2.add_argument("--se2-kx", type=float, default=0.8)
    se2.add_argument("--se2-ky", type=float, default=0.8)
    se2.add_argument("--se2-ktheta", type=float, default=0.8)
    se2.add_argument("--se2-max-vx", type=float, default=0.06)
    se2.add_argument("--se2-max-vy", type=float, default=0.04)
    se2.add_argument("--se2-max-wz", type=float, default=0.12)
    se2.add_argument("--se2-fine-max-vx", type=float, default=0.03)
    se2.add_argument("--se2-fine-max-vy", type=float, default=0.02)
    se2.add_argument("--se2-fine-max-wz", type=float, default=0.06)
    se2.add_argument("--se2-fine-position-radius", type=float, default=0.12)
    se2.add_argument("--se2-fine-yaw-error", type=float, default=0.35)
    se2.add_argument("--se2-position-tolerance", type=float, default=0.08)
    se2.add_argument("--se2-yaw-tolerance", type=float, default=0.12)
    se2.add_argument("--se2-max-linear-accel", type=float, default=0.15)
    se2.add_argument("--se2-max-angular-accel", type=float, default=0.30)
    se2.add_argument("--se2-takeover-stop", type=float, default=0.5)
    se2.add_argument("--se2-release-stop", type=float, default=0.6)
    se2.add_argument("--takeover-radius", type=float, default=0.22)
    se2.add_argument("--takeover-zero-confirm-time", type=float, default=0.20)
    se2.add_argument("--takeover-cancel-timeout", type=float, default=3.0)
    se2.add_argument("--takeover-release-timeout", type=float, default=1.5)
    se2.add_argument("--se2-settle-time", type=float, default=1.0)
    se2.add_argument("--se2-tf-max-age", type=float, default=0.20)
    se2.add_argument("--se2-tf-freeze-timeout", type=float, default=0.20)
    se2.add_argument("--se2-tf-settle-timeout", type=float, default=3.0)
    se2.add_argument("--se2-stable-tf-samples", type=int, default=5)
    se2.add_argument("--se2-max-tf-jump-xy", type=float, default=0.10)
    se2.add_argument("--se2-max-tf-jump-yaw", type=float, default=0.20)
    se2.add_argument("--se2-max-anchor-error", type=float, default=0.30)
    se2.add_argument("--se2-progress-timeout", type=float, default=4.0)
    se2.add_argument("--se2-progress-delta", type=float, default=0.02)
    se2.add_argument(
        "--se2-vy-sign",
        type=float,
        choices=(-1.0, 1.0),
        default=1.0,
        help="Set -1 only if the Lite3 lateral-axis smoke test proves ROS +Y is reversed.",
    )
    yaw_only = parser.add_argument_group("Yaw-only precision-control options")
    yaw_only.add_argument("--yaw-only-timeout", type=float, default=55.0)
    yaw_only.add_argument("--yaw-only-ktheta", type=float, default=0.8)
    yaw_only.add_argument("--yaw-only-max-wz", type=float, default=0.08)
    yaw_only.add_argument("--yaw-only-fine-max-wz", type=float, default=0.04)
    yaw_only.add_argument("--yaw-only-fine-yaw-error", type=float, default=0.35)
    yaw_only.add_argument("--yaw-only-tolerance", type=float, default=0.12)
    yaw_only.add_argument("--yaw-only-max-angular-accel", type=float, default=0.20)
    yaw_only.add_argument("--yaw-only-tf-hold-timeout", type=float, default=0.50)
    yaw_only.add_argument("--yaw-only-progress-timeout", type=float, default=6.0)
    yaw_only.add_argument("--yaw-only-progress-delta", type=float, default=0.02)
    parser.add_argument(
        "--behavior-tree",
        default="",
        help="Optional NavigateToPose behavior-tree XML path for every goal.",
    )
    parser.add_argument(
        "--terminal-behavior-tree",
        default=TERMINAL_NO_REPLANNING_BT,
        help=(
            "NavigateToPose behavior tree used after the terminal handover; "
            "the default computes one path and does not replan."
        ),
    )
    parser.add_argument(
        "--terminal-replan-stop-radius",
        type=float,
        default=0.35,
        help="Switch from periodic replanning to the terminal tree within this XY radius.",
    )
    parser.add_argument(
        "--no-terminal-replan-stop",
        dest="terminal_replan_stop",
        action="store_false",
        help="Disable the terminal no-replanning handover.",
    )
    parser.set_defaults(terminal_replan_stop=True)
    parser.add_argument("--terminal-cancel-timeout", type=float, default=3.0)
    parser.add_argument("--terminal-zero-timeout", type=float, default=2.0)
    parser.add_argument("--terminal-zero-confirm-time", type=float, default=0.20)
    parser.add_argument("--terminal-tf-max-age", type=float, default=0.20)
    parser.add_argument("--cancel-on-timeout", action="store_true", default=True)
    parser.add_argument("--no-cancel-on-timeout", dest="cancel_on_timeout", action="store_false")
    parser.add_argument("--stop-on-failure", action="store_true", default=True)
    parser.add_argument("--continue-on-failure", dest="stop_on_failure", action="store_false")
    parser.add_argument("--output-dir", default=None)
    return parser.parse_args()


def validate_args(args):
    args.waypoint_document = None
    goal_sources = [
        bool(args.goal),
        bool(args.se2_goal),
        bool(args.forward_distances),
        bool(args.route_preset),
        bool(args.waypoint_route),
    ]
    if sum(goal_sources) != 1:
        raise SystemExit(
            "Provide exactly one of --goal, --se2-goal, --forward-distances, "
            "--route-preset, or --waypoint-route"
        )
    if bool(args.waypoint_file) != bool(args.waypoint_route):
        raise SystemExit("--waypoint-file and --waypoint-route must be provided together")
    if args.allow_preview_route and not args.waypoint_route:
        raise SystemExit("--allow-preview-route requires --waypoint-file and --waypoint-route")
    if args.describe_route and not (args.route_preset or args.waypoint_route):
        raise SystemExit(
            "--describe-route requires --route-preset or --waypoint-route"
        )
    if args.waypoint_route:
        try:
            args.waypoint_document = load_waypoint_document(args.waypoint_file)
            if not str(args.waypoint_document.get("map_id", "")).strip():
                raise WaypointCalibrationError("map_id is empty")
            resolve_waypoint_route(
                args.waypoint_document,
                args.waypoint_route,
                expected_frame=args.frame_id,
            )
            calibration = args.waypoint_document.get("calibration", {})
            calibration_status = calibration.get("status")
            preview_source = calibration.get("coordinate_source")
            preview_allowed = (
                args.allow_preview_route
                and calibration_status == "preview"
                and preview_source == "legacy_pgm_route_presets"
            )
            if not args.describe_route and calibration_status != "complete" and not preview_allowed:
                if calibration_status == "preview":
                    raise WaypointCalibrationError(
                        "calibration status is preview; pass --allow-preview-route only "
                        "for the legacy-PGM controlled trial"
                    )
                raise WaypointCalibrationError(
                    "calibration status is %r; run the recorder and enter finish"
                    % calibration_status
                )
        except WaypointCalibrationError as exc:
            raise SystemExit("invalid waypoint route: %s" % exc)
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
    if args.terminal_replan_stop:
        if not 0.20 <= args.terminal_replan_stop_radius <= 1.0:
            raise SystemExit(
                "--terminal-replan-stop-radius must be between 0.20m and 1.0m"
            )
        terminal_values = {
            "--terminal-cancel-timeout": args.terminal_cancel_timeout,
            "--terminal-zero-timeout": args.terminal_zero_timeout,
            "--terminal-tf-max-age": args.terminal_tf_max_age,
        }
        for name, value in terminal_values.items():
            if not math.isfinite(value) or value <= 0.0:
                raise SystemExit("%s must be > 0" % name)
        if (
            not math.isfinite(args.terminal_zero_confirm_time)
            or args.terminal_zero_confirm_time < 0.0
            or args.terminal_zero_confirm_time > args.terminal_zero_timeout
        ):
            raise SystemExit(
                "--terminal-zero-confirm-time must be between 0 and "
                "--terminal-zero-timeout"
            )
        if not args.terminal_behavior_tree:
            raise SystemExit(
                "--terminal-behavior-tree is required unless "
                "--no-terminal-replan-stop is used"
            )
        if not Path(args.terminal_behavior_tree).is_file():
            raise SystemExit(
                "terminal behavior tree does not exist: %s"
                % args.terminal_behavior_tree
            )
        if args.behavior_tree and (
            Path(args.behavior_tree).resolve()
            == Path(args.terminal_behavior_tree).resolve()
        ):
            raise SystemExit(
                "periodic and terminal behavior trees must be different"
            )
    if args.waypoint_route or args.route_preset in (
        "nav-only-full",
        "nav-only-inspection",
        "nav-only-turn-validation",
        "nav-only-full-dwb-baseline",
        "nav-only-inspection-dwb-baseline",
        "nav-only-full-se2",
        "nav-only-inspection-se2",
        "nav-only-full-se2-resume",
        "nav-only-inspection-se2-resume",
        "nav-only-full-se2-recover",
        "nav-only-inspection-se2-recover",
    ):
        if not args.behavior_tree:
            # Lite3's turn-induced XY drift makes Nav2's in-place Spin recovery unsafe.
            args.behavior_tree = NO_RECOVERY_REPLANNING_BT
    positive_se2_values = {
        "--se2-rate": args.se2_rate,
        "--se2-timeout": args.se2_timeout,
        "--se2-position-tolerance": args.se2_position_tolerance,
        "--se2-yaw-tolerance": args.se2_yaw_tolerance,
        "--se2-settle-time": args.se2_settle_time,
        "--se2-tf-max-age": args.se2_tf_max_age,
        "--se2-tf-freeze-timeout": args.se2_tf_freeze_timeout,
        "--se2-tf-settle-timeout": args.se2_tf_settle_timeout,
        "--se2-max-anchor-error": args.se2_max_anchor_error,
        "--se2-progress-timeout": args.se2_progress_timeout,
        "--se2-progress-delta": args.se2_progress_delta,
        "--takeover-radius": args.takeover_radius,
        "--takeover-zero-confirm-time": args.takeover_zero_confirm_time,
        "--takeover-cancel-timeout": args.takeover_cancel_timeout,
        "--takeover-release-timeout": args.takeover_release_timeout,
        "--yaw-only-timeout": args.yaw_only_timeout,
        "--yaw-only-tolerance": args.yaw_only_tolerance,
        "--yaw-only-tf-hold-timeout": args.yaw_only_tf_hold_timeout,
        "--yaw-only-progress-timeout": args.yaw_only_progress_timeout,
        "--yaw-only-progress-delta": args.yaw_only_progress_delta,
    }
    for name, value in positive_se2_values.items():
        if not math.isfinite(value) or value <= 0.0:
            raise SystemExit("%s must be > 0" % name)
    if args.se2_stable_tf_samples < 2:
        raise SystemExit("--se2-stable-tf-samples must be >= 2")
    controller_values = (
        args.se2_kx,
        args.se2_ky,
        args.se2_ktheta,
        args.se2_max_vx,
        args.se2_max_vy,
        args.se2_max_wz,
        args.se2_fine_max_vx,
        args.se2_fine_max_vy,
        args.se2_fine_max_wz,
        args.se2_max_linear_accel,
        args.se2_max_angular_accel,
        args.se2_fine_position_radius,
        args.se2_fine_yaw_error,
        args.se2_max_tf_jump_xy,
        args.se2_max_tf_jump_yaw,
    )
    if not all(math.isfinite(value) and value > 0.0 for value in controller_values):
        raise SystemExit("SE(2) gains, limits, and acceleration limits must be > 0")
    if not 0.15 <= args.takeover_radius <= 0.35:
        raise SystemExit("--takeover-radius must be between 0.15m and 0.35m")
    yaw_values = (
        args.yaw_only_ktheta,
        args.yaw_only_max_wz,
        args.yaw_only_fine_max_wz,
        args.yaw_only_fine_yaw_error,
        args.yaw_only_max_angular_accel,
    )
    if not all(math.isfinite(value) and value > 0.0 for value in yaw_values):
        raise SystemExit("yaw-only gains, limits, and acceleration must be > 0")
    if not all(
        math.isfinite(value) and value >= 0.0
        for value in (args.se2_takeover_stop, args.se2_release_stop)
    ):
        raise SystemExit("SE(2) takeover/release stop durations must be >= 0")
    for values in (args.goal or []) + (args.se2_goal or []):
        if not all(math.isfinite(value) for value in values):
            raise SystemExit("goal coordinates and yaw must be finite")


def main():
    args = parse_args()
    validate_args(args)
    if args.describe_route:
        if args.waypoint_route:
            description = describe_waypoint_route(
                args.waypoint_document,
                args.waypoint_route,
                expected_frame=args.frame_id,
            )
            description["waypoint_file"] = str(
                Path(args.waypoint_file).expanduser().resolve()
            )
        else:
            description = describe_route_preset(args.route_preset)
        print(json.dumps(description, indent=2))
        return
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
        node.shutdown_background_listeners()
        node.action_client.destroy()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
