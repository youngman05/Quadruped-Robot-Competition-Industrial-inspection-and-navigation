#!/usr/bin/env python3
"""Supervised AprilTag-based axis response calibration for the Lite3 bridge.

The bridge must already be running.  Each pulse is bracketed by stationary
AprilTag samples and is followed by explicit all-axis zero commands.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from std_msgs.msg import String


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@dataclass(frozen=True)
class TagPose:
    xyz: Tuple[float, float, float]
    yaw: float


def wrap_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def median_pose(samples: Sequence[TagPose]) -> TagPose:
    if not samples:
        raise RuntimeError("no AprilTag samples collected")
    xyz = tuple(statistics.median(sample.xyz[index] for sample in samples) for index in range(3))
    sin_mean = statistics.fmean(math.sin(sample.yaw) for sample in samples)
    cos_mean = statistics.fmean(math.cos(sample.yaw) for sample in samples)
    return TagPose(xyz, math.atan2(sin_mean, cos_mean))


class AxisCalibrator(Node):
    def __init__(self, tag_id: int) -> None:
        super().__init__("lite3_axis_calibrator")
        self._tag_id = tag_id
        self._samples: List[TagPose] = []
        self._publisher = self.create_publisher(Twist, "/cmd_vel", 10)
        self._subscription = self.create_subscription(
            String, "/apriltag/detections_base", self._on_detections, 10
        )

    def _on_detections(self, message: String) -> None:
        try:
            packet = json.loads(message.data)
            if packet.get("frame_id") != "base_link":
                return
            for detection in packet.get("detections", []):
                if int(detection["tag_id"]) != self._tag_id:
                    continue
                x, y, z = (float(value) for value in detection["position_m"])
                qx, qy, qz, qw = (float(value) for value in detection["orientation_xyzw"])
                yaw = math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))
                self._samples.append(TagPose((x, y, z), yaw))
                return
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return

    def wait_for_bridge(self, timeout_s: float) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
            if self._publisher.get_subscription_count() >= 1:
                return
        raise RuntimeError("/cmd_vel bridge subscription was not discovered")

    def collect(self, frame_count: int, timeout_s: float) -> TagPose:
        self._samples.clear()
        deadline = time.monotonic() + timeout_s
        while len(self._samples) < frame_count and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
        if len(self._samples) < frame_count:
            raise RuntimeError("only collected {} of {} AprilTag frames".format(len(self._samples), frame_count))
        return median_pose(self._samples)

    def publish_zero(self) -> None:
        for _ in range(3):
            self._publisher.publish(Twist())
            rclpy.spin_once(self, timeout_sec=0.05)

    def pulse(self, axis: str, speed: float, duration_s: float) -> None:
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            command = Twist()
            if axis == "x":
                command.linear.x = speed
            elif axis == "y":
                command.linear.y = speed
            elif axis == "yaw":
                command.angular.z = speed
            else:
                raise ValueError("unsupported axis {}".format(axis))
            self._publisher.publish(command)
            rclpy.spin_once(self, timeout_sec=0.1)
        self.publish_zero()


def format_pose(pose: TagPose) -> str:
    return "xyz=[{:.3f},{:.3f},{:.3f}] yaw_deg={:.2f}".format(*pose.xyz, math.degrees(pose.yaw))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag-id", type=int, default=0)
    parser.add_argument("--frames", type=int, default=20)
    parser.add_argument("--linear-speed", type=float, default=0.0125)
    parser.add_argument("--yaw-speed", type=float, default=0.05)
    parser.add_argument("--settle-s", type=float, default=2.0)
    parser.add_argument("--durations", type=float, nargs="+", default=(2.0, 3.0))
    args = parser.parse_args()

    rclpy.init()
    calibrator = AxisCalibrator(args.tag_id)
    sequence = [(axis, sign, duration) for axis in ("y", "x", "yaw") for duration in args.durations for sign in (1, -1)]
    try:
        calibrator.wait_for_bridge(10.0)
        print("bridge discovered; beginning {} supervised pulses".format(len(sequence)), flush=True)
        for index, (axis, sign, duration) in enumerate(sequence, start=1):
            speed = sign * (args.yaw_speed if axis == "yaw" else args.linear_speed)
            before = calibrator.collect(args.frames, 10.0)
            print("{}/{} PRE axis={} speed={:+.4f} duration_s={:.1f} {}".format(index, len(sequence), axis, speed, duration, format_pose(before)), flush=True)
            calibrator.pulse(axis, speed, duration)
            time.sleep(args.settle_s)
            after = calibrator.collect(args.frames, 10.0)
            delta = tuple(after.xyz[i] - before.xyz[i] for i in range(3))
            yaw_delta = wrap_angle(after.yaw - before.yaw)
            print("{}/{} POST tag_delta=[{:+.3f},{:+.3f},{:+.3f}] yaw_delta_deg={:+.2f} {}".format(index, len(sequence), *delta, math.degrees(yaw_delta), format_pose(after)), flush=True)
    finally:
        calibrator.publish_zero()
        calibrator.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
