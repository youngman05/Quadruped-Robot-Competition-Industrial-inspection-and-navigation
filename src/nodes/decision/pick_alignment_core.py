"""ROS-independent AprilTag selection, I2 alignment, and grasp state machine."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Protocol, Tuple

from nodes.decision.manipulation_contracts import Point3, SegmentResult


Quaternion = Tuple[float, float, float, float]


@dataclass(frozen=True)
class FiducialPoseFrame:
    tag_id: int
    sequence: int
    stamp_s: float
    position_m: Point3
    orientation_xyzw: Quaternion

    @property
    def yaw(self) -> float:
        x, y, z, w = self.orientation_xyzw
        return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


@dataclass(frozen=True)
class FiducialDetectionFrame:
    sequence: int
    stamp_s: float
    detections: Tuple[FiducialPoseFrame, ...]

    def find(self, tag_id: int) -> Optional[FiducialPoseFrame]:
        return next((pose for pose in self.detections if pose.tag_id == tag_id), None)


@dataclass(frozen=True)
class I2Target:
    x: float
    y: float
    yaw: float


def parse_fiducial_frame(packet: Mapping[str, Any]) -> FiducialDetectionFrame:
    if packet.get("frame_id") != "base_link":
        raise ValueError("AprilTag frame_id must be base_link")
    sequence = packet.get("sequence")
    stamp = packet.get("stamp")
    raw_detections = packet.get("detections")
    if not isinstance(sequence, int) or sequence < 0:
        raise ValueError("AprilTag sequence must be a non-negative integer")
    if not isinstance(stamp, Mapping) or not isinstance(raw_detections, list):
        raise ValueError("AprilTag stamp and detections are required")
    sec, nanosec = stamp.get("sec"), stamp.get("nanosec")
    if not isinstance(sec, int) or not isinstance(nanosec, int):
        raise ValueError("AprilTag stamp must contain sec and nanosec")
    stamp_s = float(sec) + float(nanosec) / 1e9
    detections = []
    for raw in raw_detections:
        try:
            tag_id = int(raw["tag_id"])
            position = tuple(float(value) for value in raw["position_m"])
            orientation = tuple(float(value) for value in raw["orientation_xyzw"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("invalid AprilTag detection")
        if len(position) != 3 or len(orientation) != 4:
            raise ValueError("AprilTag pose requires xyz and quaternion xyzw")
        detections.append(FiducialPoseFrame(tag_id, sequence, stamp_s, position, orientation))
    return FiducialDetectionFrame(sequence, stamp_s, tuple(detections))


class PickState(str, Enum):
    IDLE = "idle"
    SETTLE = "settle"
    SELECT_TARGET = "select_target"
    ALIGN_TAG_YAW = "align_tag_yaw"
    ALIGN_TAG_X = "align_tag_x"
    ALIGN_TAG_Y = "align_tag_y"
    TAG_PULSE = "tag_pulse"
    TAG_PULSE_SETTLE = "tag_pulse_settle"
    CONFIRM_I2 = "confirm_i2"
    WAIT_ARM = "wait_arm"
    HOLD = "hold"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass(frozen=True)
class PickConfig:
    red_tag_ids: Tuple[int, ...] = (0, 1)
    excluded_tag_ids: Tuple[int, ...] = ()
    forced_tag_id: Optional[int] = None
    i2_targets: Mapping[int, I2Target] = field(default_factory=dict)
    initial_settle_s: float = 0.5
    x_tolerance_m: float = 0.03
    y_tolerance_m: float = 0.03
    yaw_tolerance_rad: float = math.radians(3.0)
    linear_speed_mps: float = 0.025
    x_speed_mps: Optional[float] = None
    y_speed_mps: Optional[float] = None
    yaw_speed_rps: float = 0.10
    linear_gain: float = 0.5
    x_gain: Optional[float] = None
    y_gain: Optional[float] = None
    yaw_gain: float = 0.6
    min_linear_speed_mps: float = 0.0125
    min_x_speed_mps: Optional[float] = None
    min_y_speed_mps: Optional[float] = None
    min_yaw_speed_rps: float = 0.05
    pulse_min_s: float = 0.50
    pulse_max_s: float = 0.50
    pulse_settle_s: float = 0.0
    stable_frames: int = 3
    timeout_s: float = 80.0
    lifted_hold_s: float = 3.2
    stop_after_stage: str = "grasped"


class PickRuntime(Protocol):
    def now(self) -> float: ...
    def stop(self) -> None: ...
    def command(self, axis: str, speed: float) -> None: ...
    def current_fiducial_frame(self) -> Optional[FiducialDetectionFrame]: ...
    def start_grasp(self) -> bool: ...
    def grasp_result(self) -> Optional[bool]: ...


def wrap_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


class PickOneExecutor:
    """选择一个 Tag，将其 base_link 位姿对齐到示教 I2，然后执行抓取。

    对齐采用离散脉冲控制，而不是连续速度控制：

      检查 yaw -> 检查 y -> 检查 x -> 最终确认
           |          |          |
           +------ 单轴脉冲、停车、静置，然后从 yaw 重新检查

    每次脉冲只允许一个轴非零，当前阶段顺序固定为 yaw -> y -> x。每次脉冲结束后
    必须真正停车、等待新检测帧，并从 yaw 开始重新检查三个轴。
    """

    def __init__(self, runtime: PickRuntime, config: PickConfig = PickConfig()) -> None:
        self.runtime = runtime
        self.config = config
        self.state = PickState.IDLE
        self.target_tag_id: Optional[int] = None
        self._entered_s = runtime.now()
        self._started_s = runtime.now()
        self._result: Optional[SegmentResult] = None
        self._confirm_count = 0
        self._last_confirm_sequence = -1
        self._pulse_axis = ""
        self._pulse_speed = 0.0
        self._pulse_until_s = 0.0
        self._post_pulse_sequence = -1
        self._pulse_start_pose: Optional[FiducialPoseFrame] = None

    def start(self) -> None:
        if self.state != PickState.IDLE:
            raise RuntimeError("pick executor can only start from idle")
        self._started_s = self.runtime.now()
        self._set_state(PickState.SETTLE)

    def cancel(self, reason: str) -> SegmentResult:
        return self._finish(False, reason)

    def tick(self) -> Optional[SegmentResult]:
        if self._result is not None:
            return self._result
        if self.runtime.now() - self._started_s > self.config.timeout_s:
            return self._finish(False, "AprilTag I2 alignment timed out")
        if self.state == PickState.SETTLE:
            self.runtime.stop()
            if self._elapsed() >= self.config.initial_settle_s:
                self._set_state(PickState.SELECT_TARGET)
            return None
        if self.state == PickState.SELECT_TARGET:
            return self._select_target()
        if self.state in {
            PickState.ALIGN_TAG_YAW,
            PickState.ALIGN_TAG_X,
            PickState.ALIGN_TAG_Y,
            PickState.CONFIRM_I2,
        }:
            return self._tick_alignment()
        if self.state == PickState.TAG_PULSE:
            self._tick_pulse()
            return None
        if self.state == PickState.TAG_PULSE_SETTLE:
            self._tick_pulse_settle()
            return None
        if self.state == PickState.WAIT_ARM:
            result = self.runtime.grasp_result()
            if result is False:
                return self._finish(False, "grasp service failed")
            if result is True:
                self._set_state(PickState.HOLD)
            return None
        if self.state == PickState.HOLD and self._elapsed() >= self.config.lifted_hold_s:
            return self._finish(
                True,
                "grasp completed",
                alignment_success=True,
                grasp_success=True,
                outputs={"target_tag_id": self.target_tag_id},
            )
        return None

    def _select_target(self) -> Optional[SegmentResult]:
        self.runtime.stop()
        frame = self.runtime.current_fiducial_frame()
        if frame is None:
            return None
        if self.config.forced_tag_id is not None:
            candidates = [
                pose for pose in frame.detections
                if pose.tag_id == self.config.forced_tag_id
            ]
        else:
            candidates = [
                pose
                for pose in frame.detections
                if pose.tag_id in self.config.red_tag_ids
                and pose.tag_id not in self.config.excluded_tag_ids
            ]
        if not candidates:
            return None
        # 目标只选择一次。执行器运行期间 target_tag_id 始终锁定，防止机器人运动时
        # 另一个更近的 Tag 进入画面并导致中途切换目标。
        target = min(candidates, key=lambda pose: math.hypot(pose.position_m[0], pose.position_m[1]))
        self.target_tag_id = target.tag_id
        if target.tag_id not in self.config.i2_targets:
            return self._finish(False, "I2_NOT_TAUGHT: tag {}".format(target.tag_id))
        self._set_state(PickState.ALIGN_TAG_YAW)
        return None

    def _current_target_pose(self) -> Optional[FiducialPoseFrame]:
        frame = self.runtime.current_fiducial_frame()
        if frame is None or self.target_tag_id is None:
            return None
        return frame.find(self.target_tag_id)

    def _tick_alignment(self) -> Optional[SegmentResult]:
        pose = self._current_target_pose()
        if pose is None:
            # 锁定的 Tag 丢失或数据过期时，绝不沿用上一条速度。等待期间总对齐超时
            # 仍然继续计时。
            self.runtime.stop()
            return None
        target = self.config.i2_targets[self.target_tag_id]

        # I2 是示教得到的 Tag 在 base_link 下的位姿，不是地图坐标。所有误差均定义为
        # “当前观测值 - 示教值”。运动方向已经过真机标定，因此发送与误差同号的命令
        # 会使观测误差趋近于零。wrap_angle 将 yaw 误差限制在 [-pi, pi]，避免四元数
        # 跨越 +/-pi 边界时错误地旋转接近一整圈。
        yaw_error = wrap_angle(pose.yaw - target.yaw)
        x_error = pose.position_m[0] - target.x
        y_error = pose.position_m[1] - target.y

        # 阶段 1：先修正朝向。旋转会改变观测到的 x/y 误差，因此 yaw 进入容差前
        # 不评估平移轴。
        if self.state == PickState.ALIGN_TAG_YAW:
            if abs(yaw_error) <= self.config.yaw_tolerance_rad:
                self.runtime.stop()
                self._set_state(PickState.ALIGN_TAG_Y)
            else:
                self._start_pulse("yaw", yaw_error, self.config.yaw_gain, self.config.yaw_speed_rps, self.config.min_yaw_speed_rps, pose)
            return None

        # 阶段 3：检查 x。x 达到容差后只进入最终确认状态，不会立即判定成功。
        if self.state == PickState.ALIGN_TAG_X:
            if abs(x_error) <= self.config.x_tolerance_m:
                self.runtime.stop()
                self._set_state(PickState.CONFIRM_I2)
            else:
                self._start_pulse(
                    "x", x_error,
                    self.config.x_gain if self.config.x_gain is not None else self.config.linear_gain,
                    self.config.x_speed_mps if self.config.x_speed_mps is not None else self.config.linear_speed_mps,
                    self.config.min_x_speed_mps if self.config.min_x_speed_mps is not None else self.config.min_linear_speed_mps,
                    pose,
                )
            return None

        # 阶段 2：检查 y。y 达到容差后进入 x 阶段。
        if self.state == PickState.ALIGN_TAG_Y:
            if abs(y_error) <= self.config.y_tolerance_m:
                self.runtime.stop()
                self._set_state(PickState.ALIGN_TAG_X)
            else:
                self._start_pulse(
                    "y", y_error,
                    self.config.y_gain if self.config.y_gain is not None else self.config.linear_gain,
                    self.config.y_speed_mps if self.config.y_speed_mps is not None else self.config.linear_speed_mps,
                    self.config.min_y_speed_mps if self.config.min_y_speed_mps is not None else self.config.min_linear_speed_mps,
                    pose,
                )
            return None

        # 最终确认必须在停车状态下完成。复检仍使用 yaw -> y -> x 的优先级；任一轴
        # 再次越界都会清零连续帧计数，并从第一个不合格的轴恢复对齐。
        self.runtime.stop()
        if abs(yaw_error) > self.config.yaw_tolerance_rad:
            self._restart_alignment(PickState.ALIGN_TAG_YAW)
        elif abs(y_error) > self.config.y_tolerance_m:
            self._restart_alignment(PickState.ALIGN_TAG_Y)
        elif abs(x_error) > self.config.x_tolerance_m:
            self._restart_alignment(PickState.ALIGN_TAG_X)
        elif pose.sequence != self._last_confirm_sequence:
            # 只统计序列号不同的相机新帧。管理器 tick 频率高于图像消费频率，如果按
            # tick 计数，同一帧重复观测会被误判为多个稳定帧。
            self._last_confirm_sequence = pose.sequence
            self._confirm_count += 1
            if self._confirm_count >= self.config.stable_frames:
                if self.config.stop_after_stage == "i2":
                    return self._finish(
                        True,
                        "I2 AprilTag alignment completed",
                        alignment_success=True,
                        outputs={"test_stage": "i2", "target_tag_id": self.target_tag_id},
                    )
                if not self.runtime.start_grasp():
                    return self._finish(False, "grasp service rejected")
                self._set_state(PickState.WAIT_ARM)
        return None

    def _restart_alignment(self, state: PickState) -> None:
        self._confirm_count = 0
        self._set_state(state)

    def _start_pulse(
        self,
        axis: str,
        error: float,
        gain: float,
        maximum: float,
        minimum: float,
        pose: FiducialPoseFrame,
    ) -> None:
        # 比例控制输出同时包含硬件死区下限和安全上限：
        #
        #   |command| = clamp(|error| * Kp, minimum, maximum)
        #
        # 平移和 yaw 的 gain 单位都是 1/s。minimum 必须小于 maximum，Kp 才能在
        # 中间误差区间真正参与调速。小误差区使用下限以克服 Lite3 运动死区；大误差区
        # 使用上限限制步态速度并减小过冲。
        speed = min(max(abs(error) * gain, minimum), maximum)
        self._pulse_axis = axis
        self._pulse_speed = math.copysign(speed, error)

        # 根据当前误差和选定速度计算名义脉冲时长，然后进行上下限约束。平移轴使用
        # m/(m/s)，yaw 使用 rad/(rad/s)。Kp 较小时，该商可能超过 pulse_max_s，
        # 此时实际脉冲时长等于配置上限；只要速度没有被 minimum/maximum 钳制，
        # Kp 仍然能够调节速度。
        duration = min(max(abs(error) / speed, self.config.pulse_min_s), self.config.pulse_max_s)
        self._pulse_until_s = self.runtime.now() + duration
        # 脉冲前位姿仅用于记录真机响应。脉冲后的控制必须使用新检测帧，不做位姿外推。
        self._pulse_start_pose = pose
        print(
            "AprilTag alignment pulse axis={} error={:.4f} speed={:.4f} duration_s={:.2f} "
            "tag_xyz=[{:.3f},{:.3f},{:.3f}] tag_yaw={:.3f}".format(
                axis,
                error,
                self._pulse_speed,
                duration,
                *pose.position_m,
                pose.yaw,
            ),
            flush=True,
        )
        self._set_state(PickState.TAG_PULSE)

    def _tick_pulse(self) -> None:
        if self.runtime.now() < self._pulse_until_s:
            # 按管理器 tick 频率重复发送唯一一个非零轴。ROS 运行层生成只包含该分量的
            # Twist，Lite3 bridge 再将其转换为一条对应轴的运动数据包。
            self.runtime.command(self._pulse_axis, self._pulse_speed)
            return
        # 每次脉冲都先显式停车，再观测运动结果。stop() 发布零 Twist，已验收的 bridge
        # 将其转换为最后一个实际运动轴的同轴零速数据包。
        self.runtime.stop()
        frame = self.runtime.current_fiducial_frame()
        # 停车瞬间已有的帧可能仍处于运动过程。保存其序列号，要求静置状态必须等待
        # 序列号严格更新的帧。
        self._post_pulse_sequence = -1 if frame is None else frame.sequence
        self._set_state(PickState.TAG_PULSE_SETTLE)

    def _tick_pulse_settle(self) -> None:
        # 机械运动静置期间持续发送停车命令。此阶段不使用 Tag 反馈，因为其中可能包含
        # 步态振动；若立即闭环，会触发正反方向交替修正并造成震荡。
        self.runtime.stop()
        if self._elapsed() < self.config.pulse_settle_s:
            return
        frame = self.runtime.current_fiducial_frame()
        # 只有收到停车后的新帧才恢复对齐。感知数据过期时保持停车，直到出现新帧或
        # 执行器达到总超时。
        if frame is not None and frame.sequence > self._post_pulse_sequence:
            pose = frame.find(self.target_tag_id) if self.target_tag_id is not None else None
            if pose is not None and self._pulse_start_pose is not None:
                start = self._pulse_start_pose
                print(
                    "AprilTag alignment observed axis={} tag_delta=[{:.3f},{:.3f},{:.3f}] "
                    "yaw_delta={:.3f} sequence={} -> {}".format(
                        self._pulse_axis,
                        pose.position_m[0] - start.position_m[0],
                        pose.position_m[1] - start.position_m[1],
                        pose.position_m[2] - start.position_m[2],
                        wrap_angle(pose.yaw - start.yaw),
                        start.sequence,
                        pose.sequence,
                    ),
                    flush=True,
                )
            self._pulse_start_pose = None
            # 脉冲结束后基于新帧从 yaw 重新开始，确保三个轴都按
            # yaw -> y -> x 的既定优先级重新检查。
            self._set_state(PickState.ALIGN_TAG_YAW)

    def _set_state(self, state: PickState) -> None:
        self.state = state
        self._entered_s = self.runtime.now()

    def _elapsed(self) -> float:
        return self.runtime.now() - self._entered_s

    def _finish(self, success: bool, reason: str, **kwargs) -> SegmentResult:
        self.runtime.stop()
        self.state = PickState.SUCCESS if success else PickState.FAILED
        self._result = SegmentResult(success=success, reason=reason, **kwargs)
        return self._result


QrPoseFrame = FiducialPoseFrame
