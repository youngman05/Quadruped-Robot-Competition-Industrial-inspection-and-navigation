#!/usr/bin/env python3
"""Verify RealSense RGB-D capture works (uses cv.realsense_camera wrapper)."""

from __future__ import annotations

from cv.realsense_camera import RealsenseCamera


def main() -> None:
    with RealsenseCamera() as cam:
        print(f"device: {cam.device_name}")
        print(f"serial: {cam.serial}")
        print(f"stream: {cam.width}x{cam.height} @ 30fps (depth aligned)")

        # Grab one frame
        color, depth = cam.get_frames()

        print(f"color: {color.shape[1]}x{color.shape[0]}")
        if depth is not None:
            print(f"depth: {depth.shape[1]}x{depth.shape[0]}")

        # Center depth
        cx, cy = cam.width // 2, cam.height // 2
        center_d = cam.get_distance(cx, cy)
        print(f"center depth: {center_d:.3f} m")

        # Intrinsics check
        intrin = cam.color_intrinsics
        print(
            f"intrinsics: fx={intrin.fx:.1f}, fy={intrin.fy:.1f}, "
            f"ppx={intrin.ppx:.1f}, ppy={intrin.ppy:.1f}"
        )

    print("smoke test passed")


if __name__ == "__main__":
    main()
