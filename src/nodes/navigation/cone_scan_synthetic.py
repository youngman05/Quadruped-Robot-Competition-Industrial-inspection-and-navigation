"""ROS-independent deterministic cone-scan scenarios for L2/L3 acceptance."""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass
from typing import Optional, Tuple

from nodes.navigation.cone_scan_protocol import ConeScanPacket, encode_packet


BEAM_COUNT = 180
ANGLE_MIN = -math.pi / 2.0
ANGLE_MAX = math.pi / 2.0
ANGLE_INCREMENT = (ANGLE_MAX - ANGLE_MIN) / float(BEAM_COUNT - 1)
RANGE_MIN = 0.20
RANGE_MAX = 5.00
HEALTHY_COVERAGE = (0.80, 0.80, 0.80, 0.80)
SCENARIOS = (
    "healthy-cone",
    "clear",
    "isolated-point",
    "short-run",
    "unhealthy-depth",
    "stale",
    "future",
    "bad-crc",
    "sequence-regression",
    "backlog",
    "silence",
    "stream-restart",
)


@dataclass(frozen=True)
class SyntheticFrame:
    scenario: str
    stream_id: str
    sequence: int
    payload: Optional[bytes]
    expected_scan: bool
    expected_health: bool
    note: str


def _stream(value: Optional[str]) -> str:
    return uuid.UUID(str(value)).hex if value else uuid.uuid4().hex


def _ranges(scenario: str) -> Tuple[float, ...]:
    values = [float("inf")] * BEAM_COUNT
    if scenario == "healthy-cone" or scenario == "backlog" or scenario == "stream-restart":
        for index in range(86, 96):
            values[index] = 0.75 + 0.01 * abs(index - 90)
    elif scenario == "isolated-point":
        values[90] = 0.75
    elif scenario == "short-run":
        values[90] = 0.75
        values[91] = 0.76
    elif scenario in ("clear", "unhealthy-depth", "stale", "future", "bad-crc", "sequence-regression"):
        pass
    else:
        raise ValueError("unsupported synthetic scenario: %s" % scenario)
    return tuple(values)


def scenario_packet(
    scenario: str,
    *,
    stream_id: Optional[str] = None,
    sequence: int = 1,
    now_ns: Optional[int] = None,
) -> ConeScanPacket:
    """Build one deterministic packet for a named scenario."""
    scenario = str(scenario)
    if scenario not in SCENARIOS or scenario in ("silence", "bad-crc", "sequence-regression"):
        if scenario == "silence":
            raise ValueError("silence has no packet")
        if scenario == "sequence-regression":
            scenario = "clear"
        elif scenario == "bad-crc":
            scenario = "clear"
        elif scenario not in SCENARIOS:
            raise ValueError("unsupported synthetic scenario: %s" % scenario)
    now_ns = int(now_ns if now_ns is not None else time.time_ns())
    source_stamp_ns = now_ns
    if scenario == "stale":
        source_stamp_ns -= 1_000_000_000
    elif scenario == "future":
        source_stamp_ns += 1_000_000_000
    coverage = HEALTHY_COVERAGE
    depth_healthy = True
    if scenario == "unhealthy-depth":
        coverage = (0.01, 0.0, 0.01, 0.0)
        depth_healthy = False
    if scenario in ("isolated-point", "short-run"):
        # The bridge independently checks finite runs. Keeping the source flag
        # healthy proves that the geometric filter, rather than depth coverage,
        # is what rejects the observation.
        depth_healthy = True
    return ConeScanPacket(
        stream_id=_stream(stream_id),
        sequence=max(1, int(sequence)),
        source_stamp_ns=max(1, source_stamp_ns),
        sent_wall_time_ns=max(1, now_ns),
        angle_min=ANGLE_MIN,
        angle_max=ANGLE_MAX,
        angle_increment=ANGLE_INCREMENT,
        time_increment=0.0,
        scan_time=0.1,
        range_min=RANGE_MIN,
        range_max=RANGE_MAX,
        valid_ratio=coverage[0],
        left_coverage=coverage[1],
        center_coverage=coverage[2],
        right_coverage=coverage[3],
        ranges=_ranges(scenario),
        depth_healthy=depth_healthy,
    )


def corrupt_crc(payload: bytes) -> bytes:
    """Corrupt one body byte while preserving the old CRC."""
    if len(payload) < 8:
        raise ValueError("payload is too short to corrupt")
    data = bytearray(payload)
    data[-8] ^= 0x01
    return bytes(data)


def scenario_frame(
    scenario: str,
    *,
    stream_id: Optional[str] = None,
    sequence: int = 1,
    now_ns: Optional[int] = None,
) -> SyntheticFrame:
    """Return an encoded frame and the expected bridge-level outcome."""
    if scenario == "silence":
        return SyntheticFrame(
            scenario=scenario,
            stream_id=_stream(stream_id),
            sequence=int(sequence),
            payload=None,
            expected_scan=False,
            expected_health=False,
            note="send nothing; bridge must fail closed after timeout",
        )
    packet = scenario_packet(
        scenario,
        stream_id=stream_id,
        sequence=sequence,
        now_ns=now_ns,
    )
    payload = encode_packet(packet)
    if scenario == "bad-crc":
        payload = corrupt_crc(payload)
    expected_health = scenario in ("healthy-cone", "clear", "backlog", "stream-restart")
    expected_scan = expected_health
    if scenario in ("isolated-point", "short-run", "unhealthy-depth", "stale", "future", "sequence-regression", "bad-crc"):
        expected_scan = False
        expected_health = False
    return SyntheticFrame(
        scenario=scenario,
        stream_id=packet.stream_id,
        sequence=packet.sequence,
        payload=payload,
        expected_scan=expected_scan,
        expected_health=expected_health,
        note=(
            "healthy clear-space observation"
            if scenario == "clear"
            else "healthy contiguous cone return"
            if scenario in ("healthy-cone", "backlog", "stream-restart")
            else "expected fail-closed rejection"
        ),
    )


def healthy_frame(
    *, stream_id: Optional[str] = None, sequence: int = 1, clear: bool = False
) -> SyntheticFrame:
    """Small convenience helper used by the L3 probe."""
    return scenario_frame(
        "clear" if clear else "healthy-cone",
        stream_id=stream_id,
        sequence=sequence,
    )
