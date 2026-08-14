#!/usr/bin/env python3
"""Enter Lite3 auto/motion mode and clear all velocity axes."""

import argparse
import socket
import struct
import time


HEARTBEAT = 0x21040001
AUTO_MODE = 0x21010C03
MOTION_MODE = 0x21010D06
AXIS_CODES = (320, 325, 321)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dog-ip", default="192.168.1.120")
    parser.add_argument("--dog-port", type=int, default=43893)
    args = parser.parse_args()
    address = (args.dog_ip, args.dog_port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def simple(code: int) -> None:
        sock.sendto(struct.pack("<3i", code, 0, 0), address)

    def heartbeat_for(duration: float) -> None:
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            simple(HEARTBEAT)
            time.sleep(0.1)

    try:
        heartbeat_for(1.5)
        simple(AUTO_MODE)
        heartbeat_for(0.6)
        simple(MOTION_MODE)
        heartbeat_for(0.6)
        deadline = time.monotonic() + 0.8
        while time.monotonic() < deadline:
            simple(HEARTBEAT)
            for code in AXIS_CODES:
                sock.sendto(struct.pack("<3id", code, 8, 1, 0.0), address)
            time.sleep(0.05)
    finally:
        sock.close()
    print("Lite3 auto/motion mode ready; all velocity axes cleared", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
