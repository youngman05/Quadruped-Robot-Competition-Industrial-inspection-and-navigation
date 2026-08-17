#!/usr/bin/env python3
# coding: utf-8

"""Direct placement test for the standalone ArmPi API.

The input is a TCP release point in the ArmPi base frame, in metres. This
script deliberately has no ROS dependency and is safe by default: without
--execute it only prints the planned BusLinker pulse sequence.
"""

from __future__ import print_function

import argparse
import os
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from arm_api import ArmGrabPlannerNew, BusLinkerExecutor, IKNoSolution, MotionStep  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(
        description="Move directly to an ArmPi-base TCP release point and open the gripper"
    )
    parser.add_argument("x", type=float, help="ArmPi base-frame X in metres")
    parser.add_argument("y", type=float, help="ArmPi base-frame Y in metres")
    parser.add_argument("z", type=float, help="ArmPi base-frame Z in metres")
    parser.add_argument("--duration", type=int, default=1200, help="Target move duration in ms")
    parser.add_argument("--home", action="store_true", help="Return to the known home pose after release")
    parser.add_argument("--port", default="/dev/ttyACM0", help="BusLinker serial port")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--pause", type=float, default=0.2, help="Extra wait after each step in seconds")
    parser.add_argument("--duration-scale", type=float, default=1.0, help="Scale all step durations")
    parser.add_argument("--read-before", action="store_true", help="Read IDs 1..6 before motion")
    parser.add_argument("--execute", action="store_true", help="Send BusLinker commands; default is dry-run")
    return parser.parse_args()


def scale_steps(steps, scale):
    scale = max(0.1, float(scale))
    if abs(scale - 1.0) < 1e-9:
        return steps
    return [
        MotionStep(
            step.name,
            step.coordinate,
            int(round(step.duration_ms * scale)),
            step.servos,
            step.ik_angles,
            step.used_pitch,
        )
        for step in steps
    ]


def print_steps(steps):
    print("planned steps: {}".format(len(steps)))
    for index, step in enumerate(steps, 1):
        print("[{:02d}] {} {} ms".format(index, step.name, step.duration_ms))
        if step.coordinate is not None:
            print("     xyz=({:.4f}, {:.4f}, {:.4f}) m".format(*step.coordinate))
        if step.ik_angles:
            print(
                "     theta3={:.2f}, theta4={:.2f}, theta5={:.2f}, theta6={:.2f}".format(
                    step.ik_angles.get("theta3", 0.0),
                    step.ik_angles.get("theta4", 0.0),
                    step.ik_angles.get("theta5", 0.0),
                    step.ik_angles.get("theta6", 0.0),
                )
            )
        print("     servos={}".format(dict(step.servos)))


def main():
    args = parse_args()
    target = (args.x, args.y, args.z)
    planner = ArmGrabPlannerNew()
    try:
        steps = planner.plan_place(
            target,
            duration_ms=max(1, args.duration),
            include_home=args.home,
        )
    except IKNoSolution as exc:
        print("placement IK has no solution; no serial command was sent: {}".format(exc))
        raise SystemExit(2)

    steps = scale_steps(steps, args.duration_scale)
    print_steps(steps)
    executor = BusLinkerExecutor(args.port, args.baud)

    if not args.execute:
        print("dry-run: serial port is not opened and the arm will not move")
        executor.execute_steps(steps, dry_run=True, scan_first=False, pause_s=args.pause)
        return

    print("real execution: keep the workspace clear and be ready to cut power")
    input("Press Enter to execute, or Ctrl+C to cancel: ")
    with executor:
        if args.read_before:
            print("positions before motion: {}".format(executor.read_positions()))
        executor.execute_steps(steps, dry_run=False, scan_first=True, pause_s=args.pause)


if __name__ == "__main__":
    main()
