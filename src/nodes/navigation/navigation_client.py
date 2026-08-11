"""
Navigation Client — high-level Python API for task_manager to send
navigation goals to Nav2 and track completion.

Usage (from task_manager):
    from nodes.navigation.navigation_client import NavigationClient

    nav = NavigationClient(node)
    nav.navigate_to_waypoint("pos1_middle")
    ...
    if nav.is_done():
        nav.navigate_to_waypoint("grab_area")

All waypoint coordinates are converted from competition-field millimeters to
ROS map-frame meters automatically.
"""

from __future__ import annotations

import math


FIELD_HEIGHT_MM = 6000.0

_STATUS_SUCCEEDED = 4
_STATUS_CANCELED = 5
_STATUS_ABORTED = 6
_PENDING_RESULTS = frozenset(("sending", "active"))
_TERMINAL_RESULTS = frozenset((
    "succeeded",
    "aborted",
    "canceled",
    "rejected",
    "unavailable",
    "unknown_waypoint",
    "error",
))


def _mm_to_ros(x_mm: float, y_mm: float) -> tuple[float, float]:
    """Convert mm field coords (origin top-left) to ROS map coords (origin bottom-left)."""
    ros_x = x_mm / 1000.0
    ros_y = (FIELD_HEIGHT_MM - y_mm) / 1000.0
    return ros_x, ros_y


def _deg_to_quat(yaw_deg: float) -> tuple[float, float, float, float]:
    """Field yaw in degrees (0=right, 90=down) -> ROS quaternion."""
    ros_yaw_deg = -yaw_deg
    half = math.radians(ros_yaw_deg) / 2.0
    return (0.0, 0.0, math.sin(half), math.cos(half))


# yaw=None means Nav2 only needs to reach the position.

_RAW_WAYPOINTS: dict[str, dict] = {
    # Coordinates below are base_link navigation centers, not task-object centers.
    "start":                   {"x_mm": 4650, "y_mm": 5250, "yaw_deg": 180,  "label": "出发区"},
    "pos1_middle":             {"x_mm": 1500, "y_mm": 2750, "yaw_deg": -90,  "label": "观察位① 仰头看上柜底面"},
    "pos1_middle_turned":      {"x_mm": 1500, "y_mm": 2750, "yaw_deg":  90,  "label": "观察位① 转身看下柜顶面"},
    "pos2a_upper_right":       {"x_mm": 2600, "y_mm": 1500, "yaw_deg": 180,  "label": "观察位②a 看上柜右侧面"},
    "pos2b_lower_right":       {"x_mm": 2600, "y_mm": 4000, "yaw_deg": 180,  "label": "观察位②b 看下柜右侧面"},
    "grab_area":               {"x_mm": 3100, "y_mm": 4000, "yaw_deg": 0,    "label": "抓取区左侧接近点"},
    "placement_A":             {"x_mm": 3250, "y_mm": 1050, "yaw_deg": -90,  "label": "A放置区接近点"},
    "placement_B":             {"x_mm": 3750, "y_mm": 1050, "yaw_deg": -90,  "label": "B放置区接近点"},
    "placement_C":             {"x_mm": 4250, "y_mm": 1050, "yaw_deg": -90,  "label": "C放置区接近点"},
    "placement_D":             {"x_mm": 4650, "y_mm": 1050, "yaw_deg": -90,  "label": "D放置区接近点"},
    # 原 x=500mm 适合作为前缘/通过语义点，不适合作为 Nav2 base_link 中心目标。
    # 2026-07-27 真机验证 x=1050mm / ROS x=1.05m 可成功到达。
    "obstacle_cross_target":   {"x_mm": 1050, "y_mm": 5250, "yaw_deg": 180,  "label": "穿越障碍区 → 左侧安全走廊接近点"},
}

