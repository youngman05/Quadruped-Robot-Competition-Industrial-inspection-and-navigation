"""Bounded binary contract for latest-only cone LaserScan UDP transport."""

from __future__ import annotations

import math
import struct
import uuid
import zlib
from dataclasses import dataclass
from typing import Iterable, Tuple


MAGIC = b"CNS1"
PROTOCOL_VERSION = 1
FLAG_DEPTH_HEALTHY = 0x01
MAX_BEAMS = 2048

# magic, version, flags, beams, seq, source stamp, send time, stream UUID,
# seven LaserScan scalars, then four depth-health coverage ratios.
HEADER_STRUCT = struct.Struct("!4sBBHQQQ16s11f")
CRC_STRUCT = struct.Struct("!I")


class ConeScanContractError(ValueError):
    """Raised when a cone scan datagram violates the transport contract."""


def _finite_float(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ConeScanContractError("%s must be finite" % name)
    return result


def _ratio(value: float, name: str) -> float:
    result = _finite_float(value, name)
    if not 0.0 <= result <= 1.0:
        raise ConeScanContractError("%s must be in [0, 1]" % name)
    return result


def normalize_stream_id(value: str) -> str:
    try:
        return uuid.UUID(str(value)).hex
    except (AttributeError, TypeError, ValueError) as exc:
        raise ConeScanContractError("stream_id must be a UUID") from exc


@dataclass(frozen=True)
class ConeScanPacket:
    stream_id: str
    sequence: int
    source_stamp_ns: int
    sent_wall_time_ns: int
    angle_min: float
    angle_max: float
    angle_increment: float
    time_increment: float
    scan_time: float
    range_min: float
    range_max: float
    valid_ratio: float
    left_coverage: float
    center_coverage: float
    right_coverage: float
    ranges: Tuple[float, ...]
    depth_healthy: bool

    @property
    def beam_count(self) -> int:
        return len(self.ranges)


def _validated_packet(packet: ConeScanPacket) -> ConeScanPacket:
    stream_id = normalize_stream_id(packet.stream_id)
    sequence = int(packet.sequence)
    source_stamp_ns = int(packet.source_stamp_ns)
    sent_wall_time_ns = int(packet.sent_wall_time_ns)
    if sequence < 1:
        raise ConeScanContractError("sequence must be positive")
    if source_stamp_ns < 1:
        raise ConeScanContractError("source_stamp_ns must be positive")
    if sent_wall_time_ns < 1:
        raise ConeScanContractError("sent_wall_time_ns must be positive")

    angle_min = _finite_float(packet.angle_min, "angle_min")
    angle_max = _finite_float(packet.angle_max, "angle_max")
    angle_increment = _finite_float(packet.angle_increment, "angle_increment")
    time_increment = _finite_float(packet.time_increment, "time_increment")
    scan_time = _finite_float(packet.scan_time, "scan_time")
    range_min = _finite_float(packet.range_min, "range_min")
    range_max = _finite_float(packet.range_max, "range_max")
    if angle_max <= angle_min:
        raise ConeScanContractError("angle_max must be greater than angle_min")
    if angle_increment <= 0.0:
        raise ConeScanContractError("angle_increment must be positive")
    if time_increment < 0.0 or scan_time < 0.0:
        raise ConeScanContractError("scan timing must be non-negative")
    if range_min < 0.0 or range_max <= range_min:
        raise ConeScanContractError("invalid scan range bounds")

    ranges = tuple(float(value) for value in packet.ranges)
    if not 2 <= len(ranges) <= MAX_BEAMS:
        raise ConeScanContractError("beam count must be in [2, %d]" % MAX_BEAMS)
    for value in ranges:
        if math.isnan(value) or value == float("-inf"):
            raise ConeScanContractError("ranges cannot contain NaN or -inf")
        if math.isfinite(value) and not range_min <= value <= range_max:
            raise ConeScanContractError("finite range is outside declared bounds")

    return ConeScanPacket(
        stream_id=stream_id,
        sequence=sequence,
        source_stamp_ns=source_stamp_ns,
        sent_wall_time_ns=sent_wall_time_ns,
        angle_min=angle_min,
        angle_max=angle_max,
        angle_increment=angle_increment,
        time_increment=time_increment,
        scan_time=scan_time,
        range_min=range_min,
        range_max=range_max,
        valid_ratio=_ratio(packet.valid_ratio, "valid_ratio"),
        left_coverage=_ratio(packet.left_coverage, "left_coverage"),
        center_coverage=_ratio(packet.center_coverage, "center_coverage"),
        right_coverage=_ratio(packet.right_coverage, "right_coverage"),
        ranges=ranges,
        depth_healthy=bool(packet.depth_healthy),
    )


def encode_packet(packet: ConeScanPacket) -> bytes:
    packet = _validated_packet(packet)
    flags = FLAG_DEPTH_HEALTHY if packet.depth_healthy else 0
    header = HEADER_STRUCT.pack(
        MAGIC,
        PROTOCOL_VERSION,
        flags,
        packet.beam_count,
        packet.sequence,
        packet.source_stamp_ns,
        packet.sent_wall_time_ns,
        uuid.UUID(packet.stream_id).bytes,
        packet.angle_min,
        packet.angle_max,
        packet.angle_increment,
        packet.time_increment,
        packet.scan_time,
        packet.range_min,
        packet.range_max,
        packet.valid_ratio,
        packet.left_coverage,
        packet.center_coverage,
        packet.right_coverage,
    )
    ranges = struct.pack("!%df" % packet.beam_count, *packet.ranges)
    body = header + ranges
    return body + CRC_STRUCT.pack(zlib.crc32(body) & 0xFFFFFFFF)


def decode_packet(data: bytes) -> ConeScanPacket:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ConeScanContractError("datagram must be bytes")
    raw = bytes(data)
    if len(raw) < HEADER_STRUCT.size + CRC_STRUCT.size:
        raise ConeScanContractError("datagram is truncated")
    expected_crc = CRC_STRUCT.unpack(raw[-CRC_STRUCT.size :])[0]
    actual_crc = zlib.crc32(raw[:-CRC_STRUCT.size]) & 0xFFFFFFFF
    if actual_crc != expected_crc:
        raise ConeScanContractError("CRC mismatch")

    values = HEADER_STRUCT.unpack(raw[: HEADER_STRUCT.size])
    magic, version, flags, beam_count = values[:4]
    if magic != MAGIC:
        raise ConeScanContractError("invalid magic")
    if version != PROTOCOL_VERSION:
        raise ConeScanContractError("unsupported protocol version")
    if flags & ~FLAG_DEPTH_HEALTHY:
        raise ConeScanContractError("unsupported packet flags")
    if not 2 <= beam_count <= MAX_BEAMS:
        raise ConeScanContractError("invalid beam count")
    expected_size = HEADER_STRUCT.size + beam_count * 4 + CRC_STRUCT.size
    if len(raw) != expected_size:
        raise ConeScanContractError("datagram length does not match beam count")

    range_start = HEADER_STRUCT.size
    ranges = struct.unpack(
        "!%df" % beam_count,
        raw[range_start : range_start + beam_count * 4],
    )
    return _validated_packet(
        ConeScanPacket(
            stream_id=uuid.UUID(bytes=values[7]).hex,
            sequence=values[4],
            source_stamp_ns=values[5],
            sent_wall_time_ns=values[6],
            angle_min=values[8],
            angle_max=values[9],
            angle_increment=values[10],
            time_increment=values[11],
            scan_time=values[12],
            range_min=values[13],
            range_max=values[14],
            valid_ratio=values[15],
            left_coverage=values[16],
            center_coverage=values[17],
            right_coverage=values[18],
            ranges=ranges,
            depth_healthy=bool(flags & FLAG_DEPTH_HEALTHY),
        )
    )


def depth_coverage_from_image(
    data: bytes,
    width: int,
    height: int,
    step: int,
) -> Tuple[float, float, float, float]:
    """Return valid uint16 depth ratios for the full image and three columns."""
    width = int(width)
    height = int(height)
    step = int(step)
    if width < 3 or height < 1 or step < width * 2:
        raise ConeScanContractError("invalid uint16 depth image dimensions")
    raw = memoryview(data).cast("B")
    if len(raw) < height * step:
        raise ConeScanContractError("depth image data is truncated")

    edges = (0, width // 3, (2 * width) // 3, width)
    counts = [0, 0, 0]
    totals = [
        height * (edges[index + 1] - edges[index]) for index in range(3)
    ]
    for row in range(height):
        row_offset = row * step
        for zone in range(3):
            for column in range(edges[zone], edges[zone + 1]):
                offset = row_offset + column * 2
                if raw[offset] != 0 or raw[offset + 1] != 0:
                    counts[zone] += 1
    total_valid = sum(counts)
    total_pixels = width * height
    return (
        total_valid / float(total_pixels),
        counts[0] / float(totals[0]),
        counts[1] / float(totals[1]),
        counts[2] / float(totals[2]),
    )


def depth_coverage_is_healthy(
    coverage: Iterable[float],
    min_valid_ratio: float = 0.05,
    min_zone_ratio: float = 0.01,
) -> bool:
    values = tuple(float(value) for value in coverage)
    if len(values) != 4 or not all(math.isfinite(value) for value in values):
        return False
    valid_ratio, left, center, right = values
    return bool(
        valid_ratio >= float(min_valid_ratio)
        and min(left, center, right) >= float(min_zone_ratio)
    )


def longest_finite_run(ranges: Iterable[float]) -> int:
    longest = 0
    current = 0
    for value in ranges:
        if math.isfinite(float(value)):
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def filter_short_finite_runs(
    ranges: Iterable[float],
    min_contiguous_beams: int = 3,
) -> Tuple[float, ...]:
    values = tuple(float(value) for value in ranges)
    minimum = max(2, int(min_contiguous_beams))
    filtered = list(values)
    start = None
    for index in range(len(values) + 1):
        finite = index < len(values) and math.isfinite(values[index])
        if finite and start is None:
            start = index
        if not finite and start is not None:
            if index - start < minimum:
                filtered[start:index] = [float("inf")] * (index - start)
            start = None
    return tuple(filtered)


def scan_returns_are_healthy(
    ranges: Iterable[float],
    min_contiguous_beams: int = 3,
) -> bool:
    """Reject empty scans and isolated flying points."""
    return longest_finite_run(ranges) >= max(2, int(min_contiguous_beams))
