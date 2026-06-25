#!/usr/bin/env python3
"""Short D455 input validation for cuVSLAM preparation.

Checks RGB/depth, infrared stereo, IMU, and the cuVSLAM factory preset.
Run on the Jetson with the D455 connected:

    python3 scripts/realsense_cuvslam_input_test.py
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Callable, Dict, List

import pyrealsense2 as rs

from cv.realsense_camera import RealsenseCamera


Check = Callable[[argparse.Namespace], None]


def _print_header(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def check_device(_: argparse.Namespace) -> None:
    _print_header("D455 enumeration")
    ctx = rs.context()
    devices = list(ctx.query_devices())
    print(f"device_count={len(devices)}", flush=True)
    if not devices:
        raise RuntimeError("No RealSense device found")

    for device in devices:
        name = device.get_info(rs.camera_info.name)
        serial = device.get_info(rs.camera_info.serial_number)
        firmware = device.get_info(rs.camera_info.firmware_version)
        usb = device.get_info(rs.camera_info.usb_type_descriptor)
        sensors = [s.get_info(rs.camera_info.name) for s in device.query_sensors()]
        print(f"device={name} serial={serial} firmware={firmware} usb={usb}", flush=True)
        print(f"sensors={sensors}", flush=True)


def check_color_depth(args: argparse.Namespace) -> None:
    _print_header("RGB + depth")
    with RealsenseCamera(
        width=args.width,
        height=args.height,
        fps=args.fps,
        enable_color=True,
        enable_depth=True,
        enable_infrared=False,
        enable_imu=False,
    ) as camera:
        color, depth = camera.get_frames()
        if color is None or depth is None:
            raise RuntimeError("Missing color or depth frame")
        cx, cy = camera.width // 2, camera.height // 2
        center_depth = camera.get_distance(cx, cy)
        print(
            f"PASS color={color.shape} depth={depth.shape} "
            f"center_depth_m={center_depth:.3f}",
            flush=True,
        )


def check_ir_depth(args: argparse.Namespace) -> None:
    _print_header("IR stereo + depth")
    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(
        rs.stream.infrared, 1, args.width, args.height, rs.format.y8, args.fps
    )
    config.enable_stream(
        rs.stream.infrared, 2, args.width, args.height, rs.format.y8, args.fps
    )
    config.enable_stream(
        rs.stream.depth, args.width, args.height, rs.format.z16, args.fps
    )
    try:
        profile = pipeline.start(config)
        counts: Dict[str, int] = {"ir1": 0, "ir2": 0, "depth": 0}
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            frames = pipeline.wait_for_frames(args.timeout_ms)
            if frames.get_infrared_frame(1):
                counts["ir1"] += 1
            if frames.get_infrared_frame(2):
                counts["ir2"] += 1
            if frames.get_depth_frame():
                counts["depth"] += 1

        if min(counts.values()) == 0:
            raise RuntimeError(f"Missing IR/depth frames: {counts}")
        print(f"PASS counts={counts}", flush=True)
        left = profile.get_stream(rs.stream.infrared, 1)
        right = profile.get_stream(rs.stream.infrared, 2)
        intrinsics = left.as_video_stream_profile().intrinsics
        extrinsics = left.get_extrinsics_to(right)
        print(
            "left_intrinsics="
            f"width={intrinsics.width} height={intrinsics.height} "
            f"fx={intrinsics.fx:.3f} fy={intrinsics.fy:.3f} "
            f"ppx={intrinsics.ppx:.3f} ppy={intrinsics.ppy:.3f} "
            f"baseline_m={abs(extrinsics.translation[0]):.6f}",
            flush=True,
        )
    finally:
        try:
            pipeline.stop()
        except Exception:
            pass


def check_imu(args: argparse.Namespace) -> None:
    _print_header("IMU accel + gyro")
    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.accel, rs.format.motion_xyz32f, args.accel_rate)
    config.enable_stream(rs.stream.gyro, rs.format.motion_xyz32f, args.gyro_rate)

    try:
        pipeline.start(config)
        counts: Dict[str, int] = {"accel": 0, "gyro": 0}
        samples: List[str] = []
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            frames = pipeline.wait_for_frames(args.timeout_ms)
            accel_frame = frames.first_or_default(rs.stream.accel)
            gyro_frame = frames.first_or_default(rs.stream.gyro)

            if accel_frame:
                counts["accel"] += 1
                if len(samples) < 2:
                    accel = accel_frame.as_motion_frame().get_motion_data()
                    samples.append(
                        f"accel=({accel.x:.4f},{accel.y:.4f},{accel.z:.4f})"
                    )

            if gyro_frame:
                counts["gyro"] += 1
                if len(samples) < 4:
                    gyro = gyro_frame.as_motion_frame().get_motion_data()
                    samples.append(
                        f"gyro=({gyro.x:.4f},{gyro.y:.4f},{gyro.z:.4f})"
                    )

        if min(counts.values()) == 0:
            raise RuntimeError(f"Missing IMU frames: {counts}")
        print(f"PASS counts={counts} samples={samples}", flush=True)
    finally:
        try:
            pipeline.stop()
        except Exception:
            pass


def check_cuvslam_preset(args: argparse.Namespace) -> None:
    _print_header("RealsenseCamera.for_cuvslam")
    camera = RealsenseCamera.for_cuvslam(
        width=args.width,
        height=args.height,
        accel_rate=args.accel_rate,
        gyro_rate=args.gyro_rate,
    )
    try:
        camera.start(warmup_frames=args.warmup_frames)
        left, right = camera.get_infrared_frames(args.timeout_ms)
        imu = camera.get_imu_data(args.timeout_ms)
        print(
            f"PASS left={left.shape} right={right.shape} "
            f"accel={imu.accel} gyro={imu.gyro}",
            flush=True,
        )
    finally:
        camera.stop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate D455 RGB/depth/IR/IMU inputs for cuVSLAM preparation."
    )
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--warmup-frames", type=int, default=5)
    parser.add_argument("--timeout-ms", type=int, default=5000)
    parser.add_argument("--accel-rate", type=int, default=200)
    parser.add_argument("--gyro-rate", type=int, default=200)
    parser.add_argument(
        "--skip-color-depth",
        action="store_true",
        help="Skip RGB/depth validation.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    checks: List[Check] = [check_device]
    if not args.skip_color_depth:
        checks.append(check_color_depth)
    checks.extend([check_ir_depth, check_imu, check_cuvslam_preset])

    failures: List[str] = []
    for check in checks:
        try:
            check(args)
        except Exception as exc:
            failures.append(f"{check.__name__}: {type(exc).__name__}: {exc}")
            print(f"FAIL {failures[-1]}", flush=True)

    if failures:
        print("\nFAILED checks:", flush=True)
        for failure in failures:
            print(f"- {failure}", flush=True)
        return 1

    print("\nAll D455 input checks passed.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
