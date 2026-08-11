"""Receive latest-only cone scan UDP and publish a validated Foxy LaserScan."""

from __future__ import annotations

import json
import socket
import time
from typing import Optional

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String

from nodes.navigation.cone_scan_protocol import (
    ConeScanContractError,
    ConeScanPacket,
    decode_packet,
    depth_coverage_is_healthy,
    longest_finite_run,
    scan_returns_are_healthy,
)

try:
    from rclpy.qos import HistoryPolicy
except ImportError:
    from rclpy.qos import QoSHistoryPolicy as HistoryPolicy


class ConeScanUdpBridge(Node):
    def __init__(self) -> None:
        super().__init__("cone_scan_udp_bridge")
        self.declare_parameter("bind_host", "127.0.0.1")
        self.declare_parameter("port", 19002)
        self.declare_parameter("scan_topic", "/cone_obstacle/scan")
        self.declare_parameter("health_topic", "/cone_obstacle/health")
        self.declare_parameter("frame_id", "base_link")
        self.declare_parameter("poll_rate_hz", 100.0)
        self.declare_parameter("packet_timeout_sec", 0.25)
        self.declare_parameter("source_max_age_sec", 0.25)
        self.declare_parameter("future_tolerance_sec", 0.05)
        self.declare_parameter("expected_beams", 180)
        self.declare_parameter("min_valid_ratio", 0.05)
        self.declare_parameter("min_zone_ratio", 0.01)
        self.declare_parameter("min_contiguous_beams", 3)

        self._frame_id = str(self.get_parameter("frame_id").value)
        self._packet_timeout = max(
            0.05, float(self.get_parameter("packet_timeout_sec").value)
        )
        self._source_max_age = max(
            0.05, float(self.get_parameter("source_max_age_sec").value)
        )
        self._future_tolerance = max(
            0.0, float(self.get_parameter("future_tolerance_sec").value)
        )
        self._expected_beams = int(self.get_parameter("expected_beams").value)
        self._min_valid_ratio = float(
            self.get_parameter("min_valid_ratio").value
        )
        self._min_zone_ratio = float(self.get_parameter("min_zone_ratio").value)
        self._min_contiguous_beams = max(
            2, int(self.get_parameter("min_contiguous_beams").value)
        )
        self._last_stream_id = ""
        self._last_sequence = 0
        self._last_datagram_time: Optional[float] = None
        self._last_health_publish_time = float("-inf")
        self._healthy = False
        self._received = 0
        self._drained = 0
        self._invalid = 0

        sensor_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
        )
        health_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
        )
        self._scan_publisher = self.create_publisher(
            LaserScan,
            str(self.get_parameter("scan_topic").value),
            sensor_qos,
        )
        self._health_publisher = self.create_publisher(
            String,
            str(self.get_parameter("health_topic").value),
            health_qos,
        )

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 64 * 1024)
        bind_target = (
            str(self.get_parameter("bind_host").value),
            int(self.get_parameter("port").value),
        )
        self._socket.bind(bind_target)
        self._socket.setblocking(False)
        rate = max(20.0, float(self.get_parameter("poll_rate_hz").value))
        self.create_timer(1.0 / rate, self._poll)
        self.get_logger().info(
            "cone scan UDP bridge ready | udp=%s:%d frame=%s expected_beams=%d"
            % (bind_target[0], bind_target[1], self._frame_id, self._expected_beams)
        )

    def _publish_health(
        self,
        healthy: bool,
        reason: str,
        packet: Optional[ConeScanPacket] = None,
        source_age_ms: Optional[float] = None,
    ) -> None:
        status = {
            "healthy": bool(healthy),
            "reason": str(reason),
            "stream_id": packet.stream_id if packet is not None else self._last_stream_id,
            "sequence": packet.sequence if packet is not None else self._last_sequence,
            "source_stamp_ns": packet.source_stamp_ns if packet is not None else 0,
            "source_age_ms": source_age_ms,
            "valid_ratio": packet.valid_ratio if packet is not None else 0.0,
            "left_coverage": packet.left_coverage if packet is not None else 0.0,
            "center_coverage": packet.center_coverage if packet is not None else 0.0,
            "right_coverage": packet.right_coverage if packet is not None else 0.0,
            "longest_finite_run": (
                longest_finite_run(packet.ranges) if packet is not None else 0
            ),
            "received": self._received,
            "drained_old": self._drained,
            "invalid": self._invalid,
        }
        msg = String()
        msg.data = json.dumps(status, sort_keys=True, separators=(",", ":"))
        self._health_publisher.publish(msg)
        self._healthy = bool(healthy)
        self._last_health_publish_time = time.monotonic()

    def _reject(self, reason: str, packet: Optional[ConeScanPacket] = None) -> None:
        self._invalid += 1
        self._publish_health(False, reason, packet)
        if self._invalid == 1 or self._invalid % 100 == 0:
            self.get_logger().error("rejected cone scan UDP packet: %s" % reason)

    def _publish_scan(self, packet: ConeScanPacket) -> None:
        msg = LaserScan()
        msg.header.stamp.sec = packet.source_stamp_ns // 1_000_000_000
        msg.header.stamp.nanosec = packet.source_stamp_ns % 1_000_000_000
        msg.header.frame_id = self._frame_id
        msg.angle_min = packet.angle_min
        msg.angle_max = packet.angle_max
        msg.angle_increment = packet.angle_increment
        msg.time_increment = packet.time_increment
        msg.scan_time = packet.scan_time
        msg.range_min = packet.range_min
        msg.range_max = packet.range_max
        msg.ranges = list(packet.ranges)
        self._scan_publisher.publish(msg)

    def _accept_latest(self, raw: bytes) -> None:
        try:
            packet = decode_packet(raw)
        except ConeScanContractError as exc:
            self._reject(str(exc))
            return
        if self._expected_beams > 0 and packet.beam_count != self._expected_beams:
            self._reject(
                "beam count %d does not match expected %d"
                % (packet.beam_count, self._expected_beams),
                packet,
            )
            return
        if packet.stream_id != self._last_stream_id:
            self._last_stream_id = packet.stream_id
            self._last_sequence = 0
        if packet.sequence <= self._last_sequence:
            self._reject("sequence did not advance", packet)
            return
        self._last_sequence = packet.sequence

        source_age = (time.time_ns() - packet.source_stamp_ns) / 1e9
        if source_age < -self._future_tolerance:
            self._reject("source timestamp is in the future", packet)
            return
        if source_age > self._source_max_age:
            self._reject("source timestamp is stale", packet)
            return
        coverage = (
            packet.valid_ratio,
            packet.left_coverage,
            packet.center_coverage,
            packet.right_coverage,
        )
        if not depth_coverage_is_healthy(
            coverage,
            min_valid_ratio=self._min_valid_ratio,
            min_zone_ratio=self._min_zone_ratio,
        ):
            self._reject("decimated depth coverage is unhealthy", packet)
            return
        if not scan_returns_are_healthy(
            packet.ranges,
            min_contiguous_beams=self._min_contiguous_beams,
        ):
            self._reject("scan has no contiguous obstacle returns", packet)
            return
        if not packet.depth_healthy:
            self._reject("source health flag is false", packet)
            return
        self._publish_scan(packet)
        self._publish_health(True, "ready", packet, source_age * 1000.0)

    def _poll(self) -> None:
        latest = None
        drained = 0
        while True:
            try:
                data, _ = self._socket.recvfrom(65535)
            except (BlockingIOError, InterruptedError):
                break
            latest = data
            drained += 1
        if latest is not None:
            self._received += drained
            self._drained += max(0, drained - 1)
            self._last_datagram_time = time.monotonic()
            self._accept_latest(latest)
            return
        now = time.monotonic()
        if (
            self._last_datagram_time is None
            or now - self._last_datagram_time > self._packet_timeout
        ):
            if self._healthy or now - self._last_health_publish_time >= 0.2:
                self._publish_health(False, "cone scan UDP stream is stale")

    def destroy_node(self) -> bool:
        self._publish_health(False, "cone scan UDP bridge stopped")
        self._socket.close()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ConeScanUdpBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
