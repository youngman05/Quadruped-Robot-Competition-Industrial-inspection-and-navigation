#!/usr/bin/env python3
"""Probe Docker depth relay output with a simple hysteresis safety gate.

This is a conservative 2D depth-image gate for field debugging. It does not
replace a full pointcloud transform, but it is useful for checking D455 relay
health and STOP/CLEAR hysteresis before connecting motion.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass

import numpy as np


@dataclass
class GateState:
    state: str = "CLEAR"
    last_danger_time: float = 0.0


def parse_meta(path: str) -> tuple[int, int, float]:
    with open(path, "r", encoding="utf-8") as f:
        parts = f.read().strip().split()
    if len(parts) < 2:
        raise RuntimeError(f"invalid depth meta: {path}")
    width = int(parts[0])
    height = int(parts[1])
    stamp = float(parts[2]) if len(parts) >= 3 else 0.0
    return width, height, stamp


def classify_depth(depth: np.ndarray, args: argparse.Namespace) -> tuple[str, int, float]:
    h, w = depth.shape
    x0 = int(w * (0.5 - args.roi_width_frac / 2.0))
    x1 = int(w * (0.5 + args.roi_width_frac / 2.0))
    y0 = int(h * args.roi_top_frac)
    y1 = int(h * args.roi_bottom_frac)
    roi = depth[y0:y1, x0:x1].astype(np.float32) * args.depth_scale
    valid = (roi >= args.min_depth_m) & (roi <= args.max_depth_m)
    count = int(np.count_nonzero(valid))
    nearest = float(np.min(roi[valid])) if count else float("inf")

    if count >= args.stop_count or nearest <= args.stop_depth_m:
        return "STOP", count, nearest
    if count >= args.slow_count or nearest <= args.slow_depth_m:
        return "SLOW", count, nearest
    return "CLEAR", count, nearest


def apply_hysteresis(raw: str, gate: GateState, clear_hold_sec: float) -> str:
    now = time.time()
    if raw in ("STOP", "SLOW"):
        gate.state = raw
        gate.last_danger_time = now
        return gate.state
    if now - gate.last_danger_time < clear_hold_sec:
        return gate.state
    gate.state = "CLEAR"
    return gate.state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--frames-dir",
        default=os.path.expanduser("~/isaac_ros-dev/camera_frames"),
        help="Host path mapped to Docker /workspaces/isaac_ros-dev/camera_frames.",
    )
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--rate-hz", type=float, default=10.0)
    parser.add_argument("--depth-scale", type=float, default=0.001)
    parser.add_argument("--min-depth-m", type=float, default=0.25)
    parser.add_argument("--max-depth-m", type=float, default=1.20)
    parser.add_argument("--slow-depth-m", type=float, default=1.00)
    parser.add_argument("--stop-depth-m", type=float, default=0.60)
    parser.add_argument("--slow-count", type=int, default=80)
    parser.add_argument("--stop-count", type=int, default=250)
    parser.add_argument("--clear-hold-sec", type=float, default=0.8)
    parser.add_argument("--roi-width-frac", type=float, default=0.45)
    parser.add_argument("--roi-top-frac", type=float, default=0.35)
    parser.add_argument("--roi-bottom-frac", type=float, default=0.85)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    depth_path = os.path.join(args.frames_dir, "latest_depth.raw")
    meta_path = os.path.join(args.frames_dir, "latest_depth_meta.txt")
    gate = GateState()
    period = 1.0 / max(1.0, args.rate_hz)
    deadline = time.time() + args.duration
    last_stamp = None

    print(f"Depth safety gate probe: {depth_path}")
    while time.time() < deadline:
        try:
            width, height, stamp = parse_meta(meta_path)
            raw = np.fromfile(depth_path, dtype=np.uint16)
            if raw.size != width * height:
                raise RuntimeError(
                    f"depth size mismatch: {raw.size} != {width}*{height}"
                )
            depth = raw.reshape(height, width)
            raw_state, count, nearest = classify_depth(depth, args)
            state = apply_hysteresis(raw_state, gate, args.clear_hold_sec)
            stamp_mark = "*" if stamp != last_stamp else " "
            last_stamp = stamp
            nearest_text = "inf" if not np.isfinite(nearest) else f"{nearest:.3f}"
            print(
                f"{stamp_mark} raw={raw_state:<5} gate={state:<5} "
                f"count={count:<5} nearest={nearest_text}m stamp={stamp:.3f}",
                flush=True,
            )
        except Exception as exc:
            print(f"WARN: {exc}", flush=True)
        time.sleep(period)
    return 0


if __name__ == "__main__":
    sys.exit(main())
