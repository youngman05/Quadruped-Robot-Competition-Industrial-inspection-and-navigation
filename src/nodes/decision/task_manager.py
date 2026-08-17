#!/usr/bin/env python3
"""ROS2 node: 比赛任务状态机 (Competition Task Manager).

掌控比赛全流程，协调感知、导航、语音、机械臂各模块。

订阅:
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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
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
from nodes.decision.competition_task_core import (
    ZoneAssessment,
    freeze_two_zone_tasks,
    normalize_zone_order,
)
from nodes.decision.timeout_budget import ElapsedTimeoutBudget
from nodes.decision.pick_alignment_core import (
    FiducialDetectionFrame,
    I2Target,
    PickConfig,
    PickOneExecutor,
    parse_fiducial_frame,
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
from nodes.decision.manipulation_contracts import CLASS_SCHEMA, MODEL_ID


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
    confidence: float = 0.0


class _PickRuntimeAdapter:
    def __init__(self, node: "TaskManagerNode") -> None:
        self._node = node

    @staticmethod
    def now() -> float:
        return time.monotonic()

    def stop(self) -> None:
        self._node._publish_precision_zero()

    def command(self, axis: str, speed: float) -> None:
        self._node._publish_precision_command(axis, speed)

    def current_fiducial_frame(self) -> Optional[FiducialDetectionFrame]:
        if not self._node._manipulation_packet_is_fresh(
            self._node._latest_apriltag_received_monotonic
        ):
            return None
        return self._node._latest_apriltag_frame

    @staticmethod
    def start_grasp() -> bool:
        return False

    @staticmethod
    def grasp_result() -> Optional[bool]:
        return None


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
        self.declare_parameter("timeout_per_phase", 300.0)   # 每阶段超时 (秒)
        self.declare_parameter("pass_obstacle_timeout_sec", 180.0)
        self.declare_parameter("pass_obstacle_waypoint_timeout_sec", 120.0)
        self.declare_parameter("inspection_timeout_sec", 300.0)
        self.declare_parameter("tick_rate", 10.0)             # 状态机主循环频率 (Hz)
        self.declare_parameter("require_stable_gauge", True)  # 是否必须稳定检测
        self.declare_parameter("auto_advance", False)         # 调试: 自动推进阶段
        self.declare_parameter("mission_start_armed", True)

        self.declare_parameter("phase2_map_yaml", "navi/map/competition_field_phase2.yaml")
        self.declare_parameter("gauge_topic", "/gauge/status")
        self.declare_parameter("slam_status_topic", "/visual_slam/status")
        self.declare_parameter("odom_topic", "/odom")
        self.declare_parameter("odom_timeout_sec", 10.0)
        self.declare_parameter("odom_ready_hold_sec", 10.0)
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
        self.declare_parameter("enable_manipulation", False)
        self.declare_parameter("manipulation_preset", "unconfigured")
        self.declare_parameter("enable_pick_i2_alignment", False)
        self.declare_parameter("enable_place_vision_alignment", False)
        self.declare_parameter("apriltag_topic", "/apriltag/detections_base")
        self.declare_parameter("precision_cmd_topic", "/cmd_vel_precision")
        self.declare_parameter(
            "manipulation_frames_dir",
            str(Path.home() / "workspaces/isaac_ros-dev/camera_frames"),
        )
        self.declare_parameter("manipulation_model_id", MODEL_ID)
        self.declare_parameter("manipulation_class_schema", CLASS_SCHEMA)
        self.declare_parameter("abnormal_zone_fallback_order", ["A", "B", "C", "D"])
        self.declare_parameter("pick_red_tag_ids", [])
        self.declare_parameter("pick_i2_targets_json", "{}")
        self.declare_parameter("grasp_target_arm_base", [])
        self.declare_parameter("place_target_distance_m", 0.0)
        self.declare_parameter("placement_color_width_px", 640)
        self.declare_parameter("placement_color_height_px", 360)
        self.declare_parameter("placement_camera_pitch_deg", 30.0)
        self.declare_parameter("placement_box_width_m", 0.50)
        self.declare_parameter("arm_service_timeout_sec", 30.0)
        self.declare_parameter("arm_max_sequence_sec", 20.0)
        self.declare_parameter("precision_release_duration_sec", 0.6)
        self.declare_parameter("manipulation_perception_timeout_sec", 0.5)
        self.declare_parameter("waypoint_file", "")
        self.declare_parameter("waypoint_route", "inspection_interleaved")
        self.declare_parameter("expected_map_id", "")
        self.declare_parameter("enable_cone_controller", False)
        self.declare_parameter("cone_behavior_tree", "")
        self.declare_parameter("inspection_start_index", 0)
        self.declare_parameter("inspection_count", 0)
        self.declare_parameter("enable_phase2_map_switch", False)
        self.declare_parameter("enable_depth_milestones", False)
        self.declare_parameter("require_cone_layer_startup_ready", False)
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
        self._pass_obstacle_waypoint_timeout = ElapsedTimeoutBudget(
            self.get_parameter("pass_obstacle_waypoint_timeout_sec").value
        )
        self._tick_rate = float(self.get_parameter("tick_rate").value)
        self._require_stable = bool(self.get_parameter("require_stable_gauge").value)
        self._auto_advance = bool(self.get_parameter("auto_advance").value)

        slam_status_topic = str(self.get_parameter("slam_status_topic").value)
        odom_topic = str(self.get_parameter("odom_topic").value)
        phase_topic = str(self.get_parameter("phase_topic").value)
        status_topic = str(self.get_parameter("status_topic").value)
        self._odom_timeout_sec = float(self.get_parameter("odom_timeout_sec").value)
        self._odom_ready_hold_sec = max(
            0.0, float(self.get_parameter("odom_ready_hold_sec").value)
        )
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
        self._enable_manipulation = bool(
            self.get_parameter("enable_manipulation").value
        )
        self._manipulation_preset = str(
            self.get_parameter("manipulation_preset").value
        ).strip()
        self._enable_pick_i2_alignment = bool(
            self.get_parameter("enable_pick_i2_alignment").value
        )
        self._manipulation_frames_dir = Path(
            str(self.get_parameter("manipulation_frames_dir").value)
        )
        self._manipulation_model_id = str(
            self.get_parameter("manipulation_model_id").value
        )
        self._manipulation_class_schema = str(
            self.get_parameter("manipulation_class_schema").value
        )
        self._abnormal_zone_fallback_order = normalize_zone_order(
            self.get_parameter("abnormal_zone_fallback_order").value
        )
        self._arm_service_timeout_sec = max(
            0.1, float(self.get_parameter("arm_service_timeout_sec").value)
        )
        self._arm_max_sequence_sec = max(
            0.1, float(self.get_parameter("arm_max_sequence_sec").value)
        )
        if self._arm_service_timeout_sec < self._arm_max_sequence_sec:
            raise ValueError(
                "arm_service_timeout_sec must be >= arm_max_sequence_sec"
            )
        self._precision_release_duration_sec = max(
            0.5,
            float(self.get_parameter("precision_release_duration_sec").value),
        )
        self._manipulation_perception_timeout_sec = max(
            0.05,
            float(
                self.get_parameter("manipulation_perception_timeout_sec").value
            ),
        )
        (
            self._pick_red_tag_ids,
            self._pick_i2_targets,
            self._grasp_target_arm_base,
        ) = self._load_manipulation_calibration()
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
        self._require_cone_layer_startup_ready = bool(
            self.get_parameter("require_cone_layer_startup_ready").value
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
        self._precision_pub = (
            self.create_publisher(
                Twist,
                str(self.get_parameter("precision_cmd_topic").value),
                10,
            )
            if self._enable_manipulation
            else None
        )

        # ── 订阅者 ────────────────────────────────
        self._apriltag_sub = (
            self.create_subscription(
                String,
                str(self.get_parameter("apriltag_topic").value),
                self._on_apriltag_detections,
                10,
            )
            if self._enable_manipulation
            else None
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
        self._latest_apriltag_frame: Optional[FiducialDetectionFrame] = None
        self._latest_apriltag_received_monotonic = 0.0
        self._slam_tracking_ok: bool = False
        self._slam_status_time: float = 0.0
        self._last_odom_time: float = 0.0
        self._odom_first_seen_time: float = 0.0
        self._last_odom_linear_speed: float = float("inf")
        self._last_odom_angular_speed: float = float("inf")
        self._abnormal_zones: Tuple[str, ...] = ()     # 第四次巡检后冻结的两个不同任务
        self._task_queue_frozen = False
        self._abnormal_attempted: int = 0              # 已消费的放置尝试数
        self._abnormal_handled: int = 0                # 明确完成动作序列的放置数
        self._manipulation_outcomes: List[Dict[str, str]] = []
        self._current_grasp_outcome = "not_attempted"
        self._used_pick_tag_ids: List[int] = []
        self._phase_seq_idx: int = 0                  # 在 PHASE_SEQUENCE 中的位置
        self._abort_reason: str = ""
        self._nav_retry_counts: Dict[str, int] = {}
        self._nav_retry_not_before: Dict[str, float] = {}
        self._placement_arrival_time: Optional[float] = None
        self._pick_arrived = False
        self._placement_arrived = False
        self._place_alignment_complete = False
        self._pick_executor: Optional[PickOneExecutor] = None
        self._precision_zero_until = 0.0
        self._grasp_future = None
        self._place_future = None
        self._grasp_request_started = 0.0
        self._place_request_started = 0.0
        self._arm_motion_guard_until = 0.0
        self._grasp_uncertain_reason = ""
        self._place_uncertain_reason = ""
        self._place_sequence_completed_pending = False
        self._depth_policy = None
        self._depth_mode_client = None
        self._startup_depth_mode = None
        self._depth_pending_mode = None
        self._depth_pending_milestone = ""
        self._depth_pending_request_id = ""
        self._depth_pending_started = 0.0
        self._depth_pending_odom_baseline = 0.0
        self._obstacle_depth_transition_complete = False
        self._depth_recorded_waypoints = set()
        self._mission_start_nav_ready = False
        self._mission_start_cone_layers_ready = (
            not self._require_cone_layer_startup_ready
        )
        self._mission_start_wait_reason = (
            "waiting for fresh odometry"
            if self._mission_start_is_armed()
            else "waiting for mission start arm"
        )

        # ── 地图切换客户端 ────────────────────────
        self._phase2_yaml = str(self.get_parameter("phase2_map_yaml").value)
        self._map_client = (
            self.create_client(LoadMap, "/map_server/load_map")
            if self._enable_phase2_map_switch
            else None
        )
        self._whz_client = self.create_client(Trigger, whz_service)
        self._grasp_service_type = None
        self._grasp_client = None
        self._place_client = None
        if self._enable_manipulation:
            from arm_new_interfaces.srv import ExecuteGraspFixed

            self._grasp_service_type = ExecuteGraspFixed
            self._grasp_client = self.create_client(
                ExecuteGraspFixed, "/arm/execute_grasp_fixed"
            )
            self._place_client = self.create_client(
                Trigger, "/arm/execute_place_fixed"
            )

        # ── 导航客户端 (Nav2 NavigateToPose) ─────
        waypoint_file = str(self.get_parameter("waypoint_file").value).strip()
        waypoint_route = str(self.get_parameter("waypoint_route").value).strip()
        expected_map_id = str(self.get_parameter("expected_map_id").value).strip()
        enable_cone_controller = bool(
            self.get_parameter("enable_cone_controller").value
        )
        cone_behavior_tree = str(
            self.get_parameter("cone_behavior_tree").value
        ).strip()
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
        behavior_tree_by_waypoint = {}
        if enable_cone_controller:
            if not cone_behavior_tree:
                raise ValueError("cone controller requires a behavior tree path")
            if not Path(cone_behavior_tree).is_file():
                raise ValueError(
                    "cone behavior tree does not exist: %s" % cone_behavior_tree
                )
            behavior_tree_by_waypoint["obstacle_cross_target"] = cone_behavior_tree
        self._nav = NavigationClient(
            self,
            waypoints=task_waypoints,
            behavior_tree_by_waypoint=behavior_tree_by_waypoint,
        )
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
            f"| pass_obstacle_timeout={self._phase_timeouts[Phase.PASS_OBSTACLE]}s "
            f"| pass_obstacle_waypoint_timeout="
            f"{self._pass_obstacle_waypoint_timeout.timeout_sec}s "
            f"| require_stable={self._require_stable} "
            f"| inspection_only={self._inspection_only} "
            f"| finish_after_inspection={self._finish_after_inspection} "
            f"| placeholder_manipulation={self._allow_placeholder_manipulation} "
            f"| inspection_steps={len(self._inspection_steps)} "
            f"| waypoint_source={self._waypoint_source} "
            f"| waypoint_route={self._waypoint_route} "
            f"| cone_controller={enable_cone_controller} "
            f"| cone_behavior_tree={cone_behavior_tree if enable_cone_controller else 'default'} "
            f"| depth_milestones={self._enable_depth_milestones} "
            f"| mission_start_armed={self._mission_start_is_armed()} "
            f"| phase2_map_switch={self._enable_phase2_map_switch}"
        )

    def _load_manipulation_calibration(
        self,
    ) -> Tuple[
        Tuple[int, ...],
        Dict[int, I2Target],
        Tuple[float, float, float],
    ]:
        if not self._enable_manipulation:
            return (), {}, (0.0, 0.0, 0.0)
        if self._manipulation_preset != "competition_v1":
            raise ValueError(
                "enable_manipulation requires manipulation_preset=competition_v1"
            )
        if (
            self._manipulation_model_id != MODEL_ID
            or self._manipulation_class_schema != CLASS_SCHEMA
        ):
            raise ValueError("manipulation model identity does not match the locked A-D model")

        tag_ids = tuple(
            int(value) for value in self.get_parameter("pick_red_tag_ids").value
        )
        if (
            len(tag_ids) != 2
            or len(set(tag_ids)) != 2
            or min(tag_ids) < 0
        ):
            raise ValueError("pick_red_tag_ids must contain exactly two unique non-negative IDs")
        try:
            raw_targets = json.loads(
                str(self.get_parameter("pick_i2_targets_json").value)
            )
        except json.JSONDecodeError as exc:
            raise ValueError("pick_i2_targets_json is invalid JSON") from exc
        if not isinstance(raw_targets, dict):
            raise ValueError("pick_i2_targets_json must be an object")
        try:
            raw_target_ids = {
                int(key)
                for key in raw_targets
                if isinstance(key, str) and key.isdigit() and str(int(key)) == key
            }
        except (TypeError, ValueError) as exc:
            raise ValueError("pick_i2_targets_json keys must be canonical tag IDs") from exc
        if len(raw_target_ids) != len(raw_targets):
            raise ValueError("pick_i2_targets_json keys must be canonical tag IDs")
        if self._enable_pick_i2_alignment:
            if raw_target_ids != set(tag_ids):
                raise ValueError("I2 target keys must exactly match pick_red_tag_ids")
        elif raw_targets:
            raise ValueError("disabled I2 alignment must not retain active I2 targets")
        targets: Dict[int, I2Target] = {}
        for tag_id in raw_target_ids:
            values = raw_targets.get(str(tag_id))
            if not isinstance(values, list) or len(values) != 3:
                raise ValueError("missing calibrated I2 target for tag %d" % tag_id)
            xyz = tuple(float(value) for value in values)
            if not all(math.isfinite(value) for value in xyz):
                raise ValueError("I2 target for tag %d must be finite" % tag_id)
            if not -math.pi <= xyz[2] <= math.pi:
                raise ValueError("I2 target for tag %d yaw must be within [-pi, pi]" % tag_id)
            targets[tag_id] = I2Target(*xyz)

        grasp_values = list(self.get_parameter("grasp_target_arm_base").value)
        if len(grasp_values) != 3:
            raise ValueError("grasp_target_arm_base must contain x/y/z")
        grasp_target = tuple(float(value) for value in grasp_values)
        if not all(math.isfinite(value) for value in grasp_target) or grasp_target[2] <= 0.0:
            raise ValueError("grasp_target_arm_base must be finite with positive z")
        return tag_ids, targets, grasp_target

    def _publish_precision_zero(self) -> None:
        if self._precision_pub is not None:
            self._precision_pub.publish(Twist())

    def _manipulation_packet_is_fresh(self, received_monotonic: float) -> bool:
        age = time.monotonic() - float(received_monotonic)
        return 0.0 <= age <= self._manipulation_perception_timeout_sec

    def _publish_precision_command(self, axis: str, speed: float) -> None:
        if self._precision_pub is None:
            raise RuntimeError("precision publisher is unavailable")
        if not math.isfinite(speed):
            raise ValueError("precision speed must be finite")
        message = Twist()
        if axis in ("x", "dist"):
            message.linear.x = float(speed)
        elif axis in ("y", "lat"):
            message.linear.y = float(speed)
        elif axis == "yaw":
            message.angular.z = float(speed)
        else:
            raise ValueError("unsupported precision axis: %s" % axis)
        self._precision_zero_until = 0.0
        self._precision_pub.publish(message)

    def _request_precision_release(self) -> None:
        if not self._enable_manipulation:
            return
        self._precision_zero_until = max(
            self._precision_zero_until,
            time.monotonic() + self._precision_release_duration_sec,
        )
        self._publish_precision_zero()

    def _cancel_manipulation(self, cancel_services: bool = False) -> None:
        self._pick_executor = None
        if cancel_services:
            for future in (self._grasp_future, self._place_future):
                if future is not None and not future.done():
                    future.cancel()
            self._grasp_future = None
            self._place_future = None
        self._request_precision_release()

    def _start_arm_motion_guard(self) -> None:
        self._arm_motion_guard_until = max(
            self._arm_motion_guard_until,
            time.monotonic() + self._arm_max_sequence_sec,
        )

    def _arm_motion_guard_elapsed(self) -> bool:
        return time.monotonic() >= self._arm_motion_guard_until

    # ═══════════════════════════════════════════════════════════
    #  状态机主循环
    # ═══════════════════════════════════════════════════════════

    def _state_machine_tick(self) -> None:
        """每个 tick 评估当前阶段退出条件，决定是否推进。"""
        if time.monotonic() < self._precision_zero_until:
            self._publish_precision_zero()
        if not self._arm_motion_guard_elapsed():
            self._publish_precision_zero()
        elapsed = time.time() - self._phase_enter_time
        if not self._runtime_base_safety_ok():
            return

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
        if not self._mission_start_is_armed():
            self._set_mission_start_wait_reason("waiting for mission start arm")
            return
        if self._mission_start_wait_reason == "waiting for mission start arm":
            self.get_logger().info("START armed by the startup acceptance gate")
            self._mission_start_wait_reason = "waiting for fresh odometry"

        odom_fresh = (time.time() - self._last_odom_time) <= self._odom_timeout_sec
        odom_held = (
            self._odom_first_seen_time > 0.0
            and time.time() - self._odom_first_seen_time >= self._odom_ready_hold_sec
        )
        if (
            self._enable_depth_milestones
            and odom_fresh
        ):
            if not self._mission_start_prerequisites_ready():
                return
            if not self._ensure_depth_mode(
                self._startup_depth_mode,
                "mission_start",
            ):
                return

        # 调试模式: 跳过所有条件直接推进
        if self._auto_advance and elapsed > 0.5:
            if self._inspection_only:
                self._enter_phase(Phase.INSPECT_GAUGES)
            else:
                self._advance_to_next_phase()
            return

        # 正式条件: SLAM 就绪 + 至少收到过一次 gauge 数据
        if odom_fresh and odom_held and elapsed > 1.0:
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
        if self._pass_obstacle_waypoint_timeout.expired():
            waypoint_elapsed = self._pass_obstacle_waypoint_timeout.elapsed() or 0.0
            self._abort(
                "%s 导航超时 (%.1fs > %.1fs)"
                % (
                    waypoint,
                    waypoint_elapsed,
                    self._pass_obstacle_waypoint_timeout.timeout_sec,
                )
            )
            return
        retry_key = "pass_obstacle:%s" % waypoint
        if not self._navigation_retry_ready(retry_key):
            return
        if not self._nav.goal_sent and not self._nav.is_done():
            self.get_logger().info(
                "[越障 %d/%d] 导航到 %s"
                % (self._obstacle_route_index + 1, len(route), waypoint)
            )
            if self._nav.navigate_to_waypoint(waypoint):
                self._pass_obstacle_waypoint_timeout.start()
        if not self._nav.is_done():
            return
        if not self._nav.succeeded():
            self._pass_obstacle_waypoint_timeout.reset()
            self._retry_navigation_or_abort(retry_key, waypoint)
            return

        self._pass_obstacle_waypoint_timeout.reset()

        if waypoint == "obstacle_cross_target" and not self._obstacle_depth_transition_complete:
            self._disable_depth_after_obstacle()
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

    def _disable_depth_after_obstacle(self) -> None:
        """Disable depth immediately after the cone-avoidance area.

        This is a one-shot fire-and-forget close: TaskManager stops consuming
        depth status, no later milestone may re-enable depth, and it does not
        wait for the Docker controller acknowledgement or host odom recovery.
        """
        if self._depth_policy is not None:
            self._depth_policy.waypoint_succeeded("obstacle_cross_target")
        if self._depth_mode_client is not None:
            self._depth_mode_client.direct_disable()
        self.get_logger().info(
            "depth disabled after obstacle crossing; depth subscriptions closed"
        )

    def _tick_inspect_gauges(self, elapsed: float) -> None:
        """Navigate, verify stop, call WHZ asynchronously, and store one result."""
        if self._handle_timeout(elapsed):
            return

        workflow = self._inspection_workflow
        if workflow.stage == InspectionStage.ABORTED:
            self._abort(workflow.abort_reason)
            return

        if workflow.stage == InspectionStage.COMPLETE:
            assessments = tuple(
                ZoneAssessment(
                    letter=info.letter,
                    abnormal=bool(info.status and info.status != "normal"),
                    confidence=info.confidence,
                )
                for info in self._gauge_info.values()
            )
            self._abnormal_zones = freeze_two_zone_tasks(
                assessments,
                self._abnormal_zone_fallback_order,
            )
            self._task_queue_frozen = True
            detected_abnormal = [item for item in assessments if item.abnormal]
            detected_text = ", ".join(
                "%s(%.3f)" % (item.letter, item.confidence)
                for item in detected_abnormal
            ) or "none"
            self.get_logger().info(
                "第四次巡检完成，已冻结两轮任务: %s -> %s "
                "(detected_abnormal=%s, uncertain_inspections=%d)"
                % (
                    self._abnormal_zones[0],
                    self._abnormal_zones[1],
                    detected_text,
                    len(workflow.uncertain_attempts),
                )
            )
            self._abnormal_attempted = 0
            self._abnormal_handled = 0
            self._manipulation_outcomes = []
            self._used_pick_tag_ids = []
            if self._inspection_only or self._finish_after_inspection:
                self._enter_phase(Phase.FINISH)
            elif not self._enable_manipulation:
                self._abort("production manipulation is disabled")
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
            if workflow.inspection_retries < workflow.max_inspection_retries:
                workflow.inspection_failed("service_unavailable")
                self.get_logger().warn(
                    "WHZ service unavailable，重试 %d/%d"
                    % (
                        workflow.inspection_retries,
                        workflow.max_inspection_retries,
                    )
                )
            else:
                self._complete_uncertain_inspection("service_unavailable")
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
                self._complete_uncertain_inspection(
                    "service_timeout=%.1fs" % self._inspection_response_timeout_sec
                )
            return

        try:
            response = self._inspection_future.result()
        except Exception as exc:  # noqa: BLE001
            self._inspection_future = None
            if workflow.inspection_retries < workflow.max_inspection_retries:
                workflow.inspection_failed("service_future_error: %s" % exc)
                self.get_logger().warn(
                    "WHZ service future failed，重试 %d/%d: %s"
                    % (
                        workflow.inspection_retries,
                        workflow.max_inspection_retries,
                        exc,
                    )
                )
            else:
                self._complete_uncertain_inspection(
                    "service_future_error: %s" % exc
                )
            return

        self._inspection_future = None
        if response is None:
            if workflow.inspection_retries < workflow.max_inspection_retries:
                workflow.inspection_failed("empty_service_response")
                self.get_logger().warn(
                    "WHZ returned no response，重试 %d/%d"
                    % (
                        workflow.inspection_retries,
                        workflow.max_inspection_retries,
                    )
                )
            else:
                self._complete_uncertain_inspection("empty_service_response")
            return

        try:
            reading = InspectionReading.from_trigger(
                response.success,
                response.message,
                require_audio=self._require_inspection_audio,
            )
        except InspectionContractError as exc:
            if workflow.inspection_retries < workflow.max_inspection_retries:
                workflow.inspection_failed(str(exc))
                self.get_logger().warn(
                    "WHZ inspection rejected，重试 %d/%d: %s"
                    % (
                        workflow.inspection_retries,
                        workflow.max_inspection_retries,
                        exc,
                    )
                )
            else:
                self._complete_uncertain_inspection(str(exc))
            return

        if reading.area in workflow.readings:
            self._complete_uncertain_inspection(
                "duplicate_area=%s" % reading.area
            )
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
        info.confidence = float(reading.agree_frames) / float(reading.total_frames)

    def _complete_uncertain_inspection(self, reason: str) -> None:
        self._inspection_workflow.inspection_uncertain(reason)
        self._inspection_route_index += 1
        self._inspection_future = None
        self._inspection_request_started = 0.0
        self._inspection_service_wait_started = None
        self.get_logger().warn(
            "第%d次仪表感知结果 uncertain，继续下一观察位: %s"
            % (self._inspection_workflow.step_index, reason)
        )

    def _tick_find_red_bar(self, elapsed: float) -> None:
        """Navigate coarsely, then align one approved red-tag slot to I2."""
        del elapsed
        if self._abnormal_attempted >= len(self._abnormal_zones):
            self._enter_phase(Phase.FINISH)
            return
        current_zone = self._abnormal_zones[self._abnormal_attempted]

        if not self._pick_arrived:
            retry_key = "find_red_bar:grab_area_approach"
            if not self._navigation_retry_ready(retry_key):
                return
            if not self._nav.goal_sent and not self._nav.is_done():
                self._nav.navigate_to_waypoint("grab_area_approach")
            if not self._nav.is_done():
                return
            if not self._nav.succeeded():
                exhausted_reason = self._retry_navigation(retry_key, "抓取区")
                if exhausted_reason is not None:
                    self._current_grasp_outcome = (
                        "uncertain: skipped after grab navigation failure: "
                        + exhausted_reason
                    )
                    self._complete_place_attempt(
                        current_zone,
                        uncertain_reason=(
                            "place skipped because grab navigation failed: "
                            + exhausted_reason
                        ),
                    )
                return
            self._clear_navigation_retry(retry_key)
            self._nav.reset()
            self._pick_arrived = True
            if (
                self._depth_policy is not None
                and "grab_area_approach" not in self._depth_recorded_waypoints
            ):
                self._depth_policy.waypoint_succeeded("grab_area_approach")
                self._depth_recorded_waypoints.add("grab_area_approach")
            self._request_precision_release()

        if not self._enable_pick_i2_alignment:
            self.get_logger().warn(
                "I2精对齐已关闭，使用抓取区固定偏移继续比赛"
            )
            self._advance_to_next_phase()
            return

        if self._pick_executor is None:
            self._pick_executor = PickOneExecutor(
                _PickRuntimeAdapter(self),
                PickConfig(
                    red_tag_ids=self._pick_red_tag_ids,
                    excluded_tag_ids=tuple(self._used_pick_tag_ids),
                    i2_targets=self._pick_i2_targets,
                    stop_after_stage="i2",
                ),
            )
            self._pick_executor.start()
        result = self._pick_executor.tick()
        selected_tag_id = self._pick_executor.target_tag_id
        if (
            selected_tag_id is not None
            and selected_tag_id not in self._used_pick_tag_ids
        ):
            self._used_pick_tag_ids.append(selected_tag_id)
            self.get_logger().info(
                "第%d轮抓取锁定 Tag %d；后续轮次将排除该 Tag"
                % (self._abnormal_attempted + 1, selected_tag_id)
            )
        if result is None:
            return
        if not result.success or not result.alignment_success:
            self.get_logger().warn(
                "I2精对齐失败，降级到固定抓取预设: %s" % result.reason
            )
            self._request_precision_release()
            self._advance_to_next_phase()
            return
        self.get_logger().info("抓取位 I2 对齐完成，执行固定抓取预设")
        self._advance_to_next_phase()

    def _tick_grasp_bar(self, elapsed: float) -> None:
        """Run the fixed grasp preset; uncertain arm outcomes degrade and continue."""
        del elapsed
        if self._grasp_uncertain_reason:
            if not self._arm_motion_guard_elapsed():
                return
            reason = self._grasp_uncertain_reason
            self._grasp_uncertain_reason = ""
            self._grasp_future = None
            self._arm_motion_guard_until = 0.0
            self._current_grasp_outcome = "uncertain: " + reason
            self.get_logger().warn(
                "抓取结果 uncertain，保守等待已完成，继续比赛: %s" % reason
            )
            self._advance_to_next_phase()
            return
        if self._current_grasp_outcome == "sequence_completed_unverified_grasp":
            if not self._arm_motion_guard_elapsed():
                return
            self._arm_motion_guard_until = 0.0
            self.get_logger().info("抓取动作保护时长已满足，允许进入放置阶段")
            self._advance_to_next_phase()
            return
        if self._grasp_client is None or self._grasp_service_type is None:
            self.get_logger().warn("抓取服务客户端不可用，记录 uncertain 后继续比赛")
            self._current_grasp_outcome = "uncertain: service client unavailable"
            self._advance_to_next_phase()
            return
        if self._grasp_request_started == 0.0:
            self._grasp_request_started = time.monotonic()
        if self._grasp_future is None:
            if not self._grasp_client.service_is_ready():
                if time.monotonic() - self._grasp_request_started > self._arm_service_timeout_sec:
                    self.get_logger().warn(
                        "抓取服务未就绪，记录 uncertain 后继续比赛"
                    )
                    self._current_grasp_outcome = "uncertain: service not ready"
                    self._advance_to_next_phase()
                return
            request = self._grasp_service_type.Request()
            target = request.target_arm_base
            target.x, target.y, target.z = self._grasp_target_arm_base
            try:
                self._grasp_future = self._grasp_client.call_async(request)
            except Exception as exc:  # noqa: BLE001
                self._start_arm_motion_guard()
                self._grasp_uncertain_reason = "grasp dispatch failed: %s" % exc
                self.get_logger().warn(
                    "抓取请求派发异常，无法证明服务端未收到；等待动作保护时长: %s"
                    % exc
                )
                return
            self._grasp_request_started = time.monotonic()
            self._start_arm_motion_guard()
            return
        if not self._grasp_future.done():
            if time.monotonic() - self._grasp_request_started > self._arm_service_timeout_sec:
                self._grasp_uncertain_reason = "grasp service timed out"
                self.get_logger().warn(
                    "抓取服务超时；future cancel不能停止舵机，等待动作保护时长"
                )
            return
        try:
            response = self._grasp_future.result()
        except Exception as exc:  # noqa: BLE001
            self._grasp_uncertain_reason = "grasp service failed: %s" % exc
            self.get_logger().warn(
                "抓取响应异常，等待动作保护时长后继续: %s" % exc
            )
            return
        if response is None or not response.success:
            message = "empty response" if response is None else response.message
            self._grasp_uncertain_reason = "grasp rejected: %s" % message
            self.get_logger().warn(
                "抓取未确认，等待动作保护时长后继续: %s" % message
            )
            return
        self._grasp_future = None
        self._current_grasp_outcome = "sequence_completed_unverified_grasp"
        self.get_logger().info(
            "机械臂抓取动作序列完成（未验证物体抓持）；继续保持底盘静止: %s"
            % response.message
        )
        return

    def _tick_place_to_abnormal_zone(self, elapsed: float) -> None:
        """Navigate, align to the selected A-D face, then request arm place."""
        del elapsed

        if self._abnormal_attempted >= len(self._abnormal_zones):
            self.get_logger().info("所有异常区域均已尝试处理")
            self._advance_to_next_phase()
            return

        current_zone = self._abnormal_zones[self._abnormal_attempted]
        placement_waypoint = f"placement_{current_zone}_approach"

        if not self._placement_arrived:
            retry_key = "placement:%s" % current_zone
            if not self._navigation_retry_ready(retry_key):
                return
            if not self._nav.goal_sent and not self._nav.is_done():
                self._nav.navigate_to_waypoint(placement_waypoint)
            if not self._nav.is_done():
                return
            if not self._nav.succeeded():
                exhausted_reason = self._retry_navigation(
                    retry_key,
                    "%s放置区" % current_zone,
                )
                if exhausted_reason is not None:
                    self._complete_place_attempt(
                        current_zone,
                        uncertain_reason=(
                            "place skipped after navigation failure: "
                            + exhausted_reason
                        ),
                    )
                return
            self._clear_navigation_retry(retry_key)
            self._nav.reset()
            self._placement_arrived = True
            self._request_precision_release()

        if not self._place_alignment_complete:
            self.get_logger().info(
                "placement %s: using fixed J0 preset (J1 visual alignment disabled)"
                % current_zone
            )
            self._place_alignment_complete = True
            self._place_request_started = time.monotonic()
            self._request_precision_release()

        if self._place_uncertain_reason:
            if not self._arm_motion_guard_elapsed():
                return
            reason = self._place_uncertain_reason
            self._place_uncertain_reason = ""
            self._place_future = None
            self._arm_motion_guard_until = 0.0
            self._complete_place_attempt(current_zone, uncertain_reason=reason)
            return
        if self._place_sequence_completed_pending:
            if not self._arm_motion_guard_elapsed():
                return
            self._place_sequence_completed_pending = False
            self.get_logger().info(
                "%s区放置动作保护时长已满足，允许继续任务" % current_zone
            )
            self._complete_place_attempt(current_zone)
            return

        if self._place_client is None:
            self._complete_place_attempt(
                current_zone,
                uncertain_reason="place service client is unavailable",
            )
            return
        if self._place_future is None:
            if not self._place_client.service_is_ready():
                if time.monotonic() - self._place_request_started > self._arm_service_timeout_sec:
                    self._complete_place_attempt(
                        current_zone,
                        uncertain_reason="place service did not become ready",
                    )
                return
            try:
                self._place_future = self._place_client.call_async(Trigger.Request())
            except Exception as exc:  # noqa: BLE001
                self._start_arm_motion_guard()
                self._place_uncertain_reason = "place dispatch failed: %s" % exc
                self.get_logger().warn(
                    "放置请求派发异常，无法证明服务端未收到；等待动作保护时长: %s"
                    % exc
                )
                return
            self._place_request_started = time.monotonic()
            self._start_arm_motion_guard()
            return
        if not self._place_future.done():
            if time.monotonic() - self._place_request_started > self._arm_service_timeout_sec:
                self._place_uncertain_reason = "place service timed out"
                self.get_logger().warn(
                    "放置服务超时；future cancel不能停止舵机，等待动作保护时长"
                )
            return
        try:
            response = self._place_future.result()
        except Exception as exc:  # noqa: BLE001
            self._place_uncertain_reason = "place service failed: %s" % exc
            self.get_logger().warn(
                "放置响应异常，等待动作保护时长后继续: %s" % exc
            )
            return
        if response is None or not response.success:
            message = "empty response" if response is None else response.message
            self._place_uncertain_reason = "place rejected: %s" % message
            self.get_logger().warn(
                "放置未确认，等待动作保护时长后继续: %s" % message
            )
            return
        self._place_future = None
        self._place_sequence_completed_pending = True
        self.get_logger().info(
            "%s区放置动作序列完成；继续保持底盘静止" % current_zone
        )
        return

    def _complete_place_attempt(
        self,
        current_zone: str,
        uncertain_reason: str = "",
    ) -> None:
        self._abnormal_attempted += 1
        place_outcome = "uncertain: " + uncertain_reason if uncertain_reason else "sequence_completed"
        if not uncertain_reason:
            self._abnormal_handled += 1
        self._manipulation_outcomes.append({
            "zone": current_zone,
            "grasp": self._current_grasp_outcome,
            "place": place_outcome,
        })
        self._arm_motion_guard_until = 0.0
        remaining = len(self._abnormal_zones) - self._abnormal_attempted
        if uncertain_reason:
            self.get_logger().warn(
                f"{current_zone}区放置结果 uncertain，继续下一任务 "
                f"({self._abnormal_attempted}/{len(self._abnormal_zones)} attempts): "
                f"{uncertain_reason}"
            )
        else:
            self.get_logger().info(
                f"{current_zone}区放置动作序列完成 "
                f"({self._abnormal_handled} confirmed / "
                f"{self._abnormal_attempted} attempted)"
                + (f"，剩余 {remaining} 趟" if remaining > 0 else "，全部完成！")
            )
        if remaining > 0:
            self._enter_phase(Phase.FIND_RED_BAR)
        else:
            self._enter_phase(Phase.FINISH)

    # ═══════════════════════════════════════════════════════════
    #  阶段推进
    # ═══════════════════════════════════════════════════════════

    def _abort(self, reason: str) -> None:
        if self._phase == Phase.ABORT:
            return
        self._abort_reason = str(reason)
        self.get_logger().error("任务中止: %s" % self._abort_reason)
        self._enter_phase(Phase.ABORT)

    def _runtime_base_safety_ok(self) -> bool:
        if self._phase in (Phase.START, Phase.FINISH, Phase.ABORT):
            return True
        if (
            self._last_odom_time <= 0.0
            or time.time() - self._last_odom_time > self._odom_timeout_sec
        ):
            self._abort("runtime odometry became unavailable or stale")
            return False
        if self._slam_status_time > 0.0 and not self._slam_tracking_ok:
            self._abort("runtime visual localization reported tracking loss")
            return False
        return True

    def _retry_navigation(self, key: str, label: str) -> Optional[str]:
        reason = self._nav.failure_reason or self._nav.result_name
        retries = self._nav_retry_counts.get(key, 0)
        self._nav.reset()
        if retries >= self._max_nav_retries:
            self._clear_navigation_retry(key)
            exhausted_reason = "%s导航在%d次尝试后失败: %s" % (
                label,
                self._max_nav_retries + 1,
                reason,
            )
            self.get_logger().warn(exhausted_reason)
            return exhausted_reason
        retries += 1
        self._nav_retry_counts[key] = retries
        self._nav_retry_not_before[key] = time.monotonic() + self._retry_delay_sec
        self.get_logger().warn(
            "%s导航失败，重试 %d/%d: %s"
            % (label, retries, self._max_nav_retries, reason)
        )
        return None

    def _retry_navigation_or_abort(self, key: str, label: str) -> bool:
        exhausted_reason = self._retry_navigation(key, label)
        if exhausted_reason is None:
            return True
        self._abort(exhausted_reason)
        return False

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

    def _mission_start_is_armed(self) -> bool:
        return bool(self.get_parameter("mission_start_armed").value)

    def _set_mission_start_wait_reason(self, reason: str) -> None:
        if reason == self._mission_start_wait_reason:
            return
        if reason:
            self.get_logger().info("START readiness: %s" % reason)
        else:
            self.get_logger().info(
                "START readiness confirmed: Nav2 lifecycle, action, and cone costmaps ready"
            )
        self._mission_start_wait_reason = reason

    def _mission_start_prerequisites_ready(self) -> bool:
        nav_ready, nav_reason = self._nav.startup_readiness()
        self._mission_start_nav_ready = nav_ready
        self._mission_start_cone_layers_ready = bool(
            not self._require_cone_layer_startup_ready
            or (
                self._depth_mode_client is not None
                and self._depth_mode_client.cone_layer_baseline_ready
            )
        )
        if not self._mission_start_nav_ready:
            reason = nav_reason
        elif not self._mission_start_cone_layers_ready:
            reason = self._depth_mode_client.cone_layer_baseline_reason
        else:
            reason = ""
        self._set_mission_start_wait_reason(reason)
        return not reason

    def _ensure_depth_mode(
        self,
        mode,
        milestone: str,
    ) -> bool:
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
            message = "depth pipeline readiness timed out at %s: %s" % (
                self._depth_pending_milestone,
                reason,
            )
            self._abort(message)
            return False
        if readiness.mode == DepthMode.FAULT:
            message = "depth transition failed at %s: %s" % (
                self._depth_pending_milestone,
                readiness.reason,
            )
            self._abort(message)
            return False
        self._depth_mode_client.republish_active_request(mode)
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
        self._pass_obstacle_waypoint_timeout.reset()
        self._cancel_manipulation(cancel_services=phase in (Phase.FINISH, Phase.ABORT))
        if phase == Phase.ABORT:
            if self._nav.goal_sent:
                self._nav.cancel()
            self._inspection_future = None
        if phase == Phase.FIND_RED_BAR:
            self._pick_arrived = False
            self._pick_executor = None
            self._grasp_future = None
            self._grasp_request_started = 0.0
            self._grasp_uncertain_reason = ""
            self._current_grasp_outcome = "not_attempted"
            self._arm_motion_guard_until = 0.0
        if phase == Phase.GRASP_BAR:
            self._grasp_future = None
            self._grasp_request_started = 0.0
            self._grasp_uncertain_reason = ""
            self._arm_motion_guard_until = 0.0
        if phase == Phase.PLACE_TO_ABNORMAL_ZONE:
            self._placement_arrival_time = None
            self._placement_arrived = False
            self._place_alignment_complete = False
            self._place_future = None
            self._place_request_started = 0.0
            self._place_uncertain_reason = ""
            self._place_sequence_completed_pending = False
            self._arm_motion_guard_until = 0.0
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

    def _on_apriltag_detections(self, msg: String) -> None:
        try:
            self._latest_apriltag_frame = parse_fiducial_frame(json.loads(msg.data))
            self._latest_apriltag_received_monotonic = time.monotonic()
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self.get_logger().warn(
                "Dropped invalid AprilTag frame: %s" % exc,
                throttle_duration_sec=2.0,
            )

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
        if self._odom_first_seen_time <= 0.0:
            self._odom_first_seen_time = time.time()
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
                "confidence": round(info.confidence, 4),
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
            "task_queue_frozen": self._task_queue_frozen,
            "abnormal_attempted": self._abnormal_attempted,
            "abnormal_handled": self._abnormal_handled,
            "manipulation_outcomes": self._manipulation_outcomes,
            "used_pick_tag_ids": self._used_pick_tag_ids,
            "uncertain_inspections": list(
                self._inspection_workflow.uncertain_attempts
            ),
            "abort_reason": self._abort_reason,
            "waypoint_source": self._waypoint_source,
            "waypoint_route": self._waypoint_route,
            "mission_start_readiness": {
                "armed": self._mission_start_is_armed(),
                "nav2_lifecycle_action_ready": self._mission_start_nav_ready,
                "cone_layer_baseline_required": (
                    self._require_cone_layer_startup_ready
                ),
                "cone_layer_baseline_ready": (
                    self._mission_start_cone_layers_ready
                ),
                "reason": self._mission_start_wait_reason,
            },
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
        }

        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self._status_pub.publish(msg)

    # ═══════════════════════════════════════════════════════════
    #  清理
    # ═══════════════════════════════════════════════════════════

    def destroy_node(self) -> bool:
        self.get_logger().info("Task Manager 关闭中...")
        self._cancel_manipulation(cancel_services=True)
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
