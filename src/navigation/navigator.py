"""
Navigator — lightweight navigation integration class.

Replaces Nav2's map_server, planner_server, controller_server, bt_navigator,
waypoint_follower, behavior_server, velocity_smoother, and lifecycle_manager
with a single library class that task_manager imports directly.

Internal state machine:
  IDLE → PLANNING → FOLLOWING → SUCCEEDED / FAILED → (reset) → IDLE

Public API matches the old NavigationClient for drop-in compatibility.
"""

from __future__ import annotations

import math
import json
import sys
import time
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Allow import from navi/map (for ROBOT_START_POSE)
_WS_ROOT = Path(__file__).resolve().parents[2]
_NAVI_MAP = _WS_ROOT / "navi" / "map"
if str(_NAVI_MAP) not in sys.path:
    sys.path.insert(0, str(_NAVI_MAP))
from navi_map_data import ROBOT_START_POSE  # noqa: E402

from .map_grid import build_grid, ros_to_grid, OCCUPIED, RESOLUTION
from .astar_planner import AStarPlanner, PlannerConfig
from .pure_pursuit import PurePursuitController, PursuitConfig, _normalize_angle
from .local_obstacle import LocalObstacleDetector, ObstacleConfig


# ── Waypoints (ROS map coords, from navi_map_data mm → ROS) ─────

def _mm_to_ros(x_mm: float, y_mm: float) -> Tuple[float, float]:
    """mm (top-left origin, +y down) → ROS (bottom-left origin, +y up)."""
    return x_mm / 1000.0, (6000.0 - y_mm) / 1000.0


def _deg_to_rad(yaw_deg: float) -> float:
    """Yaw degrees (0=right) → radians."""
    return math.radians(yaw_deg)


_RAW_WAYPOINTS: Dict[str, Dict[str, Any]] = {
    "start":                {"x_mm": 5350, "y_mm": 5250, "yaw_deg": 180, "label": "出发区"},
    "pos1_middle":          {"x_mm": 1500, "y_mm": 2750, "yaw_deg": -90, "label": "观察位① 看上柜底面"},
    "pos1_middle_turned":   {"x_mm": 1500, "y_mm": 2750, "yaw_deg":  90, "label": "观察位① 转身看下柜顶面"},
    "pos2a_upper_right":    {"x_mm": 2200, "y_mm": 1500, "yaw_deg": 180, "label": "观察位②a 上柜右面"},
    "pos2b_lower_right":    {"x_mm": 2200, "y_mm": 4000, "yaw_deg": 180, "label": "观察位②b 下柜右面"},
    "grab_area":            {"x_mm": 4250, "y_mm": 3450, "yaw_deg": -90, "label": "抓取区(上方)"},
    "placement_A":          {"x_mm": 3250, "y_mm": 600,  "yaw_deg": 0,   "label": "A放置区"},
    "placement_B":          {"x_mm": 3750, "y_mm": 600,  "yaw_deg": 0,   "label": "B放置区"},
    "placement_C":          {"x_mm": 4250, "y_mm": 600,  "yaw_deg": 0,   "label": "C放置区"},
    "placement_D":          {"x_mm": 4750, "y_mm": 600,  "yaw_deg": 0,   "label": "D放置区"},
    "obstacle_entry":       {"x_mm": 3000, "y_mm": 5000, "yaw_deg": 180, "label": "障碍区入口(右侧)"},
    "obstacle_exit":        {"x_mm": 950, "y_mm": 5250, "yaw_deg": 180, "label": "障碍区出口(左侧外)"},
}

# Convert waypoints to ROS coordinates
WAYPOINTS: Dict[str, Dict[str, Any]] = {}
for _name, _wp in _RAW_WAYPOINTS.items():
    ros_x, ros_y = _mm_to_ros(_wp["x_mm"], _wp["y_mm"])
    WAYPOINTS[_name] = {
        "x": ros_x,
        "y": ros_y,
        "yaw_rad": _deg_to_rad(_wp.get("yaw_deg", 0.0)),
        "has_yaw": _wp.get("yaw_deg") is not None,
        "label": _wp["label"],
    }


# ── Internal state ────────────────────────────────────────────

class _NavState(Enum):
    IDLE = auto()
    PLANNING = auto()
    FOLLOWING = auto()
    SUCCEEDED = auto()
    FAILED = auto()


