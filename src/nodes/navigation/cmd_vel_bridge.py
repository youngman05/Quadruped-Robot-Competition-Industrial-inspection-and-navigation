#!/usr/bin/env python3
"""
cmd_vel_bridge.py — 将 Nav2 的 /cmd_vel 转成 Lite3 狗的 UDP MotionComplexCMD。

链路:
    Nav2/SE2 → CmdVelArbiter → /cmd_vel → CmdVelBridge → UDP → Lite3

设计要点:
    - 心跳 + 速度指令从同一个 UDP socket 发出（狗 SDK 要求）
    - 固定频率重发最近一次速度指令（Zero-Order Hold）
    - 默认每周期发送 FWD/LAT/YAW 三轴完整状态，避免底层锁存旧轴速度
    - 角速度取反（ROS 左转为正，狗 SDK 右转为正）
    - 超过 command_timeout_sec 未收到新 /cmd_vel 时持续发送三轴 stop
"""

from __future__ import annotations

import socket
import struct
import time
import os
import math

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist


# ── 常量 (与 motion_controller.py / Jetson2Motion.cpp 一致) ──
DOG_IP = "192.168.1.120"
DOG_PORT = 43893

CMD_HEARTBEAT = 0x21040001
CMD_AUTO_MODE = 0x21010C03
CMD_MOTION    = 0x21010D06

CODE_FWD = 320   # 前向速度 (m/s)
CODE_YAW = 321   # 角速度 (rad/s, 取反)
CODE_LAT = 325   # 横向速度 (m/s)

# MotionComplexCMD 二进制格式: <3id = 3×int32 + 1×float64 = 20 bytes
PACK_FMT = "<3id"


