#!/usr/bin/env python3
"""Read and summarize AprilTag base_link detections without commanding motion."""

from __future__ import annotations

import argparse
import json
import math
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class AprilTagProbe(Node):
    def __init__(self, topic: str, frame_count: int, max_interval_s: float) -> None:
        super().__init__("apriltag_bridge_probe")
        self.frame_count = frame_count
        self.max_interval_s = max_interval_s
        self.received = 0
        self.last_received_s = None
        self.last_sequence = None
        self.error = None
        self.create_subscription(String, topic, self._on_frame, 10)

    def _on_frame(self, message: String) -> None:
        try:
            packet = json.loads(message.data)
            if packet.get("frame_id") != "base_link":
                raise ValueError("frame_id must be base_link")
            sequence = packet["sequence"]
            detections = packet["detections"]
            if not isinstance(sequence, int) or not isinstance(detections, list):
                raise ValueError("sequence and detections are required")
            if self.last_sequence is not None and sequence <= self.last_sequence:
                raise ValueError("sequence did not increase")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            self.error = "invalid AprilTag bridge packet: {}".format(exc)
            return
        now_s = time.monotonic()
        interval_ms = None
        if self.last_received_s is not None:
            interval_ms = (now_s - self.last_received_s) * 1000.0
            if interval_ms / 1000.0 > self.max_interval_s:
                self.error = "AprilTag frame gap {:.1f} ms exceeds {:.1f} ms".format(
                    interval_ms, self.max_interval_s * 1000.0
                )
                return
        self.last_received_s = now_s
        self.last_sequence = sequence
        summaries = []
        for detection in detections:
            x, y, z = detection["position_m"]
            qx, qy, qz, qw = detection["orientation_xyzw"]
            yaw = math.degrees(math.atan2(
                2.0 * (qw * qz + qx * qy),
                1.0 - 2.0 * (qy * qy + qz * qz),
            ))
            summaries.append(
                "id={} xyz=[{:.3f},{:.3f},{:.3f}] yaw_deg={:.2f}".format(
                    detection["tag_id"], x, y, z, yaw
                )
            )
        suffix = "" if interval_ms is None else " interval_ms={:.1f}".format(interval_ms)
        print(
            "sequence={} frame={} {}{}".format(
                packet["sequence"], packet["frame_id"], "; ".join(summaries), suffix
            ),
            flush=True,
        )
        self.received += 1

    @property
    def complete(self) -> bool:
        return self.received >= self.frame_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", default="/apriltag/detections_base")
    parser.add_argument("--frames", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--max-interval", type=float, default=2.0,
                        help="maximum allowed interval between accepted frames, in seconds")
    args = parser.parse_args()
    if args.frames <= 0 or args.timeout <= 0.0 or args.max_interval <= 0.0:
        parser.error("frames, timeout, and max-interval must be positive")

    rclpy.init()
    node = AprilTagProbe(args.topic, args.frames, args.max_interval)
    deadline = time.monotonic() + args.timeout
    try:
        while rclpy.ok() and not node.complete and node.error is None and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.2)
    finally:
        received = node.received
        error = node.error
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    if error is not None:
        raise SystemExit(error)
    if received == 0:
        raise SystemExit("no AprilTag frames received in {:.1f}s".format(args.timeout))
    if received < args.frames:
        raise SystemExit(
            "only received {}/{} AprilTag frames in {:.1f}s".format(
                received, args.frames, args.timeout
            )
        )


if __name__ == "__main__":
    main()
