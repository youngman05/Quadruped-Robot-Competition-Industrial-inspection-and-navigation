#!/usr/bin/env python3
"""Send one Nav2 goal, capture /plan, and save path evidence.

Default behavior is intentionally light on CPU:
  - capture only the first non-empty Path message
  - do no file I/O inside subscription callbacks
  - cancel the goal after capture unless --keep-goal is set
"""

import argparse
import csv
import html
import json
import math
import time
from datetime import datetime
from pathlib import Path

import rclpy
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Path as PathMsg
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy


def yaw_to_quaternion(yaw):
    half = yaw * 0.5
    return {
        "x": 0.0,
        "y": 0.0,
        "z": math.sin(half),
        "w": math.cos(half),
    }


def quaternion_to_yaw(q):
    siny = 2.0 * (q.w * q.z + q.x * q.y)
    cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny, cosy)


def stamp_to_dict(stamp):
    return {"sec": int(stamp.sec), "nanosec": int(stamp.nanosec)}


def pose_to_xyyaw(pose_stamped):
    pose = pose_stamped.pose
    return {
        "x": float(pose.position.x),
        "y": float(pose.position.y),
        "z": float(pose.position.z),
        "yaw": float(quaternion_to_yaw(pose.orientation)),
    }


def path_length_xy(poses):
    total = 0.0
    for prev, curr in zip(poses, poses[1:]):
        p0 = prev.pose.position
        p1 = curr.pose.position
        total += math.hypot(float(p1.x - p0.x), float(p1.y - p0.y))
    return total


def make_output_dir(value):
    if value:
        path = Path(value).expanduser()
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path.home() / "competition_logs" / "nav2_plan_probe" / stamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def make_plan_qos(name):
    reliability = (
        ReliabilityPolicy.RELIABLE
        if name == "reliable"
        else ReliabilityPolicy.BEST_EFFORT
    )
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=1,
        reliability=reliability,
    )


def summarize_path(msg, receive_time, index):
    poses = list(msg.poses)
    start = pose_to_xyyaw(poses[0])
    end = pose_to_xyyaw(poses[-1])
    return {
        "index": index,
        "receive_time": receive_time,
        "frame_id": msg.header.frame_id,
        "stamp": stamp_to_dict(msg.header.stamp),
        "point_count": len(poses),
        "path_length_xy_m": path_length_xy(poses),
        "start": start,
        "end": end,
    }


def write_path_csv(msg, csv_path):
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "index",
                "frame_id",
                "path_stamp_sec",
                "path_stamp_nanosec",
                "pose_stamp_sec",
                "pose_stamp_nanosec",
                "x",
                "y",
                "z",
                "yaw",
            ]
        )
        for index, pose_stamped in enumerate(msg.poses):
            pose = pose_to_xyyaw(pose_stamped)
            writer.writerow(
                [
                    index,
                    msg.header.frame_id,
                    msg.header.stamp.sec,
                    msg.header.stamp.nanosec,
                    pose_stamped.header.stamp.sec,
                    pose_stamped.header.stamp.nanosec,
                    f"{pose['x']:.6f}",
                    f"{pose['y']:.6f}",
                    f"{pose['z']:.6f}",
                    f"{pose['yaw']:.6f}",
                ]
            )


def write_path_svg(msg, summary, svg_path):
    width = 900
    height = 700
    padding = 70
    points = [(float(p.pose.position.x), float(p.pose.position.y)) for p in msg.poses]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 0.01)
    span_y = max(max_y - min_y, 0.01)
    scale = min((width - 2 * padding) / span_x, (height - 2 * padding) / span_y)

    def sx(x):
        return padding + (x - min_x) * scale

    def sy(y):
        return height - padding - (y - min_y) * scale

    polyline = " ".join(f"{sx(x):.2f},{sy(y):.2f}" for x, y in points)
    start_x, start_y = points[0]
    end_x, end_y = points[-1]
    title = (
        f"Nav2 global plan: {summary['point_count']} points, "
        f"{summary['path_length_xy_m']:.3f} m"
    )
    subtitle = (
        f"start=({summary['start']['x']:.3f}, {summary['start']['y']:.3f}) "
        f"end=({summary['end']['x']:.3f}, {summary['end']['y']:.3f}) "
        f"frame={summary['frame_id']}"
    )

    content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#f8fafc"/>
  <text x="24" y="34" font-family="monospace" font-size="18" fill="#0f172a">{html.escape(title)}</text>
  <text x="24" y="58" font-family="monospace" font-size="13" fill="#334155">{html.escape(subtitle)}</text>
  <rect x="{padding}" y="{padding}" width="{width - 2 * padding}" height="{height - 2 * padding}" fill="#ffffff" stroke="#cbd5e1"/>
  <polyline points="{polyline}" fill="none" stroke="#2563eb" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>
  <circle cx="{sx(start_x):.2f}" cy="{sy(start_y):.2f}" r="7" fill="#16a34a"/>
  <circle cx="{sx(end_x):.2f}" cy="{sy(end_y):.2f}" r="7" fill="#dc2626"/>
  <text x="{sx(start_x) + 10:.2f}" y="{sy(start_y) - 10:.2f}" font-family="monospace" font-size="13" fill="#166534">start</text>
  <text x="{sx(end_x) + 10:.2f}" y="{sy(end_y) - 10:.2f}" font-family="monospace" font-size="13" fill="#991b1b">end</text>
  <text x="24" y="{height - 24}" font-family="monospace" font-size="12" fill="#475569">bounds x=[{min_x:.3f}, {max_x:.3f}], y=[{min_y:.3f}, {max_y:.3f}]</text>
