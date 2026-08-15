#!/usr/bin/env python3
# coding: utf-8

"""公共数据结构和换算函数。"""


class OriginalIKUnavailable(RuntimeError):
    """原 ArmPi IK 包不可用。"""


class IKNoSolution(ValueError):
    """目标点超出 IK 可达空间。"""


def clamp(value, lower=0, upper=1000):
    """把数值限制到指定范围，默认是总线舵机 pulse 范围 0..1000。"""

    return int(max(lower, min(upper, round(value))))


def pulse_to_angle(pulse):
    """把舵机 pulse 显示为 0..240 度角。

    这个角度是舵机自身控制角，不一定等于机械臂几何关节角。
    """

    return float(pulse) * 240.0 / 1000.0


def angle_to_pulse(angle_deg):
    """把 0..240 度舵机显示角换算成 pulse。"""

    return clamp(float(angle_deg) * 1000.0 / 240.0)


class MotionStep(object):
    """一条运动步骤。

    servos 使用 ((id, pulse), ...) 作为稳定接口，方便直接发给 BusLinker。
    """

    def __init__(
        self,
        name,
        coordinate,
        duration_ms,
        servos,
        ik_angles=None,
        used_pitch=None,
    ):
        self.name = str(name)
        self.coordinate = coordinate
        self.duration_ms = int(duration_ms)
        self.servos = tuple((int(servo_id), clamp(pulse)) for servo_id, pulse in servos)
        self.ik_angles = ik_angles
        self.used_pitch = used_pitch

    def servo_pulses(self):
        """返回 {舵机 ID: pulse}。"""

        return dict(self.servos)

    def servo_angles_deg(self):
        """返回 {舵机 ID: 0..240 度显示角}。"""

        return {servo_id: pulse_to_angle(pulse) for servo_id, pulse in self.servos}

    def to_command(self):
        """转成便于 JSON 化或串口执行层消费的 dict。"""

        return {
            "name": self.name,
            "duration_ms": self.duration_ms,
            "coordinate": self.coordinate,
            "servos": [
                {
                    "id": servo_id,
                    "pulse": pulse,
                    "angle_deg": pulse_to_angle(pulse),
                }
                for servo_id, pulse in self.servos
            ],
        }


def steps_to_commands(steps):
    """把 MotionStep 列表转成普通 dict 列表。"""

    return [step.to_command() for step in steps]
