#!/usr/bin/env python3
# coding: utf-8

"""Move the arm to the same entry pose used by face_approach_grab.py.

The command sequence intentionally matches the first two steps of the face
approach plan: open/center the gripper, then move joints 3..6 to safe_pose.
Dry-run is the default and does not open the serial port.
"""

from __future__ import print_function

import argparse
import os
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from arm_api import ArmGrabConfig, BusLinkerExecutor, MotionStep  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(
        description="Move the arm to the face-approach entry pose."
    )
    parser.add_argument("--port", default="/dev/ttyACM0", help="BusLinker serial port")
    parser.add_argument("--baud", type=int, default=115200, help="serial baud rate")
    parser.add_argument(
        "--duration-scale",
        type=float,
        default=1.0,
        help="scale both motion durations; use 2.0 for the first hardware test",
    )
    parser.add_argument("--pause", type=float, default=0.2, help="extra wait after each step")
    parser.add_argument(
        "--read-before",
        action="store_true",
        help="read servo positions before moving",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="send commands to the arm; default is dry-run",
    )
    return parser.parse_args()


def make_init_steps(duration_scale=1.0):
    """Build the same two entry steps used by the face-approach planner."""

    config = ArmGrabConfig()
    scale = max(0.1, float(duration_scale))
    return [
        MotionStep(
            "pre_grasp_open_and_rotate",
            None,
            int(round(500 * scale)),
            ((1, config.open_gripper), (2, 500)),
        ),
        MotionStep(
            "safe_pose",
            None,
            int(round(800 * scale)),
            config.safe_servos,
        ),
    ]


def print_steps(steps):
    print("Face-approach entry pose:")
    for index, step in enumerate(steps, 1):
        print("[{:02d}] {} duration={}ms servos={}".format(
            index,
            step.name,
            step.duration_ms,
            dict(step.servos),
        ))


def main():
    args = parse_args()
    steps = make_init_steps(args.duration_scale)
    print_steps(steps)

    executor = BusLinkerExecutor(args.port, args.baud)
    if not args.execute:
        print("dry-run: serial port will not be opened and the arm will not move.")
        executor.execute_steps(steps, dry_run=True, scan_first=False, pause_s=args.pause)
        return

    print("Ready to move to the entry pose. Ensure the area is clear; Ctrl+C cancels.")
    input("Press Enter to execute: ")
    with executor:
        if args.read_before:
            print("positions before move: {}".format(executor.read_positions()))
        executor.execute_steps(steps, dry_run=False, scan_first=True, pause_s=args.pause)


if __name__ == "__main__":
    main()
