#!/usr/bin/env python3
# coding: utf-8

"""轻量端面靠近抓取脚本。

输入机械臂基座右手系下的目标点，自动生成水平端面靠近路径：

target -> pre_grasp -> approach -> close_gripper -> lift

端面姿态约束的 phi 固定为 0，也就是工具轴始终按水平姿态求解。
默认 dry-run，只打印动作序列；加 --execute 才会通过 BusLinker 真实执行。
"""

from __future__ import print_function

import argparse
import os
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from arm_api import ArmGrabConfig, ArmGrabPlannerNew, BusLinkerExecutor, IKNoSolution, MotionStep  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description="输入机械臂基座右手系目标点，端面靠近并抓取")
    parser.add_argument("x", type=float, help="目标 x，单位 m，机械臂基座右手系")
    parser.add_argument("y", type=float, help="目标 y，单位 m，机械臂基座右手系")
    parser.add_argument("z", type=float, help="目标 z，单位 m，机械臂基座右手系")
    parser.add_argument("--rotation", type=float, default=0.0, help="夹爪自转角，单位 deg，对应 2 号舵机")
    parser.add_argument("--pre-distance", type=float, default=0.05, help="预抓取点距离目标点的后退距离，单位 m")
    parser.add_argument("--lift-height", type=float, default=0.08, help="抓取后抬升高度，单位 m")
    parser.add_argument("--steps", type=int, default=8, help="pre_grasp 到 target 的插值段数")
    parser.add_argument("--step-time", type=int, default=180, help="每段靠近动作时间，单位 ms")
    parser.add_argument("--duration-scale", type=float, default=1.0, help="整体动作时长倍率")
    parser.add_argument("--home", action="store_true", help="抓取后追加 home 姿态")
    parser.add_argument("--port", default="/dev/ttyACM0", help="BusLinker 串口")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--pause", type=float, default=0.2, help="每步发送后的额外等待时间，单位 s")
    parser.add_argument("--read-before", action="store_true", help="执行前读取 ID3..6 当前 pulse")
    parser.add_argument("--execute", action="store_true", help="真实执行。默认只 dry-run")
    return parser.parse_args()


def make_planner(args):
    config = ArmGrabConfig(
        approach_steps=max(1, int(args.steps)),
        approach_step_duration_ms=max(1, int(args.step_time)),
    )
    return ArmGrabPlannerNew(config=config)


def scale_steps(steps, scale):
    scale = max(0.1, float(scale))
    if abs(scale - 1.0) < 1e-9:
        return steps
    scaled = []
    for step in steps:
        scaled.append(
            MotionStep(
                step.name,
                step.coordinate,
                int(round(step.duration_ms * scale)),
                step.servos,
                step.ik_angles,
                step.used_pitch,
            )
        )
    return scaled


def print_pose(pose):
    print("自动端面位姿：")
    print("  pre_point   = ({:.4f}, {:.4f}, {:.4f}) m".format(*pose.pre_point))
    print("  grasp_point = ({:.4f}, {:.4f}, {:.4f}) m".format(*pose.grasp_point))
    print("  lift_point  = ({:.4f}, {:.4f}, {:.4f}) m".format(*pose.lift_point))
    print("  face_normal = ({:.4f}, {:.4f}, {:.4f})".format(*pose.face_normal))
    print("  approach    = ({:.4f}, {:.4f}, {:.4f})".format(*pose.approach_dir))


def print_steps(steps):
    print("动作数量：{}".format(len(steps)))
    previous = None
    for index, step in enumerate(steps, 1):
        print("[{:02d}] {}  {} ms".format(index, step.name, step.duration_ms))
        if step.coordinate is not None:
            print("     xyz=({:.4f}, {:.4f}, {:.4f}) m".format(*step.coordinate))
        if step.ik_angles:
            angles = step.ik_angles
            print(
                "     theta3={:.2f}, theta4={:.2f}, theta5={:.2f}, theta6={:.2f}, mode={}".format(
                    angles.get("theta3", 0.0),
                    angles.get("theta4", 0.0),
                    angles.get("theta5", 0.0),
                    angles.get("theta6", 0.0),
                    angles.get("ik_mode", "position_only"),
                )
            )
            if "phi" in angles and "l4_abs_deg" in angles:
                print(
                    "     phi={:.2f}, l4_abs={:.2f}, diff={:+.3f} deg".format(
                        angles["phi"],
                        angles["l4_abs_deg"],
                        angles["l4_abs_deg"] - angles["phi"],
                    )
                )
        print("     servos={}".format(dict(step.servos)))
        if previous:
            deltas = {}
            for servo_id, pulse in step.servos:
                if servo_id in previous:
                    deltas[servo_id] = pulse - previous[servo_id]
            if deltas:
                print("     delta={}".format(deltas))
        if step.servos:
            previous = dict(step.servos)


def print_reach_hint(planner, target, pre_distance):
    hint = planner.horizontal_face_reach_hint(target, pre_distance=pre_distance)
    print("")
    print("水平端面可达性提示：")
    print("  tool_dir      = ({:.4f}, {:.4f}, {:.4f})".format(*hint["tool_dir"]))
    print("  generated_pre = ({:.4f}, {:.4f}, {:.4f}) m".format(*hint["pre_point"]))
    for name in ("pre", "grasp"):
        item = hint[name]
        print(
            "  {}: radial={:.4f}m, wrist_distance={:.4f}m, reachable=[{:.4f}, {:.4f}]m, ok={}".format(
                name,
                item["radial"],
                item["wrist_distance"],
                item["min_reach"],
                item["max_reach"],
                item["ok"],
            )
        )


def main():
    args = parse_args()
    target = (args.x, args.y, args.z)
    planner = make_planner(args)

    try:
        pose = planner.make_horizontal_face_grasp_pose(
            target,
            rotation_deg=args.rotation,
            pre_distance=args.pre_distance,
            lift_height=args.lift_height,
        )
        steps = planner.plan_grasp_pose(pose, include_home=args.home)
        steps = scale_steps(steps, args.duration_scale)
    except IKNoSolution as exc:
        print("IK 无解，未发送串口。")
        print("原因：{}".format(exc))
        print_reach_hint(planner, target, args.pre_distance)
        raise SystemExit(2)

    print_pose(pose)
    print_steps(steps)

    executor = BusLinkerExecutor(args.port, args.baud)
    if not args.execute:
        print("")
        print("dry-run：没有打开串口，也不会运动。确认安全后加 --execute。")
        executor.execute_steps(steps, dry_run=True, scan_first=False, pause_s=args.pause)
        return

    print("")
    print("准备真实执行：请确认机械臂周围安全，异常时立即断电。")
    input("确认后按 Enter；Ctrl+C 取消。")
    with executor:
        if args.read_before:
            print("执行前 ID3..6 pulse：{}".format(executor.read_positions((3, 4, 5, 6))))
        executor.execute_steps(steps, dry_run=False, scan_first=True, pause_s=args.pause)


if __name__ == "__main__":
    main()
