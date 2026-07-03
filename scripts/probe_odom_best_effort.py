#!/usr/bin/env python3
"""Probe /odom with explicit BEST_EFFORT QoS and latency statistics."""
import argparse
import math
import statistics
import sys
import time

import rclpy
from nav_msgs.msg import Odometry
from rclpy.qos import QoSProfile, ReliabilityPolicy

try:
    from rclpy.qos import HistoryPolicy
except ImportError:
    from rclpy.qos import QoSHistoryPolicy as HistoryPolicy


RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def color(text, code, enabled):
    return f"{code}{text}{RESET}" if enabled else text


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", default="/odom")
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--first-timeout", type=float, default=2.0)
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--max-good-latency-ms", type=float, default=50.0)
    parser.add_argument("--warn-latency-ms", type=float, default=100.0)
    parser.add_argument("--no-color", action="store_true")
    return parser.parse_args()


def percentile(values, pct):
    if not values:
        return math.nan
    ordered = sorted(values)
    index = (len(ordered) - 1) * pct / 100.0
    lo = math.floor(index)
    hi = math.ceil(index)
    if lo == hi:
        return ordered[int(index)]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)


def fmt_ms(value):
    return "nan" if math.isnan(value) else f"{value * 1000.0:.2f} ms"


def classify_latency(p95_latency, jitter, growth, args):
    p95_ms = p95_latency * 1000.0
    jitter_ms = jitter * 1000.0
    growth_ms = abs(growth * 1000.0)
    if (
        p95_ms <= args.max_good_latency_ms
        and growth_ms <= args.max_good_latency_ms
        and jitter_ms <= args.warn_latency_ms
    ):
        return "stable_good"
    if (
        p95_ms > args.warn_latency_ms
        or growth_ms > args.warn_latency_ms
        or jitter_ms > args.warn_latency_ms
    ):
        return "unstable_or_backlogged"
    return "watch"


def main():
    args = parse_args()
    use_color = not args.no_color and sys.stdout.isatty()
    rclpy.init()
    node = rclpy.create_node("probe_odom_best_effort")
    qos = QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=args.depth,
        reliability=ReliabilityPolicy.BEST_EFFORT,
    )

    samples = []
    latencies = []
    source_stamps = []
    first_sample = None
    last_sample = None

    def callback(msg):
        nonlocal first_sample, last_sample
        host_now = time.time()
        source_stamp = msg.header.stamp.sec + msg.header.stamp.nanosec / 1e9
        latency = host_now - source_stamp
        sample = {
            "host_now": host_now,
            "source_stamp": source_stamp,
            "latency": latency,
            "frame_id": msg.header.frame_id,
            "child_frame_id": msg.child_frame_id,
            "x": msg.pose.pose.position.x,
            "y": msg.pose.pose.position.y,
            "z": msg.pose.pose.position.z,
        }
        samples.append(sample)
        latencies.append(latency)
        source_stamps.append(source_stamp)
        if first_sample is None:
            first_sample = sample
        last_sample = sample

    node.create_subscription(Odometry, args.topic, callback, qos)

    start = time.time()
    first_deadline = start + args.first_timeout
    end = start + args.duration
    while time.time() < end:
        rclpy.spin_once(node, timeout_sec=0.05)
        if not samples and time.time() > first_deadline:
            print(
                color(
                    "[ERROR] No Odom data received! Check Exporter inside container. "
                    f"(timeout={args.first_timeout:.1f}s)",
                    RED,
                    use_color,
                )
            )
            node.destroy_node()
            rclpy.shutdown()
            return 2

    elapsed = time.time() - start
    count = len(samples)
    if count == 0:
        print(
            color(
                "[ERROR] No Odom data received! Check Exporter inside container.",
                RED,
                use_color,
            )
        )
        node.destroy_node()
        rclpy.shutdown()
        return 2

    host_rate = count / elapsed if elapsed > 0 else 0.0
    source_span = source_stamps[-1] - source_stamps[0] if count > 1 else 0.0
    source_rate = (count - 1) / source_span if source_span > 0 else 0.0
    mean_latency = statistics.fmean(latencies)
    min_latency = min(latencies)
    max_latency = max(latencies)
    p95_latency = percentile(latencies, 95)
    jitter = max_latency - min_latency
    growth = latencies[-1] - latencies[0]
    latency_class = classify_latency(p95_latency, jitter, growth, args)

    status = "[OK]"
    status_color = GREEN
    if latency_class != "stable_good":
        status = "[WARN]"
        status_color = YELLOW
    if count <= 1:
        status = "[ERROR]"
        status_color = RED

    print(color(f"{status} {args.topic} BEST_EFFORT probe", status_color, use_color))
    print(f"count: {count}")
    print(f"elapsed_host: {elapsed:.3f} s")
    print(f"rate_host: {host_rate:.2f} Hz")
    print(f"rate_source_stamp: {source_rate:.2f} Hz")
    print(f"latency_mean_host_now_minus_source: {fmt_ms(mean_latency)}")
    print(f"latency_min: {fmt_ms(min_latency)}")
    print(f"latency_p95: {fmt_ms(p95_latency)}")
    print(f"latency_max: {fmt_ms(max_latency)}")
    print(f"latency_jitter_max_minus_min: {fmt_ms(jitter)}")
    print(f"latency_growth_last_minus_first: {fmt_ms(growth)}")
    print(f"latency_status: {latency_class}")
    print(
        "first: "
        f"stamp={first_sample['source_stamp']:.9f} "
        f"frame={first_sample['frame_id']}->{first_sample['child_frame_id']} "
        f"xyz=({first_sample['x']:.4f}, {first_sample['y']:.4f}, {first_sample['z']:.4f})"
    )
    print(
        "last: "
        f"stamp={last_sample['source_stamp']:.9f} "
        f"frame={last_sample['frame_id']}->{last_sample['child_frame_id']} "
        f"xyz=({last_sample['x']:.4f}, {last_sample['y']:.4f}, {last_sample['z']:.4f})"
    )

    node.destroy_node()
    rclpy.shutdown()
    return 0 if status != "[ERROR]" else 1


if __name__ == "__main__":
    raise SystemExit(main())
