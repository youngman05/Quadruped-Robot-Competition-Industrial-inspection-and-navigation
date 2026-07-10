#!/usr/bin/env python3
"""Send one Nav2 goal and summarize /cmd_vel output for dry-run tests."""

import argparse
import json
import math
import time

import rclpy
from geometry_msgs.msg import Twist
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node


def yaw_to_quaternion(yaw):
    half = yaw * 0.5
    return {
        "x": 0.0,
        "y": 0.0,
        "z": math.sin(half),
        "w": math.cos(half),
    }


class Nav2GoalProbe(Node):
    def __init__(self, args):
        super().__init__("nav2_goal_cmd_vel_probe")
        self.args = args
        self.cmd_count = 0
        self.nonzero_count = 0
        self.max_linear_x = 0.0
        self.max_abs_angular_z = 0.0
        self.create_subscription(Twist, "/cmd_vel", self._cmd_callback, 10)
        self.action_client = ActionClient(self, NavigateToPose, "navigate_to_pose")

    def _cmd_callback(self, msg):
        self.cmd_count += 1
        linear_x = float(msg.linear.x)
        angular_z = float(msg.angular.z)
        if abs(linear_x) > 1e-5 or abs(angular_z) > 1e-5:
            self.nonzero_count += 1
        self.max_linear_x = max(self.max_linear_x, abs(linear_x))
        self.max_abs_angular_z = max(self.max_abs_angular_z, abs(angular_z))

    def run(self):
        if not self.action_client.wait_for_server(timeout_sec=self.args.server_timeout):
            return {"accepted": False, "error": "navigate_to_pose server unavailable"}

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

        send_future = self.action_client.send_goal_async(goal_msg)
        rclpy.spin_until_future_complete(self, send_future, timeout_sec=self.args.server_timeout)
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            return {"accepted": False, "error": "goal rejected"}

        deadline = time.time() + self.args.sample_seconds
        while rclpy.ok() and time.time() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)

        cancel_future = goal_handle.cancel_goal_async()
        rclpy.spin_until_future_complete(self, cancel_future, timeout_sec=2.0)

        return {
            "accepted": True,
            "cmd_count": self.cmd_count,
            "nonzero_count": self.nonzero_count,
            "max_linear_x": self.max_linear_x,
            "max_abs_angular_z": self.max_abs_angular_z,
            "goal": {
                "frame_id": self.args.frame_id,
                "x": self.args.x,
                "y": self.args.y,
                "yaw": self.args.yaw,
            },
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--x", type=float, required=True)
    parser.add_argument("--y", type=float, required=True)
    parser.add_argument("--yaw", type=float, default=0.0)
    parser.add_argument("--frame-id", default="map")
    parser.add_argument("--sample-seconds", type=float, default=8.0)
    parser.add_argument("--server-timeout", type=float, default=15.0)
    args = parser.parse_args()

    rclpy.init()
    node = Nav2GoalProbe(args)
    try:
        result = node.run()
        print(json.dumps(result, indent=2, sort_keys=True))
        if not result.get("accepted") or result.get("nonzero_count", 0) == 0:
            raise SystemExit(2)
    finally:
        node.action_client.destroy()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
