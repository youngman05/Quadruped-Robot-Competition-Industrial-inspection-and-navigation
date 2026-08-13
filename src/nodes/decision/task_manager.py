#!/usr/bin/env python3
"""ROS2 node: 比赛任务状态机 (Competition Task Manager).

掌控比赛全流程，协调感知、导航、语音、机械臂各模块。

订阅:
    /yolo/detections       std_msgs/String  YOLO 实例分割结果 (JSON)
    /visual_slam/status    std_msgs/String  VO 定位状态

发布:
    /task/phase            std_msgs/String  当前阶段名称
    /task/status           std_msgs/String  完整状态 (JSON)

状态机:
    START -> PASS_OBSTACLE -> INSPECT_GAUGES(4步,看一个报一个)
          -> FIND_RED_BAR -> GRASP_BAR -> PLACE_TO_ABNORMAL_ZONE
          (折返直到所有异常处理完) -> FINISH
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional

import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from std_msgs.msg import String
from std_srvs.srv import Trigger

from nav2_msgs.srv import LoadMap
from nodes.decision.inspection_workflow import (
    InspectionContractError,
    InspectionReading,
    InspectionStage,
    InspectionWorkflow,
)
from nodes.navigation.navigation_client import (
    NavigationClient,
    WAYPOINTS,
    load_calibrated_waypoints,
)
from nodes.navigation.depth_contract import DepthMode
from nodes.navigation.depth_mode_client import DepthModeClient
from nodes.navigation.mission_depth_policy import MissionDepthPolicy, StationaryWindow
from nodes.navigation.mission_route import (
    MISSION_NAV_WAYPOINTS,
    OBSTACLE_ROUTE,
    inspection_route_steps,
    observation_steps,
)


# ═══════════════════════════════════════════════════════════════════
#  状态定义
# ═══════════════════════════════════════════════════════════════════

class Phase(Enum):
    """比赛阶段枚举。"""
    START = auto()                  # 初始化，等待各子系统就绪
    PASS_OBSTACLE = auto()          # 越障 / 巡航到目标区域
    INSPECT_GAUGES = auto()         # 4个子步骤，看一个报一个
    FIND_RED_BAR = auto()           # 寻找红色条
    GRASP_BAR = auto()              # 抓取红色条
    PLACE_TO_ABNORMAL_ZONE = auto() # 放入异常区域，可能多次折返
    FINISH = auto()                 # 比赛结束
    ABORT = auto()                  # 异常中止

    def label(self) -> str:
        """返回中文阶段名。"""
        _labels = {
            Phase.START: "初始化",
            Phase.PASS_OBSTACLE: "越障巡航",
            Phase.INSPECT_GAUGES: "仪表检测(含播报)",
            Phase.FIND_RED_BAR: "寻找红条",
            Phase.GRASP_BAR: "抓取红条",
            Phase.PLACE_TO_ABNORMAL_ZONE: "放置异常区",
            Phase.FINISH: "完成",
            Phase.ABORT: "中止",
        }
        return _labels.get(self, "未知")


# ═══════════════════════════════════════════════════════════════════
#  数据结构
# ═══════════════════════════════════════════════════════════════════

@dataclass
class GaugeInfo:
    """单个仪表的检测结果。"""
    letter: str = ""                # A / B / C / D
    detected: bool = False
    stable_detected: bool = False
    color: Optional[str] = None     # yellow / green / red
    level: Optional[str] = None
    status: Optional[str] = None    # normal / high / low
    angle: Optional[float] = None


@dataclass
class YoloDetection:
    """单帧 YOLO 检测汇总。"""
    timestamp: float = 0.0
    gauges: List[Dict[str, Any]] = field(default_factory=list)   # gauge 实例
    letters: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)  # {"A": [...], ...}
    red_bars: List[Dict[str, Any]] = field(default_factory=list)
    green_bars: List[Dict[str, Any]] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
#  TaskManagerNode
# ═══════════════════════════════════════════════════════════════════

class TaskManagerNode(Node):
    """比赛任务状态机 —— 串联巡检、播报、抓取、放置全流程。"""

    # 阶段顺序（不含 START / FINISH / ABORT）
    # INSPECT_GAUGES 已内置逐次播报，REPORT_STATUS 不再单独使用
    PHASE_SEQUENCE = [
        Phase.PASS_OBSTACLE,
        Phase.INSPECT_GAUGES,         # 4 子步骤，看一个报一个
        Phase.FIND_RED_BAR,
        Phase.GRASP_BAR,
        Phase.PLACE_TO_ABNORMAL_ZONE,
    ]

    def __init__(self) -> None:
        super().__init__("task_manager_node")

        # ── 声明参数 ──────────────────────────────
        self.declare_parameter("phases", [
            "start", "pass_obstacle", "inspect_gauges", "report_status",
            "find_red_bar", "grasp_bar", "place_to_abnormal_zone", "finish",
        ])
        self.declare_parameter("timeout_per_phase", 300.0)   # 每阶段超时 (秒), 含YOLO
        self.declare_parameter("pass_obstacle_timeout_sec", 120.0)
        self.declare_parameter("inspection_timeout_sec", 300.0)
        self.declare_parameter("tick_rate", 10.0)             # 状态机主循环频率 (Hz)
        self.declare_parameter("require_stable_gauge", True)  # 是否必须稳定检测
        self.declare_parameter("auto_advance", False)         # 调试: 自动推进阶段

        self.declare_parameter("phase2_map_yaml", "navi/map/competition_field_phase2.yaml")
        self.declare_parameter("gauge_topic", "/gauge/status")
        self.declare_parameter("yolo_topic", "/yolo/detections")
        self.declare_parameter("slam_status_topic", "/visual_slam/status")
        self.declare_parameter("odom_topic", "/odom")
        self.declare_parameter("odom_timeout_sec", 1.0)
        self.declare_parameter("phase_topic", "/task/phase")
        self.declare_parameter("status_topic", "/task/status")
        self.declare_parameter("whz_service", "/whz/inspect")
        self.declare_parameter("max_nav_retries", 3)
        self.declare_parameter("max_inspection_retries", 3)
        self.declare_parameter("retry_delay_sec", 1.0)
        self.declare_parameter("settle_duration_sec", 1.0)
        self.declare_parameter("settle_linear_speed_mps", 0.02)
        self.declare_parameter("settle_angular_speed_rps", 0.05)
        self.declare_parameter("inspection_service_wait_sec", 5.0)
        self.declare_parameter("inspection_response_timeout_sec", 20.0)
        self.declare_parameter("require_inspection_audio", True)
        self.declare_parameter("inspection_only", False)
        self.declare_parameter("finish_after_inspection", False)
        self.declare_parameter("allow_placeholder_manipulation", False)
        self.declare_parameter("waypoint_file", "")
        self.declare_parameter("waypoint_route", "inspection_interleaved")
        self.declare_parameter("expected_map_id", "")
        self.declare_parameter("inspection_start_index", 0)
        self.declare_parameter("inspection_count", 0)
        self.declare_parameter("enable_phase2_map_switch", False)
        self.declare_parameter("enable_depth_milestones", False)
        self.declare_parameter("depth_mode_request_topic", "/depth/mode_request")
        self.declare_parameter("depth_mode_status_topic", "/depth/mode_status")
        self.declare_parameter("depth_safety_status_topic", "/depth/safety_gate_status")
        self.declare_parameter("depth_transition_timeout_sec", 8.0)
        self.declare_parameter("depth_transition_settle_duration_sec", 1.0)
        self.declare_parameter("verify_host_odom_after_depth_disable", True)
        self.declare_parameter("host_odom_disable_timeout_sec", 2.0)

        # ── 读取参数 ──────────────────────────────
        self._timeout_per_phase = float(self.get_parameter("timeout_per_phase").value)
        self._phase_timeouts = {
            Phase.PASS_OBSTACLE: max(
                0.1,
                float(self.get_parameter("pass_obstacle_timeout_sec").value),
            ),
            Phase.INSPECT_GAUGES: max(
                0.1,
                float(self.get_parameter("inspection_timeout_sec").value),
            ),
        }
        self._tick_rate = float(self.get_parameter("tick_rate").value)
        self._require_stable = bool(self.get_parameter("require_stable_gauge").value)
        self._auto_advance = bool(self.get_parameter("auto_advance").value)

        yolo_topic = str(self.get_parameter("yolo_topic").value)
        slam_status_topic = str(self.get_parameter("slam_status_topic").value)
        odom_topic = str(self.get_parameter("odom_topic").value)
        phase_topic = str(self.get_parameter("phase_topic").value)
        status_topic = str(self.get_parameter("status_topic").value)
        self._odom_timeout_sec = float(self.get_parameter("odom_timeout_sec").value)
        whz_service = str(self.get_parameter("whz_service").value)
        self._max_nav_retries = max(
            0, int(self.get_parameter("max_nav_retries").value)
        )
        self._max_inspection_retries = max(
            0, int(self.get_parameter("max_inspection_retries").value)
        )
        self._retry_delay_sec = max(
            0.0, float(self.get_parameter("retry_delay_sec").value)
        )
        self._settle_duration_sec = max(
            0.0, float(self.get_parameter("settle_duration_sec").value)
        )
        self._settle_linear_speed_mps = max(
            0.0, float(self.get_parameter("settle_linear_speed_mps").value)
        )
        self._settle_angular_speed_rps = max(
            0.0, float(self.get_parameter("settle_angular_speed_rps").value)
        )
        self._inspection_service_wait_sec = max(
            0.1, float(self.get_parameter("inspection_service_wait_sec").value)
        )
        self._inspection_response_timeout_sec = max(
            0.1,
            float(self.get_parameter("inspection_response_timeout_sec").value),
        )
        self._require_inspection_audio = bool(
            self.get_parameter("require_inspection_audio").value
        )
        self._inspection_only = bool(
            self.get_parameter("inspection_only").value
        )
        self._finish_after_inspection = bool(
            self.get_parameter("finish_after_inspection").value
        )
        self._allow_placeholder_manipulation = bool(
            self.get_parameter("allow_placeholder_manipulation").value
        )
        inspection_start_index = int(
            self.get_parameter("inspection_start_index").value
        )
        inspection_count = int(self.get_parameter("inspection_count").value)
        self._enable_phase2_map_switch = bool(
            self.get_parameter("enable_phase2_map_switch").value
        )
        self._enable_depth_milestones = bool(
            self.get_parameter("enable_depth_milestones").value
        )
        depth_mode_request_topic = str(
            self.get_parameter("depth_mode_request_topic").value
        )
        depth_mode_status_topic = str(
            self.get_parameter("depth_mode_status_topic").value
        )
        depth_safety_status_topic = str(
            self.get_parameter("depth_safety_status_topic").value
        )
        self._depth_transition_timeout_sec = max(
            0.1,
            float(self.get_parameter("depth_transition_timeout_sec").value),
        )
        self._depth_transition_stationary = StationaryWindow(
            max(
                0.0,
                float(
                    self.get_parameter(
                        "depth_transition_settle_duration_sec"
                    ).value
                ),
            )
        )
        self._verify_host_odom_after_depth_disable = bool(
            self.get_parameter("verify_host_odom_after_depth_disable").value
        )
        self._host_odom_disable_timeout_sec = max(
            0.1,
            float(
                self.get_parameter("host_odom_disable_timeout_sec").value
            ),
        )

        # ── 发布者 ────────────────────────────────
        self._phase_pub = self.create_publisher(String, phase_topic, 10)
        self._status_pub = self.create_publisher(String, status_topic, 10)
        self._speech_pub = self.create_publisher(String, "/speech/text", 10)

        # ── 订阅者 ────────────────────────────────
        self._yolo_sub = self.create_subscription(
            String, yolo_topic, self._on_yolo_detections, 10,
        )
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        _best_effort = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
        self._slam_sub = self.create_subscription(
            String, slam_status_topic, self._on_slam_status, _best_effort,
        )
        self._odom_sub = self.create_subscription(
            Odometry, odom_topic, self._on_odom, _best_effort,
        )

        # ── 内部状态 ──────────────────────────────
        self._phase: Phase = Phase.START
        self._phase_enter_time: float = 0.0          # 进入当前阶段的时间戳
        self._gauge_info: Dict[str, GaugeInfo] = {   # 按字母索引的仪表信息
            letter: GaugeInfo(letter=letter) for letter in "ABCD"
        }
        self._latest_yolo: Optional[YoloDetection] = None
        self._slam_tracking_ok: bool = False
        self._slam_status_time: float = 0.0
        self._last_odom_time: float = 0.0
        self._last_odom_linear_speed: float = float("inf")
        self._last_odom_angular_speed: float = float("inf")
        self._abnormal_zones: List[str] = []           # 所有异常区域字母 (可能有1~4个)
        self._abnormal_handled: int = 0                # 已完成抓取放置的异常数
        self._phase_seq_idx: int = 0                  # 在 PHASE_SEQUENCE 中的位置
        self._abort_reason: str = ""
        self._nav_retry_counts: Dict[str, int] = {}
        self._nav_retry_not_before: Dict[str, float] = {}
        self._placement_arrival_time: Optional[float] = None
        self._depth_policy = None
        self._depth_mode_client = None
        self._startup_depth_mode = None
        self._depth_pending_mode = None
        self._depth_pending_milestone = ""
        self._depth_pending_request_id = ""
        self._depth_pending_started = 0.0
        self._depth_pending_odom_baseline = 0.0
        self._obstacle_depth_mode = None
        self._obstacle_depth_transition_complete = False
        self._grab_depth_mode = None
        self._grab_depth_transition_complete = False
        self._depth_recorded_waypoints = set()

        # ── 地图切换客户端 ────────────────────────
        self._phase2_yaml = str(self.get_parameter("phase2_map_yaml").value)
        self._map_client = (
            self.create_client(LoadMap, "/map_server/load_map")
            if self._enable_phase2_map_switch
            else None
        )
        self._whz_client = self.create_client(Trigger, whz_service)

        # ── 导航客户端 (Nav2 NavigateToPose) ─────
        waypoint_file = str(self.get_parameter("waypoint_file").value).strip()
        waypoint_route = str(self.get_parameter("waypoint_route").value).strip()
        expected_map_id = str(self.get_parameter("expected_map_id").value).strip()
        task_waypoints = WAYPOINTS
        if waypoint_file:
            task_waypoints = load_calibrated_waypoints(
                waypoint_file,
                waypoint_route,
                expected_map_id=expected_map_id,
            )
            missing_waypoints = sorted(
                set(MISSION_NAV_WAYPOINTS) - set(task_waypoints)
            )
            if missing_waypoints:
                raise ValueError(
                    "calibrated route is missing required waypoints: %s"
                    % ", ".join(missing_waypoints)
                )
        self._waypoint_source = "waypoint_file" if waypoint_file else "builtin"
        self._waypoint_route = waypoint_route if waypoint_file else "builtin"
        self._nav = NavigationClient(self, waypoints=task_waypoints)
        if self._enable_depth_milestones:
            self._depth_policy = MissionDepthPolicy()
            self._depth_mode_client = DepthModeClient(
                self,
                request_topic=depth_mode_request_topic,
                status_topic=depth_mode_status_topic,
                safety_status_topic=depth_safety_status_topic,
                transition_timeout_sec=self._depth_transition_timeout_sec,
            )
            self._startup_depth_mode = self._depth_policy.mission_start()
        # 4 个观察子步骤: 位置 + 朝向 + 说明
        all_inspection_steps = list(observation_steps())
        if inspection_start_index < 0 or inspection_start_index >= len(all_inspection_steps):
            raise ValueError("inspection_start_index must be between 0 and 3")
        if inspection_count < 0:
            raise ValueError("inspection_count must be non-negative")
        inspection_end = (
            len(all_inspection_steps)
            if inspection_count == 0
            else inspection_start_index + inspection_count
        )
        if inspection_end > len(all_inspection_steps):
            raise ValueError("inspection selection exceeds the four configured steps")
        self._inspection_steps = all_inspection_steps[
            inspection_start_index:inspection_end
        ]
        self._inspection_requires_abcd = (
            inspection_start_index == 0 and len(self._inspection_steps) == 4
        )
        if not self._inspection_requires_abcd and not self._inspection_only:
            raise ValueError("partial inspection selection requires inspection_only=true")
        if self._inspection_requires_abcd:
            self._inspection_route_steps = list(inspection_route_steps())
        else:
            self._inspection_route_steps = list(self._inspection_steps)
        self._inspection_route_index = 0
        self._inspection_workflow = InspectionWorkflow(
            step_count=len(self._inspection_steps),
            settle_duration_sec=self._settle_duration_sec,
            max_nav_retries=self._max_nav_retries,
            max_inspection_retries=self._max_inspection_retries,
        )
        self._inspection_future = None
        self._inspection_request_started: float = 0.0
        self._inspection_service_wait_started: Optional[float] = None
        self._inspection_retry_not_before: float = 0.0
        self._inspection_request_id: int = 0

        # ── 主循环定时器 ──────────────────────────
        self._timer = self.create_timer(1.0 / self._tick_rate, self._state_machine_tick)

        # ── 进入初始状态 ──────────────────────────
        self._enter_phase(Phase.START)
        self.get_logger().info(
            f"Task Manager 启动完成 | tick_rate={self._tick_rate} Hz "
            f"| timeout={self._timeout_per_phase}s "
            f"| require_stable={self._require_stable} "
            f"| inspection_only={self._inspection_only} "
            f"| finish_after_inspection={self._finish_after_inspection} "
            f"| placeholder_manipulation={self._allow_placeholder_manipulation} "
            f"| inspection_steps={len(self._inspection_steps)} "
            f"| waypoint_source={self._waypoint_source} "
            f"| waypoint_route={self._waypoint_route} "
            f"| depth_milestones={self._enable_depth_milestones} "
            f"| phase2_map_switch={self._enable_phase2_map_switch}"
        )

    # ═══════════════════════════════════════════════════════════
    #  状态机主循环
    # ═══════════════════════════════════════════════════════════

    def _state_machine_tick(self) -> None:
        """每个 tick 评估当前阶段退出条件，决定是否推进。"""
        elapsed = time.time() - self._phase_enter_time

        if self._phase == Phase.START:
            self._tick_start(elapsed)

        elif self._phase == Phase.PASS_OBSTACLE:
            self._tick_pass_obstacle(elapsed)

        elif self._phase == Phase.INSPECT_GAUGES:
            self._tick_inspect_gauges(elapsed)

        elif self._phase == Phase.FIND_RED_BAR:
            self._tick_find_red_bar(elapsed)

        elif self._phase == Phase.GRASP_BAR:
            self._tick_grasp_bar(elapsed)

        elif self._phase == Phase.PLACE_TO_ABNORMAL_ZONE:
            self._tick_place_to_abnormal_zone(elapsed)

        elif self._phase == Phase.FINISH:
            pass  # 终态，不再推进

        elif self._phase == Phase.ABORT:
            pass  # 终态

    # ── 各阶段 Tick 实现 ─────────────────────────

    def _tick_start(self, elapsed: float) -> None:
        """START: 等待各子系统就绪后自动推进。"""
        odom_fresh = (time.time() - self._last_odom_time) <= self._odom_timeout_sec
        if (
            self._enable_depth_milestones
            and odom_fresh
            and not self._ensure_depth_mode(
                self._startup_depth_mode,
                "mission_start",
            )
        ):
            return

        # 调试模式: 跳过所有条件直接推进
        if self._auto_advance and elapsed > 0.5:
            if self._inspection_only:
                self._enter_phase(Phase.INSPECT_GAUGES)
            else:
                self._advance_to_next_phase()
            return

        # 正式条件: SLAM 就绪 + 至少收到过一次 gauge/yolo 数据
        if odom_fresh and elapsed > 1.0:
            if self._inspection_only:
                self.get_logger().info("定位就绪，进入限定观察位巡检")
                self._enter_phase(Phase.INSPECT_GAUGES)
            else:
                self.get_logger().info("各子系统就绪，进入越障巡航阶段")
                self._advance_to_next_phase()

    def _tick_pass_obstacle(self, elapsed: float) -> None:
        """PASS_OBSTACLE: 两步走 — 先穿障碍区到底，再到安全区观察位。"""
        if self._handle_timeout(elapsed):
            return

        if not hasattr(self, "_obstacle_route_index"):
            self._obstacle_route_index = 0
        route = OBSTACLE_ROUTE
        waypoint = route[self._obstacle_route_index]
        retry_key = "pass_obstacle:%s" % waypoint
        if not self._navigation_retry_ready(retry_key):
            return
        if not self._nav.goal_sent and not self._nav.is_done():
            self.get_logger().info(
                "[越障 %d/%d] 导航到 %s"
                % (self._obstacle_route_index + 1, len(route), waypoint)
            )
            self._nav.navigate_to_waypoint(waypoint)
        if not self._nav.is_done():
            return
        if not self._nav.succeeded():
            self._retry_navigation_or_abort(retry_key, waypoint)
            return

        if waypoint == "obstacle_cross_target" and not self._obstacle_depth_transition_complete:
            if self._obstacle_depth_mode is None:
                self._obstacle_depth_mode = (
                    self._depth_policy.waypoint_succeeded(waypoint)
                    if self._depth_policy is not None
                    else None
                )
            if not self._ensure_depth_mode(
                self._obstacle_depth_mode,
                "after_success:obstacle_cross_target",
            ):
                return
            self._obstacle_depth_transition_complete = True

        self._clear_navigation_retry(retry_key)
        if self._depth_policy is not None and waypoint not in self._depth_recorded_waypoints:
            self._depth_policy.waypoint_succeeded(waypoint)
            self._depth_recorded_waypoints.add(waypoint)
        self._nav.reset()
        self._obstacle_route_index += 1
        if self._obstacle_route_index < len(route):
            return

        self.get_logger().info("已到达观察位①，保持 Phase 1 地图并进入巡检")
        self._inspection_workflow.navigation_succeeded()
        self._switch_to_phase2_map()
        del self._obstacle_route_index
        self._advance_to_next_phase()

    def _tick_inspect_gauges(self, elapsed: float) -> None:
        """Navigate, verify stop, call WHZ asynchronously, and store one result."""
        if self._handle_timeout(elapsed):
            return

        workflow = self._inspection_workflow
        if workflow.stage == InspectionStage.ABORTED:
            self._abort(workflow.abort_reason)
            return

        if workflow.stage == InspectionStage.COMPLETE:
            if self._inspection_requires_abcd:
                workflow.require_complete_abcd()
                if workflow.stage == InspectionStage.ABORTED:
                    self._abort(workflow.abort_reason)
                    return
            abnormal = [
                info for info in self._gauge_info.values()
                if info.status and info.status != "normal"
            ]
            if abnormal:
                self._abnormal_zones = [g.letter for g in abnormal]
                zones = ", ".join(
                    f"{g.letter}区({g.color}/{g.status})" for g in abnormal
                )
                self.get_logger().info(
                    f"巡检完成 — 异常: {zones}  "
                    f"(共{len(self._abnormal_zones)}处，需{len(self._abnormal_zones)}趟往返)"
                )
            else:
                self.get_logger().info("巡检完成 — 未发现异常")
            self._abnormal_handled = 0
            if self._inspection_only or self._finish_after_inspection:
                self._enter_phase(Phase.FINISH)
            elif not self._allow_placeholder_manipulation:
                self._abort("mechanical arm feedback is not implemented")
            else:
                self._advance_to_next_phase()
            return

        if self._inspection_route_index >= len(self._inspection_route_steps):
            self._abort("inspection route ended before workflow completion")
            return
        step_info = self._inspection_route_steps[self._inspection_route_index]
        wp = step_info["waypoint"]
        now = time.monotonic()

        if step_info.get("kind") == "transit":
            if workflow.stage != InspectionStage.NAVIGATING:
                self._abort(
                    "transit waypoint reached in inspection stage %s"
                    % workflow.stage.value
                )
                return
            retry_key = "inspection_transit:%d:%s" % (
                self._inspection_route_index,
                wp,
            )
            if not self._navigation_retry_ready(retry_key):
                return
            if not self._nav.goal_sent and not self._nav.is_done():
                self.get_logger().info("[巡检转接] %s: %s" % (step_info["desc"], wp))
                self._nav.navigate_to_waypoint(wp)
            if not self._nav.is_done():
                return
            if not self._nav.succeeded():
                self._retry_navigation_or_abort(retry_key, step_info["desc"])
                return
            self._clear_navigation_retry(retry_key)
            if self._depth_policy is not None and wp not in self._depth_recorded_waypoints:
                self._depth_policy.waypoint_succeeded(wp)
                self._depth_recorded_waypoints.add(wp)
            self._nav.reset()
            self._inspection_route_index += 1
            return

        if workflow.stage == InspectionStage.NAVIGATING:
            if now < self._inspection_retry_not_before:
                return
            if not self._nav.goal_sent and not self._nav.is_done():
                self.get_logger().info(
                    "[观察 %d/%d] 导航: %s"
                    % (
                        workflow.step_index + 1,
                        workflow.step_count,
                        step_info["desc"],
                    )
                )
                self._nav.navigate_to_waypoint(wp)

            if not self._nav.is_done():
                return
            if self._nav.succeeded():
                self.get_logger().info("已到达 %s，开始停稳确认" % wp)
                if self._depth_policy is not None and wp not in self._depth_recorded_waypoints:
                    self._depth_policy.waypoint_succeeded(wp)
                    self._depth_recorded_waypoints.add(wp)
                self._nav.reset()
                self._inspection_retry_not_before = 0.0
                workflow.navigation_succeeded()
                return

            reason = self._nav.failure_reason or self._nav.result_name
            self._nav.reset()
            if workflow.navigation_failed(reason):
                self._inspection_retry_not_before = now + self._retry_delay_sec
                self.get_logger().warn(
                    "到%s导航失败，重试 %d/%d: %s"
                    % (
                        wp,
                        workflow.nav_retries,
                        workflow.max_nav_retries,
                        reason,
                    )
                )
            else:
                self._abort(workflow.abort_reason)
            return

        if workflow.stage == InspectionStage.SETTLING:
            odom_fresh = (
                time.time() - self._last_odom_time
            ) <= self._odom_timeout_sec
            stationary = (
                odom_fresh
                and self._last_odom_linear_speed <= self._settle_linear_speed_mps
                and self._last_odom_angular_speed <= self._settle_angular_speed_rps
            )
            if workflow.update_stationary(now, stationary):
                self._inspection_service_wait_started = now
                self.get_logger().info(
                    "停稳确认通过: linear=%.4f m/s angular=%.4f rad/s"
                    % (
                        self._last_odom_linear_speed,
                        self._last_odom_angular_speed,
                    )
                )
            return

        if workflow.stage == InspectionStage.WAITING_SERVICE:
            if self._whz_client.service_is_ready():
                self._inspection_request_id += 1
                self._inspection_future = self._whz_client.call_async(Trigger.Request())
                self._inspection_request_started = now
                workflow.service_started()
                self.get_logger().info(
                    "WHZ request %d started: %s"
                    % (self._inspection_request_id, step_info["desc"])
                )
                return

            if self._inspection_service_wait_started is None:
                self._inspection_service_wait_started = now
            if now - self._inspection_service_wait_started < self._inspection_service_wait_sec:
                return
            self._inspection_service_wait_started = None
            if workflow.inspection_failed("service_unavailable"):
                self.get_logger().warn(
                    "WHZ service unavailable，重试 %d/%d"
                    % (
                        workflow.inspection_retries,
                        workflow.max_inspection_retries,
                    )
                )
            else:
                self._abort(workflow.abort_reason)
            return

        if workflow.stage != InspectionStage.INSPECTING:
            self._abort("unexpected_inspection_stage=%s" % workflow.stage.value)
            return

        if self._inspection_future is None:
            self._abort("inspection_future_missing")
            return

        if not self._inspection_future.done():
            if now - self._inspection_request_started > self._inspection_response_timeout_sec:
                self._inspection_future = None
                workflow.inspection_timed_out(
                    "%.1fs" % self._inspection_response_timeout_sec
                )
                self._abort(workflow.abort_reason)
            return

        try:
            response = self._inspection_future.result()
        except Exception as exc:  # noqa: BLE001
            self._inspection_future = None
            if workflow.inspection_failed("service_future_error: %s" % exc):
                self.get_logger().warn(
                    "WHZ service future failed，重试 %d/%d: %s"
                    % (
                        workflow.inspection_retries,
                        workflow.max_inspection_retries,
                        exc,
                    )
                )
            else:
                self._abort(workflow.abort_reason)
            return

        self._inspection_future = None
        if response is None:
            if workflow.inspection_failed("empty_service_response"):
                self.get_logger().warn(
                    "WHZ returned no response，重试 %d/%d"
                    % (
                        workflow.inspection_retries,
                        workflow.max_inspection_retries,
                    )
                )
            else:
                self._abort(workflow.abort_reason)
            return

        try:
            reading = InspectionReading.from_trigger(
                response.success,
                response.message,
                require_audio=self._require_inspection_audio,
            )
        except InspectionContractError as exc:
            if workflow.inspection_failed(str(exc)):
                self.get_logger().warn(
                    "WHZ inspection rejected，重试 %d/%d: %s"
                    % (
                        workflow.inspection_retries,
                        workflow.max_inspection_retries,
                        exc,
                    )
                )
            else:
                self._abort(workflow.abort_reason)
            return

        workflow.inspection_succeeded(reading)
        if workflow.stage == InspectionStage.ABORTED:
            self._abort(workflow.abort_reason)
            return

        self._store_inspection_reading(reading)
        self._inspection_route_index += 1
        self._inspection_service_wait_started = None
        self.get_logger().info(
            "观察结果入账: %s区 %s/%s vote=%d/%d audio=%s"
            % (
                reading.area,
                reading.color,
                reading.status,
                reading.agree_frames,
                reading.total_frames,
                reading.audio_played,
            )
        )

    def _store_inspection_reading(self, reading: InspectionReading) -> None:
        info = self._gauge_info[reading.area]
        info.detected = True
        info.stable_detected = True
        info.letter = reading.area
        info.color = reading.color
        info.level = reading.state_key
        info.status = reading.status

    def _tick_find_red_bar(self, elapsed: float) -> None:
        """FIND_RED_BAR: 导航到抓取区，寻找并定位红色条。"""
        if self._handle_timeout(elapsed):
            return

        if not self._grab_depth_transition_complete:
            if self._grab_depth_mode is None:
                self._grab_depth_mode = (
                    self._depth_policy.before_waypoint("grab_area_approach")
                    if self._depth_policy is not None
                    else None
                )
            if not self._ensure_depth_mode(
                self._grab_depth_mode,
                "before:grab_area_approach",
            ):
                return
            self._grab_depth_transition_complete = True

        # 先导航到抓取区
        if not self._navigation_retry_ready("find_red_bar:grab_area_approach"):
            return
        if not self._nav.goal_sent and not self._nav.is_done():
            self._nav.navigate_to_waypoint("grab_area_approach")

        if not self._nav.is_done():
            return
        if not self._nav.succeeded():
            self._retry_navigation_or_abort("find_red_bar:grab_area_approach", "抓取区")
            return
        self._clear_navigation_retry("find_red_bar:grab_area_approach")

        # 等待 YOLO 检测到红色条
        if self._latest_yolo and len(self._latest_yolo.red_bars) > 0:
            bar = self._latest_yolo.red_bars[0]
            dist = bar.get("distance_m", "?")
            self.get_logger().info(
                f"检测到红色条 (距离={dist}m)，进入抓取阶段"
            )
            self._nav.reset()
            self._advance_to_next_phase()

    def _tick_grasp_bar(self, elapsed: float) -> None:
        """GRASP_BAR: 等待抓取完成。"""
        if self._handle_timeout(elapsed):
            return

        if not self._allow_placeholder_manipulation:
            self._abort("mechanical arm feedback is not implemented")
            return

        # Bench-only placeholder; production must use explicit arm feedback.
        if elapsed > 1.0:
            self.get_logger().info("抓取完成 (占位)，进入放置阶段")
            self._advance_to_next_phase()

    def _tick_place_to_abnormal_zone(self, elapsed: float) -> None:
        """PLACE_TO_ABNORMAL_ZONE: 导航到当前异常区域放置纸箱。"""
        if self._handle_timeout(elapsed):
            return

        if not self._allow_placeholder_manipulation:
            self._abort("mechanical arm feedback is not implemented")
            return

        if self._abnormal_handled >= len(self._abnormal_zones):
            self.get_logger().info("所有异常区域已处理完毕！")
            self._advance_to_next_phase()
            return

        current_zone = self._abnormal_zones[self._abnormal_handled]

        # 导航到对应放置区
        retry_key = "placement:%s" % current_zone
        if not self._navigation_retry_ready(retry_key):
            return
        if not self._nav.goal_sent and not self._nav.is_done():
            target = f"placement_{current_zone}_approach"
            self._nav.navigate_to_waypoint(target)

        if not self._nav.is_done():
            return
        if not self._nav.succeeded():
            self._retry_navigation_or_abort(
                retry_key,
                "%s放置区" % current_zone,
            )
            return
        self._clear_navigation_retry(retry_key)
        if self._placement_arrival_time is None:
            self._placement_arrival_time = time.monotonic()

        # Bench-only placeholder; production must use explicit arm feedback.
        if time.monotonic() - self._placement_arrival_time > 1.0:
            self._abnormal_handled += 1
            remaining = len(self._abnormal_zones) - self._abnormal_handled
            self.get_logger().info(
                f"{current_zone}区放置完成 ({self._abnormal_handled}/{len(self._abnormal_zones)})"
                + (f"，剩余 {remaining} 趟" if remaining > 0 else "，全部完成！")
            )
            self._placement_arrival_time = None
            if remaining > 0:
                # 折返：回到抓取区取下一个红色块
                self._nav.reset()
                self._enter_phase(Phase.FIND_RED_BAR)
            else:
                self._advance_to_next_phase()

    # ═══════════════════════════════════════════════════════════
    #  阶段推进
    # ═══════════════════════════════════════════════════════════

    def _abort(self, reason: str) -> None:
        if self._phase == Phase.ABORT:
            return
        self._abort_reason = str(reason)
        self.get_logger().error("任务中止: %s" % self._abort_reason)
        self._enter_phase(Phase.ABORT)

    def _retry_navigation_or_abort(self, key: str, label: str) -> bool:
        reason = self._nav.failure_reason or self._nav.result_name
        retries = self._nav_retry_counts.get(key, 0)
        self._nav.reset()
        if retries >= self._max_nav_retries:
            self._abort(
                "%s导航在%d次尝试后失败: %s"
                % (label, self._max_nav_retries + 1, reason)
            )
            return False
        retries += 1
        self._nav_retry_counts[key] = retries
        self._nav_retry_not_before[key] = time.monotonic() + self._retry_delay_sec
        self.get_logger().warn(
            "%s导航失败，重试 %d/%d: %s"
            % (label, retries, self._max_nav_retries, reason)
        )
        return True

    def _clear_navigation_retry(self, key: str) -> None:
        self._nav_retry_counts.pop(key, None)
        self._nav_retry_not_before.pop(key, None)

    def _navigation_retry_ready(self, key: str) -> bool:
        return time.monotonic() >= self._nav_retry_not_before.get(key, 0.0)

    def _robot_stopped_for_depth_transition(self) -> bool:
        odom_fresh = (time.time() - self._last_odom_time) <= self._odom_timeout_sec
        stationary = bool(
            odom_fresh
            and self._last_odom_linear_speed <= self._settle_linear_speed_mps
            and self._last_odom_angular_speed <= self._settle_angular_speed_rps
            and not self._nav.goal_sent
        )
        return self._depth_transition_stationary.update(
            time.monotonic(),
            stationary,
        )

    def _ensure_depth_mode(self, mode, milestone: str) -> bool:
        if mode is None or self._depth_mode_client is None:
            return True
        readiness = self._depth_mode_client.readiness()
        if self._depth_mode_client.end_to_end_ready(mode):
            if not self._host_odom_ready_after_depth_transition(mode):
                return False
            self._depth_pending_mode = None
            self._depth_pending_milestone = ""
            self._depth_pending_request_id = ""
            self._depth_pending_started = 0.0
            self._depth_pending_odom_baseline = 0.0
            self._depth_transition_stationary.reset()
            return True
        if self._depth_pending_mode is None:
            if not self._robot_stopped_for_depth_transition():
                return False
            request = self._depth_mode_client.begin_transition(
                mode,
                robot_stopped=True,
            )
            self._depth_pending_mode = mode
            self._depth_pending_milestone = milestone
            self._depth_pending_request_id = (
                "" if request is None else request["request_id"]
            )
            self._depth_pending_started = time.monotonic()
            self._depth_pending_odom_baseline = self._last_odom_time
            self._depth_transition_stationary.reset()
            self.get_logger().info(
                "深度模式切换请求: %s milestone=%s request=%s"
                % (mode.value, milestone, self._depth_pending_request_id or "already_ready")
            )
            return False
        if self._depth_pending_mode != mode:
            self._abort(
                "depth transition collision: pending=%s requested=%s"
                % (self._depth_pending_mode.value, mode.value)
            )
            return False
        readiness = self._depth_mode_client.readiness()
        if self._depth_mode_client.end_to_end_ready(mode):
            if not self._host_odom_ready_after_depth_transition(mode):
                return False
            self.get_logger().info(
                "深度模式已确认: %s milestone=%s"
                % (mode.value, self._depth_pending_milestone)
            )
            self._depth_pending_mode = None
            self._depth_pending_milestone = ""
            self._depth_pending_request_id = ""
            self._depth_pending_started = 0.0
            self._depth_pending_odom_baseline = 0.0
            self._depth_transition_stationary.reset()
            return True
        if (
            self._depth_pending_started > 0.0
            and time.monotonic() - self._depth_pending_started
            > self._depth_transition_timeout_sec
        ):
            reason = (
                self._depth_mode_client.end_to_end_reason(mode)
                if readiness.ready
                else readiness.reason
            )
            self._abort(
                "depth pipeline readiness timed out at %s: %s"
                % (self._depth_pending_milestone, reason)
            )
            return False
        if readiness.mode == DepthMode.FAULT:
            self._abort(
                "depth transition failed at %s: %s"
                % (self._depth_pending_milestone, readiness.reason)
            )
        return False

    def _host_odom_ready_after_depth_transition(self, mode) -> bool:
        if (
            mode != DepthMode.DISABLED
            or not self._verify_host_odom_after_depth_disable
        ):
            return True
        odom_is_new = self._last_odom_time > self._depth_pending_odom_baseline
        odom_is_fresh = (
            time.time() - self._last_odom_time
            <= min(self._odom_timeout_sec, self._host_odom_disable_timeout_sec)
        )
        if (
            not (odom_is_new and odom_is_fresh)
            and self._depth_pending_started > 0.0
            and time.monotonic() - self._depth_pending_started
            > self._host_odom_disable_timeout_sec
        ):
            self._abort("host /odom did not recover after disabling D455 depth")
        return bool(odom_is_new and odom_is_fresh)

    def _enter_phase(self, phase: Phase) -> None:
        """进入新阶段，执行入口动作并发布状态。"""
        if phase == Phase.ABORT:
            if self._nav.goal_sent:
                self._nav.cancel()
            self._inspection_future = None
        if phase == Phase.PLACE_TO_ABNORMAL_ZONE:
            self._placement_arrival_time = None
        self._phase = phase
        self._phase_enter_time = time.time()

        phase_name = phase.name.lower()
        phase_label = phase.label()

        # 发布当前阶段
        msg = String()
        msg.data = phase_name
        self._phase_pub.publish(msg)

        # 日志
        if phase in (Phase.FINISH, Phase.ABORT):
            self.get_logger().info(f"══════ 状态机进入终态: {phase_label} ══════")
        else:
            idx = self.PHASE_SEQUENCE.index(phase) + 1 if phase in self.PHASE_SEQUENCE else 0
            total = len(self.PHASE_SEQUENCE)
            self.get_logger().info(
                f"──> [{idx}/{total}] 进入阶段: {phase_label} ({phase_name})"
            )

        self._publish_full_status()

    def _switch_to_phase2_map(self) -> None:
        """越障完成后切换地图: 障碍区封堵, 后续不走回头路."""
        if not self._enable_phase2_map_switch:
            self.get_logger().info("保持 competition_field_phase1 地图，不执行阶段切图")
            return
        if not self._map_client.wait_for_service(timeout_sec=3.0):
            self.get_logger().warn("map_server 不可用, 跳过地图切换")
            return
        req = LoadMap.Request()
        req.map_url = self._phase2_yaml
        future = self._map_client.call_async(req)
        future.add_done_callback(
            lambda f: self.get_logger().info(
                "地图已切换 → Phase 2 (障碍区封堵)"
            ) if f.result().result == LoadMap.Response().RESULT_SUCCESS
            else self.get_logger().error("地图切换失败")
        )

    def _advance_to_next_phase(self) -> None:
        """推进到下一个阶段。"""
        if self._phase == Phase.START:
            self._enter_phase(Phase.PASS_OBSTACLE)
            self._phase_seq_idx = 0
            return

        # 在 PHASE_SEQUENCE 中找下一个
        try:
            current_idx = self.PHASE_SEQUENCE.index(self._phase)
            next_idx = current_idx + 1
        except ValueError:
            self.get_logger().error(f"当前阶段 {self._phase} 不在序列中!")
            return

        if next_idx >= len(self.PHASE_SEQUENCE):
            self._enter_phase(Phase.FINISH)
        else:
            self._phase_seq_idx = next_idx
            self._enter_phase(self.PHASE_SEQUENCE[next_idx])

    def _handle_timeout(self, elapsed: float) -> bool:
        """检查超时。返回 True 表示已超时并中止。"""
        timeout = self._phase_timeouts.get(self._phase, self._timeout_per_phase)
        if elapsed > timeout:
            self._abort(
                "阶段 %s 超时 (%.1fs > %.1fs)"
                % (self._phase.label(), elapsed, timeout)
            )
            return True
        return False

    # ═══════════════════════════════════════════════════════════
    #  订阅回调
    # ═══════════════════════════════════════════════════════════

    def _on_yolo_detections(self, msg: String) -> None:
        """解析 /yolo/detections JSON，提取仪表/字母/红条/绿条。"""
        try:
            data = json.loads(msg.data)
        except (json.JSONDecodeError, TypeError) as exc:
            self.get_logger().warn(f"yolo/detections JSON 解析失败: {exc}")
            return

        detections = data.get("detections", [])
        detection = YoloDetection(
            timestamp=time.time(),
        )

        for d in detections:
            class_name = d.get("class_name", "")
            class_id = d.get("class_id", -1)

            if class_name == "gauge" or class_id == 0:
                detection.gauges.append(d)
            elif class_name in ("A", "B", "C", "D") or class_id in (1, 2, 3, 4):
                letter = class_name if class_name in "ABCD" else {1: "A", 2: "B", 3: "C", 4: "D"}.get(class_id, "?")
                detection.letters.setdefault(letter, []).append(d)
            elif class_name == "red_bar" or class_id == 5:
                detection.red_bars.append(d)
            elif class_name == "green_bar" or class_id == 6:
                detection.green_bars.append(d)

        self._latest_yolo = detection

    def _on_slam_status(self, msg: String) -> None:
        """解析 /visual_slam/status，追踪定位状态。"""
        try:
            data = json.loads(msg.data)
        except (json.JSONDecodeError, TypeError):
            # SLAM status 可能不是 JSON，尝试直接读字符串
            text = msg.data.strip().lower()
            if text in ("ok", "tracking", "nominal"):
                self._slam_tracking_ok = True
            elif text in ("lost", "degraded", "unknown"):
                self._slam_tracking_ok = False
            self._slam_status_time = time.time()
            return

        # JSON 格式: 检查 vo_state 字段
        state = data.get("vo_state", data.get("state", "")).lower()
        self._slam_tracking_ok = state in ("ok", "tracking", "nominal")
        self._slam_status_time = time.time()

        if not self._slam_tracking_ok and self._phase not in (
            Phase.START,
            Phase.FINISH,
            Phase.ABORT,
        ):
            self.get_logger().warn(
                f"SLAM 定位状态异常: {state}，当前阶段 {self._phase.label()}"
            )

    def _on_odom(self, msg: Odometry) -> None:
        """Track host-side localization readiness from /odom."""
        twist = msg.twist.twist
        self._last_odom_linear_speed = math.sqrt(
            twist.linear.x * twist.linear.x
            + twist.linear.y * twist.linear.y
            + twist.linear.z * twist.linear.z
        )
        self._last_odom_angular_speed = abs(twist.angular.z)
        self._last_odom_time = time.time()

    # ═══════════════════════════════════════════════════════════
    #  状态发布
    # ═══════════════════════════════════════════════════════════

    def _publish_speech(self, text: str) -> None:
        """发布语音播报文本到 /speech/text。"""
        msg = String()
        msg.data = text
        self._speech_pub.publish(msg)

    def _publish_full_status(self) -> None:
        """发布完整状态 JSON 到 /task/status。"""
        gauge_data = {}
        for letter, info in self._gauge_info.items():
            gauge_data[letter] = {
                "detected": info.detected,
                "stable_detected": info.stable_detected,
                "color": info.color,
                "level": info.level,
                "status": info.status,
            }

        yolo_summary = None
        if self._latest_yolo:
            yolo_summary = {
                "num_gauges": len(self._latest_yolo.gauges),
                "num_letters": sum(len(v) for v in self._latest_yolo.letters.values()),
                "num_red_bars": len(self._latest_yolo.red_bars),
                "num_green_bars": len(self._latest_yolo.green_bars),
            }

        payload = {
            "phase": self._phase.name.lower(),
            "phase_label": self._phase.label(),
            "phase_elapsed_s": round(time.time() - self._phase_enter_time, 2),
            "timeout_s": self._phase_timeouts.get(
                self._phase,
                self._timeout_per_phase,
            ),
            "slam_tracking_ok": self._slam_tracking_ok,
            "slam_ok": self._slam_tracking_ok,
            "slam_status_age_s": (
                round(time.time() - self._slam_status_time, 3)
                if self._slam_status_time > 0.0 else None
            ),
            "odom_ok": (
                time.time() - self._last_odom_time <= self._odom_timeout_sec
                if self._last_odom_time > 0.0 else False
            ),
            "odom_age_s": (
                round(time.time() - self._last_odom_time, 3)
                if self._last_odom_time > 0.0 else None
            ),
            "abnormal_zones": self._abnormal_zones,
            "abnormal_handled": self._abnormal_handled,
            "abort_reason": self._abort_reason,
            "waypoint_source": self._waypoint_source,
            "waypoint_route": self._waypoint_route,
            "navigation": self._nav.status_dict(),
            "depth": {
                "enabled": self._enable_depth_milestones,
                "current_mode": (
                    self._depth_mode_client.current_mode.value
                    if self._depth_mode_client is not None
                    else DepthMode.DISABLED.value
                ),
                "pending_mode": (
                    self._depth_pending_mode.value
                    if self._depth_pending_mode is not None
                    else None
                ),
                "pending_milestone": self._depth_pending_milestone or None,
                "pending_request_id": self._depth_pending_request_id or None,
                "safety_ready": (
                    self._depth_mode_client.safety_ready
                    if self._depth_mode_client is not None
                    else None
                ),
                "safety_reason": (
                    self._depth_mode_client.safety_reason
                    if self._depth_mode_client is not None
                    else None
                ),
                "verify_host_odom_after_disable": (
                    self._verify_host_odom_after_depth_disable
                ),
                "host_odom_ready_after_transition": (
                    self._last_odom_time > self._depth_pending_odom_baseline
                    if self._depth_pending_mode == DepthMode.DISABLED
                    else None
                ),
            },
            "inspection": {
                "stage": self._inspection_workflow.stage.value,
                "step_index": self._inspection_workflow.step_index,
                "step_count": self._inspection_workflow.step_count,
                "nav_retries": self._inspection_workflow.nav_retries,
                "inspection_retries": self._inspection_workflow.inspection_retries,
                "areas": sorted(self._inspection_workflow.readings),
                "abort_reason": self._inspection_workflow.abort_reason,
                "last_linear_speed_mps": (
                    self._last_odom_linear_speed
                    if math.isfinite(self._last_odom_linear_speed)
                    else None
                ),
                "last_angular_speed_rps": (
                    self._last_odom_angular_speed
                    if math.isfinite(self._last_odom_angular_speed)
                    else None
                ),
            },
            "gauges": gauge_data,
            "yolo": yolo_summary,
        }

        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self._status_pub.publish(msg)

    # ═══════════════════════════════════════════════════════════
    #  清理
    # ═══════════════════════════════════════════════════════════

    def destroy_node(self) -> bool:
        self.get_logger().info("Task Manager 关闭中...")
        if self._nav.goal_sent:
            self._nav.cancel()
        self._inspection_future = None
        return super().destroy_node()


# ═══════════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════════

def main(args=None) -> None:
    rclpy.init(args=args)
    node = TaskManagerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
