#!/usr/bin/env python3
"""ROS 2 state machine for the competition red-block pick-and-place task.

The robot is manually placed at calibrated I0 before ``/task/start_grasp_place``
is called.  From that point this node completes two jobs automatically:

    observe -> lock -> I1 alignment -> grasp -> place -> return to I0 -> repeat

Obstacle traversal and gauge inspection intentionally stay outside this node.
Their eventual integration point is the explicit abnormal-zone job queue.
"""

from __future__ import annotations

import json
import math
import time
from enum import Enum, auto
from pathlib import Path
from statistics import median
from typing import List, Optional, Tuple

import rclpy
from geometry_msgs.msg import Point, Twist
from rclpy.node import Node
from rclpy.time import Time
from std_msgs.msg import String
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformException, TransformListener
from rclpy.duration import Duration

from arm_new_interfaces.srv import ExecuteGraspFixed
from navi.navigation_client import NavigationClient
from nodes.decision.manipulation_core import (
    CalibrationError,
    HostDetectionFrame,
    JobQueue,
    LockedTarget,
    ManipulationSites,
    StableRedObserver,
    load_manipulation_sites,
    median_point,
    parse_host_detection_packet,
    proportional_axis_pulse,
)


Point3 = Tuple[float, float, float]


class ManipulationState(Enum):
    """Fine-grained states are published for field diagnosis and dry runs."""

    IDLE = auto()                 # 等待人工确认：狗已手动到达 I0。
    PREFLIGHT_ARM = auto()        # 调用机械臂 preflight，拒绝带故障起步。
    WAIT_PREFLIGHT = auto()       # 等待 preflight 异步服务返回。
    WAIT_I0_SETTLE = auto()       # 机器人停车，等待机身和深度图稳定。
    OBSERVE_BLOCKS = auto()       # 只收新 sequence，建立多帧稳定观测。
    ALIGN_I1_Y = auto()           # 先横向微调，避免同时控制两个轴。
    ALIGN_I1_X = auto()           # 横向满足后才进行前后微调。
    CONFIRM_I1 = auto()           # 不运动，连续确认 I1 的最终误差。
    PULSE = auto()                # 单轴短脉冲；结束后一定发送零速度。
    SETTLE_AFTER_PULSE = auto()   # 脉冲后停车观察，不能沿用旧检测驱动。
    CALL_GRASP = auto()           # 仅发送一次异步抓取请求。
    WAIT_GRASP = auto()           # 等待机械臂抬起到运输位姿。
    HOLD_LIFTED = auto()          # 保持夹紧和抬起，不做 D455 抓取验证。
    NAV_PLACE = auto()            # Nav2 前往当前异常区固定 map 位姿。
    SETTLE_PLACE = auto()         # Nav2 到位后等待底盘停止。
    ALIGN_PLACE_Y = auto()        # 依据 map->base_link 修正横向放置误差。
    ALIGN_PLACE_X = auto()        # 依据 map->base_link 修正前后放置误差。
    ALIGN_PLACE_YAW = auto()      # 最后修正放置朝向。
    CALL_PLACE = auto()           # 仅发送一次固定放置请求。
    WAIT_PLACE = auto()           # 等待放置动作真正结束。
    COMPLETE_JOB = auto()         # 仅在 place success 后递增任务索引。
    NAV_I0 = auto()               # 第一趟放置后自动回 I0 处理第二根红条。
    FINISH = auto()               # 两次明确成功放置后的终态。
    ABORT = auto()                # 停狗、取消导航，保持机械臂当前持物状态。


