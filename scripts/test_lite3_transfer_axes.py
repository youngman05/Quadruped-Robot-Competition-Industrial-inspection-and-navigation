#!/usr/bin/env python3
"""Smoke-test the official Lite3 transfer driver using dog state feedback."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rclpy.executors import SingleThreadedExecutor


@dataclass(frozen=True)
class OdomSample:
    received_s: float
    x: float
    y: float
    yaw: float
    vx: float
    vy: float
    wz: float


@dataclass(frozen=True)
class GoalSample:
    received_s: float
    vx: float
    vy: float
    wz: float


def yaw_from_odometry(message: Odometry) -> float:
    q = message.pose.pose.orientation
    return math.atan2(
        2.0 * (q.w * q.z + q.x * q.y),
        1.0 - 2.0 * (q.y * q.y + q.z * q.z),
    )


def wrapped_delta(current: float, previous: float) -> float:
    return math.atan2(math.sin(current - previous), math.cos(current - previous))


class TransferAxisProbe(Node):
    def __init__(self) -> None:
        super().__init__("lite3_transfer_axis_probe")
        best_effort = QoSProfile(depth=10)
        best_effort.reliability = ReliabilityPolicy.BEST_EFFORT
        self.publisher = self.create_publisher(Twist, "/cmd_vel", 10)
        self.odom_samples: List[OdomSample] = []
        self.goal_samples: List[GoalSample] = []
        self.create_subscription(Odometry, "/leg_odom2", self._on_odom, best_effort)
        self.create_subscription(Twist, "/handle_goal_vel", self._on_goal, best_effort)

    def _on_odom(self, message: Odometry) -> None:
        twist = message.twist.twist
        pose = message.pose.pose.position
        self.odom_samples.append(
            OdomSample(
                time.monotonic(), pose.x, pose.y, yaw_from_odometry(message),
                twist.linear.x, twist.linear.y, twist.angular.z,
            )
        )
        del self.odom_samples[:-4000]

    def _on_goal(self, message: Twist) -> None:
        self.goal_samples.append(
            GoalSample(
                time.monotonic(), message.linear.x, message.linear.y, message.angular.z,
            )
        )
        del self.goal_samples[:-4000]

    def wait_ready(self, timeout_s: float) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if (
                self.publisher.get_subscription_count() == 1
                and self.odom_samples
                and self.goal_samples
            ):
                return
            time.sleep(0.05)
        raise RuntimeError(
            "official transfer is not ready: cmd_vel_subscribers={} odom={} goal={}".format(
                self.publisher.get_subscription_count(),
                len(self.odom_samples),
                len(self.goal_samples),
            )
        )

    def command(self, axis: Optional[str], speed: float = 0.0) -> None:
        message = Twist()
        if axis == "x":
            message.linear.x = speed
        elif axis == "y":
            message.linear.y = speed
        elif axis == "yaw":
            message.angular.z = speed
        elif axis is not None:
            raise ValueError("unsupported axis {}".format(axis))
        self.publisher.publish(message)

    def drive_for(self, axis: Optional[str], speed: float, duration_s: float, rate_hz: float) -> Tuple[float, float]:
        period = 1.0 / rate_hz
        started = time.monotonic()
        deadline = started + duration_s
        while time.monotonic() < deadline:
            self.command(axis, speed)
            time.sleep(period)
        return started, time.monotonic()

    def stop_for(self, duration_s: float, rate_hz: float) -> None:
        self.drive_for(None, 0.0, duration_s, rate_hz)


def median(values: List[float]) -> Optional[float]:
    return None if not values else statistics.median(values)


def nearest_odom(samples: List[OdomSample], at_s: float) -> Optional[OdomSample]:
    if not samples:
        return None
    return min(samples, key=lambda sample: abs(sample.received_s - at_s))


def summarize(
    node: TransferAxisProbe,
    axis: str,
    speed: float,
    started: float,
    ended: float,
) -> Dict[str, object]:
    odom = [sample for sample in node.odom_samples if started <= sample.received_s <= ended]
    goals = [sample for sample in node.goal_samples if started <= sample.received_s <= ended]
    before = nearest_odom(node.odom_samples, started)
    after = nearest_odom(node.odom_samples, ended)
    delta = None
    if before is not None and after is not None:
        delta = {
            "x_m": after.x - before.x,
            "y_m": after.y - before.y,
            "yaw_deg": math.degrees(wrapped_delta(after.yaw, before.yaw)),
        }
    return {
        "axis": axis,
        "command": speed,
        "duration_s": ended - started,
        "goal_samples": len(goals),
        "goal_median": {
            "vx": median([sample.vx for sample in goals]),
            "vy": median([sample.vy for sample in goals]),
            "wz": median([sample.wz for sample in goals]),
        },
        "odom_samples": len(odom),
        "vel_body_median": {
            "vx": median([sample.vx for sample in odom]),
            "vy": median([sample.vy for sample in odom]),
            "wz": median([sample.wz for sample in odom]),
        },
        "pose_delta": delta,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Required to publish non-zero commands")
    parser.add_argument("--duration", type=float, default=1.0)
    parser.add_argument("--settle", type=float, default=1.0)
    parser.add_argument("--rate", type=float, default=20.0)
    parser.add_argument("--x-speed", type=float, default=0.04)
    parser.add_argument("--yaw-speed", type=float, default=0.05)
    parser.add_argument("--y-speed", type=float, default=0.04)
    parser.add_argument("--axes", nargs="+", choices=("x", "yaw", "y"), default=("x", "yaw", "y"))
    parser.add_argument("--output", default="/tmp/lite3_transfer_axes.json")
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required for real motion")
    if args.duration <= 0.0 or args.settle < 0.5 or args.rate < 10.0:
        parser.error("duration must be positive, settle >= 0.5, and rate >= 10")

    rclpy.init()
    node = TransferAxisProbe()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()
    results: List[Dict[str, object]] = []
    try:
        node.wait_ready(10.0)
        node.stop_for(0.5, args.rate)
        speeds = {"x": args.x_speed, "yaw": args.yaw_speed, "y": args.y_speed}
        sequence = tuple((axis, speeds[axis]) for axis in args.axes)
        for axis, speed in sequence:
            print("PULSE axis={} speed={:+.4f} duration_s={:.2f}".format(axis, speed, args.duration), flush=True)
            started, ended = node.drive_for(axis, speed, args.duration, args.rate)
            node.stop_for(args.settle, args.rate)
            result = summarize(node, axis, speed, started, ended)
            results.append(result)
            print("RESULT " + json.dumps(result, sort_keys=True), flush=True)
    finally:
        node.stop_for(0.6, max(args.rate, 20.0))
        executor.shutdown()
        spin_thread.join(timeout=2.0)
        node.destroy_node()
        rclpy.shutdown()

    with open(args.output, "w") as handle:
        json.dump(results, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
