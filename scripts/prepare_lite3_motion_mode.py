#!/usr/bin/env python3
"""Prepare Lite3 high-level motion mode without touching the stand/lie toggle.

This script intentionally never sends 0x21010202. That command is a stand/lie
toggle, not an idempotent "stand up" command.
"""

from __future__ import annotations

import argparse
import socket
import struct
import time
from datetime import datetime


DOG_IP = "192.168.1.120"
DOG_PORT = 43893

CMD_HEARTBEAT = 0x21040001
CMD_AUTO_MODE = 0x21010C03
CMD_MOTION = 0x21010D06

CODE_FWD = 320
CODE_LAT = 325
CODE_YAW = 321


def timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


class Lite3ModePreparer:
    def __init__(self, dog_ip: str, dog_port: int) -> None:
        self.addr = (dog_ip, dog_port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.count_simple = 0
        self.count_complex = 0
        self.count_errors = 0

    def close(self) -> None:
        self.sock.close()

    def send_simple(self, code: int, label: str, p1: int = 0, p2: int = 0) -> None:
        try:
            self.sock.sendto(struct.pack("<3i", code, p1, p2), self.addr)
            self.count_simple += 1
            print(f"{timestamp()} simple {label} code=0x{code:08X} p1={p1} p2={p2}", flush=True)
        except OSError as exc:
            self.count_errors += 1
            print(f"{timestamp()} ERROR simple {label}: {exc}", flush=True)

    def send_complex(self, code: int, value: float, label: str) -> None:
        try:
            self.sock.sendto(struct.pack("<3id", code, 8, 1, float(value)), self.addr)
            self.count_complex += 1
        except OSError as exc:
            self.count_errors += 1
            print(f"{timestamp()} ERROR complex {label}: {exc}", flush=True)

    def heartbeat_for(self, duration_sec: float, period_sec: float, label: str) -> None:
        deadline = time.time() + max(0.0, duration_sec)
        while time.time() < deadline:
            self.send_simple(CMD_HEARTBEAT, label)
            time.sleep(period_sec)

    def send_zero_velocity_for(self, duration_sec: float, period_sec: float) -> int:
        deadline = time.time() + max(0.0, duration_sec)
        ticks = 0
        while time.time() < deadline:
            self.send_simple(CMD_HEARTBEAT, "zero_hb")
            self.send_complex(CODE_FWD, 0.0, "fwd_zero")
            self.send_complex(CODE_LAT, 0.0, "lat_zero")
            self.send_complex(CODE_YAW, 0.0, "yaw_zero")
            ticks += 1
            time.sleep(period_sec)
        return ticks

    def send_motion_test(self, vx: float, duration_sec: float, period_sec: float) -> int:
        deadline = time.time() + max(0.0, duration_sec)
        ticks = 0
        while time.time() < deadline:
            self.send_simple(CMD_HEARTBEAT, "test_hb")
            self.send_complex(CODE_FWD, vx, "fwd")
            self.send_complex(CODE_LAT, 0.0, "lat")
            self.send_complex(CODE_YAW, 0.0, "yaw")
            ticks += 1
            time.sleep(period_sec)
        return ticks

    def prepare(self, args: argparse.Namespace) -> None:
        print(f"{timestamp()} target={self.addr[0]}:{self.addr[1]}", flush=True)
        print(f"{timestamp()} warmup heartbeat {args.warmup_sec:.2f}s", flush=True)
        self.heartbeat_for(args.warmup_sec, args.heartbeat_period_sec, "warmup")

        print(f"{timestamp()} auto/nav mode", flush=True)
        self.send_simple(CMD_AUTO_MODE, "auto_mode")
        self.heartbeat_for(args.post_auto_sec, args.heartbeat_period_sec, "post_auto")

        print(f"{timestamp()} motion mode", flush=True)
        self.send_simple(CMD_MOTION, "motion_mode")
        self.heartbeat_for(args.post_motion_sec, args.heartbeat_period_sec, "post_motion")

        if args.test_duration_sec > 0.0:
            print(
                f"{timestamp()} optional motion test vx={args.test_vx:.3f} "
                f"for {args.test_duration_sec:.2f}s",
                flush=True,
            )
            test_ticks = self.send_motion_test(
                args.test_vx,
                args.test_duration_sec,
                args.motion_period_sec,
            )
            print(f"{timestamp()} test_ticks={test_ticks}", flush=True)

        print(f"{timestamp()} zero velocity {args.zero_sec:.2f}s", flush=True)
        zero_ticks = self.send_zero_velocity_for(args.zero_sec, args.motion_period_sec)
        print(f"{timestamp()} zero_ticks={zero_ticks}", flush=True)

        print(f"{timestamp()} tail heartbeat {args.tail_sec:.2f}s", flush=True)
        self.heartbeat_for(args.tail_sec, args.heartbeat_period_sec, "tail")

        print(
            f"{timestamp()} done simple={self.count_simple} "
            f"complex={self.count_complex} errors={self.count_errors}",
            flush=True,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare Lite3 Auto/Nav + Motion mode without stand/lie toggle."
    )
    parser.add_argument("--dog-ip", default=DOG_IP)
    parser.add_argument("--dog-port", type=int, default=DOG_PORT)
    parser.add_argument("--warmup-sec", type=float, default=1.5)
    parser.add_argument("--post-auto-sec", type=float, default=0.6)
    parser.add_argument("--post-motion-sec", type=float, default=0.6)
    parser.add_argument("--zero-sec", type=float, default=0.8)
    parser.add_argument("--tail-sec", type=float, default=0.5)
    parser.add_argument("--heartbeat-period-sec", type=float, default=0.1)
    parser.add_argument("--motion-period-sec", type=float, default=0.05)
    parser.add_argument(
        "--test-vx",
        type=float,
        default=0.0,
        help="Optional low-speed forward test. Default 0 disables motion test.",
    )
    parser.add_argument("--test-duration-sec", type=float, default=0.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    preparer = Lite3ModePreparer(args.dog_ip, args.dog_port)
    try:
        preparer.prepare(args)
    finally:
        preparer.close()


if __name__ == "__main__":
    main()
