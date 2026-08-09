#!/usr/bin/env python3
# coding: utf-8

"""机器狗 task_manager 调用机械臂 API 的示例。

这里假设上游已经输出 ArmPi 机械臂基座坐标系下的目标点。
相机坐标到机械臂坐标的转换后续由独立 API 接入。
"""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARM_ROOT = PROJECT_ROOT / "arm_new"
if str(ARM_ROOT) not in sys.path:
    sys.path.insert(0, str(ARM_ROOT))

from arm_api import ArmService, ArmServiceConfig  # noqa: E402


class CompetitionTaskManager(object):
    """示例状态机。"""

    def __init__(self):
        self.arm = ArmService(
            ArmServiceConfig(
                port="/dev/ttyACM0",
                dry_run=True,   # 联调第一阶段保持 True，确认后改 False
                include_home=True,
            )
        )

    def run(self):
        abnormal_zone = self.inspect_gauges()
        target_position = self.find_red_bar_position_arm()

        if not self.grasp_bar(target_position):
            print("抓取失败：进入重试、跳过或人工保护逻辑")
            return

        self.place_to_abnormal_zone(abnormal_zone)

    def inspect_gauges(self):
        """这里接仪表识别结果，例如 A/B/C/D 哪个区域异常。"""

        return "A"

    def find_red_bar_position_arm(self):
        """这里接上游转换结果，输出机械臂基座坐标系目标点。"""

        # 示例数据：实际项目中替换成视觉/坐标转换 API 输出。
        return (0.0, 0.18, 0.06)

    def grasp_bar(self, target_position):
        """GRASP_BAR 状态里调用机械臂服务。"""

        result = self.arm.grab_from_pose(target_position, rotation_deg=0.0)
        if not result.ok:
            print("机械臂抓取异常:", result.message)
            return False

        print("机械臂抓取完成:", result.message)
        return True

    def place_to_abnormal_zone(self, abnormal_zone):
        """PLACE_TO_ABNORMAL_ZONE 状态，后续可继续扩展放置动作 API。"""

        print("准备放置到异常区域:", abnormal_zone)


if __name__ == "__main__":
    CompetitionTaskManager().run()
