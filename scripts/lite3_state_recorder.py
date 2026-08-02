#!/usr/bin/env python3
"""Read-only recorder for Lite3 motion-controller UDP state packets.

The official Lite3 ROS driver receives packed C++ structs on UDP port 43897.
This tool never sends packets. It records RobotState (code 2305) and
HandleState (code 2309) so a motion command can be verified independently of
camera odometry.
"""

from __future__ import annotations

import argparse
import csv
import json
import socket
import struct
import sys
import time
from collections import Counter
from typing import Any, Dict, Optional, Tuple


ROBOT_STATE_CODE = 2305
HANDLE_STATE_CODE = 2309
# The Lite3 motion host sends a 212-byte RobotStateReceived packet in practice.
# RobotState's trailing mixed bool/integer fields use the packed wire ABI even
# though the upstream header only applies pack(4) explicitly to the wrapper.
ROBOT_STATE_PACKET_SIZE = 212
HANDLE_STATE_PACKET_SIZE = 60

CSV_FIELDS = [
    "host_time",
    "elapsed_sec",
    "sender_ip",
    "sender_port",
    "packet_len",
    "code",
    "size",
    "cons_code",
    "kind",
    "rpy_roll_deg",
    "rpy_pitch_deg",
    "rpy_yaw_deg",
    "rpy_vel_x",
    "rpy_vel_y",
    "rpy_vel_z",
    "pos_world_x",
    "pos_world_y",
    "pos_world_z",
    "vel_world_x",
    "vel_world_y",
    "vel_world_z",
    "vel_body_x",
    "vel_body_y",
    "vel_body_z",
    "robot_basic_state",
    "robot_gait_state",
    "robot_motion_state",
    "battery_level",
    "left_axis_forward",
    "left_axis_side",
    "right_axis_yaw",
    "goal_vel_forward",
    "goal_vel_side",
    "goal_vel_yaw",
]


def decode_header(packet: bytes) -> Tuple[int, int, int]:
    if len(packet) < 12:
        raise ValueError("packet is shorter than the 12-byte Lite3 header")
    return struct.unpack_from("<iii", packet, 0)


def decode_robot_state(packet: bytes) -> Dict[str, Any]:
    if len(packet) != ROBOT_STATE_PACKET_SIZE:
        raise ValueError(
            "RobotState packet must be {} bytes, got {}".format(
                ROBOT_STATE_PACKET_SIZE, len(packet)
            )
        )
    code, size, cons_code = decode_header(packet)
    if code != ROBOT_STATE_CODE:
        raise ValueError("RobotState packet has unexpected code {}".format(code))

    # Current Lite3 firmware omits robot_policy_state from the public header's
    # layout. The 200-byte payload starts with two ints, then pack(4) doubles.
    return {
        "code": code,
        "size": size,
        "cons_code": cons_code,
        "kind": "robot_state",
        "robot_basic_state": struct.unpack_from("<i", packet, 12)[0],
        "robot_gait_state": struct.unpack_from("<i", packet, 16)[0],
        "rpy_roll_deg": struct.unpack_from("<d", packet, 20)[0],
        "rpy_pitch_deg": struct.unpack_from("<d", packet, 28)[0],
        "rpy_yaw_deg": struct.unpack_from("<d", packet, 36)[0],
        "rpy_vel_x": struct.unpack_from("<d", packet, 44)[0],
        "rpy_vel_y": struct.unpack_from("<d", packet, 52)[0],
        "rpy_vel_z": struct.unpack_from("<d", packet, 60)[0],
        "pos_world_x": struct.unpack_from("<d", packet, 92)[0],
        "pos_world_y": struct.unpack_from("<d", packet, 100)[0],
        "pos_world_z": struct.unpack_from("<d", packet, 108)[0],
        "vel_world_x": struct.unpack_from("<d", packet, 116)[0],
        "vel_world_y": struct.unpack_from("<d", packet, 124)[0],
        "vel_world_z": struct.unpack_from("<d", packet, 132)[0],
        "vel_body_x": struct.unpack_from("<d", packet, 140)[0],
        "vel_body_y": struct.unpack_from("<d", packet, 148)[0],
        "vel_body_z": struct.unpack_from("<d", packet, 156)[0],
        "robot_motion_state": struct.unpack_from("<i", packet, 176)[0],
        "battery_level": struct.unpack_from("<d", packet, 180)[0],
    }


