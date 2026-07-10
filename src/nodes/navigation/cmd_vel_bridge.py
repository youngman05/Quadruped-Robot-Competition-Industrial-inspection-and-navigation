#!/usr/bin/env python3
"""
cmd_vel_bridge.py — 将 Nav2 的 /cmd_vel 转成 Lite3 狗的 UDP MotionComplexCMD。

链路:
    Nav2 → /cmd_vel (Twist) → CmdVelBridge → UDP MotionComplexCMD → 狗 (192.168.1.120:43893)

设计要点:
    - 心跳 + 速度指令从同一个 UDP socket 发出（狗 SDK 要求）
    - 固定频率重发最近一次速度指令（Zero-Order Hold）
    - 默认每次只发一种运动指令（实测前更保守）
    - 角速度取反（ROS 左转为正，狗 SDK 右转为正）
    - 超过 command_timeout_sec 未收到新 /cmd_vel 时主动发 stop
"""

from __future__ import annotations

import socket
import struct
import time

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
        self.declare_parameter("init_dog", True)   # 是否自动初始化狗 (auto mode + motion mode)
        self.declare_parameter("send_rate_hz", 40.0)
        self.declare_parameter("command_timeout_sec", 0.35)
        self.declare_parameter("send_combined_axes", False)
        self.declare_parameter("vx_deadband", 0.005)
        self.declare_parameter("vy_deadband", 0.005)
        self.declare_parameter("az_deadband", 0.005)

        dog_ip = str(self.get_parameter("dog_ip").value)
        dog_port = int(self.get_parameter("dog_port").value)
        init_dog = bool(self.get_parameter("init_dog").value)
        self._send_rate_hz = max(5.0, float(self.get_parameter("send_rate_hz").value))
        self._command_timeout_sec = max(
            0.1,
            float(self.get_parameter("command_timeout_sec").value),
        )
        self._send_combined_axes = bool(
            self.get_parameter("send_combined_axes").value
        )
        self._vx_deadband = abs(float(self.get_parameter("vx_deadband").value))
        self._vy_deadband = abs(float(self.get_parameter("vy_deadband").value))
        self._az_deadband = abs(float(self.get_parameter("az_deadband").value))
        self._dog_addr = (dog_ip, dog_port)

        # ── UDP socket ────────────────────────────
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(0.1)

        # ── 狗初始化 (心跳 + auto mode + motion mode) ──
        if init_dog:
            self._init_dog()

        # ── 订阅 /cmd_vel ─────────────────────────
        self._cmd_sub = self.create_subscription(
            Twist, "/cmd_vel", self._on_cmd_vel, 10,
        )

        # ── 固定频率输出: ZOH + heartbeat + timeout stop ──
        self._last_cmd_time = 0.0
        self._last_vx = 0.0
        self._last_vy = 0.0
        self._last_az = 0.0
        self._send_timer = self.create_timer(
            1.0 / self._send_rate_hz,
            self._send_held_command,
        )

        self.get_logger().info(
            f"CmdVelBridge 就绪 → {dog_ip}:{dog_port} | "
            f"init_dog={init_dog} | send_rate={self._send_rate_hz:.1f}Hz | "
            f"timeout={self._command_timeout_sec:.2f}s | "
            f"combined_axes={self._send_combined_axes}"
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
        self._last_cmd_time = time.time()
        self._last_vx = float(msg.linear.x)
        self._last_vy = float(msg.linear.y)
        self._last_az = float(msg.angular.z)

    # ── 固定频率 ZOH 输出 ─────────────────────────

    def _send_held_command(self) -> None:
        """定频发送 heartbeat 和最近一次速度指令；超时则发送 stop。"""
        now = time.time()
        stale = (
            self._last_cmd_time <= 0.0
            or now - self._last_cmd_time > self._command_timeout_sec
        )

        vx = 0.0 if stale else self._last_vx
        vy = 0.0 if stale else self._last_vy
        az = 0.0 if stale else self._last_az

        # 心跳和运动指令必须从同一个 socket 发出。
        self._send_simple(CMD_HEARTBEAT)

        if self._send_combined_axes:
            self._send_combined(vx, vy, az)
        else:
            self._send_single_axis(vx, vy, az)

    def _send_single_axis(self, vx: float, vy: float, az: float) -> None:
        """保守模式：每周期只发一个主运动轴，避免后发覆盖导致行为不确定。"""
        if abs(az) > self._az_deadband:
            self._send_complex(CODE_YAW, float(-az))
        elif abs(vx) > self._vx_deadband:
            self._send_complex(CODE_FWD, float(vx))
        elif abs(vy) > self._vy_deadband:
            self._send_complex(CODE_LAT, float(vy))
        else:
            self._send_complex(CODE_FWD, 0.0)

    def _send_combined(self, vx: float, vy: float, az: float) -> None:
        """实验模式：按官方 transfer driver 顺序发送三个轴。"""
        self._send_complex(CODE_FWD, 0.0 if abs(vx) <= self._vx_deadband else float(vx))
        self._send_complex(CODE_LAT, 0.0 if abs(vy) <= self._vy_deadband else float(vy))
        self._send_complex(CODE_YAW, 0.0 if abs(az) <= self._az_deadband else float(-az))

    # ── 底层 UDP 发送 ────────────────────────────

    def _send_simple(self, code: int, p1: int = 0, p2: int = 0) -> None:
        """发送 SimpleCMD (12 bytes)。"""
        try:
            self._sock.sendto(
                struct.pack("<3i", code, p1, p2), self._dog_addr,
            )
        except OSError:
            pass

    def _send_complex(self, code: int, data: float) -> None:
        """发送 MotionComplexCMD (20 bytes)。"""
        try:
            self._sock.sendto(
                struct.pack(PACK_FMT, code, 8, 1, data), self._dog_addr,
            )
        except OSError:
            pass

    # ── 清理 ─────────────────────────────────────

    def destroy_node(self) -> bool:
        self.get_logger().info("CmdVelBridge 关闭中，停狗...")
        self._send_complex(CODE_FWD, 0.0)
        time.sleep(0.1)
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