# Build ROS-coordinate waypoint dict
WAYPOINTS: dict[str, dict] = {}
for name, wp in _RAW_WAYPOINTS.items():
    ros_x, ros_y = _mm_to_ros(wp["x_mm"], wp["y_mm"])
    if wp["yaw_deg"] is not None:
        qx, qy, qz, qw = _deg_to_quat(wp["yaw_deg"])
    else:
        qx, qy, qz, qw = 0.0, 0.0, 0.0, 1.0  # identity: 不管朝向
    WAYPOINTS[name] = {
        "x": ros_x,
        "y": ros_y,
        "qx": qx,
        "qy": qy,
        "qz": qz,
        "qw": qw,
        "yaw_set": wp["yaw_deg"] is not None,  # True=到位后转朝向, False=只到位置
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
        self._result_name = "idle"
        self._failure_reason = ""
        self._generation = 0

        self._logger.info("NavigationClient ready")

    # ── public API ──────────────────────────────────────────

    def navigate_to_waypoint(self, waypoint_name: str) -> bool:
        """Submit a goal for a named waypoint; acceptance arrives asynchronously."""
        if waypoint_name not in WAYPOINTS:
            reason = f"Unknown waypoint '{waypoint_name}'. Available: {list(WAYPOINTS)}"
            self._logger.error(reason)
            self._mark_terminal("unknown_waypoint", reason)
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
        """Submit a NavigateToPose goal; acceptance arrives asynchronously."""
        from nav2_msgs.action import NavigateToPose
        from geometry_msgs.msg import PoseStamped

        label = waypoint_label or f"({x:.2f}, {y:.2f})"
        self._current_waypoint = label
        if not self._action_client.server_is_ready():
            reason = "NavigateToPose action server not available"
            self._logger.error(reason)
            self._mark_terminal("unavailable", reason)
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
        self._result_name = "sending"
        self._failure_reason = ""
        self._generation += 1
        generation = self._generation

        try:
            send_goal_future = self._action_client.send_goal_async(
                goal_msg, feedback_callback=self._feedback_callback
            )
            send_goal_future.add_done_callback(
                lambda future: self._goal_response_callback(future, generation)
            )
        except Exception as exc:  # noqa: BLE001
            reason = "send_goal_async failed: %s" % exc
            self._logger.error(reason)
            self._mark_terminal("error", reason)
            return False

        self._logger.info(f"Nav goal sent → {label}")
        return True

    def cancel(self):
        """Cancel the current navigation goal."""
        self._generation += 1
        if self._goal_handle is not None:
            self._logger.info("Cancelling navigation goal")
            self._goal_handle.cancel_goal_async()
        self._mark_terminal("canceled", "navigation canceled by TaskManager")

    def is_done(self) -> bool:
        """Check if the current navigation goal has completed."""
        return self._result_name in _TERMINAL_RESULTS

    def succeeded(self) -> bool:
        """Check if the last goal completed successfully."""
        return self._result_name == "succeeded"

    def reset(self):
        """Reset state for a new goal."""
        self._generation += 1
        self._goal_sent = False
        self._goal_handle = None
        self._goal_result = None
        self._current_waypoint = None
        self._result_name = "idle"
        self._failure_reason = ""

    @property
    def goal_sent(self) -> bool:
        """True if a goal has been sent but not yet resolved."""
        return self._goal_sent and self._result_name in _PENDING_RESULTS

    @property
    def current_waypoint(self) -> str:
        return self._current_waypoint or ""

    @property
    def result_name(self) -> str:
        return self._result_name

    @property
    def failure_reason(self) -> str:
        return self._failure_reason

    def status_dict(self) -> dict:
        """Return a dict suitable for task_manager's status JSON."""
        return {
            "nav_goal_sent": self._goal_sent,
            "nav_goal_reached": self.succeeded(),
            "nav_result": self._result_name,
            "nav_failure_reason": self._failure_reason,
            "current_waypoint": self._current_waypoint or "",
        }

    # ── action callbacks ────────────────────────────────────

    def _goal_response_callback(self, future, generation):
        try:
            goal_handle = future.result()
        except Exception as exc:  # noqa: BLE001
            if generation == self._generation:
                reason = "goal response failed: %s" % exc
                self._logger.error(reason)
                self._mark_terminal("error", reason)
            return

        if generation != self._generation:
            if goal_handle and goal_handle.accepted:
                goal_handle.cancel_goal_async()
            return
        if not goal_handle or not goal_handle.accepted:
            reason = "Nav goal rejected by server"
            self._logger.warn(reason)
            self._mark_terminal("rejected", reason)
            return
        self._goal_handle = goal_handle
        self._result_name = "active"
        try:
            result_future = goal_handle.get_result_async()
            result_future.add_done_callback(
                lambda result: self._result_callback(result, generation)
            )
        except Exception as exc:  # noqa: BLE001
            reason = "get_result_async failed: %s" % exc
            self._logger.error(reason)
            self._mark_terminal("error", reason)

    def _result_callback(self, future, generation):
        if generation != self._generation:
            return
        try:
            self._goal_result = future.result()
        except Exception as exc:  # noqa: BLE001
            reason = "navigation result failed: %s" % exc
            self._logger.error(reason)
            self._mark_terminal("error", reason)
            return
        if self._goal_result is None:
            reason = "navigation result was empty"
            self._logger.error(reason)
            self._mark_terminal("error", reason)
            return

        status = self._goal_result.status
        status_names = {
            _STATUS_SUCCEEDED: "succeeded",
            _STATUS_CANCELED: "canceled",
            _STATUS_ABORTED: "aborted",
        }
        result_name = status_names.get(status, "error")
        reason = "" if result_name == "succeeded" else "action_status=%s" % status
        self._mark_terminal(result_name, reason, keep_result=True)
        self._logger.info("Nav goal finished: status=%s (%s)" % (status, result_name))

    def _mark_terminal(self, result_name, reason, keep_result=False):
        self._goal_sent = False
        self._goal_handle = None
        if not keep_result:
            self._goal_result = None
        self._result_name = result_name
        self._failure_reason = str(reason)

    def _feedback_callback(self, feedback_msg):
        # Could log distance remaining, but keeping quiet for now
        pass
