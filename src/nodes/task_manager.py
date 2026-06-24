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
    START -> PASS_OBSTACLE -> INSPECT_GAUGES -> REPORT_STATUS
          -> FIND_RED_BAR -> GRASP_BAR -> PLACE_TO_ABNORMAL_ZONE -> FINISH
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


# ═══════════════════════════════════════════════════════════════════
#  状态定义
# ═══════════════════════════════════════════════════════════════════

class Phase(Enum):
    """比赛阶段枚举。"""
    START = auto()                  # 初始化，等待各子系统就绪
    PASS_OBSTACLE = auto()          # 越障 / 巡航到目标区域
    INSPECT_GAUGES = auto()         # 检测仪表 + 识别字母/颜色条
    REPORT_STATUS = auto()          # 中文语音播报结果
    FIND_RED_BAR = auto()           # 寻找红色条
    GRASP_BAR = auto()              # 抓取红色条
    PLACE_TO_ABNORMAL_ZONE = auto() # 放入异常区域
    FINISH = auto()                 # 比赛结束
    ABORT = auto()                  # 异常中止

    def label(self) -> str:
        """返回中文阶段名。"""
        _labels = {
            Phase.START: "初始化",
            Phase.PASS_OBSTACLE: "越障巡航",
            Phase.INSPECT_GAUGES: "仪表检测",
            Phase.REPORT_STATUS: "语音播报",
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

    # 阶段顺序（不含 START / FINISH / ABORT 三个元状态）
    PHASE_SEQUENCE = [
        Phase.PASS_OBSTACLE,
        Phase.INSPECT_GAUGES,
        Phase.REPORT_STATUS,
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
        self.declare_parameter("report_duration", 5.0)        # 语音播报最短时长
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
        self._report_duration = float(self.get_parameter("report_duration").value)
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

        # ── 订阅者 ────────────────────────────────
        self._gauge_sub = self.create_subscription(
            String, gauge_topic, self._on_gauge_status, 10,
        )
        self._yolo_sub = self.create_subscription(
            String, yolo_topic, self._on_yolo_detections, 10,
        )
        self._slam_sub = self.create_subscription(
            String, slam_status_topic, self._on_slam_status, 10,
        )

        # ── 内部状态 ──────────────────────────────
        self._phase: Phase = Phase.START
        self._phase_enter_time: float = 0.0          # 进入当前阶段的时间戳
        self._gauge_info: Dict[str, GaugeInfo] = {   # 按字母索引的仪表信息
            letter: GaugeInfo(letter=letter) for letter in "ABCD"
        }
        self._latest_yolo: Optional[YoloDetection] = None
        self._slam_ok: bool = False                  # SLAM 定位是否正常
        self._abnormal_zone: Optional[str] = None     # 异常区域字母 (A/B/C/D)
        self._report_start_time: float = 0.0
        self._phase_seq_idx: int = 0                  # 在 PHASE_SEQUENCE 中的位置

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

        elif self._phase == Phase.REPORT_STATUS:
            self._tick_report_status(elapsed)

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

        # 正式条件: SLAM 就绪 + 至少收到过一次 gauge/yolo 数据
        if self._slam_ok and elapsed > 1.0:
            self.get_logger().info("各子系统就绪，进入越障巡航阶段")
            self._advance_to_next_phase()

    def _tick_pass_obstacle(self, elapsed: float) -> None:
        """PASS_OBSTACLE: 巡航到目标区域。"""
        if self._handle_timeout(elapsed):
            return

        # TODO: 接入导航反馈 —— 收到 "target_reached" 时推进
        # 当前占位: SLAM 正常 + 检测到仪表 → 视为已到达
        if self._slam_ok and self._latest_yolo is not None:
            if len(self._latest_yolo.gauges) > 0:
                self.get_logger().info("检测到仪表，进入仪表检测阶段")
                self._advance_to_next_phase()

    def _tick_inspect_gauges(self, elapsed: float) -> None:
        """INSPECT_GAUGES: 等待所有仪表稳定检测结果。"""
        if self._handle_timeout(elapsed):
            return

        # 检查是否所有仪表都有了稳定结果
        all_stable = all(
            info.stable_detected for info in self._gauge_info.values()
        )
        if all_stable:
            # 找出异常区域
            abnormal = [
                info for info in self._gauge_info.values()
                if info.status and info.status != "normal"
            ]
            if abnormal:
                zones = ", ".join(
                    f"{g.letter}区({g.color}/{g.status})" for g in abnormal
                )
                self.get_logger().info(f"全部仪表检测完成，异常区域: {zones}")
                # 记录第一个异常区域作为后续放置目标
                self._abnormal_zone = abnormal[0].letter
            else:
                self.get_logger().info("全部仪表检测完成，未发现异常")
            self._advance_to_next_phase()

    def _tick_report_status(self, elapsed: float) -> None:
        """REPORT_STATUS: 语音播报结果。"""
        if self._handle_timeout(elapsed):
            return

        # 等待播报完成（最短播报时长）
        if elapsed >= self._report_duration:
            self.get_logger().info("语音播报完成，进入寻找红条阶段")
            self._advance_to_next_phase()

    def _tick_find_red_bar(self, elapsed: float) -> None:
        """FIND_RED_BAR: 寻找并定位红色条。"""
        if self._handle_timeout(elapsed):
            return

        if self._latest_yolo and len(self._latest_yolo.red_bars) > 0:
            bar = self._latest_yolo.red_bars[0]
            dist = bar.get("distance_m", "?")
            self.get_logger().info(
                f"检测到红色条 (距离={dist}m)，进入抓取阶段"
            )
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
        """PLACE_TO_ABNORMAL_ZONE: 等待放置完成。"""
        if self._handle_timeout(elapsed):
            return

        # TODO: 接入机械臂反馈 —— 收到 "place_success" 时推进
        # 当前占位: 1 秒后自动推进
        if elapsed > 1.0:
            self.get_logger().info("放置完成 (占位)，比赛结束！")
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
            "abnormal_zone": self._abnormal_zone,
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