</svg>
"""
    svg_path.write_text(content, encoding="utf-8")


class Nav2GoalPlanProbe(Node):
    def __init__(self, args):
        super().__init__("nav2_goal_plan_probe")
        self.args = args
        self.captured = []
        self.plan_messages_seen = 0
        self.empty_plan_messages = 0
        self.last_capture_time = 0.0
        self.capture_enabled = False
        self.action_client = ActionClient(self, NavigateToPose, args.action_name)
        self.plan_sub = self.create_subscription(
            PathMsg,
            args.plan_topic,
            self._plan_callback,
            make_plan_qos(args.plan_qos),
        )

    def _plan_callback(self, msg):
        self.plan_messages_seen += 1
        if not self.capture_enabled or len(self.captured) >= self.args.max_plans:
            return
        if not msg.poses:
            self.empty_plan_messages += 1
            return
        now = time.monotonic()
        if self.captured and now - self.last_capture_time < self.args.min_plan_interval:
            return
        self.captured.append({"receive_time": time.time(), "msg": msg})
        self.last_capture_time = now

    def _build_goal(self):
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose.header.frame_id = self.args.frame_id
        goal_msg.pose.header.stamp = self.get_clock().now().to_msg()
        goal_msg.pose.pose.position.x = self.args.x
        goal_msg.pose.pose.position.y = self.args.y
        goal_msg.pose.pose.position.z = 0.0
        q = yaw_to_quaternion(self.args.yaw)
        goal_msg.pose.pose.orientation.x = q["x"]
        goal_msg.pose.pose.orientation.y = q["y"]
        goal_msg.pose.pose.orientation.z = q["z"]
        goal_msg.pose.pose.orientation.w = q["w"]
        return goal_msg

    def run(self):
        if not self.action_client.wait_for_server(timeout_sec=self.args.server_timeout):
            return {"accepted": False, "error": "navigate_to_pose server unavailable"}

        self.capture_enabled = True
        send_future = self.action_client.send_goal_async(self._build_goal())
        rclpy.spin_until_future_complete(
            self, send_future, timeout_sec=self.args.server_timeout
        )
        if not send_future.done():
            return {"accepted": False, "error": "goal send timed out"}

        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            return {"accepted": False, "error": "goal rejected"}

        deadline = time.monotonic() + self.args.plan_timeout
        while (
            rclpy.ok()
            and time.monotonic() < deadline
            and len(self.captured) < self.args.max_plans
        ):
            rclpy.spin_once(self, timeout_sec=0.05)

        if not self.args.keep_goal:
            cancel_future = goal_handle.cancel_goal_async()
            rclpy.spin_until_future_complete(self, cancel_future, timeout_sec=2.0)

        return self._write_outputs()

    def _write_outputs(self):
        output_dir = make_output_dir(self.args.output_dir)
        plans = []
        for index, capture in enumerate(self.captured, start=1):
            msg = capture["msg"]
            summary = summarize_path(msg, capture["receive_time"], index)
            csv_path = output_dir / f"plan_{index:03d}.csv"
            svg_path = output_dir / f"plan_{index:03d}.svg"
            write_path_csv(msg, csv_path)
            write_path_svg(msg, summary, svg_path)
            summary["csv_path"] = str(csv_path)
            summary["svg_path"] = str(svg_path)
            plans.append(summary)

        result = {
            "accepted": True,
            "plan_received": bool(plans),
            "plan_topic": self.args.plan_topic,
            "plan_qos": self.args.plan_qos,
            "plan_messages_seen": self.plan_messages_seen,
            "empty_plan_messages": self.empty_plan_messages,
            "captured_plan_count": len(plans),
            "max_plans": self.args.max_plans,
            "output_dir": str(output_dir),
            "goal": {
                "frame_id": self.args.frame_id,
                "x": self.args.x,
                "y": self.args.y,
                "yaw": self.args.yaw,
            },
            "plans": plans,
        }
        (output_dir / "summary.json").write_text(
            json.dumps(result, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return result


def parse_args():
    parser = argparse.ArgumentParser(
        description="Send a Nav2 goal and save the resulting /plan path."
    )
    parser.add_argument("--x", type=float, required=True)
    parser.add_argument("--y", type=float, required=True)
    parser.add_argument("--yaw", type=float, default=0.0)
    parser.add_argument("--frame-id", default="map")
    parser.add_argument("--action-name", default="navigate_to_pose")
    parser.add_argument("--plan-topic", default="/plan")
    parser.add_argument("--plan-qos", choices=("best_effort", "reliable"), default="best_effort")
    parser.add_argument("--server-timeout", type=float, default=15.0)
    parser.add_argument("--plan-timeout", type=float, default=8.0)
    parser.add_argument("--max-plans", type=int, default=1)
    parser.add_argument("--min-plan-interval", type=float, default=1.0)
    parser.add_argument("--output-dir")
    parser.add_argument(
        "--keep-goal",
        action="store_true",
        help="Do not cancel the navigation goal after capturing the plan.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.max_plans < 1:
        raise SystemExit("--max-plans must be >= 1")
    if args.min_plan_interval < 0:
        raise SystemExit("--min-plan-interval must be >= 0")

    rclpy.init()
    node = Nav2GoalPlanProbe(args)
    try:
        result = node.run()
        print(json.dumps(result, indent=2, sort_keys=True))
        if not result.get("accepted") or not result.get("plan_received"):
            raise SystemExit(2)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
