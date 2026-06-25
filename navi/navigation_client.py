"""
Navigation Client — high-level Python API for task_manager to send
navigation goals to Nav2 and track completion.

Usage (from task_manager):
    from navigation_client import NavigationClient

    nav = NavigationClient(node)
    nav.navigate_to_waypoint("pos1_middle")
    ...
    if nav.is_done():
        nav.navigate_to_waypoint("grab_area")

All waypoint coordinates are converted from mm (navi_map_data) to ROS
map frame coordinates automatically.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import math
import sys
from pathlib import Path

# Resolve workspace root for navi_map_data import
_WS_ROOT = Path(__file__).resolve().parents[1]
_NAVI_MAP = _WS_ROOT / "navi" / "map"
if str(_NAVI_MAP) not in sys.path:
    sys.path.insert(0, str(_NAVI_MAP))

from navi_map_data import FIELD


def _mm_to_ros(x_mm: float, y_mm: float) -> tuple[float, float]:
    """Convert mm field coords (origin top-left) to ROS map coords (origin bottom-left)."""
    ros_x = x_mm / 1000.0
    ros_y = (FIELD["height"] - y_mm) / 1000.0
    return ros_x, ros_y


def _deg_to_quat(yaw_deg: float) -> tuple[float, float, float, float]:
    """Yaw in degrees (0=right, mm coords) → quaternion (qx, qy, qz, qw)."""
    half = math.radians(yaw_deg) / 2.0
    return (0.0, 0.0, math.sin(half), math.cos(half))


# ── Named waypoints (mm coords, yaw_deg in mm frame) ───────

_RAW_WAYPOINTS: dict[str, dict] = {
    "start":                   {"x_mm": 5350, "y_mm": 5250, "yaw_deg": 180, "label": "出发区"},
    "pos1_middle":             {"x_mm": 1500, "y_mm": 2750, "yaw_deg": -90, "label": "观察位① 仰头看上柜底面"},
    "pos1_middle_turned":      {"x_mm": 1500, "y_mm": 2750, "yaw_deg":  90, "label": "观察位① 180°转身看下柜顶面"},
    "pos2a_upper_right":       {"x_mm": 2200, "y_mm": 1500, "yaw_deg": 180, "label": "观察位②a 看上柜右侧面"},
    "pos2b_lower_right":       {"x_mm": 2200, "y_mm": 4000, "yaw_deg": 180, "label": "观察位②b 看下柜右侧面"},
    "grab_area":               {"x_mm": 4250, "y_mm": 4000, "yaw_deg": 180, "label": "抓取区"},
    "placement_A":             {"x_mm": 3250, "y_mm": 250,  "yaw_deg": 0,   "label": "A放置区"},
    "placement_B":             {"x_mm": 3750, "y_mm": 250,  "yaw_deg": 0,   "label": "B放置区"},
    "placement_C":             {"x_mm": 4250, "y_mm": 250,  "yaw_deg": 0,   "label": "C放置区"},
    "placement_D":             {"x_mm": 4750, "y_mm": 250,  "yaw_deg": 0,   "label": "D放置区"},
    "obstacle_entry":          {"x_mm": 3000, "y_mm": 5000, "yaw_deg": 180, "label": "障碍区入口"},
    "obstacle_exit":           {"x_mm": 1500, "y_mm": 2750, "yaw_deg": -90, "label": "障碍区出口→观察位①"},
}

# Build ROS-coordinate waypoint dict
WAYPOINTS: dict[str, dict] = {}
for name, wp in _RAW_WAYPOINTS.items():
    ros_x, ros_y = _mm_to_ros(wp["x_mm"], wp["y_mm"])
    qx, qy, qz, qw = _deg_to_quat(wp["yaw_deg"])
    WAYPOINTS[name] = {
        "x": ros_x,
        "y": ros_y,
        "qx": qx,
        "qy": qy,
        "qz": qz,
        "qw": qw,
        "label": wp["label"],
    }


class NavigationClient:
    """
    High-level navigation client wrapping a Nav2 NavigateToPose action.

    Typical use in task_manager tick callbacks:
        if not self._nav.goal_sent:
            self._nav.navigate_to_waypoint("pos1_middle")
        if self._nav.is_done():
            advance_to_next_phase()
    """

    def __init__(self, node, action_name: str = "navigate_to_pose"):
        """
        Args:
            node: A rclpy Node instance (e.g., the TaskManagerNode).
            action_name: Nav2 action server name.
        """
        self._node = node
        self._logger = node.get_logger()

        # Lazy import so the module is importable without rclpy in non-ROS contexts
        from rclpy.action import ActionClient
        from nav2_msgs.action import NavigateToPose

        self._action_client = ActionClient(node, NavigateToPose, action_name)
        self._goal_handle = None
        self._goal_sent = False
        self._goal_result = None
        self._current_waypoint: str | None = None

        self._logger.info("NavigationClient ready")

    # ── public API ──────────────────────────────────────────

    def navigate_to_waypoint(self, waypoint_name: str) -> bool:
        """Send navigation goal to a named waypoint. Returns True if goal accepted."""
        if waypoint_name not in WAYPOINTS:
            self._logger.error(
                f"Unknown waypoint '{waypoint_name}'. Available: {list(WAYPOINTS)}"
            )
            return False

        wp = WAYPOINTS[waypoint_name]
        return self.navigate_to_pose(
            x=wp["x"], y=wp["y"],
            qx=wp["qx"], qy=wp["qy"], qz=wp["qz"], qw=wp["qw"],
            waypoint_label=wp["label"],
        )

    def navigate_to_pose(
        self,
        x: float, y: float,
        qx: float = 0.0, qy: float = 0.0, qz: float = 0.0, qw: float = 1.0,
        waypoint_label: str = "",
    ) -> bool:
        """Send a NavigateToPose goal. Returns True if accepted."""
        from nav2_msgs.action import NavigateToPose
        from geometry_msgs.msg import PoseStamped

        if not self._action_client.wait_for_server(timeout_sec=5.0):
            self._logger.error("NavigateToPose action server not available")
            self._goal_sent = False
            return False

        pose = PoseStamped()
        pose.header.frame_id = "map"
        pose.header.stamp = self._node.get_clock().now().to_msg()
        pose.pose.position.x = x
        pose.pose.position.y = y
        pose.pose.position.z = 0.0
        pose.pose.orientation.x = qx
        pose.pose.orientation.y = qy
        pose.pose.orientation.z = qz
        pose.pose.orientation.w = qw

        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = pose
        goal_msg.behavior_tree = ""

        self._goal_handle = None
        self._goal_result = None
        self._goal_sent = True
        self._current_waypoint = waypoint_label

        send_goal_future = self._action_client.send_goal_async(
            goal_msg, feedback_callback=self._feedback_callback
        )
        send_goal_future.add_done_callback(self._goal_response_callback)

        label = waypoint_label or f"({x:.2f}, {y:.2f})"
        self._logger.info(f"Nav goal sent → {label}")
        return True

    def cancel(self):
        """Cancel the current navigation goal."""
        if self._goal_handle is not None:
            self._logger.info("Cancelling navigation goal")
            self._goal_handle.cancel_goal_async()
        self._goal_sent = False
        self._goal_handle = None
        self._goal_result = None

    def is_done(self) -> bool:
        """Check if the current navigation goal has completed."""
        return self._goal_result is not None

    def succeeded(self) -> bool:
        """Check if the last goal completed successfully."""
        if self._goal_result is None:
            return False
        from action_msgs.msg import GoalStatus
        return self._goal_result.status == GoalStatus.STATUS_SUCCEEDED

    def reset(self):
        """Reset state for a new goal."""
        self._goal_sent = False
        self._goal_handle = None
        self._goal_result = None
        self._current_waypoint = None

    @property
    def goal_sent(self) -> bool:
        """True if a goal has been sent but not yet resolved."""
        return self._goal_sent and self._goal_result is None

    @property
    def current_waypoint(self) -> str:
        return self._current_waypoint or ""

    def status_dict(self) -> dict:
        """Return a dict suitable for task_manager's status JSON."""
        result = "unknown"
        if self._goal_result is not None:
            from action_msgs.msg import GoalStatus
            status_names = {
                GoalStatus.STATUS_SUCCEEDED: "succeeded",
                GoalStatus.STATUS_ABORTED: "aborted",
                GoalStatus.STATUS_CANCELED: "canceled",
                GoalStatus.STATUS_UNKNOWN: "unknown",
            }
            result = status_names.get(self._goal_result.status, f"code_{self._goal_result.status}")
        return {
            "nav_goal_sent": self._goal_sent,
            "nav_goal_reached": self.succeeded(),
            "nav_result": result,
            "current_waypoint": self._current_waypoint or "",
        }

    # ── action callbacks ────────────────────────────────────

    def _goal_response_callback(self, future):
        from rclpy.action import GoalResponse
        goal_handle = future.result()
        if not goal_handle or not goal_handle.accepted:
            self._logger.warn("Nav goal rejected by server")
            self._goal_sent = False
            return
        self._goal_handle = goal_handle
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._result_callback)

    def _result_callback(self, future):
        self._goal_result = future.result()
        if self._goal_result is not None:
            self._logger.info(
                f"Nav goal finished: status={self._goal_result.status}"
            )

    def _feedback_callback(self, feedback_msg):
        # Could log distance remaining, but keeping quiet for now
        pass
