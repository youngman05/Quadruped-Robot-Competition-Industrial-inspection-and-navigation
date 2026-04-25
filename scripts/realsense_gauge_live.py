#!/usr/bin/env python3
"""Live gauge recognition from Intel RealSense D455.

This script reads RGB frames from D455, runs the existing OpenCV gauge detector,
and prints the gauge state to the terminal.
"""

from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path
import sys

import cv2
import numpy as np
import pyrealsense2 as rs


ROOT = Path(__file__).resolve().parents[1]
GAUGE_DIR = ROOT / "src" / "cv" / "gauge_detector"
sys.path.insert(0, str(GAUGE_DIR))

from gauge_detector import detect_gauge  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live D455 gauge recognition.")
    parser.add_argument("--width", type=int, default=640, help="Color stream width.")
    parser.add_argument("--height", type=int, default=480, help="Color stream height.")
    parser.add_argument("--fps", type=int, default=30, help="Color stream FPS.")
    parser.add_argument(
        "--interval",
        type=float,
        default=0.5,
        help="Recognition interval in seconds. Lower values use more CPU.",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=0,
        help="Number of recognition iterations. 0 means run until Ctrl+C.",
    )
    parser.add_argument(
        "--debug-dir",
        type=Path,
        default=None,
        help="Optional directory for debug images.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print debug messages for missed or invalid detections.",
    )
    parser.add_argument(
        "--min-color-ratio",
        type=float,
        default=0.04,
        help="Minimum colored ring pixel ratio required to accept a gauge.",
    )
    parser.add_argument(
        "--min-direction-score",
        type=int,
        default=100,
        help="Minimum color hit count near needle direction required to accept a gauge.",
    )
    parser.add_argument(
        "--min-zone-pixels",
        type=int,
        default=300,
        help="Minimum pixels required for each yellow/green/red gauge zone.",
    )
    return parser.parse_args()


def is_valid_gauge_result(
    result: dict,
    min_color_ratio: float,
    min_direction_score: int,
    min_zone_pixels: int,
):
    if result is None:
        return False, "no_result"
    if not result.get("circle_detected"):
        return False, "no_hough_circle"
    if result.get("angle") is None:
        return False, "no_needle_angle"

    level = result.get("level")
    status = result.get("status")
    color = result.get("color")
    if not level or not status or level == "未知" or status == "未知" or not color:
        return False, "unknown_state"

    coverage = result.get("color_coverage") or {}
    color_ratio = float(coverage.get("ratio") or 0.0)
    if color_ratio < min_color_ratio:
        return False, f"low_color_ratio={color_ratio:.4f}"

    zone_counts = coverage.get("counts") or {}
    weak_zones = [
        color for color in ("yellow", "green", "red")
        if int(zone_counts.get(color) or 0) < min_zone_pixels
    ]
    if weak_zones:
        return False, f"weak_color_zones={weak_zones}"

    direction_scores = result.get("direction_scores") or {}
    direction_score = int(direction_scores.get(color) or 0)
    if direction_score < min_direction_score:
        return False, f"low_direction_score={direction_score}"

    return True, "ok"


def main() -> None:
    args = parse_args()
    if args.debug_dir:
        args.debug_dir.mkdir(parents=True, exist_ok=True)

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.color, args.width, args.height, rs.format.bgr8, args.fps)

    profile = pipeline.start(config)
    device = profile.get_device()
    device_name = device.get_info(rs.camera_info.name)
    serial = device.get_info(rs.camera_info.serial_number)
    print(f"D455 started: {device_name}, serial={serial}")
    print("把仪表盘放到相机前，尽量居中、占画面主要区域。按 Ctrl+C 结束。")

    count = 0
    tmp_path = Path(tempfile.gettempdir()) / "d455_gauge_frame.jpg"
    last_run = 0.0

    try:
        while True:
            frames = pipeline.wait_for_frames(5000)
            color_frame = frames.get_color_frame()
            if not color_frame:
                continue

            now = time.monotonic()
            if now - last_run < args.interval:
                continue
            last_run = now

            image = np.asanyarray(color_frame.get_data())

            # Reuse the path-based detector to avoid changing the proven module now.
            cv2.imwrite(str(tmp_path), image)

            debug_out = None
            if args.debug_dir:
                debug_out = str(args.debug_dir / f"gauge_live_{count:04d}_debug.jpg")

            result = detect_gauge(str(tmp_path), debug=bool(debug_out), debug_out=debug_out)
            ts = time.strftime("%H:%M:%S")
            valid, reason = is_valid_gauge_result(
                result,
                min_color_ratio=args.min_color_ratio,
                min_direction_score=args.min_direction_score,
                min_zone_pixels=args.min_zone_pixels,
            )
            if not valid:
                if args.verbose:
                    print(f"[{ts}] 未识别到有效仪表盘: {reason}")
                count += 1
                if args.frames > 0 and count >= args.frames:
                    break
                continue

            level = result.get("level")
            status = result.get("status")
            color = result.get("color")
            angle = result.get("angle")
            print(
                f"[{ts}] 仪表盘显示{level}，状态{status} "
                f"(color={color}, angle={angle})"
            )

            count += 1
            if args.frames > 0 and count >= args.frames:
                break
    except KeyboardInterrupt:
        print("\n已停止识别")
    finally:
        pipeline.stop()


if __name__ == "__main__":
    main()
