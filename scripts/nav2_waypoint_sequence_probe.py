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

from nodes.navigation.se2_pose_control import Se2ControllerConfig, Se2PoseController


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
    # Keep the proven same-spot route unchanged as the regression baseline.
    "nav-only-full": _INSPECTION_PREFIX_LEGACY + _INSPECTION_TAIL + _FULL_TAIL,
    "nav-only-inspection": _INSPECTION_PREFIX_LEGACY + _INSPECTION_TAIL,
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
        self.precision_cmd_pub = self.create_publisher(
            Twist,
            args.se2_cmd_topic,
            cmd_qos,
        )

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
        goals = self.resolve_goals()
        needs_nav2 = any(goal.get("kind", "nav2") == "nav2" for goal in goals)
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
            "segments": self.segments,
        }

    def resolve_goals(self):
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
        if goal["source"] in ("absolute", "route_preset"):
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
        goal_msg = self.build_goal_from_pose(goal["x"], goal["y"], goal["yaw"])

        send_future = self.action_client.send_goal_async(goal_msg)
        rclpy.spin_until_future_complete(self, send_future, timeout_sec=self.args.server_timeout)
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            end_pose = self.lookup_map_pose()
            segment = {
                "index": index,
                "kind": "nav2",
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
            self._clear_segment_logging()
            return segment

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
            "kind": "nav2",
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
        "control_mode",
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
    goal_sources = [
        bool(args.goal),
        bool(args.se2_goal),
        bool(args.forward_distances),
        bool(args.route_preset),
    ]
    if sum(goal_sources) != 1:
        raise SystemExit(
            "Provide exactly one of --goal, --se2-goal, --forward-distances, "
            "or --route-preset"
        )
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
    if args.route_preset in (
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
