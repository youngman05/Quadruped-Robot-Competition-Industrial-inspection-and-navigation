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
        help="Print extra debug messages.",
    )
    parser.add_argument(
        "--quiet-invalid",
        action="store_true",
        help="Do not print invalid/no-gauge recognition messages.",
    )
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="Do not open the live camera preview window.",
    )
    parser.add_argument(
        "--window-name",
        default="D455 Gauge Recognition",
        help="OpenCV preview window name.",
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


def draw_status_overlay(image: np.ndarray, valid: bool, result: dict, reason: str, ts: str) -> np.ndarray:
    """Draw the latest recognition status on the live camera frame."""
    frame = image.copy()
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (w, 86), (0, 0, 0), thickness=-1)

    if valid and result:
        level = result.get("level")
        status = result.get("status")
        color_name = result.get("color")
        angle = result.get("angle")
        status_color = (0, 220, 0) if status == "正常" else (0, 0, 255)
        line1 = f"{ts}  VALID  level={level}  status={status}"
        line2 = f"color={color_name}  angle={angle}"
    else:
        status_color = (0, 200, 255)
        line1 = f"{ts}  INVALID"
        line2 = f"reason={reason}"

    cv2.putText(frame, line1, (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2, cv2.LINE_AA)
    cv2.putText(frame, line2, (12, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (230, 230, 230), 2, cv2.LINE_AA)
    cv2.putText(
        frame,
        "Press q to quit",
        (12, h - 18),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return frame


def is_valid_gauge_result(
    result: dict,
    min_color_ratio: float,
    min_direction_score: int,
    min_zone_pixels: int,
    max_zone_fraction: float,
    min_direction_margin: float,
):
    if result is None:
        return False, "no_result"
    if result.get("angle") is None:
        return False, "no_needle_angle"

    level = result.get("level")
    status = result.get("status")
    color = result.get("color")
    if not level or not status or level == "未知" or status == "未知" or not color:
        return False, "unknown_state"

    # Compatibility mode for the original Task 1 detector. That detector returns
    # circle/color/angle/status, but not the newer live-validation confidence
    # fields used by the ROS2 version.
    if "circle_detected" not in result:
        if result.get("circle") and color in {"yellow", "green", "red"}:
            return True, "ok_legacy_detector"
        return False, "no_circle"

    if not result.get("circle_detected"):
        return False, "no_hough_circle"

    coverage = result.get("color_coverage") or {}
    if not coverage:
        return True, "ok_no_confidence_fields"

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

    color_total = max(sum(int(v or 0) for v in zone_counts.values()), 1)
    max_fraction = max(int(zone_counts.get(color) or 0) for color in ("yellow", "green", "red")) / color_total
    if max_fraction > max_zone_fraction:
        return False, f"dominant_color_fraction={max_fraction:.3f}"

    direction_scores = result.get("direction_scores") or {}
    if not direction_scores:
        return True, "ok_no_direction_scores"

    direction_score = int(direction_scores.get(color) or 0)
    if direction_score < min_direction_score:
        return False, f"low_direction_score={direction_score}"

    sorted_scores = sorted((int(v or 0) for v in direction_scores.values()), reverse=True)
    second_score = sorted_scores[1] if len(sorted_scores) > 1 else 0
    if second_score > 0 and direction_score / second_score < min_direction_margin:
        return False, f"weak_direction_margin={direction_score}/{second_score}"

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
    if not args.no_window:
        print("实时图像窗口已启用。按图像窗口中的 q 键可退出。")
        try:
            cv2.startWindowThread()
        except cv2.error:
            pass
        cv2.namedWindow(args.window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(args.window_name, args.width, args.height)
        cv2.moveWindow(args.window_name, 80, 80)

    count = 0
    tmp_path = Path(tempfile.gettempdir()) / "d455_gauge_frame.jpg"
    last_run = 0.0
    window_enabled = not args.no_window
    latest_valid = False
    latest_result = None
    latest_reason = "waiting_for_first_detection"
    latest_ts = time.strftime("%H:%M:%S")

    try:
        while True:
            frames = pipeline.wait_for_frames(5000)
            color_frame = frames.get_color_frame()
            if not color_frame:
                continue

            image = np.asanyarray(color_frame.get_data())
            now = time.monotonic()

            if now - last_run >= args.interval:
                last_run = now

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
                    max_zone_fraction=args.max_zone_fraction,
                    min_direction_margin=args.min_direction_margin,
                )
                latest_valid = valid
                latest_result = result
                latest_reason = reason
                latest_ts = ts

                if not valid:
                    if not args.quiet_invalid:
                        print(f"[{ts}] 未识别到有效仪表盘: {reason}", flush=True)
                else:
                    level = result.get("level")
                    status = result.get("status")
                    color = result.get("color")
                    angle = result.get("angle")
                    print(
                        f"[{ts}] 仪表盘显示{level}，状态{status} "
                        f"(color={color}, angle={angle})",
                        flush=True,
                    )

                count += 1
                if args.frames > 0 and count >= args.frames:
                    if not window_enabled:
                        break

            if window_enabled:
                preview = draw_status_overlay(
                    image, latest_valid, latest_result, latest_reason, latest_ts
                )
                try:
                    cv2.imshow(args.window_name, preview)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                except cv2.error as exc:
                    print(f"OpenCV 图像窗口不可用，已自动关闭窗口显示: {exc}")
                    window_enabled = False

            if args.frames > 0 and count >= args.frames and not window_enabled:
                break
    except KeyboardInterrupt:
        print("\n已停止识别")
    finally:
        pipeline.stop()
        if window_enabled:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
