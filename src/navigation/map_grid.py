"""
Occupancy grid builder — builds a 2D numpy grid directly from navi_map_data
at runtime, replacing the Nav2 PGM+YAML map_server pipeline.

Supports two phases:
  phase1 — obstacle area OPEN (traversable, cones handled by depth camera)
  phase2 — obstacle area SEALED (wall, robot stays in safe zone)

Coordinate systems:
  mm  (navi_map_data): origin top-left, +x right, +y down
  ROS map:             origin bottom-left, +x right, +y up, unit meters
  Grid:                row 0 = top (max ROS y), col 0 = left (ROS x = 0)
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Tuple

import numpy as np

# Allow import from navi/map
_WS_ROOT = Path(__file__).resolve().parents[2]  # navigation → src → root
_NAVI_MAP = _WS_ROOT / "navi" / "map"
if str(_NAVI_MAP) not in sys.path:
    sys.path.insert(0, str(_NAVI_MAP))

from navi_map_data import (  # noqa: E402
    FIELD,
    REGIONS,
    START_AREA,
    WALL_REGION_IDS,
    PLACEMENT_CELLS,
)

# ── Constants ──────────────────────────────────────────────────
RESOLUTION = 0.025          # meters per cell
OCCUPIED: int = 0           # A* blocked cell
FREE: int = 254             # A* traversable cell

# Grid dimensions
_CANVAS_WIDTH_MM = max(FIELD["width"], START_AREA.rect[0] + START_AREA.rect[2])  # 5650
_CANVAS_HEIGHT_MM = FIELD["height"]  # 6000
COLS = math.ceil(_CANVAS_WIDTH_MM / 1000.0 / RESOLUTION)    # 226
ROWS = math.ceil(_CANVAS_HEIGHT_MM / 1000.0 / RESOLUTION)   # 240

# Grab area inflation: walls shrink 15cm inward from region edges
INFLATE_MM = 150.0


# ── Wall rects per phase ───────────────────────────────────────

def _inflated(mm_rect: Tuple[float, float, float, float]):
    """Shrink rect inward by INFLATE_MM on all sides."""
    x, y, w, h = mm_rect
    return (x + INFLATE_MM, y + INFLATE_MM,
            w - 2 * INFLATE_MM, h - 2 * INFLATE_MM)


# Placement cells — four 500×500mm cells, always walls
_PLACEMENT_WALLS = [(f"placement_{c}", r.rect) for c, r in PLACEMENT_CELLS.items()]

# Grab area — inflated 15cm inward
_GRAB_WALL = ("grab_inflated", _inflated(REGIONS["grab"].rect))

# Phase 1: inspection walls + grab(inflated) + placement(strict)
_PHASE1_WALLS = [_GRAB_WALL] + _PLACEMENT_WALLS

# Phase 2: phase1 + obstacle area sealed
_PHASE2_WALLS = _PHASE1_WALLS + [("obstacle_sealed", REGIONS["obstacle"].rect)]


# ── Internal helpers ───────────────────────────────────────────

def _fill_rect(grid: np.ndarray, mm_rect: Tuple[float, float, float, float],
               value: int) -> None:
    """Fill a rectangular region in the grid. mm_rect in mm coords (top-left origin)."""
    x, y, w, h = mm_rect
    # Grid row 0 = ROS y max = 6.0m. row = (6.0 - ros_y) / resolution
    ros_y_top = (FIELD["height"] - y) / 1000.0
    ros_y_bot = (FIELD["height"] - (y + h)) / 1000.0
    # PGM convention: row increases downward = higher ROS y is higher in image
    r0 = int(round((_CANVAS_HEIGHT_MM / 1000.0 - ros_y_top) / RESOLUTION))
    r1 = int(round((_CANVAS_HEIGHT_MM / 1000.0 - ros_y_bot) / RESOLUTION))
    c0 = int(round(x / 1000.0 / RESOLUTION))
    c1 = int(round((x + w) / 1000.0 / RESOLUTION))
    # Clamp
    r0, r1 = max(0, r0), min(ROWS, r1)
    c0, c1 = max(0, c0), min(COLS, c1)
    if r0 < r1 and c0 < c1:
        grid[r0:r1, c0:c1] = value


# ── Public API ───────────────────────────────────────────────────

def build_grid(phase: str = "phase1") -> np.ndarray:
    """
    Build occupancy grid for the given competition phase.

    Args:
        phase: "phase1" (obstacle area free) or "phase2" (obstacle area sealed).

    Returns:
        np.ndarray of shape (ROWS, COLS), dtype uint8.
        OCCUPIED=0 for blocked cells, FREE=254 for traversable.
    """
    grid = np.full((ROWS, COLS), FREE, dtype=np.uint8)

    # Main field area is already FREE from np.full. We only need to fill
    # occupied regions (walls). The canvas already covers start area + field.

    # Inspection walls (always occupied)
    for rid in WALL_REGION_IDS:
        if rid in REGIONS:
            _fill_rect(grid, REGIONS[rid].rect, OCCUPIED)

    # Phase-specific walls
    walls = _PHASE1_WALLS if phase == "phase1" else _PHASE2_WALLS
    for _name, rect in walls:
        _fill_rect(grid, rect, OCCUPIED)

    return grid


def mm_to_grid(x_mm: float, y_mm: float) -> Tuple[int, int]:
    """
    Convert mm field coordinates (top-left origin, +y down) to grid (row, col).

    Args:
        x_mm, y_mm: Position in millimeters from top-left of field.

    Returns:
        (row, col) tuple for grid indexing.
    """
    ros_x = x_mm / 1000.0
    ros_y = (FIELD["height"] - y_mm) / 1000.0
    col = int(round(ros_x / RESOLUTION))
    row = int(round((_CANVAS_HEIGHT_MM / 1000.0 - ros_y) / RESOLUTION))
    # Clamp
    col = max(0, min(COLS - 1, col))
    row = max(0, min(ROWS - 1, row))
    return row, col


def grid_to_ros(row: int, col: int) -> Tuple[float, float]:
    """
    Convert grid coordinates to ROS map coordinates (bottom-left origin, +y up).

    Args:
        row, col: Grid indices.

    Returns:
        (x_m, y_m) tuple in ROS map frame.
    """
    ros_x = col * RESOLUTION
    # Grid row 0 = Y = 6.0m, grid row ROWS-1 = Y = 0m
    ros_y = (ROWS - row) * RESOLUTION
    return ros_x, ros_y


def ros_to_grid(x_m: float, y_m: float) -> Tuple[int, int]:
    """
    Convert ROS map coordinates to grid (row, col).

    Args:
        x_m, y_m: Position in meters, ROS map frame (bottom-left origin).

    Returns:
        (row, col) tuple, clamped to grid bounds.
    """
    col = int(round(x_m / RESOLUTION))
    row = int(round((_CANVAS_HEIGHT_MM / 1000.0 - y_m) / RESOLUTION))
    col = max(0, min(COLS - 1, col))
    row = max(0, min(ROWS - 1, row))
    return row, col


def grid_bounds() -> Tuple[int, int]:
    """Return (rows, cols) of the occupancy grid."""
    return ROWS, COLS
