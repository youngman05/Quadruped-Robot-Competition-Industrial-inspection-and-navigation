#!/usr/bin/env python3
"""Receive one fresh, healthy production cone-scan UDP packet."""

from __future__ import annotations

import argparse
import json
import socket
import time

from nodes.navigation.cone_scan_protocol import (
    ConeScanContractError,
    decode_packet,
)


def receive_packet(host: str, port: int, timeout_sec: float):
    deadline = time.monotonic() + max(0.1, float(timeout_sec))
    last_error = "no datagram received"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((str(host), int(port)))
        while time.monotonic() < deadline:
            sock.settimeout(min(0.5, max(0.01, deadline - time.monotonic())))
            try:
                raw, _ = sock.recvfrom(65535)
            except socket.timeout:
                continue
            try:
                packet = decode_packet(raw)
            except ConeScanContractError as exc:
                last_error = str(exc)
                continue
            age_ms = (time.time_ns() - packet.sent_wall_time_ns) / 1e6
            if not 0.0 <= age_ms <= 1000.0:
                last_error = "packet wall age is %.1f ms" % age_ms
                continue
            if not packet.depth_healthy:
                last_error = "packet depth health is false"
                continue
            return packet, age_ms
    raise TimeoutError(last_error)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=19002)
    parser.add_argument("--timeout-sec", type=float, default=8.0)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        packet, age_ms = receive_packet(args.host, args.port, args.timeout_sec)
    except (OSError, TimeoutError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(
        json.dumps(
            {
                "passed": True,
                "stream_id": packet.stream_id,
                "sequence": packet.sequence,
                "beam_count": packet.beam_count,
                "depth_healthy": packet.depth_healthy,
                "packet_age_ms": round(age_ms, 3),
                "valid_ratio": round(packet.valid_ratio, 6),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
