"""
A* path planner — 8-connected grid search on the occupancy grid.

Features:
- 8-connected (includes diagonals, cost sqrt(2) × cardinal)
- Euclidean distance heuristic
- Obstacle inflation to account for robot footprint
- Path simplification (collinear point removal) + waypoint downsampling
- Goal tolerance: stops search within ~6 cells of goal
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from .map_grid import (
    COLS,
    ROWS,
    FREE,
    OCCUPIED,
    RESOLUTION,
    ros_to_grid,
    grid_to_ros,
)


@dataclass
class PlannerConfig:
    """A* planner configuration."""
    inflation_radius_m: float = 0.05   # inflate occupied cells by robot half-width
    goal_tolerance_m: float = 0.05     # stop search near goal
    waypoint_spacing_m: float = 0.3    # spacing between output waypoints


class AStarPlanner:
    """
    8-connected A* grid planner for the competition field.

    Usage:
        planner = AStarPlanner(grid, config)
        path = planner.plan((start_x, start_y), (goal_x, goal_y))
        if path is None:
            ...  # no path found
        else:
            ...  # path is list of (x_m, y_m) in ROS map coords
    """

    def __init__(self, grid: np.ndarray, config: PlannerConfig = None):
        self._config = config or PlannerConfig()
        self._grid: np.ndarray = grid
        self._inflated: np.ndarray = self._inflate_obstacles(grid)
        self._rows, self._cols = grid.shape

    # ── public API ────────────────────────────────────────────

    def set_grid(self, grid: np.ndarray) -> None:
        """Replace the occupancy grid (e.g., for phase switching)."""
        self._grid = grid
        self._inflated = self._inflate_obstacles(grid)

    def plan(
        self,
        start_xy: Tuple[float, float],
        goal_xy: Tuple[float, float],
    ) -> Optional[List[Tuple[float, float]]]:
        """
        Plan a path from start to goal.

        Args:
            start_xy: (x_m, y_m) in ROS map coordinates.
            goal_xy: (x_m, y_m) in ROS map coordinates.

        Returns:
            List of (x_m, y_m) waypoints from start to goal (excluding start),
            or None if no path found.
        """
        sr, sc = ros_to_grid(*start_xy)
        gr, gc = ros_to_grid(*goal_xy)

        # Clamp to grid
        sr = max(0, min(self._rows - 1, sr))
        sc = max(0, min(self._cols - 1, sc))
        gr = max(0, min(self._rows - 1, gr))
        gc = max(0, min(self._cols - 1, gc))

        # If start or goal is blocked by inflation, find nearest free cell
        if self._inflated[sr, sc] == OCCUPIED:
            sr, sc = self._find_nearest_free(sr, sc)
            if sr is None:
                return None
        if self._inflated[gr, gc] == OCCUPIED:
            gr, gc = self._find_nearest_free(gr, gc)
            if gr is None:
                return None

        # A* search
        path_grid = self._search(sr, sc, gr, gc)
        if path_grid is None:
            return None

        # Simplify and downsample
        simplified = self._simplify_path(path_grid)
        downsampled = self._downsample(simplified)

        # Convert to ROS coordinates
        return [grid_to_ros(r, c) for r, c in downsampled]

    # ── internal ───────────────────────────────────────────────

    def _inflate_obstacles(self, grid: np.ndarray) -> np.ndarray:
        """Dilate occupied cells by inflation_radius_m to account for robot footprint."""
        inflate_cells = int(math.ceil(self._config.inflation_radius_m / RESOLUTION))
        if inflate_cells <= 0:
            return grid.copy()

        # Dilate occupied cells by painting a circle around each one.
        # For grids this small (226×240, ~54k cells), direct iteration
        # over occupied cells is fast enough (~5ms one-time cost per phase).
        occupied_mask = grid == OCCUPIED
        occ_rows, occ_cols = np.where(occupied_mask)
        inflated = grid.astype(np.uint8).copy()

        # Precompute circle offsets
        offsets = []
        r2 = inflate_cells * inflate_cells
        for dr in range(-inflate_cells, inflate_cells + 1):
            for dc in range(-inflate_cells, inflate_cells + 1):
                if dr * dr + dc * dc <= r2:
                    offsets.append((dr, dc))

        rows, cols = grid.shape
        for r, c in zip(occ_rows, occ_cols):
            for dr, dc in offsets:
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    inflated[nr, nc] = OCCUPIED

        return inflated

    def _find_nearest_free(self, r: int, c: int, max_dist: int = 30):
        """BFS to find nearest non-occupied cell. Returns (row, col) or (None, None)."""
        from collections import deque
        if self._inflated[r, c] != OCCUPIED:
            return r, c
        visited = {(r, c)}
        q = deque([(r, c)])
        while q:
            cr, cc = q.popleft()
            for dr, dc in [(0,1),(0,-1),(1,0),(-1,0),(1,1),(1,-1),(-1,1),(-1,-1)]:
                nr, nc = cr + dr, cc + dc
                if (nr, nc) in visited:
                    continue
                if not (0 <= nr < self._rows and 0 <= nc < self._cols):
                    continue
                if (nr - r) ** 2 + (nc - c) ** 2 > max_dist * max_dist:
                    continue
                if self._inflated[nr, nc] != OCCUPIED:
                    return nr, nc
                visited.add((nr, nc))
                q.append((nr, nc))
        return None, None

    def _search(
        self, sr: int, sc: int, gr: int, gc: int,
    ) -> Optional[List[Tuple[int, int]]]:
        """
        A* search on the inflated grid. Returns list of grid (row, col) from
        start to goal, or None if no path.
        """
        resolution_m = RESOLUTION
        tolerance_cells = int(math.ceil(self._config.goal_tolerance_m / resolution_m))

        # 8-connected neighbors: (dr, dc, cost)
        diag_cost = resolution_m * math.sqrt(2)
        neighbors = [
            (-1,  0, resolution_m), (1,  0, resolution_m),
            (0, -1, resolution_m),  (0,  1, resolution_m),
            (-1, -1, diag_cost),    (-1,  1, diag_cost),
            (1, -1, diag_cost),     (1,  1, diag_cost),
        ]

        # A* state
        open_set = [(0.0, 0, sr, sc)]  # (f_score, tiebreaker, row, col)
        g_score = {(sr, sc): 0.0}
        parent = {}
        tiebreaker = 0
        max_iter = 50000  # safety limit

        while open_set and tiebreaker < max_iter:
            f_val, _, r, c = heapq.heappop(open_set)

            # Goal check: within tolerance cells
            if abs(r - gr) <= tolerance_cells and abs(c - gc) <= tolerance_cells:
                # Reconstruct path
                path = [(r, c)]
                cur = (r, c)
                while cur in parent:
                    cur = parent[cur]
                    path.append(cur)
                path.reverse()
                # If close to goal but not exact, append the actual goal
                if (gr, gc) != (r, c):
                    path.append((gr, gc))
                return path

            cur_g = g_score.get((r, c), float('inf'))

            for dr, dc, cost in neighbors:
                nr, nc = r + dr, c + dc
                if not (0 <= nr < self._rows and 0 <= nc < self._cols):
                    continue
                if self._inflated[nr, nc] == OCCUPIED:
                    continue
                new_g = cur_g + cost
                if new_g < g_score.get((nr, nc), float('inf')):
                    g_score[(nr, nc)] = new_g
                    # Heuristic: Euclidean distance to goal
                    h = math.hypot(nr - gr, nc - gc) * resolution_m
                    tiebreaker += 1
                    heapq.heappush(open_set, (new_g + h, tiebreaker, nr, nc))
                    parent[(nr, nc)] = (r, c)

        return None  # no path

    @staticmethod
    def _simplify_path(path: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
        """Remove collinear intermediate points (grid-space)."""
        if len(path) <= 2:
            return path

        result = [path[0]]
        for i in range(1, len(path) - 1):
            prev_r, prev_c = result[-1]
            cur_r, cur_c = path[i]
            next_r, next_c = path[i + 1]

            # Check if prev→cur→next are collinear
            # Cross product of (cur-prev) and (next-cur) should be 0
            dx1 = cur_c - prev_c
            dy1 = cur_r - prev_r
            dx2 = next_c - cur_c
            dy2 = next_r - cur_r
            if dx1 * dy2 != dy1 * dx2:
                # Not collinear — keep this point
                result.append(path[i])

        result.append(path[-1])
        return result

    @staticmethod
    def _downsample(
        path: List[Tuple[int, int]],
        spacing_m: float = 0.3,
    ) -> List[Tuple[int, int]]:
        """Downsample path to approximately spacing_m between waypoints."""
        if len(path) <= 2:
            return path

        spacing_cells = spacing_m / RESOLUTION
        result = [path[0]]
        last = path[0]
        for pt in path[1:-1]:
            if math.hypot(pt[0] - last[0], pt[1] - last[1]) >= spacing_cells:
                result.append(pt)
                last = pt
        result.append(path[-1])
        return result