class CmdVelBridge(Node):
    """订阅 /cmd_vel，转为 UDP MotionComplexCMD 发给狗。"""

    def __init__(self) -> None:
        super().__init__("cmd_vel_bridge")

        # ── 参数 ──────────────────────────────────
        self.declare_parameter("dog_ip", DOG_IP)
        self.declare_parameter("dog_port", DOG_PORT)
        self.declare_parameter("init_dog", False)  # 是否自动初始化狗 (auto mode + motion mode)
        self.declare_parameter("send_rate_hz", 40.0)
        self.declare_parameter("command_timeout_sec", 0.35)
        self.declare_parameter("idle_stop_duration_sec", 0.5)
        self.declare_parameter("send_combined_axes", True)
        self.declare_parameter("shutdown_stop_burst_count", 12)
        self.declare_parameter("shutdown_stop_burst_interval_sec", 0.05)
        self.declare_parameter("vx_deadband", 0.005)
        self.declare_parameter("vy_deadband", 0.005)
        self.declare_parameter("az_deadband", 0.005)
        self.declare_parameter("hard_max_vx", 0.12)
        self.declare_parameter("hard_max_vy", 0.05)
        self.declare_parameter("hard_max_az", 0.15)
        self.declare_parameter("hard_max_speed_xy", 0.12)
        self.declare_parameter("diag_log_period_sec", 1.0)

        dog_ip = str(self.get_parameter("dog_ip").value)
        dog_port = int(self.get_parameter("dog_port").value)
        init_dog = bool(self.get_parameter("init_dog").value)
        self._send_rate_hz = max(5.0, float(self.get_parameter("send_rate_hz").value))
        self._command_timeout_sec = max(
            0.1,
            float(self.get_parameter("command_timeout_sec").value),
        )
        self._idle_stop_duration_sec = max(
            0.0,
            float(self.get_parameter("idle_stop_duration_sec").value),
        )
        self._send_combined_axes = bool(
            self.get_parameter("send_combined_axes").value
        )
        self._shutdown_stop_burst_count = max(
            1,
            int(self.get_parameter("shutdown_stop_burst_count").value),
        )
        self._shutdown_stop_burst_interval_sec = max(
            0.01,
            float(self.get_parameter("shutdown_stop_burst_interval_sec").value),
        )
        self._vx_deadband = abs(float(self.get_parameter("vx_deadband").value))
        self._vy_deadband = abs(float(self.get_parameter("vy_deadband").value))
        self._az_deadband = abs(float(self.get_parameter("az_deadband").value))
        self._hard_max_vx = abs(float(self.get_parameter("hard_max_vx").value))
        self._hard_max_vy = abs(float(self.get_parameter("hard_max_vy").value))
        self._hard_max_az = abs(float(self.get_parameter("hard_max_az").value))
        self._hard_max_speed_xy = abs(
            float(self.get_parameter("hard_max_speed_xy").value)
        )
        self._diag_log_period_sec = max(
            0.2,
            float(self.get_parameter("diag_log_period_sec").value),
        )
        self._dog_addr = (dog_ip, dog_port)

        # ── UDP socket ────────────────────────────
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(0.1)

        # ── 运行诊断计数 ────────────────────────────
        self._last_cmd_time = 0.0
        self._has_seen_cmd = False
        self._last_vx = 0.0
        self._last_vy = 0.0
        self._last_az = 0.0
        self._recv_count = 0
        self._recv_motion_count = 0
        self._recv_initial_zero_count = 0
        self._recv_invalid_count = 0
        self._send_tick_count = 0
        self._send_stale_tick_count = 0
        self._udp_simple_count = 0
        self._udp_complex_count = 0
        self._udp_error_count = 0
        self._last_recv_vx = 0.0
        self._last_recv_vy = 0.0
        self._last_recv_az = 0.0
        self._last_send_vx = 0.0
        self._last_send_vy = 0.0
        self._last_send_az = 0.0
        self._last_diag_time = time.time()
        self._last_diag_snapshot = None

        # ── 狗初始化 (心跳 + auto mode + motion mode) ──
        if init_dog:
            self._init_dog()

        # ── 订阅 /cmd_vel ─────────────────────────
        self._cmd_sub = self.create_subscription(
            Twist, "/cmd_vel", self._on_cmd_vel, 10,
        )

        # ── 固定频率输出: ZOH + heartbeat + timeout stop ──
        self._send_timer = self.create_timer(
            1.0 / self._send_rate_hz,
            self._send_held_command,
        )

        self.get_logger().info(
            f"CmdVelBridge 就绪 → {dog_ip}:{dog_port} | "
            f"init_dog={init_dog} | send_rate={self._send_rate_hz:.1f}Hz | "
            f"timeout={self._command_timeout_sec:.2f}s | "
            f"idle_stop={self._idle_stop_duration_sec:.2f}s | "
            f"combined_axes={self._send_combined_axes} | "
            f"shutdown_stop_burst={self._shutdown_stop_burst_count} | "
            f"diag_period={self._diag_log_period_sec:.1f}s"
        )
        self.get_logger().info(
            "CmdVelBridge ROS env | "
            f"ROS_DOMAIN_ID={os.environ.get('ROS_DOMAIN_ID', '<unset>')} | "
            f"RMW_IMPLEMENTATION={os.environ.get('RMW_IMPLEMENTATION', '<unset>')} | "
            f"FASTRTPS_DEFAULT_PROFILES_FILE={os.environ.get('FASTRTPS_DEFAULT_PROFILES_FILE', '<unset>')}"
        )

    # ── 狗初始化 ─────────────────────────────────

    def _init_dog(self) -> None:
        """发送初始化序列: 心跳 × 10 → auto mode → motion mode。"""
        self.get_logger().info("正在初始化狗...")
        for _ in range(10):
            self._send_simple(CMD_HEARTBEAT)
            time.sleep(0.1)
        self._send_simple(CMD_AUTO_MODE)
        time.sleep(0.5)
        self._send_simple(CMD_MOTION)
        time.sleep(0.3)
        self.get_logger().info("狗初始化完成 (auto + motion mode)")

    # ── /cmd_vel 回调 ────────────────────────────

    def _on_cmd_vel(self, msg: Twist) -> None:
        """收到速度指令后只更新保持值，实际发送由固定频率 timer 完成。"""
        vx = float(msg.linear.x)
        vy = float(msg.linear.y)
        az = float(msg.angular.z)
        self._recv_count += 1
        if not all(math.isfinite(value) for value in (vx, vy, az)):
            self._recv_invalid_count += 1
            vx = 0.0
            vy = 0.0
            az = 0.0
            self.get_logger().error("拒绝 NaN/Inf cmd_vel，锁定本周期三轴零速")
        vx = max(-self._hard_max_vx, min(self._hard_max_vx, vx))
        vy = max(-self._hard_max_vy, min(self._hard_max_vy, vy))
        az = max(-self._hard_max_az, min(self._hard_max_az, az))
        speed_xy = math.hypot(vx, vy)
        if speed_xy > self._hard_max_speed_xy > 0.0:
            scale = self._hard_max_speed_xy / speed_xy
            vx *= scale
            vy *= scale
        self._last_recv_vx = vx
        self._last_recv_vy = vy
        self._last_recv_az = az
        is_motion = (
            abs(vx) > self._vx_deadband
            or abs(vy) > self._vy_deadband
            or abs(az) > self._az_deadband
        )
        if not self._has_seen_cmd and not is_motion:
            self._recv_initial_zero_count += 1
        if is_motion:
            self._recv_motion_count += 1
        self._has_seen_cmd = True
        self._last_cmd_time = time.time()
        self._last_vx = vx
        self._last_vy = vy
        self._last_az = az
        self._maybe_log_diag(force=False)

    # ── 固定频率 ZOH 输出 ─────────────────────────

    def _send_held_command(self) -> None:
        """定频发送 heartbeat 和最近一次速度指令；超时则发送 stop。"""
        now = time.time()
        stale = (
            self._last_cmd_time <= 0.0
            or now - self._last_cmd_time > self._command_timeout_sec
        )
        if not self._has_seen_cmd:
            return

        vx = 0.0 if stale else self._last_vx
        vy = 0.0 if stale else self._last_vy
        az = 0.0 if stale else self._last_az

        # 心跳和运动指令必须从同一个 socket 发出。
        self._send_simple(CMD_HEARTBEAT)
        self._send_tick_count += 1
        if stale:
            self._send_stale_tick_count += 1
        self._last_send_vx = vx
        self._last_send_vy = vy
        self._last_send_az = az

        if self._send_combined_axes:
            self._send_combined(vx, vy, az)
        else:
            self._send_single_axis(vx, vy, az)
        self._maybe_log_diag(force=False)

    def _maybe_log_diag(self, force: bool = False) -> None:
        """按节流周期输出 ROS 接收与 UDP 发送摘要，避免逐帧刷屏。"""
        now = time.time()
        if not force and now - self._last_diag_time < self._diag_log_period_sec:
            return
        snapshot = (
            self._recv_count,
            self._recv_motion_count,
            self._recv_initial_zero_count,
            self._recv_invalid_count,
            self._send_tick_count,
            self._send_stale_tick_count,
            self._udp_simple_count,
            self._udp_complex_count,
            self._udp_error_count,
            round(self._last_recv_vx, 4),
            round(self._last_recv_vy, 4),
            round(self._last_recv_az, 4),
            round(self._last_send_vx, 4),
            round(self._last_send_vy, 4),
            round(self._last_send_az, 4),
            self._has_seen_cmd,
        )
        if not force and snapshot == self._last_diag_snapshot:
            return
        self._last_diag_time = now
        self._last_diag_snapshot = snapshot
        self.get_logger().info(
            "[diag] "
            f"recv={self._recv_count} motion={self._recv_motion_count} "
            f"initial_zero={self._recv_initial_zero_count} "
            f"invalid={self._recv_invalid_count} "
            f"send_ticks={self._send_tick_count} stale_ticks={self._send_stale_tick_count} "
            f"udp_simple={self._udp_simple_count} udp_complex={self._udp_complex_count} "
            f"udp_errors={self._udp_error_count} "
            f"last_recv=({self._last_recv_vx:.3f},{self._last_recv_vy:.3f},{self._last_recv_az:.3f}) "
            f"last_send=({self._last_send_vx:.3f},{self._last_send_vy:.3f},{self._last_send_az:.3f}) "
            f"seen_cmd={self._has_seen_cmd}"
        )

    def _send_single_axis(self, vx: float, vy: float, az: float) -> None:
        """保守模式：每周期只发一个主运动轴，避免后发覆盖导致行为不确定。"""
        # Clear every latched axis before selecting the single active one.
        self._send_full_stop()
        if abs(az) > self._az_deadband:
            self._send_complex(CODE_YAW, float(-az))
        elif abs(vx) > self._vx_deadband:
            self._send_complex(CODE_FWD, float(vx))
        elif abs(vy) > self._vy_deadband:
            self._send_complex(CODE_LAT, float(vy))

    def _send_combined(self, vx: float, vy: float, az: float) -> None:
        """按官方 transfer driver 顺序发送三个轴，完整覆盖底层速度状态。"""
        self._send_complex(CODE_FWD, 0.0 if abs(vx) <= self._vx_deadband else float(vx))
        self._send_complex(CODE_LAT, 0.0 if abs(vy) <= self._vy_deadband else float(vy))
        self._send_complex(CODE_YAW, 0.0 if abs(az) <= self._az_deadband else float(-az))

    def _send_full_stop(self) -> None:
        """发送三轴零速，避免只清掉单个运动轴。"""
        self._send_complex(CODE_FWD, 0.0)
        self._send_complex(CODE_LAT, 0.0)
        self._send_complex(CODE_YAW, 0.0)

    # ── 底层 UDP 发送 ────────────────────────────

    def _send_simple(self, code: int, p1: int = 0, p2: int = 0) -> None:
        """发送 SimpleCMD (12 bytes)。"""
        try:
            self._sock.sendto(
                struct.pack("<3i", code, p1, p2), self._dog_addr,
            )
            self._udp_simple_count += 1
        except OSError:
            self._udp_error_count += 1
            pass

    def _send_complex(self, code: int, data: float) -> None:
        """发送 MotionComplexCMD (20 bytes)。"""
        try:
            self._sock.sendto(
                struct.pack(PACK_FMT, code, 8, 1, data), self._dog_addr,
            )
            self._udp_complex_count += 1
        except OSError:
            self._udp_error_count += 1
            pass

    # ── 清理 ─────────────────────────────────────

    def destroy_node(self) -> bool:
        self._maybe_log_diag(force=True)
        self.get_logger().info("CmdVelBridge 关闭中，停狗...")
        for _ in range(self._shutdown_stop_burst_count):
            self._send_simple(CMD_HEARTBEAT)
            self._send_full_stop()
            time.sleep(self._shutdown_stop_burst_interval_sec)
        if self._sock:
            self._sock.close()
        return super().destroy_node()


# ═══════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════

def main(args=None) -> None:
    rclpy.init(args=args)
    node = CmdVelBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
