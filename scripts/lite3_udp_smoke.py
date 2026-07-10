#!/usr/bin/env python3
"""Conservative Lite3 UDP smoke test with fixed-rate command hold.

This script is intentionally independent from ROS. It verifies the lowest
motion layer before Nav2 or task_manager is involved.

Safety:
  - By default it is dry-run and sends nothing.
  - Pass --armed to send packets.
  - It always sends stop packets on exit.
"""

from __future__ import annotations

import argparse
import socket
import struct
import sys
import time
from dataclasses import dataclass


CMD_HEARTBEAT = 0x21040001
CMD_AUTO_MODE = 0x21010C03
CMD_MOTION = 0x21010D06

CODE_FWD = 320
CODE_LAT = 325
CODE_YAW = 321


@dataclass
class HeldCommand:
    vx: float = 0.0
    vy: float = 0.0
    az: float = 0.0


class Lite3Udp:
    def __init__(self, dog_ip: str, dog_port: int, armed: bool) -> None:
        self.addr = (dog_ip, dog_port)
        self.armed = armed
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def close(self) -> None:
        self.stop_burst()
        self.sock.close()

    def simple(self, code: int, p1: int = 0, p2: int = 0) -> None:
        if self.armed:
            self.sock.sendto(struct.pack("<3i", code, p1, p2), self.addr)

    def complex(self, code: int, data: float) -> None:
        if self.armed:
            self.sock.sendto(struct.pack("<3id", code, 8, 1, float(data)), self.addr)

    def init_motion(self) -> None:
        for _ in range(10):
            self.simple(CMD_HEARTBEAT)
            time.sleep(0.1)
        self.simple(CMD_AUTO_MODE)
        time.sleep(0.5)
        self.simple(CMD_MOTION)
        time.sleep(0.3)

    def send_held(self, cmd: HeldCommand, combined_axes: bool) -> None:
        self.simple(CMD_HEARTBEAT)
        if combined_axes:
            self.complex(CODE_FWD, cmd.vx)
            self.complex(CODE_LAT, cmd.vy)
            self.complex(CODE_YAW, -cmd.az)
            return

        if abs(cmd.az) > 0.005:
            self.complex(CODE_YAW, -cmd.az)
        elif abs(cmd.vx) > 0.005:
            self.complex(CODE_FWD, cmd.vx)
        elif abs(cmd.vy) > 0.005:
            self.complex(CODE_LAT, cmd.vy)
        else:
            self.complex(CODE_FWD, 0.0)

    def stop_burst(self) -> None:
        for _ in range(8):
            self.simple(CMD_HEARTBEAT)
            self.complex(CODE_FWD, 0.0)
            time.sleep(0.05)


def hold(
    client: Lite3Udp,
    label: str,
    cmd: HeldCommand,
    duration: float,
    rate_hz: float,
    combined_axes: bool,
) -> None:
    period = 1.0 / rate_hz
    deadline = time.monotonic() + duration
    print(
        f"{label}: {duration:.1f}s vx={cmd.vx:.3f} "
        f"vy={cmd.vy:.3f} az={cmd.az:.3f}"
    )
    next_tick = time.monotonic()
    while time.monotonic() < deadline:
        client.send_held(cmd, combined_axes=combined_axes)
        next_tick += period
        time.sleep(max(0.0, next_tick - time.monotonic()))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dog-ip", default="192.168.1.120")
    parser.add_argument("--dog-port", type=int, default=43893)
    parser.add_argument("--rate-hz", type=float, default=40.0)
    parser.add_argument("--forward-vx", type=float, default=0.04)
    parser.add_argument("--yaw-az", type=float, default=0.12)
    parser.add_argument("--move-sec", type=float, default=1.0)
    parser.add_argument("--stop-sec", type=float, default=1.0)
    parser.add_argument("--combined-axes", action="store_true")
    parser.add_argument(
        "--armed",
        action="store_true",
        help="Actually send UDP packets. Without this flag, dry-run only.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rate_hz = max(5.0, args.rate_hz)

    if not args.armed:
        print("DRY RUN: pass --armed to send Lite3 UDP packets.")

    client = Lite3Udp(args.dog_ip, args.dog_port, armed=args.armed)
    try:
        print(f"Lite3 UDP target: {args.dog_ip}:{args.dog_port}")
        client.init_motion()
        hold(client, "stop", HeldCommand(), args.stop_sec, rate_hz, args.combined_axes)
        hold(
            client,
            "slow_forward",
            HeldCommand(vx=args.forward_vx),
            args.move_sec,
            rate_hz,
            args.combined_axes,
        )
        hold(client, "stop", HeldCommand(), args.stop_sec, rate_hz, args.combined_axes)
        hold(
            client,
            "slow_yaw_left",
            HeldCommand(az=args.yaw_az),
            args.move_sec,
            rate_hz,
            args.combined_axes,
        )
        hold(client, "final_stop", HeldCommand(), args.stop_sec, rate_hz, args.combined_axes)
    except KeyboardInterrupt:
        print("Interrupted; sending stop.")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
