#!/usr/bin/env python3
# coding: utf-8

"""面向机器狗主程序的机械臂服务层。

本工作空间只接收 ArmPi 机械臂基座坐标系下的目标点：

目标点相对机械臂坐标 -> IK/动作序列 -> BusLinker 执行。

相机坐标到机械臂坐标的转换后续由独立 API 提供，不在这里耦合。
"""

from .buslinker import BusLinkerExecutor
from .common import INITIAL_POSITION_SERVOS, MotionStep
from .planner import ArmGrabPlanner


DEFAULT_HOME_SERVOS = INITIAL_POSITION_SERVOS


class ArmServiceConfig(object):
    """ArmService 配置。

    dry_run 默认为 True，避免主程序误触发真实运动。
    """

    def __init__(
        self,
        port="/dev/ttyACM0",
        baud=115200,
        dry_run=True,
        scan_first=True,
        include_home=True,
        pause_s=0.2,
    ):
        self.port = port
        self.baud = int(baud)
        self.dry_run = bool(dry_run)
        self.scan_first = bool(scan_first)
        self.include_home = bool(include_home)
        self.pause_s = float(pause_s)


class ArmServiceResult(object):
    """ArmService 调用结果。"""

    def __init__(self, ok, message="", steps=None):
        self.ok = bool(ok)
        self.message = message
        self.steps = list(steps or [])

    def to_dict(self):
        return {
            "ok": self.ok,
            "message": self.message,
            "steps": [step.to_command() for step in self.steps],
        }


def make_home_step(duration_ms=1500):
    """生成当前标定的 ArmPi initial position。"""

    return MotionStep("home_from_sorting_py", None, duration_ms, DEFAULT_HOME_SERVOS)


def make_gripper_smoke_test_steps(center=200, delta=20, duration_ms=600):
    """生成只动夹爪的一组小幅测试动作。"""

    center = int(center)
    delta = abs(int(delta))
    return [
        MotionStep("gripper_test_open", None, duration_ms, ((1, center + delta),)),
        MotionStep("gripper_test_close", None, duration_ms, ((1, center - delta),)),
        MotionStep("gripper_test_back", None, duration_ms, ((1, center),)),
    ]


class ArmService(object):
    """给 task_manager 调用的机械臂服务。

    常用方法：
    - plan_from_pose(position, rotation_deg): 已知机械臂基座坐标时只规划
    - grab_from_pose(position, rotation_deg): 已知机械臂基座坐标时规划并执行
    - execute_steps(steps): 执行动作序列
    """

    def __init__(self, config=None, planner=None, executor=None):
        self.config = config or ArmServiceConfig()
        self.planner = planner or ArmGrabPlanner()
        self.executor = executor or BusLinkerExecutor(self.config.port, self.config.baud)

    def plan_from_pose(self, position, rotation_deg=0.0, include_home=None):
        """ArmPi 基座坐标系抓取点 -> 抓取动作序列，不执行。"""

        if include_home is None:
            include_home = self.config.include_home
        steps = self.planner.plan_grab(position, rotation_deg=rotation_deg, include_home=include_home)
        return ArmServiceResult(True, "planned", steps=steps)

    def execute_steps(self, steps, dry_run=None, scan_first=None):
        """执行或 dry-run 一组动作序列。"""

        if dry_run is None:
            dry_run = self.config.dry_run
        if scan_first is None:
            scan_first = self.config.scan_first

        if dry_run:
            self.executor.execute_steps(steps, dry_run=True, scan_first=False, pause_s=self.config.pause_s)
            return ArmServiceResult(True, "dry-run finished", steps=steps)

        with self.executor:
            self.executor.execute_steps(
                steps,
                dry_run=False,
                scan_first=scan_first,
                pause_s=self.config.pause_s,
            )
        return ArmServiceResult(True, "motion finished", steps=steps)

    def grab_from_pose(self, position, rotation_deg=0.0, include_home=None, dry_run=None):
        """已知 ArmPi 基座坐标系抓取点时，直接规划并执行。"""

        try:
            planned = self.plan_from_pose(position, rotation_deg=rotation_deg, include_home=include_home)
            executed = self.execute_steps(planned.steps, dry_run=dry_run)
            return ArmServiceResult(executed.ok, executed.message, steps=planned.steps)
        except Exception as exc:
            return ArmServiceResult(False, str(exc))

    def smoke_test_gripper(self, dry_run=None):
        """只动 1 号夹爪的小幅测试动作。"""

        return self.execute_steps(make_gripper_smoke_test_steps(), dry_run=dry_run, scan_first=True)

    def go_home(self, dry_run=None):
        """移动到原 ArmPi 稳定初始姿态。"""

        return self.execute_steps([make_home_step()], dry_run=dry_run, scan_first=True)
