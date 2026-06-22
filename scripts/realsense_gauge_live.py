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

import cv2

from cv.realsense_camera import RealsenseCamera
from cv.gauge_detector import detect_gauge
from cv.gauge_detector.live_validation import (
    GaugeValidationConfig,
    is_valid_gauge_result,
)


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
    parser.add_argument(
        "--max-zone-fraction",
        type=float,
        default=0.62,
        help="Reject detections where one color dominates the ring too much.",
    )
    parser.add_argument(
        "--min-direction-margin",
        type=float,
        default=2.0,
        help="Best direction color score must be this many times the second best.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.debug_dir:
        args.debug_dir.mkdir(parents=True, exist_ok=True)

    validation_config = GaugeValidationConfig(
        min_color_ratio=args.min_color_ratio,
        min_direction_score=args.min_direction_score,
        min_zone_pixels=args.min_zone_pixels,
        max_zone_fraction=args.max_zone_fraction,
        min_direction_margin=args.min_direction_margin,
    )

    cam = RealsenseCamera(width=args.width, height=args.height, fps=args.fps)

    try:
        cam.start()
        print(f"D455 started: {cam.device_name}, serial={cam.serial}")
        print("把仪表盘放到相机前，尽量居中、占画面主要区域。按 Ctrl+C 结束。")

        count = 0
        tmp_path = Path(tempfile.gettempdir()) / "d455_gauge_frame.jpg"
        last_run = 0.0

        while True:
            image = cam.get_color_image()
            if image is None:
                continue

            now = time.monotonic()
            if now - last_run < args.interval:
                continue
            last_run = now

            # Save to temp file (detector expects a path)
            cv2.imwrite(str(tmp_path), image)

            debug_out = None
            if args.debug_dir:
                debug_out = str(args.debug_dir / f"gauge_live_{count:04d}_debug.jpg")

            result = detect_gauge(str(tmp_path), debug=bool(debug_out), debug_out=debug_out)
            ts = time.strftime("%H:%M:%S")
            valid, reason = is_valid_gauge_result(result, validation_config)
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
        cam.stop()


if __name__ == "__main__":
    main()
