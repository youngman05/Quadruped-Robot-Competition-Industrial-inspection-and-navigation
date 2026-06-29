"""
Local obstacle detector — monitors PointCloud2 from D455 depth camera
for obstacles in the robot's forward path. Provides binary safety signals
(CLEAR / SLOW / STOP) rather than a full costmap.

The point cloud arrives in camera_link frame and is transformed to
base_link frame using the known static TF (camera at z=0.3m above base).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Tuple

import numpy as np


class ObstacleState(Enum):
    CLEAR = auto()
    SLOW = auto()
    STOP = auto()


@dataclass
class ObstacleConfig:
    """Local obstacle detection parameters."""
    safety_zone_forward_m: float = 1.0     # meters ahead of robot
    safety_zone_half_width_m: float = 0.6  # half-width (total 1.2m)
    min_height_m: float = 0.05             # ignore floor points
    max_height_m: float = 0.5              # ignore overhead
    obstacle_stop_threshold: int = 20      # points in zone to trigger STOP
    obstacle_slow_threshold: int = 5       # points in zone to trigger SLOW
    slowdown_factor: float = 0.3           # multiply speed by this when SLOW


# Known static transform: camera_link → base_link
# camera is mounted at (0, 0, 0.3) relative to base_link
CAMERA_Z_OFFSET = 0.3  # meters


class LocalObstacleDetector:
    """
    Binary obstacle detector from PointCloud2 data.

    Usage per frame:
        detector.update_pointcloud(points_nx3)           # process new scan
        state = detector.check_obstacle(cur_vx, cur_vz)  # get safety state
        vx, vz = detector.apply(vx, vz, state)           # apply velocity override
    """

    def __init__(self, config: ObstacleConfig = None):
        self._cfg = config or ObstacleConfig()
        self._latest_points: np.ndarray | None = None
        self._latest_state: ObstacleState = ObstacleState.CLEAR

    def update_pointcloud(self, points: np.ndarray) -> None:
        """
        Process a new point cloud.

        Args:
            points: N×3 numpy array of (x, y, z) in camera_link frame.
                    May be None if no new data.
        """
        self._latest_points = points

    def check_obstacle(self) -> ObstacleState:
        """
        Check the safety zone and return the current obstacle state.

        Returns:
            ObstacleState: CLEAR, SLOW, or STOP.
        """
        if self._latest_points is None or len(self._latest_points) == 0:
            self._latest_state = ObstacleState.CLEAR
            return self._latest_state

        # Transform from camera_link to base_link:
        # camera is at (0, 0, CAMERA_Z_OFFSET) in base_link frame.
        # For points in camera_link, z_base = z_camera - CAMERA_Z_OFFSET.
        # x and y are unchanged (camera faces forward, no rotation).
        pts = self._latest_points.astype(np.float64)
        z_base = pts[:, 2] - CAMERA_Z_OFFSET

        # Height filter: remove floor and overhead
        height_mask = (z_base >= self._cfg.min_height_m) & (z_base <= self._cfg.max_height_m)
        pts_filtered = pts[height_mask]

        if len(pts_filtered) == 0:
            self._latest_state = ObstacleState.CLEAR
            return self._latest_state

        # Safety zone filter: in front of robot, within lateral bounds
        x = pts_filtered[:, 0]
        y = pts_filtered[:, 1]
        zone_mask = (
            (x > 0.0) &
            (x < self._cfg.safety_zone_forward_m) &
            (np.abs(y) < self._cfg.safety_zone_half_width_m)
        )
        zone_count = int(np.sum(zone_mask))

        # Classify
        if zone_count >= self._cfg.obstacle_stop_threshold:
            self._latest_state = ObstacleState.STOP
        elif zone_count >= self._cfg.obstacle_slow_threshold:
            self._latest_state = ObstacleState.SLOW
        else:
            self._latest_state = ObstacleState.CLEAR

        return self._latest_state

    @property
    def state(self) -> ObstacleState:
        return self._latest_state

    def apply_override(
        self,
        vx: float,
        az: float,
        state: ObstacleState | None = None,
    ) -> Tuple[float, float]:
        """
        Apply velocity override based on obstacle state.

        Args:
            vx, az: Desired linear and angular velocity.
            state: ObstacleState (uses last check if not provided).

        Returns:
            (vx_override, az_override)
        """
        s = state if state is not None else self._latest_state
        if s == ObstacleState.STOP:
            return 0.0, 0.0
        elif s == ObstacleState.SLOW:
            return vx * self._cfg.slowdown_factor, az * self._cfg.slowdown_factor
        else:  # CLEAR
            return vx, az
