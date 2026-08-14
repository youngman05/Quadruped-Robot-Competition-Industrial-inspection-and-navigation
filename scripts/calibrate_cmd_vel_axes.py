#!/usr/bin/env python3
"""Supervised Lite3 axis-response calibration using Tag 0 and RobotState.

This tool is intentionally separate from the pickup state machine.  It sends
one axis at a time, records a Tag 0 median before and after each pulse, and
records the Lite3 RobotState yaw/velocity samples at UDP port 43897.
"""

from __future__ import annotations

import argparse
import json
import math
import socket
import statistics
import struct
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from std_msgs.msg import String


ROBOT_STATE_CODE = 2305
ROBOT_STATE_BYTES = 212
# Firmware packets omit robot_policy_state from the public header layout.
ROBOT_STATE_RPY_OFFSET = 20
ROBOT_STATE_VEL_BODY_OFFSET = 140


@dataclass
class TagSample:
    sequence: int
    x: float
    y: float
    z: float
    yaw: float


@dataclass
class RobotStateSample:
    received_s: float
    yaw_deg: float
    vx: float
    vy: float


class RobotStateListener:
    def __init__(self, port: int = 43897) -> None:
        self._samples: List[RobotStateSample] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("0.0.0.0", port))
        self._socket.settimeout(0.2)
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        self._socket.close()

    def samples_between(self, start_s: float, end_s: float) -> List[RobotStateSample]:
        with self._lock:
            return [sample for sample in self._samples if start_s <= sample.received_s <= end_s]

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                packet, _address = self._socket.recvfrom(512)
            except socket.timeout:
                continue
            if len(packet) != ROBOT_STATE_BYTES:
                continue
            code, _size, _type = struct.unpack_from("<3i", packet)
            if code != ROBOT_STATE_CODE:
                continue
            roll, pitch, yaw_deg = struct.unpack_from("<3d", packet, ROBOT_STATE_RPY_OFFSET)
            del roll, pitch
            vx, vy, _vz = struct.unpack_from("<3d", packet, ROBOT_STATE_VEL_BODY_OFFSET)
            sample = RobotStateSample(time.monotonic(), yaw_deg, vx, vy)
            with self._lock:
                self._samples.append(sample)
                del self._samples[:-2000]


class CalibrationNode(Node):
    def __init__(self, tag_id: int) -> None:
        super().__init__("cmd_vel_axis_calibration")
        self._tag_id = tag_id
        self._tag_samples: List[TagSample] = []
        self._tag_lock = threading.Lock()
        self._publisher = self.create_publisher(Twist, "/cmd_vel", 10)
        self._subscription = self.create_subscription(
            String, "/apriltag/detections_base", self._on_tag, 10
        )

    def tag_samples_after(self, sequence: int) -> List[TagSample]:
        with self._tag_lock:
            return [sample for sample in self._tag_samples if sample.sequence > sequence]

    def latest_tag_sequence(self) -> int:
        with self._tag_lock:
            return self._tag_samples[-1].sequence if self._tag_samples else -1

    def command(self, axis: str, speed: float) -> None:
        message = Twist()
        if axis == "x":
            message.linear.x = speed
        elif axis == "y":
            message.linear.y = speed
        elif axis == "yaw":
            message.angular.z = speed
        else:
            raise ValueError("unsupported axis: {}".format(axis))
        self._publisher.publish(message)

    def stop(self) -> None:
        for _ in range(3):
            self._publisher.publish(Twist())
            time.sleep(0.05)

    def _on_tag(self, message: String) -> None:
        try:
            packet = json.loads(message.data)
            sequence = int(packet["sequence"])
            for detection in packet["detections"]:
                if int(detection["tag_id"]) != self._tag_id:
                    continue
                x, y, z = (float(value) for value in detection["position_m"])
                qx, qy, qz, qw = (float(value) for value in detection["orientation_xyzw"])
                yaw = math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))
                sample = TagSample(sequence, x, y, z, yaw)
                with self._tag_lock:
                    if not self._tag_samples or sample.sequence > self._tag_samples[-1].sequence:
                        self._tag_samples.append(sample)
                        del self._tag_samples[:-2000]
                return
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return


def wrapped_delta(current: float, previous: float) -> float:
    return math.atan2(math.sin(current - previous), math.cos(current - previous))


