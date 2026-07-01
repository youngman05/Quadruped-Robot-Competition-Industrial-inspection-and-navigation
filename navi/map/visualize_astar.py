"""
Visualize A* planned path on the competition field grid.

Usage:
    python navi/map/visualize_astar.py                          # default path
    python navi/map/visualize_astar.py --from start --to pos1_middle
    python navi/map/visualize_astar.py --phase phase2 --from pos1_middle --to grab_area
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

# ── Waypoints (mm coords) ──────────────────────────────
_WAYPOINTS_MM = {
    "start":              (5350, 5250),
    "obstacle_exit":      (600, 5250),
    "pos1_middle":        (1500, 2750),
    "pos1_middle_turned": (1500, 2750),
    "pos2a_upper_right":  (2200, 1500),
    "pos2b_lower_right":  (2200, 4000),
    "grab_area":          (4250, 3450),
    "placement_A":        (3250, 600),
    "placement_B":        (3750, 600),
    "placement_C":        (4250, 600),
    "placement_D":        (4750, 600),
}

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from navigation.map_grid import build_grid, mm_to_grid, grid_to_ros
from navigation.astar_planner import AStarPlanner, PlannerConfig


def _mm_to_ros(x, y):
    return x / 1000.0, (6000 - y) / 1000.0


def render(grid, path_ros, waypoint_labels, output_path):
    """Render grid + path + waypoints as PNG."""
    rows, cols = grid.shape
    scale = 4  # pixels per cell
    img = np.zeros((rows * scale, cols * scale, 3), dtype=np.uint8)

    # Grid
    free_mask = grid == 254
    wall_mask = grid == 0
    img[free_mask.repeat(scale, axis=0).repeat(scale, axis=1)] = (240, 240, 240)
    img[wall_mask.repeat(scale, axis=0).repeat(scale, axis=1)] = (60, 60, 80)

    # Path
    if path_ros:
        pts = []
        for x, y in path_ros:
            col = int(x / 0.025 * scale)
            row = int((6.0 - y) / 0.025 * scale)
            pts.append((col, row))
        for i in range(len(pts) - 1):
            cv2.line(img, pts[i], pts[i + 1], (0, 220, 0), 4)
        for col, row in pts:
            cv2.circle(img, (col, row), 6, (0, 255, 0), -1)

    # Waypoints
    for name, (x_mm, y_mm) in waypoint_labels.items():
        x, y = _mm_to_ros(x_mm, y_mm)
        col = int(x / 0.025 * scale)
        row = int((6.0 - y) / 0.025 * scale)
        # Orange circle for waypoints
        cv2.circle(img, (col, row), 10, (0, 140, 255), -1)
        cv2.putText(img, name, (col + 12, row + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

    cv2.imwrite(str(output_path), img)
    print(f"Saved: {output_path}")
    return img


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="from_wp", default="start")
    p.add_argument("--to", dest="to_wp", default="pos1_middle")
    p.add_argument("--phase", default="phase1", choices=["phase1", "phase2"])
    p.add_argument("--output", default=None)
    p.add_argument("--show-all-waypoints", action="store_true", default=True)
    args = p.parse_args()

    out = Path(args.output) if args.output else (
        Path(__file__).resolve().parent /
        f"astar_{args.from_wp}_to_{args.to_wp}_{args.phase}.png"
    )

    # Build grid and plan
    print(f"Phase: {args.phase}")
    grid = build_grid(args.phase)
    planner_config = PlannerConfig(inflation_radius_m=0.15, goal_tolerance_m=0.15)
    planner = AStarPlanner(grid, planner_config)

    start_xy = _mm_to_ros(*_WAYPOINTS_MM[args.from_wp])
    goal_xy = _mm_to_ros(*_WAYPOINTS_MM[args.to_wp])
    print(f"Planning: {args.from_wp}({start_xy[0]:.2f},{start_xy[1]:.2f}) → "
          f"{args.to_wp}({goal_xy[0]:.2f},{goal_xy[1]:.2f})")

    path = planner.plan(start_xy, goal_xy)
    if path is None:
        print("NO PATH FOUND")
        path = []
    else:
        dist = sum(np.hypot(path[i+1][0]-path[i][0], path[i+1][1]-path[i][1])
                   for i in range(len(path)-1))
        print(f"Path: {len(path)} waypoints, {dist:.2f}m")

    # Labels for start and goal
    labels = {args.from_wp: _WAYPOINTS_MM[args.from_wp],
              args.to_wp: _WAYPOINTS_MM[args.to_wp]}
    if args.show_all_waypoints:
        for name, wp in _WAYPOINTS_MM.items():
            if name not in labels:
                labels[name] = wp

    render(grid, path, labels, out)


if __name__ == "__main__":
    main()
