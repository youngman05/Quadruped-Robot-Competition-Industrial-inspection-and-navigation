"""
Generate two Nav2 PGM maps for the competition:

  phase1 (越障)  — obstacle FREE, grab inflated 15cm, placement strict walls
  phase2 (任务)  — obstacle WALL,  same grab/placement walls

Usage:
  python3 generate_nav2_map.py                  # both maps
  python3 generate_nav2_map.py --phase 1        # phase1 only
"""

from __future__ import annotations

import argparse
import math
import struct
from pathlib import Path

from navi_map_data import FIELD, REGIONS, START_AREA, WALL_REGION_IDS, PLACEMENT_CELLS

OCCUPIED = 0
FREE = 254
UNKNOWN = 205
DEFAULT_RESOLUTION = 0.025
OUT_DIR = Path(__file__).resolve().parent
INFLATE_MM = 150.0  # 抓取区向内膨胀 15cm


def _inflated(mm_rect):
    x, y, w, h = mm_rect
    return (x + INFLATE_MM, y + INFLATE_MM,
            w - 2 * INFLATE_MM, h - 2 * INFLATE_MM)


# ── wall rects per phase ───────────────────────────────────

# 放置区 — 四个格子全部是墙 (不进)
_PLACEMENT_WALLS = [(f"placement_{c}", r.rect) for c, r in PLACEMENT_CELLS.items()]

# 抓取区 — 向内膨胀 15cm
_GRAB_WALL = ("grab_inflated", _inflated(REGIONS["grab"].rect))

# Phase 1: inspection + grab(inflated) + placement(strict)
_PHASE1_WALLS = [_GRAB_WALL] + _PLACEMENT_WALLS

# Phase 2: phase1 + obstacle
_PHASE2_WALLS = _PHASE1_WALLS + [("obstacle_sealed", REGIONS["obstacle"].rect)]


# ── helpers ────────────────────────────────────────────────

def _canvas_width_mm():
    return max(FIELD["width"], START_AREA.rect[0] + START_AREA.rect[2])


def _canvas_height_mm():
    return FIELD["height"]


def _pixel_dims(resolution):
    cols = math.ceil(_canvas_width_mm() / 1000.0 / resolution)
    rows = math.ceil(_canvas_height_mm() / 1000.0 / resolution)
    return cols, rows


def _fill_rect(grid, mm_rect, value, resolution, canvas_h_ros, cols, rows):
    x, y, w, h = mm_rect
    c0 = int(x / 1000.0 / resolution)
    c1 = int((x + w) / 1000.0 / resolution)
    ros_y = (FIELD["height"] - y) / 1000.0
    r0 = int((canvas_h_ros - ros_y) / resolution)
    ros_yb = (FIELD["height"] - (y + h)) / 1000.0
    r1 = int((canvas_h_ros - ros_yb) / resolution)
    for r in range(max(0, r0), min(rows, r1)):
        for c in range(max(0, c0), min(cols, c1)):
            grid[r][c] = value


def _build_grid(extra_walls, resolution):
    cols, rows = _pixel_dims(resolution)
    ch = _canvas_height_mm() / 1000.0
    grid = [[UNKNOWN] * cols for _ in range(rows)]

    # field → FREE
    fc = int(FIELD["width"] / 1000.0 / resolution)
    fr = int(FIELD["height"] / 1000.0 / resolution)
    fr0 = int((ch - FIELD["height"] / 1000.0) / resolution)
    for r in range(max(0, fr0), min(rows, fr0 + fr)):
        for c in range(min(cols, fc)):
            grid[r][c] = FREE

    # start area → FREE
    _fill_rect(grid, START_AREA.rect, FREE, resolution, ch, cols, rows)

    # inspection walls
    for rid in WALL_REGION_IDS:
        _fill_rect(grid, REGIONS[rid].rect, OCCUPIED, resolution, ch, cols, rows)

    # extra walls
    for _, rect in extra_walls:
        _fill_rect(grid, rect, OCCUPIED, resolution, ch, cols, rows)

    return grid, cols, rows


def _write(grid, cols, rows, resolution, pgm_path, yaml_path):
    pgm_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pgm_path, "wb") as f:
        f.write(f"P5\n{cols} {rows}\n255\n".encode())
        for row in grid:
            f.write(struct.pack("B" * cols, *row))
    yaml_path.write_text(
        f"image: {pgm_path.name}\n"
        f"mode: trinary\n"
        f"resolution: {resolution}\n"
        f"origin: [0.0, 0.0, 0.0]\n"
        f"negate: 0\n"
        f"occupied_thresh: 0.65\n"
        f"free_thresh: 0.25\n"
    )
    f = sum(row.count(FREE) for row in grid)
    w = sum(row.count(OCCUPIED) for row in grid)
    u = sum(row.count(UNKNOWN) for row in grid)
    print(f"  {pgm_path.name}: {cols}x{rows} px  {f} free | {w} wall | {u} unk")


# ── main ───────────────────────────────────────────────────

def generate_all(output_dir=None, resolution=DEFAULT_RESOLUTION):
    if output_dir is None:
        output_dir = OUT_DIR
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for phase, walls, fname in [
        (1, _PHASE1_WALLS, "competition_field_phase1.pgm"),
        (2, _PHASE2_WALLS, "competition_field_phase2.pgm"),
    ]:
        print(f"\n── Phase {phase} ──")
        grid, cols, rows = _build_grid(walls, resolution)
        _write(grid, cols, rows, resolution,
               output_dir / fname,
               output_dir / fname.replace(".pgm", ".yaml"))
    print(f"\nDone → {output_dir}/")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=str, default=None)
    p.add_argument("--resolution", type=float, default=DEFAULT_RESOLUTION)
    p.add_argument("--phase", type=int, choices=[1, 2], default=0)
    args = p.parse_args()
    out = Path(args.output) if args.output else OUT_DIR
    if args.phase in (1, 2):
        walls = _PHASE1_WALLS if args.phase == 1 else _PHASE2_WALLS
        fname = f"competition_field_phase{args.phase}.pgm"
        grid, cols, rows = _build_grid(walls, args.resolution)
        _write(grid, cols, rows, args.resolution, out / fname, out / fname.replace(".pgm", ".yaml"))
    else:
        generate_all(args.output, args.resolution)


if __name__ == "__main__":
    main()
