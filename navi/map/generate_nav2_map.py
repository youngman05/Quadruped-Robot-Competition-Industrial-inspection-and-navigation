"""
Generate Nav2-compatible PGM occupancy grid + YAML metadata
from the authoritative field data in navi_map_data.py.

Output: competition_field.pgm + competition_field.yaml

Coordinate mapping (mm → ROS):
  ros_x = mm_x / 1000.0
  ros_y = (6000 - mm_y) / 1000.0    # flip y: top→bottom to bottom→top

Pixel mapping (ROS → PGM row/col):
  col = ros_x / resolution
  row = (canvas_height_ros - ros_y) / resolution

Usage:
  python3 generate_nav2_map.py                    # default output to current dir
  python3 generate_nav2_map.py --output ./out      # custom output directory
  python3 generate_nav2_map.py --resolution 0.05   # lower resolution (50mm/px)
"""

from __future__ import annotations

import argparse
import math
import struct
from pathlib import Path

from navi_map_data import FIELD, REGIONS, START_AREA, WALL_REGION_IDS

# ── constants ──────────────────────────────────────────────
OCCUPIED = 0       # black  — wall / obstacle
FREE = 254         # white  — traversable
UNKNOWN = 205      # gray   — unexplored / outside field

DEFAULT_RESOLUTION = 0.025   # 25 mm/px
OUT_DIR = Path(__file__).resolve().parent
PGM_NAME = "competition_field.pgm"
YAML_NAME = "competition_field.yaml"


# ── helpers ────────────────────────────────────────────────

def _canvas_width_mm() -> float:
    """Total canvas width including start area outside the right boundary."""
    return max(FIELD["width"], START_AREA.rect[0] + START_AREA.rect[2])


def _canvas_height_mm() -> float:
    return FIELD["height"]


def _pixel_dims(resolution: float):
    """Return (cols, rows) for the output PGM."""
    cols = math.ceil(_canvas_width_mm() / 1000.0 / resolution)
    rows = math.ceil(_canvas_height_mm() / 1000.0 / resolution)
    return cols, rows


# ── main generator ─────────────────────────────────────────

def generate(output_dir: Path | None = None, resolution: float = DEFAULT_RESOLUTION):
    if output_dir is None:
        output_dir = OUT_DIR
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cols, rows = _pixel_dims(resolution)
    canvas_height_ros = _canvas_height_mm() / 1000.0

    # initialise entire grid as UNKNOWN
    grid = [[UNKNOWN] * cols for _ in range(rows)]

    # ── fill field interior as FREE ────────────────────
    field_cols = int(FIELD["width"] / 1000.0 / resolution)
    field_rows = int(FIELD["height"] / 1000.0 / resolution)
    field_row_start = int((canvas_height_ros - FIELD["height"] / 1000.0) / resolution)
    field_row_end = field_row_start + field_rows

    for r in range(max(0, field_row_start), min(rows, field_row_end)):
        for c in range(min(cols, field_cols)):
            grid[r][c] = FREE

    # ── fill start area as FREE ────────────────────────
    sx, sy, sw, sh = START_AREA.rect
    start_ros_y = (FIELD["height"] - sy) / 1000.0
    sc0 = int(sx / 1000.0 / resolution)
    sc1 = int((sx + sw) / 1000.0 / resolution)
    sr0 = int((canvas_height_ros - start_ros_y) / resolution)
    sr1 = int((canvas_height_ros - (start_ros_y - sh / 1000.0)) / resolution)
    for r in range(max(0, sr0), min(rows, sr1)):
        for c in range(max(0, sc0), min(cols, sc1)):
            grid[r][c] = FREE

    # ── fill wall regions as OCCUPIED ─────────────────
    for region_id in WALL_REGION_IDS:
        region = REGIONS[region_id]
        x, y, w, h = region.rect
        ros_y = (FIELD["height"] - y) / 1000.0
        c0 = int(x / 1000.0 / resolution)
        c1 = int((x + w) / 1000.0 / resolution)
        r0 = int((canvas_height_ros - ros_y) / resolution)
        r1 = int((canvas_height_ros - (ros_y - h / 1000.0)) / resolution)
        for r in range(max(0, r0), min(rows, r1)):
            for c in range(max(0, c0), min(cols, c1)):
                grid[r][c] = OCCUPIED

    # ── write PGM (P5 binary) ─────────────────────────
    pgm_path = output_dir / PGM_NAME
    with open(pgm_path, "wb") as f:
        f.write(f"P5\n{cols} {rows}\n255\n".encode())
        for row in grid:
            f.write(struct.pack("B" * cols, *row))
    print(f"PGM saved: {pgm_path}  ({cols}x{rows} px, {resolution*1000:.0f} mm/px)")

    # ── write YAML ─────────────────────────────────────
    yaml_path = output_dir / YAML_NAME
    yaml_content = f"""image: {PGM_NAME}
mode: trinary
resolution: {resolution}
origin: [0.0, 0.0, 0.0]
negate: 0
occupied_thresh: 0.65
free_thresh: 0.25
"""
    yaml_path.write_text(yaml_content)
    print(f"YAML saved: {yaml_path}")

    # ── summary ────────────────────────────────────────
    free_px = sum(row.count(FREE) for row in grid)
    wall_px = sum(row.count(OCCUPIED) for row in grid)
    unk_px = sum(row.count(UNKNOWN) for row in grid)
    print(f"Summary: {free_px} free  |  {wall_px} occupied  |  {unk_px} unknown")

    return pgm_path, yaml_path


# ── CLI ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate Nav2 PGM map from field data.")
    parser.add_argument("--output", type=str, default=None, help="Output directory")
    parser.add_argument("--resolution", type=float, default=DEFAULT_RESOLUTION,
                        help=f"Grid resolution in m/px (default {DEFAULT_RESOLUTION})")
    args = parser.parse_args()
    generate(output_dir=args.output, resolution=args.resolution)


if __name__ == "__main__":
    main()