def tag_median(samples: Sequence[TagSample]) -> Dict[str, float]:
    if not samples:
        raise RuntimeError("no Tag samples collected")
    reference = samples[0].yaw
    unwrapped_yaws = [reference + wrapped_delta(sample.yaw, reference) for sample in samples]
    median_yaw = statistics.median(unwrapped_yaws)
    return {
        "x": statistics.median(sample.x for sample in samples),
        "y": statistics.median(sample.y for sample in samples),
        "z": statistics.median(sample.z for sample in samples),
        "yaw": math.atan2(math.sin(median_yaw), math.cos(median_yaw)),
        "frames": len(samples),
    }


def robot_summary(samples: Sequence[RobotStateSample]) -> Optional[Dict[str, float]]:
    if not samples:
        return None
    return {
        "samples": len(samples),
        "yaw_deg_median": statistics.median(sample.yaw_deg for sample in samples),
        "vx_median": statistics.median(sample.vx for sample in samples),
        "vy_median": statistics.median(sample.vy for sample in samples),
    }


def spin_until(node: CalibrationNode, predicate, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.05)
        if predicate():
            return
    raise RuntimeError("timed out waiting for AprilTag samples")


def collect_tag_median(node: CalibrationNode, frames: int, timeout_s: float) -> Dict[str, float]:
    start_sequence = node.latest_tag_sequence()
    spin_until(node, lambda: len(node.tag_samples_after(start_sequence)) >= frames, timeout_s)
    return tag_median(node.tag_samples_after(start_sequence)[-frames:])


def publish_pulse(node: CalibrationNode, axis: str, speed: float, duration_s: float) -> Tuple[float, float]:
    start_s = time.monotonic()
    deadline = start_s + duration_s
    while time.monotonic() < deadline:
        node.command(axis, speed)
        rclpy.spin_once(node, timeout_sec=0.0)
        time.sleep(0.05)
    node.stop()
    return start_s, time.monotonic()


def run_pulse(
    node: CalibrationNode,
    states: RobotStateListener,
    axis: str,
    sign: int,
    duration_s: float,
    linear_speed: float,
    yaw_speed: float,
    frames: int,
) -> Dict[str, object]:
    speed = sign * (yaw_speed if axis == "yaw" else linear_speed)
    pre = collect_tag_median(node, frames, 8.0)
    print("CALIBRATE axis={} sign={:+d} duration_s={:.1f} speed={:.4f}".format(axis, sign, duration_s, speed), flush=True)
    pulse_start, pulse_end = publish_pulse(node, axis, speed, duration_s)
    time.sleep(2.0)
    post = collect_tag_median(node, frames, 8.0)
    robot = robot_summary(states.samples_between(pulse_start, pulse_end + 2.0))
    result: Dict[str, object] = {
        "axis": axis,
        "sign": sign,
        "duration_s": duration_s,
        "speed": speed,
        "tag_pre": pre,
        "tag_post": post,
        "tag_delta": {
            "x": post["x"] - pre["x"],
            "y": post["y"] - pre["y"],
            "z": post["z"] - pre["z"],
            "yaw_deg": math.degrees(wrapped_delta(post["yaw"], pre["yaw"])),
        },
        "robot_state": robot,
    }
    print("RESULT " + json.dumps(result, ensure_ascii=True), flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag-id", type=int, default=0)
    parser.add_argument("--linear-speed", type=float, default=0.0125)
    parser.add_argument("--yaw-speed", type=float, default=0.05)
    parser.add_argument("--frames", type=int, default=20)
    parser.add_argument("--durations", type=float, nargs="+", default=[2.0, 3.0])
    parser.add_argument("--output", type=Path, default=Path("/tmp/cmd_vel_axis_calibration.json"))
    args = parser.parse_args()
    if args.frames < 5 or any(duration <= 0.0 for duration in args.durations):
        parser.error("frames must be >= 5 and all durations must be positive")

    rclpy.init()
    node = CalibrationNode(args.tag_id)
    states = RobotStateListener()
    states.start()
    results = []
    try:
        print("Waiting for /cmd_vel bridge subscription...", flush=True)
        spin_until(node, lambda: node._publisher.get_subscription_count() >= 1, 8.0)
        print("Bridge matched; waiting for Tag {}...".format(args.tag_id), flush=True)
        collect_tag_median(node, args.frames, 10.0)
        for duration_s in args.durations:
            for axis in ("y", "x", "yaw"):
                for sign in (1, -1):
                    results.append(run_pulse(
                        node, states, axis, sign, duration_s,
                        args.linear_speed, args.yaw_speed, args.frames,
                    ))
        args.output.write_text(json.dumps(results, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        print("Saved {} results to {}".format(len(results), args.output), flush=True)
        return 0
    finally:
        node.stop()
        states.close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
