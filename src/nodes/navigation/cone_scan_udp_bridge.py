"""Bridge cone scan from Docker to a validated Foxy LaserScan.

By default the node uses the legacy UDP protocol.  When ``enable_dds`` is true
it subscribes directly to the Humble LaserScan/depth topics published by the
cuVSLAM Docker container and performs the same depth-health validation before
publishing ``/cone_obstacle/scan`` and ``/cone_obstacle/health`` on the host.
"""

from __future__ import annotations

import json
import math
import socket
import time
import uuid
from typing import Optional

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image, LaserScan
from std_msgs.msg import String

from nodes.navigation.cone_scan_protocol import (
    ConeScanContractError,
    ConeScanPacket,
    decode_packet,
    depth_coverage_from_image,
    depth_coverage_is_healthy,
    filter_short_finite_runs,
    longest_finite_run,
    scan_observation_is_healthy,
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
        self.declare_parameter("poll_rate_hz", 50.0)
        self.declare_parameter("packet_timeout_sec", 1.0)
        self.declare_parameter("source_max_age_sec", 1.0)
        self.declare_parameter("future_tolerance_sec", 0.10)
        self.declare_parameter("expected_beams", 180)
        self.declare_parameter("min_valid_ratio", 0.05)
        self.declare_parameter("min_zone_ratio", 0.01)
        self.declare_parameter("min_contiguous_beams", 3)
        self.declare_parameter("enable_dds", False)
        self.declare_parameter("source_scan_topic", "/cone_obstacle/scan_humble")
        self.declare_parameter("source_depth_topic", "/camera/depth/image_rect_raw")
        self.declare_parameter("max_rate_hz", 10.0)

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
        self._enable_dds = bool(self.get_parameter("enable_dds").value)
        self._dds_scan_topic = str(self.get_parameter("source_scan_topic").value)
        self._dds_depth_topic = str(self.get_parameter("source_depth_topic").value)
        self._dds_max_rate = max(1.0, float(self.get_parameter("max_rate_hz").value))
        self._dds_rate_guard = max(0.0, 1.0 / self._dds_max_rate - 0.005)
        self._dds_stream_id = uuid.uuid4().hex
        self._dds_sequence = 0
        self._latest_depth = None
        self._invalid_depth = 0
        self._last_depth_processing = float("-inf")
        self._last_scan_send = float("-inf")

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

        if self._enable_dds:
            self._socket = None
            self._create_dds_subscriptions()
            self.get_logger().info(
                "cone scan DDS bridge ready | scan=%s depth=%s frame=%s "
                "expected_beams=%d"
                % (
                    self._dds_scan_topic,
                    self._dds_depth_topic,
                    self._frame_id,
                    self._expected_beams,
                )
            )
        else:
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
                % (
                    bind_target[0],
                    bind_target[1],
                    self._frame_id,
                    self._expected_beams,
                )
            )

    def _create_dds_subscriptions(self) -> None:
        sensor_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
        )
        self.create_subscription(
            LaserScan,
            self._dds_scan_topic,
            self._on_dds_scan,
            sensor_qos,
        )
        self.create_subscription(
            Image,
            self._dds_depth_topic,
            self._on_dds_depth,
            sensor_qos,
        )

    @staticmethod
    def _stamp_ns(msg) -> int:
        return int(msg.header.stamp.sec) * 1_000_000_000 + int(
            msg.header.stamp.nanosec
        )

    @staticmethod
    def _normalized_ranges(msg: LaserScan):
        lower = float(msg.range_min)
        upper = float(msg.range_max)
        result = []
        for value in msg.ranges:
            value = float(value)
            if math.isfinite(value) and lower <= value <= upper:
                result.append(value)
            else:
                result.append(float("inf"))
        return tuple(result)

    def _on_dds_depth(self, msg: Image) -> None:
        now = time.monotonic()
        if now - self._last_depth_processing < self._dds_rate_guard:
            return
        self._last_depth_processing = now
        try:
            if str(msg.encoding) not in ("16UC1", "mono16"):
                raise ConeScanContractError(
                    "unsupported depth encoding: %s" % msg.encoding
                )
            coverage = depth_coverage_from_image(
                bytes(msg.data),
                int(msg.width),
                int(msg.height),
                int(msg.step),
            )
            self._latest_depth = {
                "source_stamp_ns": self._stamp_ns(msg),
                "received_monotonic": now,
                "coverage": coverage,
            }
        except ConeScanContractError as exc:
            self._latest_depth = None
            self._invalid_depth += 1
            if self._invalid_depth == 1 or self._invalid_depth % 100 == 0:
                self.get_logger().error(
                    "invalid DDS depth health frame: %s" % exc
                )

    def _on_dds_scan(self, msg: LaserScan) -> None:
        now = time.monotonic()
        if now - self._last_scan_send < self._dds_rate_guard:
            return
        self._last_scan_send = now
        self._received += 1
        self._last_datagram_time = now
        self._dds_sequence += 1

        scan_stamp_ns = self._stamp_ns(msg)
        source_age = (time.time_ns() - scan_stamp_ns) / 1e9
        if source_age < -self._future_tolerance:
            self._publish_health_fields(
                False,
                "source timestamp is in the future",
                source_stamp_ns=scan_stamp_ns,
                source_age_ms=source_age * 1000.0,
            )
            return
        if source_age > self._source_max_age:
            self._publish_health_fields(
                False,
                "source timestamp is stale",
                source_stamp_ns=scan_stamp_ns,
                source_age_ms=source_age * 1000.0,
            )
            return
        if (
            self._expected_beams > 0
            and len(msg.ranges) != self._expected_beams
        ):
            self._publish_health_fields(
                False,
                "beam count %d does not match expected %d"
                % (len(msg.ranges), self._expected_beams),
                source_stamp_ns=scan_stamp_ns,
                source_age_ms=source_age * 1000.0,
            )
            return

        raw_ranges = self._normalized_ranges(msg)
        ranges = filter_short_finite_runs(
            raw_ranges,
            min_contiguous_beams=self._min_contiguous_beams,
        )
        finite_run = longest_finite_run(ranges)
        coverage = (0.0, 0.0, 0.0, 0.0)
        depth_age = float("inf")
        source_skew = float("inf")
        depth_healthy = False
        if self._latest_depth is not None:
            coverage = self._latest_depth["coverage"]
            depth_age = now - self._latest_depth["received_monotonic"]
            source_skew = abs(
                scan_stamp_ns - self._latest_depth["source_stamp_ns"]
            ) / 1e9
            depth_healthy = bool(
                0.0 <= depth_age <= 0.25
                and source_skew <= 0.15
                and depth_coverage_is_healthy(
                    coverage,
                    min_valid_ratio=self._min_valid_ratio,
                    min_zone_ratio=self._min_zone_ratio,
                )
                and scan_observation_is_healthy(
                    ranges,
                    min_contiguous_beams=self._min_contiguous_beams,
                )
            )

        reason = "ready"
        if not depth_healthy:
            if self._latest_depth is None:
                reason = "depth image unavailable"
            elif depth_age > 0.25 or source_skew > 0.15:
                reason = "depth image is stale or unsynchronized"
            elif not depth_coverage_is_healthy(
                coverage,
                min_valid_ratio=self._min_valid_ratio,
                min_zone_ratio=self._min_zone_ratio,
            ):
                reason = "decimated depth coverage is unhealthy"
            elif not scan_observation_is_healthy(
                ranges,
                min_contiguous_beams=self._min_contiguous_beams,
            ):
                reason = "scan has only isolated or short finite returns"

        if not depth_healthy:
            self._publish_health_fields(
                False,
                reason,
                source_stamp_ns=scan_stamp_ns,
                source_age_ms=max(0.0, source_age * 1000.0),
                coverage=coverage,
                finite_run=finite_run,
            )
            return

        out = LaserScan()
        out.header.stamp.sec = scan_stamp_ns // 1_000_000_000
        out.header.stamp.nanosec = scan_stamp_ns % 1_000_000_000
        out.header.frame_id = self._frame_id
        out.angle_min = float(msg.angle_min)
        out.angle_max = float(msg.angle_max)
        out.angle_increment = float(msg.angle_increment)
        out.time_increment = float(msg.time_increment)
        out.scan_time = float(msg.scan_time)
        out.range_min = float(msg.range_min)
        out.range_max = float(msg.range_max)
        out.ranges = list(ranges)
        self._scan_publisher.publish(out)
        self._publish_health_fields(
            True,
            "ready",
            source_stamp_ns=scan_stamp_ns,
            source_age_ms=max(0.0, source_age * 1000.0),
            coverage=coverage,
            finite_run=finite_run,
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

    def _publish_health_fields(
        self,
        healthy: bool,
        reason: str,
        source_stamp_ns: int = 0,
        source_age_ms: Optional[float] = None,
        coverage=(0.0, 0.0, 0.0, 0.0),
        finite_run: int = 0,
    ) -> None:
        status = {
            "healthy": bool(healthy),
            "reason": str(reason),
            "stream_id": self._dds_stream_id,
            "sequence": self._dds_sequence,
            "source_stamp_ns": int(source_stamp_ns),
            "source_age_ms": source_age_ms,
            "valid_ratio": coverage[0],
            "left_coverage": coverage[1],
            "center_coverage": coverage[2],
            "right_coverage": coverage[3],
            "longest_finite_run": int(finite_run),
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
        if not scan_observation_is_healthy(
            packet.ranges,
            min_contiguous_beams=self._min_contiguous_beams,
        ):
            self._reject("scan has only isolated or short finite returns", packet)
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
        if self._socket is not None:
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
