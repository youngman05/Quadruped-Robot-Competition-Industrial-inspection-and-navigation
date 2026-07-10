#!/usr/bin/env python3
"""Probe /odom direction conventions during a short manual or robot motion.

Run this while cuVSLAM bridge is publishing host /odom. Move the robot forward
or rotate it during the sampling window, then inspect the reported deltas.
"""

from __future__ import annotations

import argparse
import math
import sys
import time


def yaw_from_quat(q) -> float:
    siny = 2.0 * (q.w * q.z + q.x * q.y)
    cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny, cosy)


def normalize_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", default="/odom")
    parser.add_argument("--duration", type=float, default=8.0)
    parser.add_argument("--qos", choices=("best_effort", "reliable"), default="best_effort")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.qos import QoSProfile, ReliabilityPolicy

    rclpy.init()
    node = rclpy.create_node("odom_direction_probe")
    reliability = (
        ReliabilityPolicy.BEST_EFFORT
        if args.qos == "best_effort"
        else ReliabilityPolicy.RELIABLE
    )
    qos = QoSProfile(depth=10, reliability=reliability)
    samples = []

    def cb(msg: Odometry) -> None:
        p = msg.pose.pose.position
        yaw = yaw_from_quat(msg.pose.pose.orientation)
        samples.append((time.time(), p.x, p.y, p.z, yaw))

    node.create_subscription(Odometry, args.topic, cb, qos)
    deadline = time.time() + args.duration
    print(
        f"Sampling {args.topic} for {args.duration:.1f}s. "
        "Move forward / rotate now if doing a manual direction check."
    )
    while time.time() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)

    node.destroy_node()
    rclpy.shutdown()

    if len(samples) < 2:
        print("ERROR: received fewer than 2 odom samples.")
        return 2

    first = samples[0]
    last = samples[-1]
    dt = last[0] - first[0]
    dx = last[1] - first[1]
    dy = last[2] - first[2]
    dz = last[3] - first[3]
    dyaw = normalize_angle(last[4] - first[4])
    dist_xy = math.hypot(dx, dy)
    heading = math.atan2(dy, dx) if dist_xy > 1e-6 else 0.0

    print(f"samples={len(samples)} dt={dt:.3f}s")
    print(
        "start: "
        f"x={first[1]:.4f} y={first[2]:.4f} z={first[3]:.4f} "
        f"yaw={math.degrees(first[4]):.2f}deg"
    )
    print(
        "end:   "
        f"x={last[1]:.4f} y={last[2]:.4f} z={last[3]:.4f} "
        f"yaw={math.degrees(last[4]):.2f}deg"
    )
    print(
        "delta: "
        f"dx={dx:.4f} dy={dy:.4f} dz={dz:.4f} "
        f"dist_xy={dist_xy:.4f} heading={math.degrees(heading):.2f}deg "
        f"dyaw={math.degrees(dyaw):.2f}deg"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
