#!/usr/bin/env python3
"""ROS2 node: 比赛任务状态机 (Competition Task Manager).

掌控比赛全流程，协调感知、导航、语音、机械臂各模块。

订阅:
    /gauge/status          std_msgs/String  仪表检测结果 (JSON)
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
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from navigation.navigator import Navigator


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
        self.declare_parameter("timeout_per_phase", 120.0)   # 每阶段超时 (秒)
        self.declare_parameter("tick_rate", 10.0)             # 状态机主循环频率 (Hz)
        self.declare_parameter("require_stable_gauge", True)  # 是否必须稳定检测
        self.declare_parameter("auto_advance", False)         # 调试: 自动推进阶段

        self.declare_parameter("gauge_topic", "/gauge/status")
        self.declare_parameter("yolo_topic", "/yolo/detections")
        self.declare_parameter("slam_status_topic", "/visual_slam/status")
        self.declare_parameter("phase_topic", "/task/phase")
        self.declare_parameter("status_topic", "/task/status")

        # ── 读取参数 ──────────────────────────────
        self._timeout_per_phase = float(self.get_parameter("timeout_per_phase").value)
        self._tick_rate = float(self.get_parameter("tick_rate").value)
        self._require_stable = bool(self.get_parameter("require_stable_gauge").value)
        self._auto_advance = bool(self.get_parameter("auto_advance").value)

        gauge_topic = str(self.get_parameter("gauge_topic").value)
        yolo_topic = str(self.get_parameter("yolo_topic").value)
        slam_status_topic = str(self.get_parameter("slam_status_topic").value)
        phase_topic = str(self.get_parameter("phase_topic").value)
        status_topic = str(self.get_parameter("status_topic").value)

        # ── 发布者 ────────────────────────────────
        self._phase_pub = self.create_publisher(String, phase_topic, 10)
        self._status_pub = self.create_publisher(String, status_topic, 10)
        self._speech_pub = self.create_publisher(String, "/speech/text", 10)

        # ── 订阅者 ────────────────────────────────
        self._gauge_sub = self.create_subscription(
            String, gauge_topic, self._on_gauge_status, 10,
        )
        self._yolo_sub = self.create_subscription(
            String, yolo_topic, self._on_yolo_detections, 10,
        )
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        _best_effort = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
        self._slam_sub = self.create_subscription(
            String, slam_status_topic, self._on_slam_status, _best_effort,
        )

        # ── 内部状态 ──────────────────────────────
        self._phase: Phase = Phase.START
        self._phase_enter_time: float = 0.0          # 进入当前阶段的时间戳
        self._gauge_info: Dict[str, GaugeInfo] = {   # 按字母索引的仪表信息
            letter: GaugeInfo(letter=letter) for letter in "ABCD"
        }
        self._latest_yolo: Optional[YoloDetection] = None
        self._slam_ok: bool = False                  # SLAM 定位是否正常
        self._abnormal_zones: List[str] = []           # 所有异常区域字母 (可能有1~4个)
        self._abnormal_handled: int = 0                # 已完成抓取放置的异常数
        self._phase_seq_idx: int = 0                  # 在 PHASE_SEQUENCE 中的位置

        # ── 导航客户端 (轻量 A* + 纯追踪) ─────
        self._nav = Navigator(self)
        # 4 个观察子步骤: 位置 + 朝向 + 说明
        self._inspection_steps = [
            {"waypoint": "pos1_middle",        "desc": "仰头看上柜底面 (上区仪表)"},
            {"waypoint": "pos1_middle_turned", "desc": "180°转身看下柜顶面 (下区仪表)"},
            {"waypoint": "pos2a_upper_right",  "desc": "看上柜右侧面 (上区字母)"},
            {"waypoint": "pos2b_lower_right",  "desc": "看下柜右侧面 (下区字母)"},
        ]
        self._inspection_step: int = 0           # 当前子步骤 (0-3)
        self._gauges_filled_count: int = 0       # 已填入的仪表数量

        # ── 主循环定时器 ──────────────────────────
        self._timer = self.create_timer(1.0 / self._tick_rate, self._state_machine_tick)

        # ── 进入初始状态 ──────────────────────────
        self._enter_phase(Phase.START)
        self.get_logger().info(
            f"Task Manager 启动完成 | tick_rate={self._tick_rate} Hz "
            f"| timeout={self._timeout_per_phase}s "
            f"| require_stable={self._require_stable}"
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
        # 调试模式: 跳过所有条件直接推进
        if self._auto_advance and elapsed > 0.5:
            self._advance_to_next_phase()

        # 用 odom 数据到达判断定位就绪 (DDS QoS 兼容性更好)
        slam_ready = self._slam_ok or self._nav._has_odom
        if slam_ready and elapsed > 1.0:
            self.get_logger().info("各子系统就绪，进入越障巡航阶段")
            self._advance_to_next_phase()

    def _tick_pass_obstacle(self, elapsed: float) -> None:
        """PASS_OBSTACLE: 两步走 — 先穿障碍区到底，再到安全区观察位。"""
        if self._handle_timeout(elapsed):
            return

        # 子步骤定义
        if not hasattr(self, "_obstacle_step"):
            self._obstacle_step = 0  # 0=穿越障碍区, 1=安全区到观察位

        # ── 子步骤 0: start → obstacle_exit ──
        if self._obstacle_step == 0:
            if not self._nav.goal_sent and not self._nav.is_done():
                self.get_logger().info("[越障 1/2] 穿越障碍区...")
                self._nav.navigate_to_waypoint("obstacle_exit")

            if self._nav.is_done():
                if self._nav.succeeded():
                    self.get_logger().info("已穿过障碍区，切换地图+进入安全区域")
                    self._switch_to_phase2_map()
                    self._obstacle_step = 1
                    self._nav.reset()
                else:
                    self.get_logger().warn("越障导航失败，重试...")
                    self._nav.reset()

        # ── 子步骤 1: 安全区内 → 第一个观察位 ──
        elif self._obstacle_step == 1:
            if not self._nav.goal_sent and not self._nav.is_done():
                self.get_logger().info("[越障 2/2] 安全区 → 观察位①...")
                self._nav.navigate_to_waypoint("pos1_middle")

            if self._nav.is_done():
                if self._nav.succeeded():
                    self.get_logger().info("已到达观察位①，进入仪表检测")
                    del self._obstacle_step
                    self._advance_to_next_phase()
                else:
                    self.get_logger().warn("安全区导航失败，重试...")
                    self._nav.reset()

    def _tick_inspect_gauges(self, elapsed: float) -> None:
        """INSPECT_GAUGES: 4 个观察位，到位置后拍一帧→识别→播报→关。"""
        if self._handle_timeout(elapsed):
            return

        # ── 全部 4 个子步骤完成 → 收尾 ──────────
        if self._inspection_step >= len(self._inspection_steps):
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
            self._advance_to_next_phase()
            return

        step_info = self._inspection_steps[self._inspection_step]
        wp = step_info["waypoint"]

        # ── 导航到当前观察位 ──────────────────────
        if not self._nav.goal_sent and not self._nav.is_done():
            self.get_logger().info(
                f"[观察 {self._inspection_step+1}/4] {step_info['desc']}"
            )
            self._nav.navigate_to_waypoint(wp)

        # 导航失败 → 重试
        if self._nav.is_done():
            if not self._nav.succeeded():
                self.get_logger().warn(f"到{wp}导航失败，重试...")
                self._nav.reset()
                return

        # ── 已到达 → 拍一帧, 识别, 播报, 关 ──────
        if not hasattr(self, "_inspect_done"):
            self._inspect_done = False

        if self._inspect_done:
            return  # already processed, wait for step advance

        self._inspect_done = True
        self._run_whz_inline(step_info["desc"])

    def _run_whz_inline(self, desc: str):
        """Capture one relay frame, run letter+gauge detection, play audio."""
        import cv2, numpy as np, sys, time
        from pathlib import Path
        from collections import Counter

        self.get_logger().info(f"[whz] 拍一帧识别: {desc}")

        # Lazy-load whz modules (only during inspection, keeps CPU free otherwise)
        _WS = Path(__file__).resolve().parents[3]
        _WHZ = _WS / "src" / "whz" / "whz"
        if str(_WHZ) not in sys.path:
            sys.path.insert(0, str(_WHZ))
        from letter_detector import LetterDetector
        from gauge_detector import detect_gauge
        from audio_player import AudioPlayer

        relay_dir = Path.home() / "workspaces" / "isaac_ros-dev" / "camera_frames"
        jpg = relay_dir / "latest_color.jpg"
        raw = relay_dir / "latest_depth.raw"
        meta = relay_dir / "latest_depth_meta.txt"

        if not jpg.exists():
            self.get_logger().error("[whz] 无 relay JPEG, 跳过")
            self._advance_step()
            return

        # Wait for a fresh frame (up to 2s)
        color = None
        for _ in range(20):
            color = cv2.imread(str(jpg), cv2.IMREAD_COLOR)
            if color is not None and color.shape[0] > 0:
                break
            time.sleep(0.1)

        if color is None:
            self.get_logger().error("[whz] JPEG 读取失败")
            self._advance_step()
            return

        # Depth (optional)
        depth = None
        if raw.exists():
            try:
                data = raw.read_bytes()
                w, h = 640, 360
                if meta.exists():
                    parts = meta.read_text().strip().split()
                    if len(parts) >= 2:
                        w, h = int(parts[0]), int(parts[1])
                if len(data) == w * h * 2:
                    depth = np.frombuffer(data, dtype=np.uint16).reshape(h, w).astype(np.float32) * 0.001
            except Exception:
                pass

        # Detect
        template_dir = _WS / "src" / "whz" / "assets" / "templates"
        audio_dir = _WS / "src" / "whz" / "assets" / "audio"
        letter_det = LetterDetector(template_dir, min_score=0.38)
        audio = AudioPlayer(audio_dir, timeout_sec=10.0)

        letter = letter_det.detect(color)
        gauge = detect_gauge(color, depth)

        if letter is None or gauge is None:
            err = f"letter={'OK' if letter else 'FAIL'} gauge={'OK' if gauge else 'FAIL'}"
            self.get_logger().warn(f"[whz] 检测失败: {err}")
            self._advance_step()
            return

        area = letter.area
        state = gauge.state_key
        self.get_logger().info(
            f"[whz] 检测成功: {area}区 {gauge.color}/{gauge.status} "
            f"letter_score={letter.score:.3f} gauge_conf={gauge.confidence:.3f}"
        )

        # Play audio (blocking, but only ~2s)
        try:
            audio.play(audio.audio_path_for(area, state))
        except Exception:
            pass

        # Save result
        if area in self._gauge_info:
            info = self._gauge_info[area]
            info.detected = True
            info.stable_detected = True
            info.letter = area
            info.color = gauge.color
            info.level = gauge.level
            info.status = gauge.status

        self._advance_step()

    def _advance_step(self):
        """Move to next inspection sub-step."""
        self._inspect_done = False
        self._inspection_step += 1
        self._nav.reset()
        self.get_logger().info(f"观察子步骤完成 → {self._inspection_step}/4")

    def _tick_find_red_bar(self, elapsed: float) -> None:
        """FIND_RED_BAR: 导航到抓取区，寻找并定位红色条。"""
        if self._handle_timeout(elapsed):
            return

        # 先导航到抓取区
        if not self._nav.goal_sent and not self._nav.is_done():
            self._nav.navigate_to_waypoint("grab_area")

        if self._nav.is_done():
            if not self._nav.succeeded():
                self.get_logger().warn("抓取区导航失败，重试...")
                self._nav.reset()
                return

        # 等待 YOLO 检测到红色条
        if self._latest_yolo and len(self._latest_yolo.red_bars) > 0:
            bar = self._latest_yolo.red_bars[0]
            dist = bar.get("distance_m", "?")
            self.get_logger().info(
                f"检测到红色条 (距离={dist}m)，进入抓取阶段"
            )
            self._nav.cancel()
            self._advance_to_next_phase()

    def _tick_grasp_bar(self, elapsed: float) -> None:
        """GRASP_BAR: 等待抓取完成。"""
        if self._handle_timeout(elapsed):
            return

        # TODO: 接入机械臂反馈 —— 收到 "grasp_success" 时推进
        # 当前占位: 1 秒后自动推进
        if elapsed > 1.0:
            self.get_logger().info("抓取完成 (占位)，进入放置阶段")
            self._advance_to_next_phase()

    def _tick_place_to_abnormal_zone(self, elapsed: float) -> None:
        """PLACE_TO_ABNORMAL_ZONE: 导航到当前异常区域放置纸箱。"""
        if self._handle_timeout(elapsed):
            return

        if self._abnormal_handled >= len(self._abnormal_zones):
            self.get_logger().info("所有异常区域已处理完毕！")
            self._advance_to_next_phase()
            return

        current_zone = self._abnormal_zones[self._abnormal_handled]

        # 导航到对应放置区
        if not self._nav.goal_sent and not self._nav.is_done():
            target = f"placement_{current_zone}"
            self._nav.navigate_to_waypoint(target)

        if self._nav.is_done():
            if not self._nav.succeeded():
                self.get_logger().warn(f"{current_zone}放置区导航失败，重试...")
                self._nav.reset()
                return

        # TODO: 接入机械臂反馈 —— 收到 "place_success" 时推进
        # 当前占位: 到达后 1 秒视为放置完成
        if elapsed > 1.0:
            self._abnormal_handled += 1
            remaining = len(self._abnormal_zones) - self._abnormal_handled
            self.get_logger().info(
                f"{current_zone}区放置完成 ({self._abnormal_handled}/{len(self._abnormal_zones)})"
                + (f"，剩余 {remaining} 趟" if remaining > 0 else "，全部完成！")
            )
            if remaining > 0:
                # 折返：回到抓取区取下一个红色块
                self._nav.reset()
                self._enter_phase(Phase.FIND_RED_BAR)
            else:
                self._advance_to_next_phase()

    # ═══════════════════════════════════════════════════════════
    #  阶段推进
    # ═══════════════════════════════════════════════════════════

    def _enter_phase(self, phase: Phase) -> None:
        """进入新阶段，执行入口动作并发布状态。"""
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
        self._nav.switch_phase2_map()
        self.get_logger().info("地图已切换 → Phase 2 (障碍区封堵)")

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
        if elapsed > self._timeout_per_phase:
            self.get_logger().error(
                f"阶段 {self._phase.label()} 超时 "
                f"({elapsed:.1f}s > {self._timeout_per_phase}s)，进入中止状态!"
            )
            self._enter_phase(Phase.ABORT)
            return True
        return False

    # ═══════════════════════════════════════════════════════════
    #  订阅回调
    # ═══════════════════════════════════════════════════════════

    def _on_gauge_status(self, msg: String) -> None:
        """解析 /gauge/status JSON，更新仪表信息。"""
        try:
            data = json.loads(msg.data)
        except (json.JSONDecodeError, TypeError) as exc:
            self.get_logger().warn(f"gauge/status JSON 解析失败: {exc}")
            return

        # 用 stable_* 字段（按照 CONTRIBUTING.md 要求）
        if self._require_stable:
            if not data.get("stable_detected"):
                return
            color = data.get("stable_color")
            level = data.get("stable_level")
            status = data.get("stable_status")
            angle = data.get("stable_angle")
            detected = data.get("stable_detected", False)
        else:
            color = data.get("color")
            level = data.get("level")
            status = data.get("status")
            angle = data.get("angle")
            detected = data.get("detected", False)

        # 通过 YOLO 确定当前瞄准的是哪个字母的仪表
        # gauge_status 本身不区分 A/B/C/D，需要配合 YOLO 定位
        # 这里做一个简化: 如果当前阶段是 INSPECT_GAUGES，按顺序填充
        if self._phase == Phase.INSPECT_GAUGES:
            # 找到第一个尚未稳定检测的仪表，填入当前数据
            for letter in "ABCD":
                info = self._gauge_info[letter]
                if not info.stable_detected and detected:
                    info.detected = True
                    info.stable_detected = True
                    info.color = color
                    info.level = level
                    info.status = status
                    info.angle = angle
                    self.get_logger().info(
                        f"仪表 {letter} 区: color={color} level={level} status={status}"
                    )
                    break

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
                self._slam_ok = True
            elif text in ("lost", "degraded", "unknown"):
                self._slam_ok = False
            return

        # JSON 格式: 检查 vo_state 字段
        state = data.get("vo_state", data.get("state", "")).lower()
        self._slam_ok = state in ("ok", "tracking", "nominal")

        if not self._slam_ok and self._phase not in (Phase.START, Phase.FINISH, Phase.ABORT):
            self.get_logger().warn(
                f"SLAM 定位状态异常: {state}，当前阶段 {self._phase.label()}"
            )

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
            "timeout_s": self._timeout_per_phase,
            "slam_ok": self._slam_ok,
            "abnormal_zones": self._abnormal_zones,
            "abnormal_handled": self._abnormal_handled,
            "navigation": self._nav.status_dict(),
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