class Navigator:
    """
    Lightweight navigator replacing Nav2.

    Create one instance per task_manager, sharing its ROS2 node:

        from navigation.navigator import Navigator
        self._nav = Navigator(self)  # 'self' is the rclpy Node

    Then use:
        self._nav.navigate_to_waypoint("pos1_middle")
        if self._nav.is_done():
            if self._nav.succeeded():
                advance()
            else:
                self._nav.reset()
    """

    def __init__(self, node):
        """
        Args:
            node: rclpy Node instance (task_manager or any other node).
        """
        self._node = node
        self._logger = node.get_logger()

        # ── Planner config ────────────────────────────
        planner_cfg = PlannerConfig(
            inflation_radius_m=0.15,
            goal_tolerance_m=0.15,
            waypoint_spacing_m=0.3,
        )
        pursuit_cfg = PursuitConfig(
            lookahead_distance_m=0.5,
            min_lookahead_m=0.3,
            max_lookahead_m=0.9,
            max_linear_vel=0.25,
            max_angular_vel=0.5,
            goal_tolerance_m=0.15,
            yaw_tolerance_rad=0.25,
            turn_in_place_threshold_rad=0.3,
            k_linear=0.8,
            k_angular=1.5,
        )
        obstacle_cfg = ObstacleConfig(
            safety_zone_forward_m=1.0,
            safety_zone_half_width_m=0.6,
            min_height_m=0.05,
            max_height_m=0.5,
            obstacle_stop_threshold=20,
            obstacle_slow_threshold=5,
            slowdown_factor=0.3,
        )

        # ── Internal modules ──────────────────────────
        self._grid = build_grid("phase1")
        self._planner = AStarPlanner(self._grid, planner_cfg)
        self._controller = PurePursuitController(pursuit_cfg)
        self._obstacle = LocalObstacleDetector(obstacle_cfg)

        # ── State ──────────────────────────────────────
        self._state = _NavState.IDLE
        self._path: List[Tuple[float, float]] = []
        self._goal_waypoint: Optional[str] = None
        self._goal_pos: Optional[Tuple[float, float]] = None
        self._goal_yaw: Optional[float] = None
        self._goal_has_yaw: bool = False

        # Odom→map offset (from robot start pose in navi_map_data)
        ros_sx, ros_sy = _mm_to_ros(ROBOT_START_POSE["x_mm"], ROBOT_START_POSE["y_mm"])
        self._odom_offset_x: float = ros_sx
        self._odom_offset_y: float = ros_sy
        self._odom_offset_yaw: float = _deg_to_rad(ROBOT_START_POSE["yaw_deg"])
        self._odom_cos: float = math.cos(self._odom_offset_yaw)
        self._odom_sin: float = math.sin(self._odom_offset_yaw)

        # Current pose in map frame (from /odom + offset)
        self._current_x: float = 0.0
        self._current_y: float = 0.0
        self._current_yaw: float = 0.0
        self._has_odom: bool = False

        # Stuck detection
        self._stuck_start_x: float = 0.0
        self._stuck_start_y: float = 0.0
        self._stuck_start_time: float = 0.0
        self._stuck_timeout: float = 10.0
        self._stuck_dist_threshold: float = 0.05

        # Obstacle zone tracking
        self._ignore_obstacles: bool = False

        # API compatibility
        self._goal_sent: bool = False
        self._goal_result: Optional[int] = None   # None=pending, 0=SUCCEEDED, -1=FAILED
        self._current_waypoint: Optional[str] = None

        # ── ROS2 subscriptions (via node) ─────────────
        # Lazy imports so the module is importable without rclpy
        from nav_msgs.msg import Odometry
        from geometry_msgs.msg import Twist
        from sensor_msgs.msg import PointCloud2
        from std_msgs.msg import String
        from rclpy.qos import QoSProfile, ReliabilityPolicy

        _best_effort = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)

        self._odom_sub = node.create_subscription(
            Odometry, "/odom", self._odom_callback, _best_effort,
        )
        self._cmd_vel_pub = node.create_publisher(Twist, "/cmd_vel", 10)
        self._pc_sub = node.create_subscription(
            PointCloud2, "/camera/depth/points", self._pointcloud_callback, 10,
        )
        # YOLO cone detection → dynamic obstacle injection
        self._yolo_sub = node.create_subscription(
            String, "/yolo/detections", self._yolo_callback, 10,
        )

        # D455 RGB intrinsics (640x480)
        self._fx = 617.0
        self._fy = 617.0
        self._cx = 320.0
        self._cy = 240.0

        # Control loop timer (10 Hz)
        self._timer = node.create_timer(0.1, self._control_loop)

        self._logger.info("Navigator initialized (lightweight A* + Pure Pursuit)")

    # ── Public API ──────────────────────────────────────────

    def navigate_to_waypoint(self, waypoint_name: str) -> bool:
        """Start navigating to a named waypoint. Returns True if path found."""
        if waypoint_name not in WAYPOINTS:
            self._logger.error(
                f"Unknown waypoint '{waypoint_name}'. Available: {list(WAYPOINTS)}"
            )
            return False

        wp = WAYPOINTS[waypoint_name]
        self._goal_waypoint = waypoint_name
        self._goal_pos = (wp["x"], wp["y"])
        self._goal_yaw = wp["yaw_rad"] if wp["has_yaw"] else None
        self._goal_has_yaw = wp["has_yaw"]
        self._current_waypoint = wp["label"]

        self._goal_sent = True
        self._goal_result = None
        self._state = _NavState.PLANNING

        self._logger.info(f"Nav goal → {wp['label']} ({wp['x']:.2f}, {wp['y']:.2f})")
        return True

    def navigate_to_pose(
        self,
        x: float, y: float,
        yaw_rad: Optional[float] = None,
        label: str = "",
    ) -> bool:
        """Start navigating to (x, y, yaw) in ROS map coordinates."""
        self._goal_pos = (x, y)
        self._goal_yaw = yaw_rad
        self._goal_has_yaw = yaw_rad is not None
        self._goal_waypoint = None
        self._current_waypoint = label or f"({x:.2f}, {y:.2f})"

        self._goal_sent = True
        self._goal_result = None
        self._state = _NavState.PLANNING

        self._logger.info(f"Nav goal → {self._current_waypoint}")
        return True

    def cancel(self) -> None:
        """Stop current navigation and halt the robot."""
        self._state = _NavState.IDLE
        self._path = []
        self._goal_sent = False
        self._goal_result = None
        self._publish_cmd_vel(0.0, 0.0)
        self._logger.info("Navigation cancelled")

    def is_done(self) -> bool:
        """True when navigation goal completed or failed."""
        return self._goal_result is not None

    def succeeded(self) -> bool:
        """True if goal was reached successfully."""
        return self._goal_result == 0

    def reset(self) -> None:
        """Reset for a new navigation goal."""
        self._state = _NavState.IDLE
        self._path = []
        self._goal_sent = False
        self._goal_result = None
        self._goal_waypoint = None
        self._goal_pos = None
        self._goal_yaw = None
        self._current_waypoint = None
        self._controller.reset()

    def switch_phase2_map(self) -> None:
        """Regenerate occupancy grid with obstacle area sealed."""
        self._grid = build_grid("phase2")
        self._planner.set_grid(self._grid)
        self._path = []
        self._state = _NavState.IDLE  # force replan on next goal
        self.ignore_obstacles()       # YOLO cones no longer relevant
        self._logger.info("Map switched → Phase 2 (obstacle area sealed)")

    @property
    def goal_sent(self) -> bool:
        return self._goal_sent and self._goal_result is None

    @property
    def current_waypoint(self) -> str:
        return self._current_waypoint or ""

    def status_dict(self) -> Dict[str, Any]:
        """Return status dict compatible with task_manager's JSON output."""
        result = "unknown"
        if self._goal_result == 0:
            result = "succeeded"
        elif self._goal_result is not None:
            result = "aborted"
        return {
            "nav_goal_sent": self._goal_sent,
            "nav_goal_reached": self._goal_result == 0,
            "nav_result": result,
            "current_waypoint": self._current_waypoint or "",
        }

    def get_current_pose(self) -> Tuple[float, float, float]:
        """Return (x_m, y_m, yaw_rad) from /odom."""
        return self._current_x, self._current_y, self._current_yaw

    # ── ROS2 callbacks ────────────────────────────────────────

    def _odom_callback(self, msg) -> None:
        """Update current pose in map frame from /odom + static map→odom offset."""
        # Odometry gives pose of base_link in odom frame.
        # Transform to map frame using the static map→odom offset.
        odom_x = msg.pose.pose.position.x
        odom_y = msg.pose.pose.position.y
        q = msg.pose.pose.orientation
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        odom_yaw = math.atan2(siny, cosy)

        # Apply static transform: map = T_map_odom * odom_pose
        # where T_map_odom = (tx, ty, θ) from robot start pose
        self._current_x = self._odom_offset_x + odom_x * self._odom_cos - odom_y * self._odom_sin
        self._current_y = self._odom_offset_y + odom_x * self._odom_sin + odom_y * self._odom_cos
        self._current_yaw = _normalize_angle(self._odom_offset_yaw + odom_yaw)
        self._has_odom = True

    def ignore_obstacles(self) -> None:
        """Stop injecting YOLO obstacles (called after obstacle zone is crossed)."""
        self._ignore_obstacles = True
        self._logger.info("YOLO obstacle injection disabled")

    def _yolo_callback(self, msg) -> None:
        """Parse YOLO detections, inject cone obstacles into the A* grid."""
        if self._ignore_obstacles:
            return
        try:
            data = json.loads(msg.data)
        except (json.JSONDecodeError, TypeError):
            return

        cones = [d for d in data.get("detections", [])
                 if d.get("class_id") == 2 or d.get("class_name") == "obstacle"]
        if not cones:
            return

        need_replan = False
        for cone in cones:
            dist_m = cone.get("distance_m")
            center = cone.get("center", {})
            px = center.get("x", 320)
            py_val = center.get("y", 240)
            if dist_m is None or dist_m <= 0:
                continue

            # ── Pixel + distance → camera_link 3D ──────
            # Cone surface → cone center: +10cm
            depth_to_center = dist_m + 0.10  # m
            x_cam = depth_to_center
            y_cam = (px - self._cx) / self._fx * dist_m
            z_cam = (py_val - self._cy) / self._fy * dist_m

            # ── camera_link → base_link ────────────────
            pitch = -0.523599  # camera mount pitch (-30°)
            cp, sp = math.cos(pitch), math.sin(pitch)
            x_rot = x_cam * cp + z_cam * sp
            z_rot = -x_cam * sp + z_cam * cp
            x_base = x_rot + 0.080
            y_base = y_cam + 0.000
            z_base = z_rot + 0.493

            # Ignore points on the ground (below robot) or too high
            if z_base < 0.02 or z_base > 0.8:
                continue

            # ── base_link → map frame ──────────────────
            cos_yaw = math.cos(self._current_yaw)
            sin_yaw = math.sin(self._current_yaw)
            map_x = self._current_x + x_base * cos_yaw - y_base * sin_yaw
            map_y = self._current_y + x_base * sin_yaw + y_base * cos_yaw

            # ── Map → grid, mark with 20cm inflation ───
            grid_r, grid_c = ros_to_grid(map_x, map_y)
            self._mark_obstacle(grid_r, grid_c, radius_m=0.20)
            need_replan = True

        # Re-plan if we have an active path and obstacle is near it
        if need_replan and self._state == _NavState.FOLLOWING and self._goal_pos:
            self._state = _NavState.PLANNING
            self._logger.info("YOLO cone detected — re-planning path")

    def _mark_obstacle(self, center_r: int, center_c: int, radius_m: float):
        """Paint an obstacle circle directly onto the inflated A* grid."""
        radius_cells = int(math.ceil(radius_m / RESOLUTION))
        rows, cols = self._grid.shape
        for dr in range(-radius_cells, radius_cells + 1):
            for dc in range(-radius_cells, radius_cells + 1):
                if dr * dr + dc * dc <= radius_cells * radius_cells:
                    nr, nc = center_r + dr, center_c + dc
                    if 0 <= nr < rows and 0 <= nc < cols:
                        self._planner._inflated[nr, nc] = OCCUPIED

    def _pointcloud_callback(self, msg) -> None:
        """Decode PointCloud2 and update obstacle detector."""
        try:
            # Read points from PointCloud2
            # depth_image_proc produces structured pointcloud (float32 x,y,z)
            data = np.frombuffer(msg.data, dtype=np.float32)
            n_points = len(data) // 3
            if n_points > 0 and msg.point_step == 12:  # 3 × float32
                points = data.reshape(n_points, 3)
                self._obstacle.update_pointcloud(points)
        except Exception:
            pass  # Silently ignore decoding errors

    # ── Control loop (10 Hz) ──────────────────────────────────

    def _control_loop(self) -> None:
        """Timer callback: plan, follow, or idle."""
        if self._state == _NavState.IDLE:
            # Publish zero velocity to keep robot stationary
            if self._has_odom:
                self._publish_cmd_vel(0.0, 0.0)
            return

        if not self._has_odom:
            # No odometry yet — can't navigate
            return

        if self._state == _NavState.PLANNING:
            self._do_planning()

        elif self._state == _NavState.FOLLOWING:
            self._do_following()

        # SUCCEEDED / FAILED: do nothing (caller reads is_done() / succeeded())

    def _do_planning(self) -> None:
        """Perform A* search and transition to FOLLOWING if successful."""
        if self._goal_pos is None:
            self._state = _NavState.FAILED
            self._goal_result = -1
            return

        start = (self._current_x, self._current_y)
        path = self._planner.plan(start, self._goal_pos)

        if path is None:
            self._logger.error(
                f"A* planning failed: ({start[0]:.2f}, {start[1]:.2f}) "
                f"→ ({self._goal_pos[0]:.2f}, {self._goal_pos[1]:.2f})"
            )
            self._state = _NavState.FAILED
            self._goal_result = -1
            return

        self._path = path
        self._controller.reset()

        # Initialize stuck detection
        self._stuck_start_x = self._current_x
        self._stuck_start_y = self._current_y
        self._stuck_start_time = time.time()

        self._state = _NavState.FOLLOWING
        self._logger.info(
            f"A* path found: {len(path)} waypoints, starting follow"
        )

    def _do_following(self) -> None:
        """Compute velocity command and publish. Check goal reached / stuck."""
        if self._goal_pos is None:
            self._state = _NavState.FAILED
            self._goal_result = -1
            return

        # ── Goal check ────────────────────────────────
        reached = self._controller.is_goal_reached(
            self._current_x, self._current_y,
            self._goal_pos,
            self._current_yaw,
            self._goal_yaw if self._goal_has_yaw else None,
        )
        if reached:
            self._publish_cmd_vel(0.0, 0.0)
            self._state = _NavState.SUCCEEDED
            self._goal_result = 0
            self._logger.info(
                f"Goal reached: {self._current_waypoint or '?'} "
                f"({self._current_x:.2f}, {self._current_y:.2f})"
            )
            return

        # ── Velocity computation ──────────────────────
        vx, az = self._controller.compute_velocity(
            self._current_x, self._current_y, self._current_yaw,
            self._path,
            self._goal_yaw if self._goal_has_yaw else None,
        )

        # ── Obstacle override ─────────────────────────
        obs_state = self._obstacle.check_obstacle()
        vx, az = self._obstacle.apply_override(vx, az, obs_state)

        # ── Stuck detection ───────────────────────────
        now = time.time()
        moved = math.hypot(
            self._current_x - self._stuck_start_x,
            self._current_y - self._stuck_start_y,
        )
        if moved < self._stuck_dist_threshold:
            if now - self._stuck_start_time > self._stuck_timeout:
                self._logger.warn(
                    f"Stuck detected (moved {moved:.3f}m in "
                    f"{now - self._stuck_start_time:.1f}s)"
                )
                self._publish_cmd_vel(0.0, 0.0)
                self._state = _NavState.FAILED
                self._goal_result = -1
                return
        else:
            # Reset stuck timer when robot moves
            self._stuck_start_x = self._current_x
            self._stuck_start_y = self._current_y
            self._stuck_start_time = now

        self._publish_cmd_vel(vx, az)

    def _publish_cmd_vel(self, vx: float, az: float) -> None:
        """Publish Twist to /cmd_vel."""
        from geometry_msgs.msg import Twist
        msg = Twist()
        msg.linear.x = float(vx)
        msg.linear.y = 0.0
        msg.linear.z = 0.0
        msg.angular.x = 0.0
        msg.angular.y = 0.0
        msg.angular.z = float(az)
        self._cmd_vel_pub.publish(msg)
