#!/usr/bin/env python3
"""Send deterministic cone-scan UDP scenarios on an isolated test port."""

from __future__ import annotations

import argparse
import ipaddress
import json
import socket
import sys
import time
import uuid
from pathlib import Path

try:
    from nodes.navigation.cone_scan_synthetic import SCENARIOS, scenario_frame
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from nodes.navigation.cone_scan_synthetic import SCENARIOS, scenario_frame


DEFAULT_PORT = 19012
PRODUCTION_PORT = 19002


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, default="healthy-cone")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--count", type=int)
    parser.add_argument("--interval-sec", type=float, default=0.10)
    parser.add_argument("--start-sequence", type=int, default=1)
    parser.add_argument("--stream-id")
    parser.add_argument("--silence-sec", type=float, default=0.35)
    return parser.parse_args(argv)


def validate_target(args):
    try:
        address = ipaddress.ip_address(str(args.host))
    except ValueError as exc:
        raise SystemExit("--host must be a numeric IPv4 loopback address") from exc
    if address.version != 4 or not address.is_loopback:
        raise SystemExit("synthetic sender host must be IPv4 loopback")
    if int(args.port) == PRODUCTION_PORT or not 1024 <= int(args.port) <= 65535:
        raise SystemExit("synthetic sender requires a valid non-production port")


def _send(sock, target, frame, sent):
    if frame.payload is None:
        return
    sock.sendto(frame.payload, target)
    sent.append(
        {
            "scenario": frame.scenario,
            "stream_id": frame.stream_id,
            "sequence": frame.sequence,
            "bytes": len(frame.payload),
            "expected_scan": frame.expected_scan,
            "expected_health": frame.expected_health,
        }
    )


def main(argv=None) -> int:
    args = parse_args(argv)
    validate_target(args)
    stream_id = uuid.UUID(args.stream_id).hex if args.stream_id else uuid.uuid4().hex
    target = (str(args.host), int(args.port))
    sent = []
    started = time.time_ns()

    if args.scenario == "silence":
        time.sleep(max(0.0, float(args.silence_sec)))
    else:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            if args.scenario == "sequence-regression":
                first = scenario_frame(
                    "clear",
                    stream_id=stream_id,
                    sequence=max(2, int(args.start_sequence) + 1),
                )
                _send(sock, target, first, sent)
                time.sleep(max(0.0, float(args.interval_sec)))
                regressed = scenario_frame(
                    "sequence-regression",
                    stream_id=stream_id,
                    sequence=max(1, int(args.start_sequence)),
                )
                _send(sock, target, regressed, sent)
            else:
                default_count = 32 if args.scenario == "backlog" else 3 if args.scenario == "stream-restart" else 1
                count = max(1, int(args.count if args.count is not None else default_count))
                interval = 0.0 if args.scenario == "backlog" else max(0.0, float(args.interval_sec))
                for offset in range(count):
                    frame = scenario_frame(
                        args.scenario,
                        stream_id=stream_id,
                        sequence=max(1, int(args.start_sequence) + offset),
                    )
                    _send(sock, target, frame, sent)
                    if interval > 0.0 and offset + 1 < count:
                        time.sleep(interval)

    summary = {
        "schema": "cone_scan_synthetic_sender/v1",
        "scenario": args.scenario,
        "target": "%s:%d" % target,
        "started_wall_time_ns": started,
        "finished_wall_time_ns": time.time_ns(),
        "sent_count": len(sent),
        "frames": sent,
    }
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