def decode_handle_state(packet: bytes) -> Dict[str, Any]:
    if len(packet) != HANDLE_STATE_PACKET_SIZE:
        raise ValueError(
            "HandleState packet must be {} bytes, got {}".format(
                HANDLE_STATE_PACKET_SIZE, len(packet)
            )
        )
    code, size, cons_code = decode_header(packet)
    if code != HANDLE_STATE_CODE:
        raise ValueError("HandleState packet has unexpected code {}".format(code))
    values = struct.unpack_from("<6d", packet, 12)
    return {
        "code": code,
        "size": size,
        "cons_code": cons_code,
        "kind": "handle_state",
        "left_axis_forward": values[0],
        "left_axis_side": values[1],
        "right_axis_yaw": values[2],
        "goal_vel_forward": values[3],
        "goal_vel_side": values[4],
        "goal_vel_yaw": values[5],
    }


def decode_packet(packet: bytes) -> Optional[Dict[str, Any]]:
    if len(packet) < 12:
        return None
    code, _, _ = decode_header(packet)
    if len(packet) == ROBOT_STATE_PACKET_SIZE and code == ROBOT_STATE_CODE:
        return decode_robot_state(packet)
    if len(packet) == HANDLE_STATE_PACKET_SIZE and code == HANDLE_STATE_CODE:
        return decode_handle_state(packet)
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind-host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=43897)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--output-csv")
    parser.add_argument("--summary-json")
    parser.add_argument("--print-every", type=int, default=100)
    return parser.parse_args()


def run(args: argparse.Namespace) -> Dict[str, Any]:
    output_handle = None
    writer = None
    if args.output_csv:
        output_handle = open(args.output_csv, "w", newline="")
        writer = csv.DictWriter(output_handle, fieldnames=CSV_FIELDS)
        writer.writeheader()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((args.bind_host, args.port))
    sock.settimeout(0.2)

    started_wall = time.time()
    started_mono = time.monotonic()
    packet_lengths: Counter[int] = Counter()
    codes: Counter[int] = Counter()
    code_lengths: Counter[str] = Counter()
    decoded_counts: Counter[str] = Counter()
    first_packet_hex: Dict[str, str] = {}
    total_packets = 0
    last_robot_state = None
    last_handle_state = None

    print(
        "Listening read-only on udp://{}:{} for {:.1f}s".format(
            args.bind_host, args.port, args.duration
        ),
        flush=True,
    )
    try:
        while time.monotonic() - started_mono < args.duration:
            try:
                packet, sender = sock.recvfrom(2048)
            except socket.timeout:
                continue

            now_wall = time.time()
            elapsed = time.monotonic() - started_mono
            total_packets += 1
            packet_lengths[len(packet)] += 1
            code = None
            size = None
            cons_code = None
            if len(packet) >= 12:
                code, size, cons_code = decode_header(packet)
                codes[code] += 1
                code_length_key = "{}/{}".format(code, len(packet))
                code_lengths[code_length_key] += 1
                if code in (ROBOT_STATE_CODE, HANDLE_STATE_CODE):
                    first_packet_hex.setdefault(code_length_key, packet.hex())

            decoded = decode_packet(packet)
            if decoded is None:
                continue

            decoded_counts[decoded["kind"]] += 1
            if decoded["kind"] == "robot_state":
                last_robot_state = decoded.copy()
            else:
                last_handle_state = decoded.copy()

            row = {field: "" for field in CSV_FIELDS}
            row.update(decoded)
            row.update(
                {
                    "host_time": now_wall,
                    "elapsed_sec": elapsed,
                    "sender_ip": sender[0],
                    "sender_port": sender[1],
                    "packet_len": len(packet),
                    "code": code,
                    "size": size,
                    "cons_code": cons_code,
                }
            )
            if writer is not None:
                writer.writerow(row)
            if args.print_every > 0 and decoded_counts[decoded["kind"]] % args.print_every == 0:
                print(json.dumps(row, sort_keys=True), flush=True)
    finally:
        sock.close()
        if output_handle is not None:
            output_handle.flush()
            output_handle.close()

    summary = {
        "started_wall": started_wall,
        "elapsed_sec": time.monotonic() - started_mono,
        "total_packets": total_packets,
        "packet_lengths": dict(sorted(packet_lengths.items())),
        "codes": dict(sorted(codes.items())),
        "code_lengths": dict(sorted(code_lengths.items())),
        "decoded_counts": dict(sorted(decoded_counts.items())),
        "first_packet_hex": dict(sorted(first_packet_hex.items())),
        "last_robot_state": last_robot_state,
        "last_handle_state": last_handle_state,
    }
    print("SUMMARY " + json.dumps(summary, sort_keys=True), flush=True)
    if args.summary_json:
        with open(args.summary_json, "w") as handle:
            json.dump(summary, handle, indent=2, sort_keys=True)
            handle.write("\n")
    return summary


def main() -> int:
    args = parse_args()
    try:
        summary = run(args)
    except OSError as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 1
    return 0 if summary["total_packets"] > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