class GraspPlaceManager(Node):
    """Coordinate YOLO, Nav2 and arm services for exactly two abnormal zones."""

    def __init__(self) -> None:
        super().__init__("grasp_place_manager_node")
        self._declare_parameters()

        self._yolo_topic = str(self.get_parameter("yolo_topic").value)
        self._cmd_vel_topic = str(self.get_parameter("cmd_vel_topic").value)
        self._state_pub = self.create_publisher(String, "/task/manipulation_state", 10)
        self._status_pub = self.create_publisher(String, "/task/manipulation_status", 10)
        self._cmd_vel_pub = self.create_publisher(Twist, self._cmd_vel_topic, 10)
        self._yolo_sub = self.create_subscription(String, self._yolo_topic, self._on_yolo, 10)
        self._start_srv = self.create_service(Trigger, "/task/start_grasp_place", self._on_start)
        self._abort_srv = self.create_service(Trigger, "/task/abort_grasp_place", self._on_abort)

        self._nav = NavigationClient(self)
        self._grasp_client = self.create_client(ExecuteGraspFixed, "/arm/execute_grasp_fixed")
        self._place_client = self.create_client(Trigger, "/arm/execute_place_fixed")
        self._preflight_client = self.create_client(Trigger, "/arm/preflight")
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)

        self._state = ManipulationState.IDLE
        self._state_entered_s = time.monotonic()
        self._timer = self.create_timer(1.0 / float(self.get_parameter("tick_rate").value), self._tick)
        self._latest_frame: Optional[HostDetectionFrame] = None
        self._last_consumed_sequence = -1
        self._observer = StableRedObserver(
            int(self.get_parameter("observe_window_size").value),
            int(self.get_parameter("required_stable_frames").value),
            float(self.get_parameter("target_match_gate_m").value),
        )
        self._locked_target: Optional[LockedTarget] = None
        self._confirm_points: List[Point3] = []
        self._final_target_base: Optional[Point3] = None
        self._jobs: Optional[JobQueue] = None
        self._sites: Optional[ManipulationSites] = None
        self._future = None
        self._pulse_end_s = 0.0
        self._pulse_resume_state: Optional[ManipulationState] = None
        self._nav_retries = 0
        self._last_error = ""

        self._set_state(ManipulationState.IDLE, "等待人工将机器狗遥控至 I0")
        self.get_logger().info("grasp_place_manager ready; call /task/start_grasp_place at I0")

    def _declare_parameters(self) -> None:
        # 手动测试输入：正式总状态机未来会用巡检结果替换该数组。
        self.declare_parameter("manual_abnormal_zones", [])
        self.declare_parameter("manual_abnormal_zones_csv", "")
        self.declare_parameter("calibration_file", "configs/calibration/competition_sites.yaml")
        self.declare_parameter("required_calibration_status", "calibrated")
        self.declare_parameter("tick_rate", 10.0)
        self.declare_parameter("yolo_topic", "/yolo/detections")
        self.declare_parameter("cmd_vel_topic", "/cmd_vel")
        self.declare_parameter("min_yolo_confidence", 0.5)
        self.declare_parameter("min_depth_valid_ratio", 0.60)
        self.declare_parameter("yolo_stale_timeout_s", 0.5)
        self.declare_parameter("observe_timeout_s", 12.0)
        self.declare_parameter("observe_window_size", 8)
        self.declare_parameter("required_stable_frames", 5)
        self.declare_parameter("target_match_gate_m", 0.10)
        self.declare_parameter("target_lost_limit", 3)
        self.declare_parameter("expected_green_count", 2)
        self.declare_parameter("i0_settle_s", 0.8)
        self.declare_parameter("confirm_frames", 5)

        # I1 的 arm_base_link 参考位置会在运行时经静态 TF 转为 base_link。
        self.declare_parameter("grasp_reference_arm", [0.45, 0.0])
        self.declare_parameter("grasp_reference_z_for_selection_m", 0.06)
        self.declare_parameter("align_kx", 0.6)
        self.declare_parameter("align_ky", 0.6)
        self.declare_parameter("align_max_speed_mps", 0.06)
        self.declare_parameter("align_min_speed_mps", 0.025)
        self.declare_parameter("align_xy_tolerance_m", 0.02)
        self.declare_parameter("align_pulse_min_s", 0.15)
        self.declare_parameter("align_pulse_max_s", 0.40)
        self.declare_parameter("align_settle_s", 0.70)
        self.declare_parameter("align_timeout_s", 30.0)
        # 现场确认 Lite3 轴方向后，如有必要仅修改符号参数。
        self.declare_parameter("align_x_sign", 1.0)
        self.declare_parameter("align_y_sign", 1.0)

        self.declare_parameter("lifted_hold_s", 3.2)
        self.declare_parameter("service_wait_timeout_s", 5.0)
        self.declare_parameter("service_result_timeout_s", 35.0)
        self.declare_parameter("max_nav_retries", 1)
        self.declare_parameter("place_nav_settle_s", 1.0)
        self.declare_parameter("place_xy_tolerance_m", 0.04)
        self.declare_parameter("place_yaw_tolerance_rad", 0.0873)
        self.declare_parameter("place_align_kxy", 0.5)
        self.declare_parameter("place_align_kyaw", 0.8)
        self.declare_parameter("place_align_max_speed_mps", 0.05)
        self.declare_parameter("place_align_min_speed_mps", 0.025)
        self.declare_parameter("place_align_max_yaw_rps", 0.20)
        self.declare_parameter("place_pulse_min_s", 0.15)
        self.declare_parameter("place_pulse_max_s", 0.40)
        self.declare_parameter("place_settle_s", 0.70)
        self.declare_parameter("tf_timeout_s", 0.2)

    # ------------------------------------------------------------------
    # ROS callbacks and top-level safety handling
    # ------------------------------------------------------------------

    def _on_yolo(self, msg: String) -> None:
        """Accept only the Host bridge contract; no image processing happens here."""

        try:
            packet = json.loads(msg.data)
            self._latest_frame = parse_host_detection_packet(
                packet,
                time.monotonic(),
                float(self.get_parameter("min_yolo_confidence").value),
                float(self.get_parameter("min_depth_valid_ratio").value),
            )
        except (json.JSONDecodeError, ValueError) as exc:
            self.get_logger().warn("ignored invalid /yolo/detections: {}".format(exc), throttle_duration_sec=2.0)

    def _on_start(self, _request: Trigger.Request, response: Trigger.Response) -> Trigger.Response:
        if self._state not in {ManipulationState.IDLE, ManipulationState.FINISH, ManipulationState.ABORT}:
            response.success = False
            response.message = "task is already running in {}".format(self._state.name)
            return response
        try:
            zones_csv = str(self.get_parameter("manual_abnormal_zones_csv").value).strip()
            zones = zones_csv.split(",") if zones_csv else list(self.get_parameter("manual_abnormal_zones").value)
            self._jobs = JobQueue.from_zones(zones)
            self._sites = load_manipulation_sites(
                self._resolve_calibration_path(),
                self._jobs.zones,
                str(self.get_parameter("required_calibration_status").value),
            )
        except (CalibrationError, ValueError) as exc:
            self._abort("启动被拒绝：{}".format(exc))
            response.success = False
            response.message = self._last_error
            return response

        self._last_consumed_sequence = -1
        self._observer.clear()
        self._locked_target = None
        self._confirm_points.clear()
        self._final_target_base = None
        self._nav_retries = 0
        self._set_state(ManipulationState.PREFLIGHT_ARM, "人工确认 I0；开始机械臂 preflight")
        response.success = True
        response.message = "started at I0 with zones {}".format(list(self._jobs.zones))
        return response

    def _on_abort(self, _request: Trigger.Request, response: Trigger.Response) -> Trigger.Response:
        self._abort("人工请求中止")
        response.success = True
        response.message = "base stopped and navigation cancellation requested; arm is left powered"
        return response

    def _tick(self) -> None:
        """Drive at most one state transition per timer tick; never block the executor."""

        if self._state in {ManipulationState.IDLE, ManipulationState.FINISH, ManipulationState.ABORT}:
            return
        if self._state in {
            ManipulationState.OBSERVE_BLOCKS,
            ManipulationState.ALIGN_I1_Y,
            ManipulationState.ALIGN_I1_X,
            ManipulationState.CONFIRM_I1,
            ManipulationState.PULSE,
            ManipulationState.SETTLE_AFTER_PULSE,
        } and self._latest_frame_is_stale():
            # 感知断流时绝不持续沿用旧非零速度；观察状态会在自身超时后中止。
            self._publish_stop()
        if self._state_timed_out():
            return

        if self._state == ManipulationState.PREFLIGHT_ARM:
            self._tick_preflight_arm()
        elif self._state == ManipulationState.WAIT_PREFLIGHT:
            self._tick_wait_preflight()
        elif self._state == ManipulationState.WAIT_I0_SETTLE:
            self._tick_wait_i0_settle()
        elif self._state == ManipulationState.OBSERVE_BLOCKS:
            self._tick_observe_blocks()
        elif self._state == ManipulationState.ALIGN_I1_Y:
            self._tick_align_i1(axis="y")
        elif self._state == ManipulationState.ALIGN_I1_X:
            self._tick_align_i1(axis="x")
        elif self._state == ManipulationState.CONFIRM_I1:
            self._tick_confirm_i1()
        elif self._state == ManipulationState.PULSE:
            self._tick_pulse()
        elif self._state == ManipulationState.SETTLE_AFTER_PULSE:
            self._tick_settle_after_pulse()
        elif self._state == ManipulationState.CALL_GRASP:
            self._tick_call_grasp()
        elif self._state == ManipulationState.WAIT_GRASP:
            self._tick_wait_grasp()
        elif self._state == ManipulationState.HOLD_LIFTED:
            self._tick_hold_lifted()
        elif self._state == ManipulationState.NAV_PLACE:
            self._tick_nav_place()
        elif self._state == ManipulationState.SETTLE_PLACE:
            self._tick_settle_place()
        elif self._state == ManipulationState.ALIGN_PLACE_Y:
            self._tick_align_place("y")
        elif self._state == ManipulationState.ALIGN_PLACE_X:
            self._tick_align_place("x")
        elif self._state == ManipulationState.ALIGN_PLACE_YAW:
            self._tick_align_place("yaw")
        elif self._state == ManipulationState.CALL_PLACE:
            self._tick_call_place()
        elif self._state == ManipulationState.WAIT_PLACE:
            self._tick_wait_place()
        elif self._state == ManipulationState.COMPLETE_JOB:
            self._tick_complete_job()
        elif self._state == ManipulationState.NAV_I0:
            self._tick_nav_i0()

    # ------------------------------------------------------------------
    # Preflight, stable observation, target lock and I0 -> I1 alignment
    # ------------------------------------------------------------------

    def _tick_preflight_arm(self) -> None:
        if not self._preflight_client.wait_for_service(timeout_sec=0.0):
            if self._elapsed() > float(self.get_parameter("service_wait_timeout_s").value):
                self._abort("/arm/preflight 服务不可用")
            return
        self._future = self._preflight_client.call_async(Trigger.Request())
        self._set_state(ManipulationState.WAIT_PREFLIGHT, "等待机械臂 preflight 结果")

    def _tick_wait_preflight(self) -> None:
        if self._future is None or not self._future.done():
            return
        try:
            response = self._future.result()
        except Exception as exc:
            self._abort("机械臂 preflight 调用异常：{}".format(exc))
            return
        if not response.success:
            self._abort("机械臂 preflight 失败：{}".format(response.message))
            return
        self._set_state(ManipulationState.WAIT_I0_SETTLE, "preflight 通过，I0 停车观察")

    def _tick_wait_i0_settle(self) -> None:
        self._publish_stop()
        if self._elapsed() < float(self.get_parameter("i0_settle_s").value):
            return
        self._observer.clear()
        self._locked_target = None
        self._confirm_points.clear()
        self._set_state(ManipulationState.OBSERVE_BLOCKS, "开始收集 I0 处的新 YOLO 序列")

    def _tick_observe_blocks(self) -> None:
        frame = self._consume_new_frame()
        if frame is None:
            return
        assert self._jobs is not None
        self._observer.add(frame)
        # 观察阶段尚未选中单个目标，使用经标定的典型平台高度做排序参考。
        try:
            reference = self._grasp_reference_base_xy_for_arm_z(
                float(self.get_parameter("grasp_reference_z_for_selection_m").value)
            )
        except TransformException as exc:
            self._abort("I0 观察缺少 base_link->arm_base_link：{}".format(exc))
            return
        expected_red = len(self._jobs.zones) - self._jobs.index
        target = self._observer.select_target(
            expected_red_count=expected_red,
            expected_green_count=int(self.get_parameter("expected_green_count").value),
            reference_base_xy=reference,
        )
        if target is None:
            return
        self._locked_target = LockedTarget(target, last_sequence=frame.sequence)
        self.get_logger().info(
            "稳定观测完成：锁定红块 base_link=(%.3f, %.3f, %.3f)" % target
        )
        self._set_state(ManipulationState.ALIGN_I1_Y, "先执行 I1 横向增量 P 对齐")

    def _tick_align_i1(self, axis: str) -> None:
        point = self._matched_target_from_new_frame()
        if point is None:
            return
        try:
            reference = self._grasp_reference_base_xy_for_target(point)
        except TransformException as exc:
            self._abort("I1 对齐缺少 base_link->arm_base_link：{}".format(exc))
            return
        error = point[1] - reference[1] if axis == "y" else point[0] - reference[0]
        tolerance = float(self.get_parameter("align_xy_tolerance_m").value)
        if abs(error) <= tolerance:
            next_state = ManipulationState.ALIGN_I1_X if axis == "y" else ManipulationState.CONFIRM_I1
            self._set_state(next_state, "I1 {} 轴进入容差".format(axis))
            return
        gain = float(self.get_parameter("align_ky" if axis == "y" else "align_kx").value)
        sign = float(self.get_parameter("align_y_sign" if axis == "y" else "align_x_sign").value)
        pulse = proportional_axis_pulse(
            error,
            gain,
            float(self.get_parameter("align_max_speed_mps").value),
            float(self.get_parameter("align_min_speed_mps").value),
            float(self.get_parameter("align_pulse_min_s").value),
            float(self.get_parameter("align_pulse_max_s").value),
            sign,
        )
        self._start_pulse(axis, pulse.speed_mps, pulse.duration_s, self._state)

    def _tick_confirm_i1(self) -> None:
        point = self._matched_target_from_new_frame()
        if point is None:
            return
        try:
            ref_x, ref_y = self._grasp_reference_base_xy_for_target(point)
        except TransformException as exc:
            self._abort("I1 最终确认缺少 base_link->arm_base_link：{}".format(exc))
            return
        tolerance = float(self.get_parameter("align_xy_tolerance_m").value)
        err_x, err_y = point[0] - ref_x, point[1] - ref_y
        if abs(err_y) > tolerance:
            self._confirm_points.clear()
            self._set_state(ManipulationState.ALIGN_I1_Y, "最终确认发现横向超差")
            return
        if abs(err_x) > tolerance:
            self._confirm_points.clear()
            self._set_state(ManipulationState.ALIGN_I1_X, "最终确认发现前后超差")
            return
        self._confirm_points.append(point)
        if len(self._confirm_points) < int(self.get_parameter("confirm_frames").value):
            return
        self._final_target_base = median_point(self._confirm_points)
        self._publish_stop()
        self._set_state(ManipulationState.CALL_GRASP, "I1 连续确认通过，发送抓取请求")

    # ------------------------------------------------------------------
    # Asynchronous grasp and lifted transport
    # ------------------------------------------------------------------

    def _tick_call_grasp(self) -> None:
        if not self._grasp_client.wait_for_service(timeout_sec=0.0):
            if self._elapsed() > float(self.get_parameter("service_wait_timeout_s").value):
                self._abort("/arm/execute_grasp_fixed 服务不可用")
            return
        if self._final_target_base is None:
            self._abort("内部错误：缺少最终抓取目标")
            return
        try:
            target_arm = self._base_to_arm(self._final_target_base)
            ref_arm = self.get_parameter("grasp_reference_arm").value
            request = ExecuteGraspFixed.Request()
            # x/y 是经过 I1 闭环后的固定参考；只有 z 使用最终多帧观测。
            request.target_arm_base = Point(x=float(ref_arm[0]), y=float(ref_arm[1]), z=target_arm[2])
        except Exception as exc:
            self._abort("无法构造抓取目标：{}".format(exc))
            return
        self._future = self._grasp_client.call_async(request)
        self._set_state(ManipulationState.WAIT_GRASP, "机械臂执行抓取、夹紧并抬起")

    def _tick_wait_grasp(self) -> None:
        if self._future is None or not self._future.done():
            return
        try:
            response = self._future.result()
        except Exception as exc:
            self._abort("抓取服务调用异常：{}".format(exc))
            return
        if not response.success:
            self._abort("抓取服务失败：{}".format(response.message))
            return
        self._set_state(ManipulationState.HOLD_LIFTED, "抓取服务成功；保持抬起后的运输位姿")

    def _tick_hold_lifted(self) -> None:
        # 设计约定：不回 Home，不掉电，不进行 D455 抓取后视觉验证。
        if self._elapsed() >= float(self.get_parameter("lifted_hold_s").value):
            self._nav_retries = 0
            self._set_state(ManipulationState.NAV_PLACE, "开始导航至当前异常区")

    # ------------------------------------------------------------------
    # Fixed placement navigation and final map-frame correction
    # ------------------------------------------------------------------

    def _tick_nav_place(self) -> None:
        assert self._jobs is not None and self._sites is not None
        if not self._nav.goal_sent and not self._nav.is_done():
            x, y, yaw = self._sites.placements[self._jobs.current_zone]
            qz, qw = math.sin(yaw / 2.0), math.cos(yaw / 2.0)
            self._nav.navigate_to_pose(x, y, qz=qz, qw=qw, waypoint_label="placement_{}".format(self._jobs.current_zone))
            return
        if not self._nav.is_done():
            return
        if self._nav.succeeded():
            self._nav.reset()
            self._set_state(ManipulationState.SETTLE_PLACE, "Nav2 到放置位，等待底盘停止")
            return
        self._retry_navigation_or_abort("放置区导航失败")

    def _tick_settle_place(self) -> None:
        self._publish_stop()
        if self._elapsed() >= float(self.get_parameter("place_nav_settle_s").value):
            self._set_state(ManipulationState.ALIGN_PLACE_Y, "按 map->base_link 修正放置横向误差")

    def _tick_align_place(self, axis: str) -> None:
        try:
            error_x, error_y, error_yaw = self._placement_error_in_base()
        except TransformException as exc:
            self._abort("放置最终对齐缺少 map->base_link：{}".format(exc))
            return

        if axis == "y":
            error, tolerance, next_state = error_y, float(self.get_parameter("place_xy_tolerance_m").value), ManipulationState.ALIGN_PLACE_X
            gain = float(self.get_parameter("place_align_kxy").value)
            max_speed = float(self.get_parameter("place_align_max_speed_mps").value)
            min_speed = float(self.get_parameter("place_align_min_speed_mps").value)
        elif axis == "x":
            error, tolerance, next_state = error_x, float(self.get_parameter("place_xy_tolerance_m").value), ManipulationState.ALIGN_PLACE_YAW
            gain = float(self.get_parameter("place_align_kxy").value)
            max_speed = float(self.get_parameter("place_align_max_speed_mps").value)
            min_speed = float(self.get_parameter("place_align_min_speed_mps").value)
        else:
            error, tolerance, next_state = error_yaw, float(self.get_parameter("place_yaw_tolerance_rad").value), ManipulationState.CALL_PLACE
            gain = float(self.get_parameter("place_align_kyaw").value)
            max_speed = float(self.get_parameter("place_align_max_yaw_rps").value)
            min_speed = min(max_speed, float(self.get_parameter("place_align_min_speed_mps").value))

        if abs(error) <= tolerance:
            self._set_state(next_state, "放置 {} 轴进入容差".format(axis))
            return
        pulse = proportional_axis_pulse(
            error, gain, max_speed, min_speed,
            float(self.get_parameter("place_pulse_min_s").value),
            float(self.get_parameter("place_pulse_max_s").value),
        )
        self._start_pulse(axis, pulse.speed_mps, pulse.duration_s, self._state)

    def _tick_call_place(self) -> None:
        if not self._place_client.wait_for_service(timeout_sec=0.0):
            if self._elapsed() > float(self.get_parameter("service_wait_timeout_s").value):
                self._abort("/arm/execute_place_fixed 服务不可用")
            return
        self._future = self._place_client.call_async(Trigger.Request())
        self._set_state(ManipulationState.WAIT_PLACE, "机械臂执行固定放置动作")

    def _tick_wait_place(self) -> None:
        if self._future is None or not self._future.done():
            return
        try:
            response = self._future.result()
        except Exception as exc:
            self._abort("放置服务调用异常：{}".format(exc))
            return
        if not response.success:
            # 此处分支故意不递增 job_index，防止把未放置物块算作完成。
            self._abort("放置服务失败：{}".format(response.message))
            return
        self._set_state(ManipulationState.COMPLETE_JOB, "放置服务明确成功")

    def _tick_complete_job(self) -> None:
        assert self._jobs is not None
        if not self._jobs.complete_current(place_success=True):
            self._abort("内部错误：无法完成当前任务")
            return
        if self._jobs.complete:
            self._set_state(ManipulationState.FINISH, "两根红条均已抓取并放置成功")
            return
        self._observer.clear()
        self._locked_target = None
        self._confirm_points.clear()
        self._final_target_base = None
        self._nav_retries = 0
        self._set_state(ManipulationState.NAV_I0, "第一趟完成，自动返回 I0 抓取第二根红条")

    def _tick_nav_i0(self) -> None:
        assert self._sites is not None
        if not self._nav.goal_sent and not self._nav.is_done():
            x, y, yaw = self._sites.grasp_i0
            self._nav.navigate_to_pose(
                x, y, qz=math.sin(yaw / 2.0), qw=math.cos(yaw / 2.0), waypoint_label="grasp_i0"
            )
            return
        if not self._nav.is_done():
            return
        if self._nav.succeeded():
            self._nav.reset()
            self._set_state(ManipulationState.WAIT_I0_SETTLE, "已回到 I0，准备第二趟观察")
            return
        self._retry_navigation_or_abort("返回 I0 导航失败")

    # ------------------------------------------------------------------
    # Shared helpers: pulse ownership, TF geometry, status and abort
    # ------------------------------------------------------------------

    def _consume_new_frame(self) -> Optional[HostDetectionFrame]:
        frame = self._latest_frame
        if frame is None or frame.sequence <= self._last_consumed_sequence:
            return None
        self._last_consumed_sequence = frame.sequence
        return frame

    def _latest_frame_is_stale(self) -> bool:
        if self._latest_frame is None:
            return False
        return time.monotonic() - self._latest_frame.received_monotonic_s > float(
            self.get_parameter("yolo_stale_timeout_s").value
        )

    def _matched_target_from_new_frame(self) -> Optional[Point3]:
        frame = self._consume_new_frame()
        if frame is None:
            return None
        if self._locked_target is None:
            self._abort("内部错误：细对齐时没有锁定目标")
            return None
        point = self._locked_target.match(frame, float(self.get_parameter("target_match_gate_m").value))
        if point is not None:
            return point
        self._publish_stop()
        if self._locked_target.lost_frames >= int(self.get_parameter("target_lost_limit").value):
            self._observer.clear()
            self._locked_target = None
            self._set_state(ManipulationState.OBSERVE_BLOCKS, "锁定红块持续丢失，停车后重新观察")
        return None

    def _start_pulse(self, axis: str, speed: float, duration_s: float, resume_state: ManipulationState) -> None:
        command = Twist()
        if axis == "x":
            command.linear.x = speed
        elif axis == "y":
            command.linear.y = speed
        elif axis == "yaw":
            command.angular.z = speed
        else:
            self._abort("未知速度轴 {}".format(axis))
            return
        self._cmd_vel_pub.publish(command)
        self._pulse_end_s = time.monotonic() + duration_s
        self._pulse_resume_state = resume_state
        self._set_state(ManipulationState.PULSE, "{} 轴低速脉冲 {:.3f}s".format(axis, duration_s))

    def _tick_pulse(self) -> None:
        if time.monotonic() < self._pulse_end_s:
            return
        self._publish_stop()
        self._set_state(ManipulationState.SETTLE_AFTER_PULSE, "脉冲结束，停车等待新观测")

    def _tick_settle_after_pulse(self) -> None:
        self._publish_stop()
        settle_s = float(self.get_parameter("align_settle_s").value)
        if self._pulse_resume_state in {
            ManipulationState.ALIGN_PLACE_Y,
            ManipulationState.ALIGN_PLACE_X,
            ManipulationState.ALIGN_PLACE_YAW,
        }:
            settle_s = float(self.get_parameter("place_settle_s").value)
        if self._elapsed() >= settle_s and self._pulse_resume_state is not None:
            self._set_state(self._pulse_resume_state, "停车观察完成")

    def _grasp_reference_base_xy_for_target(self, point_base: Point3) -> Tuple[float, float]:
        """Use this target's arm-frame z so a pitched arm mount stays correct."""

        point_arm = self._base_to_arm(point_base)
        return self._grasp_reference_base_xy_for_arm_z(point_arm[2])

    def _grasp_reference_base_xy_for_arm_z(self, arm_z: float) -> Tuple[float, float]:
        ref = self.get_parameter("grasp_reference_arm").value
        point = self._arm_to_base((float(ref[0]), float(ref[1]), float(arm_z)))
        return point[0], point[1]

    def _placement_error_in_base(self) -> Tuple[float, float, float]:
        assert self._jobs is not None and self._sites is not None
        transform = self._tf_buffer.lookup_transform(
            "map", "base_link", Time(), timeout=Duration(seconds=float(self.get_parameter("tf_timeout_s").value))
        )
        current_x = transform.transform.translation.x
        current_y = transform.transform.translation.y
        rotation = transform.transform.rotation
        current_yaw = math.atan2(
            2.0 * (rotation.w * rotation.z + rotation.x * rotation.y),
            1.0 - 2.0 * (rotation.y * rotation.y + rotation.z * rotation.z),
        )
        target_x, target_y, target_yaw = self._sites.placements[self._jobs.current_zone]
        dx_map, dy_map = target_x - current_x, target_y - current_y
        # map 误差转到当前 body 坐标，才能安全发布 base_link Twist。
        error_x = math.cos(current_yaw) * dx_map + math.sin(current_yaw) * dy_map
        error_y = -math.sin(current_yaw) * dx_map + math.cos(current_yaw) * dy_map
        error_yaw = self._normalise_angle(target_yaw - current_yaw)
        return error_x, error_y, error_yaw

    def _arm_to_base(self, point_arm: Point3) -> Point3:
        return self._transform_point("base_link", "arm_base_link", point_arm)

    def _base_to_arm(self, point_base: Point3) -> Point3:
        return self._transform_point("arm_base_link", "base_link", point_base)

    def _transform_point(self, target_frame: str, source_frame: str, point: Point3) -> Point3:
        transform = self._tf_buffer.lookup_transform(
            target_frame, source_frame, Time(), timeout=Duration(seconds=float(self.get_parameter("tf_timeout_s").value))
        )
        q = transform.transform.rotation
        t = transform.transform.translation
        x, y, z, w = q.x, q.y, q.z, q.w
        px, py, pz = point
        return (
            (1 - 2 * (y * y + z * z)) * px + 2 * (x * y - z * w) * py + 2 * (x * z + y * w) * pz + t.x,
            2 * (x * y + z * w) * px + (1 - 2 * (x * x + z * z)) * py + 2 * (y * z - x * w) * pz + t.y,
            2 * (x * z - y * w) * px + 2 * (y * z + x * w) * py + (1 - 2 * (x * x + y * y)) * pz + t.z,
        )

    def _retry_navigation_or_abort(self, reason: str) -> None:
        if self._nav_retries >= int(self.get_parameter("max_nav_retries").value):
            self._abort(reason)
            return
        self._nav_retries += 1
        self._nav.reset()
        self.get_logger().warn("{}，第 {} 次重试".format(reason, self._nav_retries))

    def _state_timed_out(self) -> bool:
        elapsed = self._elapsed()
        if self._state in {ManipulationState.OBSERVE_BLOCKS}:
            limit = float(self.get_parameter("observe_timeout_s").value)
        elif self._state in {ManipulationState.ALIGN_I1_Y, ManipulationState.ALIGN_I1_X, ManipulationState.CONFIRM_I1}:
            limit = float(self.get_parameter("align_timeout_s").value)
        elif self._state in {ManipulationState.PREFLIGHT_ARM, ManipulationState.WAIT_PREFLIGHT, ManipulationState.CALL_GRASP, ManipulationState.CALL_PLACE}:
            limit = float(self.get_parameter("service_wait_timeout_s").value)
        elif self._state in {ManipulationState.WAIT_GRASP, ManipulationState.WAIT_PLACE}:
            limit = float(self.get_parameter("service_result_timeout_s").value)
        else:
            return False
        if elapsed > limit:
            self._abort("状态 {} 超时 {:.1f}s".format(self._state.name, elapsed))
            return True
        return False

    def _set_state(self, state: ManipulationState, reason: str) -> None:
        self._state = state
        self._state_entered_s = time.monotonic()
        state_message = String()
        state_message.data = state.name.lower()
        self._state_pub.publish(state_message)
        self.get_logger().info("[{}] {}".format(state.name, reason))
        self._publish_status(reason)

    def _abort(self, reason: str) -> None:
        self._last_error = reason
        self._publish_stop()
        self._nav.cancel()
        self._set_state(ManipulationState.ABORT, reason)

    def _publish_stop(self) -> None:
        self._cmd_vel_pub.publish(Twist())

    def _publish_status(self, reason: str) -> None:
        zone = ""
        job_index = 0
        total_jobs = 0
        if self._jobs is not None:
            job_index = self._jobs.index
            total_jobs = len(self._jobs.zones)
            if not self._jobs.complete:
                zone = self._jobs.current_zone
        target = None if self._locked_target is None else list(self._locked_target.last_position_base)
        message = String()
        message.data = json.dumps({
            "state": self._state.name.lower(),
            "reason": reason,
            "job_index": job_index,
            "total_jobs": total_jobs,
            "current_zone": zone,
            "locked_target_base_link_m": target,
            "calibration_set_id": "" if self._sites is None else self._sites.calibration_set_id,
        }, ensure_ascii=False, separators=(",", ":"))
        self._status_pub.publish(message)

    def _resolve_calibration_path(self) -> Path:
        path = Path(str(self.get_parameter("calibration_file").value))
        if path.is_absolute():
            return path
        # Source checkout, colcon install space and direct ``ros2 run`` use
        # different working directories.  Prefer an existing explicit path.
        if (Path.cwd() / path).is_file():
            return Path.cwd() / path
        try:
            from ament_index_python.packages import get_package_share_directory
            installed = Path(get_package_share_directory("quadruped_robot_competition")) / path
            if installed.is_file():
                return installed
        except (ImportError, ValueError):
            pass
        for parent in Path(__file__).resolve().parents:
            candidate = parent / path
            if candidate.is_file():
                return candidate
        return Path.cwd() / path

    def _elapsed(self) -> float:
        return time.monotonic() - self._state_entered_s

    @staticmethod
    def _normalise_angle(angle: float) -> float:
        return math.atan2(math.sin(angle), math.cos(angle))

    def destroy_node(self) -> bool:
        self._publish_stop()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = GraspPlaceManager()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
