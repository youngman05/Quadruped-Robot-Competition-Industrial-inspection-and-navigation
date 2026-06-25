#!/usr/bin/env python3
"""Verify RealSense RGB-D capture on Jetson."""

import pyrealsense2 as rs


def main() -> None:
    ctx = rs.context()
    devices = ctx.query_devices()
    print(f"devices: {len(devices)}")
    for device in devices:
        print("device:", device.get_info(rs.camera_info.name))
        print("serial:", device.get_info(rs.camera_info.serial_number))

    if len(devices) == 0:
        raise RuntimeError("No RealSense device found")

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
    config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)

    pipeline.start(config)
    try:
        for _ in range(30):
            frames = pipeline.wait_for_frames(5000)
            color = frames.get_color_frame()
            depth = frames.get_depth_frame()
            if not color or not depth:
                continue

            cx = depth.get_width() // 2
            cy = depth.get_height() // 2
            print(f"color: {color.get_width()}x{color.get_height()}")
            print(f"depth: {depth.get_width()}x{depth.get_height()}")
            print(f"center depth: {depth.get_distance(cx, cy):.3f} m")
            return
    finally:
        pipeline.stop()

    raise RuntimeError("RealSense streams opened but no valid frame was received")


if __name__ == "__main__":
    main()

