"""
Pure Pursuit controller — follows a path of waypoints by computing
velocity commands, with support for turn-in-place and goal orientation.

Robot can turn in place (no minimum turning radius), so pure pursuit
without kinematic constraints is sufficient.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Optional, Tuple


@dataclass
class PursuitConfig:
    """Pure pursuit controller configuration."""
    lookahead_distance_m: float = 0.5    # base lookahead
    min_lookahead_m: float = 0.3         # minimum (at low speed)
    max_lookahead_m: float = 0.9         # maximum (at high speed)
    max_linear_vel: float = 0.25         # m/s
    max_angular_vel: float = 0.5         # rad/s
    goal_tolerance_m: float = 0.05       # position tolerance
    yaw_tolerance_rad: float = 0.25      # orientation tolerance
    turn_in_place_threshold_rad: float = 0.3  # if yaw error > this, turn first
    k_linear: float = 0.8               # proportional gain for velocity
    k_angular: float = 1.5              # proportional gain for angular correction


def _normalize_angle(a: float) -> float:
    """Normalize angle to [-pi, pi)."""
    return math.atan2(math.sin(a), math.cos(a))


def _shortest_angular_dist(target: float, current: float) -> float:
    """Shortest signed angular distance from current to target."""
    return _normalize_angle(target - current)


class PurePursuitController:
    """
    Pure pursuit path-following controller.

    Usage per control cycle:
        vx, vz = controller.compute_velocity(robot_x, robot_y, robot_yaw, path, goal_yaw)
        # publish vx, vz to /cmd_vel

        if controller.is_goal_reached(robot_x, robot_y, goal, robot_yaw, goal_yaw):
            # navigation complete
    """

    def __init__(self, config: PursuitConfig = None):
        self._cfg = config or PursuitConfig()
        self._arrived_at_position = False

    def reset(self) -> None:
        """Reset internal state for a new path."""
        self._arrived_at_position = False

    def compute_velocity(
        self,
        current_x: float,
        current_y: float,
        current_yaw: float,
        path: List[Tuple[float, float]],
        goal_yaw: Optional[float] = None,
    ) -> Tuple[float, float]:
        """
        Compute velocity command for one control cycle.

        Args:
            current_x, current_y: Robot position in ROS map frame (meters).
            current_yaw: Robot heading in radians.
            path: List of (x_m, y_m) waypoints (from A* planner).
            goal_yaw: Optional desired final heading.

        Returns:
            (linear_x, angular_z) in m/s and rad/s.
        """
        if not path:
            return 0.0, 0.0

        goal_x, goal_y = path[-1]
        dist_to_goal = math.hypot(goal_x - current_x, goal_y - current_y)

        # ── Goal position reached? ──────────────────────
        if dist_to_goal < self._cfg.goal_tolerance_m:
            self._arrived_at_position = True
            # If goal yaw is specified, turn to match it
            if goal_yaw is not None:
                yaw_err = _shortest_angular_dist(goal_yaw, current_yaw)
                if abs(yaw_err) < self._cfg.yaw_tolerance_rad:
                    return 0.0, 0.0  # fully done
                # Turn in place to match goal yaw
                az = self._cfg.k_angular * yaw_err
                az = max(-self._cfg.max_angular_vel, min(self._cfg.max_angular_vel, az))
                return 0.0, az
            return 0.0, 0.0  # done, no yaw requirement
        else:
            self._arrived_at_position = False

        # ── Find lookahead point ─────────────────────────
        la_point = self._find_lookahead(current_x, current_y, path)
        if la_point is None:
            # All path points are behind us or path empty — head to goal
            la_point = path[-1]

        la_x, la_y = la_point
        la_dist = math.hypot(la_x - current_x, la_y - current_y)

        # ── Transform lookahead to robot frame ───────────
        # local_x: forward, local_y: lateral (cross-track error)
        dx = la_x - current_x
        dy = la_y - current_y
        cos_yaw = math.cos(-current_yaw)
        sin_yaw = math.sin(-current_yaw)
        local_x = dx * cos_yaw - dy * sin_yaw
        local_y = dx * sin_yaw + dy * cos_yaw

        # Dynamically scale lookahead with speed
        effective_la = self._cfg.lookahead_distance_m
        if la_dist < effective_la:
            effective_la = max(self._cfg.min_lookahead_m, la_dist)

        # ── Compute curvature from pure pursuit geometry ─
        # curvature = 2 * lateral_error / lookahead²
        curvature = 2.0 * local_y / max(effective_la * effective_la, 0.01)
        # Clamp curvature
        max_curvature = self._cfg.max_angular_vel / max(self._cfg.max_linear_vel, 0.01)
        curvature = max(-max_curvature, min(max_curvature, curvature))

        # ── Velocity ──────────────────────────────────────
        # Linear: proportional to distance to goal
        vx = self._cfg.k_linear * dist_to_goal
        vx = min(vx, self._cfg.max_linear_vel)

        # Turn-in-place: if angular error to lookahead is large and point is close
        ang_to_la = math.atan2(local_y, local_x)
        if abs(ang_to_la) > self._cfg.turn_in_place_threshold_rad and la_dist < 1.0:
            vx = 0.0

        # Angular
        az = curvature * vx
        if vx == 0.0:
            # Turn in place toward lookahead
            az = self._cfg.k_angular * ang_to_la

        az = max(-self._cfg.max_angular_vel, min(self._cfg.max_angular_vel, az))

        # Deadband for small angular velocities
        if abs(az) < 0.03:
            az = 0.0
        if abs(vx) < 0.01:
            vx = 0.0

        return vx, az

    def is_goal_reached(
        self,
        current_x: float,
        current_y: float,
        goal: Tuple[float, float],
        current_yaw: float,
        goal_yaw: Optional[float],
    ) -> bool:
        """
        Check if the robot has reached the goal.

        Args:
            current_x, current_y: Current ROS map position.
            goal: (x_m, y_m) of the target.
            current_yaw: Current heading in radians.
            goal_yaw: Required final heading (None = no requirement).

        Returns:
            True if position and (optionally) yaw are within tolerance.
        """
        dist = math.hypot(goal[0] - current_x, goal[1] - current_y)
        if dist >= self._cfg.goal_tolerance_m:
            return False
        if goal_yaw is not None:
            yaw_err = abs(_shortest_angular_dist(goal_yaw, current_yaw))
            if yaw_err >= self._cfg.yaw_tolerance_rad:
                return False
        return True

    # ── internal ───────────────────────────────────────────────

    def _find_lookahead(
        self,
        robot_x: float,
        robot_y: float,
        path: List[Tuple[float, float]],
    ) -> Optional[Tuple[float, float]]:
        """
        Find the first point on the path at or beyond the lookahead distance
        from the robot.
        """
        # Step 1: find the closest point on the path (robot may have drifted)
        closest_idx = 0
        closest_dist = float('inf')
        for i, (px, py) in enumerate(path):
            d = math.hypot(px - robot_x, py - robot_y)
            if d < closest_dist:
                closest_dist = d
                closest_idx = i

        # Step 2: advance from closest point until distance >= lookahead
        for i in range(closest_idx, len(path)):
            px, py = path[i]
            d = math.hypot(px - robot_x, py - robot_y)
            if d >= self._cfg.lookahead_distance_m:
                return (px, py)

        # Fallback: use the last point
        return path[-1]
