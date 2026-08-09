#!/usr/bin/env python3
# coding: utf-8

"""BusLinker 执行层。

输入 MotionStep，按步骤发送 55 55 总线舵机指令。
"""

import time

from .common import pulse_to_angle
from .protocol import move_to_position, read_position, scan_ids


class SerialUnavailable(RuntimeError):
    """串口库不可用或串口打不开。"""


class BusLinkerExecutor(object):
    """BusLinker 串口执行器。"""

    def __init__(self, port="/dev/ttyACM0", baud=115200, timeout=0):
        self.port = port
        self.baud = int(baud)
        self.timeout = timeout
        self.ser = None

    def open(self):
        """打开串口。"""

        if self.ser is not None:
            return self
        try:
            import serial
            from serial import SerialException
        except ModuleNotFoundError:
            raise SerialUnavailable("缺少 pyserial，请执行：python3 -m pip install pyserial") from None

        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
        except SerialException as exc:
            raise SerialUnavailable("无法打开串口 {} @ {}：{}".format(self.port, self.baud, exc)) from None
        return self

    def close(self):
        """关闭串口。"""

        if self.ser is not None:
            self.ser.close()
            self.ser = None

    def __enter__(self):
        return self.open()

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def require_open(self):
        if self.ser is None:
            self.open()

    def scan_servos(self, start=1, end=6, retries=3, verbose=True):
        """扫描总线上的舵机 ID。"""

        self.require_open()
        return scan_ids(self.ser, start, end, retries, verbose=verbose)

    def require_servos_online(self, expected=(1, 2, 3, 4, 5, 6), retries=3):
        """确认期望的舵机都在线。"""

        expected = tuple(int(x) for x in expected)
        found = self.scan_servos(min(expected), max(expected), retries, verbose=True)
        missing = [servo_id for servo_id in expected if servo_id not in found]
        if missing:
            raise RuntimeError("舵机 ID 缺失：found={} missing={}".format(found, missing))
        return found

    def read_positions(self, servo_ids=(1, 2, 3, 4, 5, 6)):
        """读取多个舵机当前位置。"""

        self.require_open()
        return {int(servo_id): read_position(self.ser, int(servo_id)) for servo_id in servo_ids}

    def execute_step(self, step, dry_run=True, pause_s=0.2):
        """执行一个 MotionStep。"""

        if dry_run:
            print_step(step, prefix="dry-run")
            return

        self.require_open()
        print_step(step, prefix="send")
        for servo_id, pulse in step.servos:
            move_to_position(self.ser, servo_id, pulse, step.duration_ms)
        time.sleep(step.duration_ms / 1000.0 + float(pause_s))

    def execute_steps(self, steps, dry_run=True, pause_s=0.2, scan_first=True):
        """按顺序执行动作序列。"""

        if scan_first and not dry_run:
            self.require_servos_online()
        for step in steps:
            self.execute_step(step, dry_run=dry_run, pause_s=pause_s)


def print_step(step, prefix="step"):
    """打印一条运动命令，便于 dry-run 人工核对。"""

    print("{}: {} duration={}ms".format(prefix, step.name, step.duration_ms))
    if step.coordinate is not None:
        print("  xyz=({:.4f}, {:.4f}, {:.4f}) m".format(*step.coordinate))
    for servo_id, pulse in step.servos:
        print("  ID{} -> {} pulse / {:.1f} deg".format(servo_id, pulse, pulse_to_angle(pulse)))
