# 机器狗主程序调用 arm_new

`arm_new` 当前只接收 ArmPi 机械臂基座坐标系下的目标点。ROS 接入时，视觉
模块通过 TF（由 `configs/transforms/static_extrinsics.yaml` 发布）先完成：

```text
目标点相对相机坐标 -> 目标点相对机械臂坐标
```

然后再调用机械臂服务。

## 推荐部署结构

```text
/home/ubuntu/competition_ws/
+-- arm_new/
+-- quadruped-robot-competition-main/
```

## 最小调用代码

在机器狗项目主程序里加入：

```python
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PROJECT_ROOT.parent
ARM_ROOT = WORKSPACE_ROOT / "arm_new"
sys.path.insert(0, str(ARM_ROOT))

from arm_api import ArmService, ArmServiceConfig


arm = ArmService(
    ArmServiceConfig(
        port="/dev/ttyACM0",
        dry_run=True,
        include_home=True,
    )
)
```

在 `GRASP_BAR` 状态：

```python
target_arm = (0.0, 0.42, 0.06)  # 单位 m，ArmPi 机械臂基座坐标系
result = arm.grab_from_pose(target_arm, rotation_deg=0.0)

if not result.ok:
    print("机械臂抓取失败:", result.message)
else:
    print("机械臂抓取完成:", result.message)
```

## 输入要求

```text
shape: (3,) 或长度为 3 的 tuple/list
单位：米
坐标系：ArmPi 机械臂基座坐标系
+Y：机械臂正前方
+X：横向偏移
+Z：向上
```

不要把 D455 相机坐标、像素坐标或整幅点云直接传给 `grab_from_pose()`。

## 联调顺序

```text
1. dry_run=True，确认主程序能走到 GRASP_BAR
2. grab_from_pose(..., dry_run=True)，确认 IK 有解和动作序列合理
3. smoke_test_gripper(dry_run=False)，确认 BusLinker 链路通
4. go_home(dry_run=False)，确认舵机 ID 和方向正确
5. grab_from_pose(..., dry_run=False)，低速小范围真机验证
6. 验证 `camera_link -> arm_base_link` TF，并完成至少三个已知 TCP 点测试
```

## 安全注意

- 没扫到 1..6 号舵机时不要真实执行。
- `pulse` 是主控制量，范围是 `0..1000`；不要把几何角直接发给 BusLinker。
- 第一次真实运动时，手要放在电源开关附近，异常立即断电。
