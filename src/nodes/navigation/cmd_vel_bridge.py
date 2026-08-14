#!/usr/bin/env python3
"""
cmd_vel_bridge.py — 将 Nav2 RPP 的 /cmd_vel 转成 Lite3 狗的 UDP MotionComplexCMD。

链路:
    Nav2 RPP → /cmd_vel (Twist) → CmdVelBridge → UDP MotionComplexCMD → 狗 (192.168.1.120:43893)

设计要点:
    - 心跳 + 速度指令从同一个 UDP socket 发出（狗 SDK 要求）
    - 每次只发一种运动指令（狗固件: 最后一个 MotionComplexCMD 覆盖前面的）
    - 角速度取反（ROS 左转为正，狗 SDK 右转为正）
    - 20Hz 发布，远快于狗 250ms 超时阈值
"""

from __future__ import annotations

import socket
import struct
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist

from nodes.navigation.cmd_vel_bridge_core import (
    STOP_MOTION_COMMAND,
    select_motion_command,
)

# ── 常量 (与 motion_controller.py / Jetson2Motion.cpp 一致) ──
DOG_IP = "192.168.1.120"
DOG_PORT = 43893

CMD_HEARTBEAT = 0x21040001
CMD_AUTO_MODE = 0x21010C03
CMD_MOTION    = 0x21010D06

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

        dog_ip = str(self.get_parameter("dog_ip").value)
        dog_port = int(self.get_parameter("dog_port").value)
        init_dog = bool(self.get_parameter("init_dog").value)
        self._dog_addr = (dog_ip, dog_port)
        # 零 Twist 不包含轴信息。记录最后一个实际运动轴，停车时给同一轴发送 0.0。
        self._last_motion_code = STOP_MOTION_COMMAND[0]

        # ── UDP socket ────────────────────────────
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(0.1)

        # ── 狗初始化 (心跳 + auto mode + motion mode) ──
        if init_dog:
            self._init_dog()

        # ── 心跳定时器 (10Hz, 快于狗 2Hz 要求) ──
        self._hb_timer = self.create_timer(0.1, self._send_heartbeat)

        # ── 订阅 /cmd_vel ─────────────────────────
        self._cmd_sub = self.create_subscription(
            Twist, "/cmd_vel", self._on_cmd_vel, 10,
        )

        # ── 看门狗: 超过 0.5s 没收 /cmd_vel → 自动停狗 ──
        self._last_cmd_time = time.time()
        self._watchdog_timer = self.create_timer(0.1, self._check_watchdog)

        self.get_logger().info(
            f"CmdVelBridge 就绪 → {dog_ip}:{dog_port} | "
            f"init_dog={init_dog}"
        )

    # ── 狗初始化 ─────────────────────────────────

    def _init_dog(self) -> None:
        """Enter SDK motion mode and clear stale velocity channels before use."""
        self.get_logger().info("正在初始化狗...")
        for _ in range(10):
            self._send_simple(CMD_HEARTBEAT)
            time.sleep(0.1)
        self._send_simple(CMD_AUTO_MODE)
        self._heartbeat_for(0.6, 0.1)
        self._send_simple(CMD_MOTION)
        self._heartbeat_for(0.6, 0.1)
        self._send_zero_velocity_for(0.8, 0.05)
        self.get_logger().info("狗初始化完成 (auto + motion mode)")

    def _heartbeat_for(self, duration_s: float, period_s: float) -> None:
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            self._send_simple(CMD_HEARTBEAT)
            time.sleep(period_s)

    def _send_zero_velocity_for(self, duration_s: float, period_s: float) -> None:
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            self._send_simple(CMD_HEARTBEAT)
            self._stop_motion()
            time.sleep(period_s)

    # ── /cmd_vel 回调 ────────────────────────────

    def _on_cmd_vel(self, msg: Twist) -> None:
        """收到 RPP 速度指令 → 转成 UDP 包发给狗。"""
        self._last_cmd_time = time.time()

        vx = msg.linear.x
        vy = msg.linear.y
        az = msg.angular.z   # ROS 约定: 左转为正

        # 心跳 (同 socket — 狗 SDK 要求心跳和运动同一来源)
        self._send_simple(CMD_HEARTBEAT)

        # 每周期只发送一个运动轴，优先级保持 yaw、前进、横移。
        motion_command = select_motion_command(vx, vy, az)
        if motion_command != STOP_MOTION_COMMAND:
            self._last_motion_code = motion_command[0]
            self._send_complex(*motion_command)
        else:
            self._stop_motion()

    # ── 看门狗 ───────────────────────────────────

    def _send_heartbeat(self) -> None:
        """定时心跳 (10Hz)。"""
        self._send_simple(CMD_HEARTBEAT)

    def _check_watchdog(self) -> None:
        """如果超过 0.6s 没收 /cmd_vel，主动停狗。"""
        if time.time() - self._last_cmd_time > 0.6:
            self._stop_motion()

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

    def _stop_motion(self) -> None:
        """给最后一个实际运动轴发送零值，避免其他轴继续保持上一速度。"""
        self._send_complex(self._last_motion_code, 0.0)

    # ── 清理 ─────────────────────────────────────

    def destroy_node(self) -> bool:
        self.get_logger().info("CmdVelBridge 关闭中，停狗...")
        self._stop_motion()
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
