#!/usr/bin/env python3
"""Verify the live cone scan and health streams without publishing data."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ProbeState:
    scan_count: int = 0
    first_scan_time: Optional[float] = None
    last_scan_time: Optional[float] = None
    health_count: int = 0
    unhealthy: List[Dict[str, Any]] = field(default_factory=list)
    first_sequence: Optional[int] = None
    last_sequence: Optional[int] = None
    last_stream_id: Optional[str] = None
    max_source_age_ms: float = 0.0

    def record_scan(self, now: float) -> None:
        self.scan_count += 1
        if self.first_scan_time is None:
            self.first_scan_time = now
        self.last_scan_time = now

    def record_health(self, payload: str) -> None:
        try:
            status = json.loads(payload)
        except (TypeError, ValueError) as exc:
            self.unhealthy.append({"reason": "invalid health JSON", "error": str(exc)})
            return

        self.health_count += 1
        reason = str(status.get("reason", ""))
        healthy = status.get("healthy") is True and reason == "ready"
        stream_id = str(status.get("stream_id", ""))
        try:
            sequence = int(status["sequence"])
            source_age_ms = float(status["source_age_ms"])
        except (KeyError, TypeError, ValueError) as exc:
            self.unhealthy.append(
                {"reason": "incomplete health payload", "error": str(exc)}
            )
            return

        if not healthy:
            self.unhealthy.append(
                {"reason": reason or "not ready", "sequence": sequence}
            )
        if not stream_id:
            self.unhealthy.append(
                {"reason": "empty stream_id", "sequence": sequence}
            )
        elif self.last_stream_id is not None and stream_id != self.last_stream_id:
            self.unhealthy.append(
                {"reason": "stream_id changed", "sequence": sequence}
            )
        if self.last_sequence is not None and sequence <= self.last_sequence:
            self.unhealthy.append(
                {"reason": "health sequence did not advance", "sequence": sequence}
            )

        if self.first_sequence is None:
            self.first_sequence = sequence
        self.last_sequence = sequence
        self.last_stream_id = stream_id
        self.max_source_age_ms = max(self.max_source_age_ms, source_age_ms)

    def result(self, min_scan_rate_hz: float, min_health_samples: int) -> Dict[str, Any]:
        elapsed = 0.0
        scan_rate_hz = 0.0
        if self.first_scan_time is not None and self.last_scan_time is not None:
            elapsed = self.last_scan_time - self.first_scan_time
            if elapsed > 0.0 and self.scan_count > 1:
                scan_rate_hz = (self.scan_count - 1) / elapsed

        errors: List[str] = []
        if self.scan_count < 2:
            errors.append("fewer than two scan samples")
        elif scan_rate_hz < min_scan_rate_hz:
            errors.append(
                "scan rate %.3f Hz is below %.3f Hz"
                % (scan_rate_hz, min_scan_rate_hz)
            )
        if self.health_count < min_health_samples:
            errors.append(
                "health sample count %d is below %d"
                % (self.health_count, min_health_samples)
            )
        if self.unhealthy:
            errors.append("health stream was not continuously ready")

        return {
            "passed": not errors,
            "scan_count": self.scan_count,
            "scan_rate_hz": scan_rate_hz,
            "health_count": self.health_count,
            "first_sequence": self.first_sequence,
            "last_sequence": self.last_sequence,
            "max_source_age_ms": self.max_source_age_ms,
            "unhealthy_samples": self.unhealthy[:10],
            "errors": errors,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-sec", type=float, default=10.0)
    parser.add_argument("--min-scan-rate-hz", type=float, default=8.0)
    parser.add_argument("--min-health-samples", type=int, default=8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.duration_sec <= 0.0 or args.min_scan_rate_hz <= 0.0:
        raise SystemExit("duration and minimum scan rate must be positive")
    if args.min_health_samples < 1:
        raise SystemExit("minimum health samples must be positive")

    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import LaserScan
    from std_msgs.msg import String

    try:
        from rclpy.qos import HistoryPolicy
    except ImportError:
        from rclpy.qos import QoSHistoryPolicy as HistoryPolicy

    rclpy.init()
    node = Node("cone_startup_health_probe")
    state = ProbeState()
    scan_qos = QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=1,
        reliability=ReliabilityPolicy.BEST_EFFORT,
    )
    health_qos = QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=10,
        reliability=ReliabilityPolicy.RELIABLE,
    )
    node.create_subscription(
        LaserScan,
        "/cone_obstacle/scan",
        lambda _msg: state.record_scan(time.monotonic()),
        scan_qos,
    )
    node.create_subscription(
        String,
        "/cone_obstacle/health",
        lambda msg: state.record_health(msg.data),
        health_qos,
    )

    deadline = time.monotonic() + args.duration_sec
    try:
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        node.destroy_node()
        rclpy.shutdown()

    result = state.result(args.min_scan_rate_hz, args.min_health_samples)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
