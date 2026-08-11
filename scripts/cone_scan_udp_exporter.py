#!/usr/bin/env python3
"""Export a Humble base_link LaserScan and decimated-depth health over UDP."""

from __future__ import annotations

import argparse
import math
import socket
import time
import uuid
from dataclasses import dataclass
from typing import Optional, Tuple

import rclpy
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image, LaserScan

try:
    from rclpy.qos import HistoryPolicy
except ImportError:
    from rclpy.qos import QoSHistoryPolicy as HistoryPolicy

try:
    from cone_scan_protocol import (
        ConeScanContractError,
        ConeScanPacket,
        depth_coverage_from_image,
        depth_coverage_is_healthy,
        encode_packet,
        filter_short_finite_runs,
        longest_finite_run,
        scan_returns_are_healthy,
    )
except ImportError:
    from nodes.navigation.cone_scan_protocol import (
        ConeScanContractError,
        ConeScanPacket,
        depth_coverage_from_image,
        depth_coverage_is_healthy,
        encode_packet,
        filter_short_finite_runs,
        longest_finite_run,
        scan_returns_are_healthy,
    )


@dataclass(frozen=True)
class DepthHealthSample:
    source_stamp_ns: int
    received_monotonic: float
    coverage: Tuple[float, float, float, float]


def stamp_ns(msg) -> int:
    return int(msg.header.stamp.sec) * 1_000_000_000 + int(
        msg.header.stamp.nanosec
    )


def normalized_ranges(msg: LaserScan) -> Tuple[float, ...]:
    result = []
    lower = float(msg.range_min)
    upper = float(msg.range_max)
    for value in msg.ranges:
        value = float(value)
        if math.isfinite(value) and lower <= value <= upper:
            result.append(value)
        else:
            result.append(float("inf"))
    return tuple(result)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan-topic", default="/cone_obstacle/scan_humble")
    parser.add_argument("--depth-topic", default="/camera/depth/image_rect_raw")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=19002)
    parser.add_argument("--qos-depth", type=int, default=1)
    parser.add_argument("--max-rate-hz", type=float, default=10.0)
    parser.add_argument("--max-depth-age-sec", type=float, default=0.25)
    parser.add_argument("--max-source-skew-sec", type=float, default=0.15)
    parser.add_argument("--min-valid-ratio", type=float, default=0.05)
    parser.add_argument("--min-zone-ratio", type=float, default=0.01)
    parser.add_argument("--min-contiguous-beams", type=int, default=3)
    parser.add_argument("--log-every", type=int, default=100)
    return parser.parse_args(argv)


def main(args=None) -> None:
    cli = parse_args(args)
    rclpy.init()
    node = rclpy.create_node("cone_scan_udp_exporter")
    qos = QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=max(1, int(cli.qos_depth)),
        reliability=ReliabilityPolicy.BEST_EFFORT,
    )
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 64 * 1024)
    sock.setblocking(False)
    target = (cli.host, int(cli.port))
    stream_id = uuid.uuid4().hex
    latest_depth: Optional[DepthHealthSample] = None
    sequence = 0
    invalid_depth = 0
    send_errors = 0
    last_depth_processing = float("-inf")
    last_scan_send = float("-inf")
    minimum_period = 1.0 / max(1.0, float(cli.max_rate_hz))
    rate_guard = max(0.0, minimum_period - 0.005)

    def on_depth(msg: Image) -> None:
        nonlocal latest_depth, invalid_depth, last_depth_processing
        now = time.monotonic()
        if now - last_depth_processing < rate_guard:
            return
        last_depth_processing = now
        try:
            if str(msg.encoding) not in ("16UC1", "mono16"):
                raise ConeScanContractError(
                    "unsupported depth encoding: %s" % msg.encoding
                )
            coverage = depth_coverage_from_image(
                bytes(msg.data),
                msg.width,
                msg.height,
                msg.step,
            )
            latest_depth = DepthHealthSample(
                source_stamp_ns=stamp_ns(msg),
                received_monotonic=now,
                coverage=coverage,
            )
        except ConeScanContractError as exc:
            invalid_depth += 1
            latest_depth = None
            if invalid_depth == 1 or invalid_depth % 100 == 0:
                node.get_logger().error("invalid depth health frame: %s" % exc)

    def on_scan(msg: LaserScan) -> None:
        nonlocal sequence, send_errors, last_scan_send
        now = time.monotonic()
        if now - last_scan_send < rate_guard:
            return
        last_scan_send = now
        sequence += 1
        scan_stamp_ns = stamp_ns(msg)
        coverage = (0.0, 0.0, 0.0, 0.0)
        ranges = filter_short_finite_runs(
            normalized_ranges(msg),
            min_contiguous_beams=cli.min_contiguous_beams,
        )
        finite_run = longest_finite_run(ranges)
        depth_healthy = False
        depth_age = float("inf")
        source_skew = float("inf")
        if latest_depth is not None:
            coverage = latest_depth.coverage
            depth_age = now - latest_depth.received_monotonic
            source_skew = abs(scan_stamp_ns - latest_depth.source_stamp_ns) / 1e9
            depth_healthy = bool(
                0.0 <= depth_age <= float(cli.max_depth_age_sec)
                and source_skew <= float(cli.max_source_skew_sec)
                and depth_coverage_is_healthy(
                    coverage,
                    min_valid_ratio=cli.min_valid_ratio,
                    min_zone_ratio=cli.min_zone_ratio,
                )
                and scan_returns_are_healthy(
                    ranges,
                    min_contiguous_beams=cli.min_contiguous_beams,
                )
            )
        try:
            packet = ConeScanPacket(
                stream_id=stream_id,
                sequence=sequence,
                source_stamp_ns=scan_stamp_ns,
                sent_wall_time_ns=time.time_ns(),
                angle_min=msg.angle_min,
                angle_max=msg.angle_max,
                angle_increment=msg.angle_increment,
                time_increment=msg.time_increment,
                scan_time=msg.scan_time,
                range_min=msg.range_min,
                range_max=msg.range_max,
                valid_ratio=coverage[0],
                left_coverage=coverage[1],
                center_coverage=coverage[2],
                right_coverage=coverage[3],
                ranges=ranges,
                depth_healthy=depth_healthy,
            )
            sock.sendto(encode_packet(packet), target)
        except (ConeScanContractError, OSError) as exc:
            send_errors += 1
            if send_errors == 1 or send_errors % 100 == 0:
                node.get_logger().error("cone scan UDP send failed: %s" % exc)
            return
        if cli.log_every > 0 and sequence % cli.log_every == 1:
            node.get_logger().info(
                "sent cone scan seq=%d beams=%d healthy=%s "
                "depth_age=%.3fs skew=%.3fs valid=%.3f finite_run=%d target=%s:%d"
                % (
                    sequence,
                    len(packet.ranges),
                    depth_healthy,
                    depth_age,
                    source_skew,
                    coverage[0],
                    finite_run,
                    cli.host,
                    cli.port,
                )
            )

    node.create_subscription(Image, cli.depth_topic, on_depth, qos)
    node.create_subscription(LaserScan, cli.scan_topic, on_scan, qos)
    node.get_logger().info(
        "cone scan exporter ready | scan=%s depth=%s udp=%s:%d stream=%s"
        % (cli.scan_topic, cli.depth_topic, cli.host, cli.port, stream_id)
    )
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
