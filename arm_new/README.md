# arm_new 工作空间

`arm_new` 是可独立迁移到 Jetson 的机械臂控制工作空间。当前主链路只处理已经转换到 ArmPi 机械臂基座坐标系下的目标点：

```text
目标点相对机械臂坐标 -> IK/动作序列 -> BusLinker 执行
```

运行时相机坐标到机械臂坐标的转换由 ROS TF 完成：项目从
`configs/transforms/static_extrinsics.yaml` 发布静态外参，机械臂节点查询
TF 后才调用本模块。离线 `FrameTransformer` API 仅保留兼容用途。

## 坐标约定

输入目标点必须是 ArmPi 机械臂基座坐标系，单位米：

```text
+Y = 机械臂正前方
+X = 横向偏移
+Z = 向上
```

不要直接把相机坐标或像素坐标传给 `grab_from_pose()`。

## Initial position

当前统一定义的 initial position 为：

```text
ID1: 502
ID2: 504
ID3: 256
ID4: 755
ID5: 636
ID6: 519
```

代码真值位于 `arm_api/common.py` 的 `INITIAL_POSITION_SERVOS`。旧 initial
position 为 `(1:200, 2:500, 3:80, 4:825, 5:625, 6:500)`，仅保留作历史记录，
不再用于生成动作。

## 运动学模型参数

当前几何 IK 使用的连杆长度如下，单位均为米：

| 参数 | 长度 | 定义 |
|---|---:|---|
| `L1` | `0.0610` | 基座高度偏置 |
| `L2` | `0.1016` | 第一段主连杆 |
| `L3` | `0.0964` | 第二段主连杆 |
| `L4` | `0.2700` | 从腕部到 TCP 的加长末端组件 |

> 备注：`L4` 已由旧模型的 `0.1665 m` 更新为 `0.2700 m`。普通位置 IK、端面姿态约束 IK、可达性判断和正运动学校验都会使用该新值。旧长度下生成的动作序列不再可用于真机；恢复真机测试时必须从 dry-run、低速和小范围动作重新验证。

## 新模型已验证的中心线可达范围

下表是当前 `L4=0.2700 m` 模型在 `x=0`、水平端面靠近、
`pre_distance=0.05 m` 条件下的纯 IK 扫描结果。`y` 为机械臂正前方距离，
单位均为米。

| TCP z | 可规划 y 范围 |
|---:|---:|
| 0.04 | 0.42 - 0.46 |
| 0.06 | 0.42 - 0.46 |
| 0.08 | 0.42 - 0.44 |
| 0.10 | 0.42 - 0.44 |
| 0.12 | 0.40 - 0.44 |
| 0.14 | 0.18 - 0.44 |
| 0.16 | 0.18 - 0.42 |

这不是完整三维工作空间：横向 `x` 偏移、夹爪旋转、安装误差、舵机实际零位和
周围碰撞都会收缩可用范围。`(0.0, 0.42, 0.15)` 是当前待实机服务验证的抓取
测试点；真实执行前仍必须核对 pulse、速度和空间干涉。

## 目录结构

```text
arm_new/
+-- README.md
+-- DEPLOY_ARM_BOARD_README.md
+-- ROBOT_INTEGRATION_README.md
+-- requirements.txt
+-- arm_api/
|   +-- __init__.py
|   +-- buslinker.py
|   +-- common.py
|   +-- posture.py
|   +-- planner.py
|   +-- planner_new.py
|   +-- protocol.py
|   +-- service.py
+-- scripts/
|   +-- face_approach_grab.py
|   +-- initialize_arm.py
+-- examples/
    +-- task_manager_arm_example.py
```

## 安装依赖

```bash
cd /home/ubuntu/arm_new
python3 -m pip install -r requirements.txt
```

`pyserial` 用于 BusLinker 串口控制。当前主链路不依赖点云处理。

## 高层 API

推荐主程序使用 `ArmService`：

```python
from arm_api import ArmService, ArmServiceConfig

arm = ArmService(
    ArmServiceConfig(
        port="/dev/ttyACM0",
        dry_run=True,
        include_home=True,
    )
)

result = arm.grab_from_pose(
    position=(0.0, 0.42, 0.15),
    rotation_deg=0.0,
)

if not result.ok:
    print("抓取失败:", result.message)
```

`dry_run=True` 时只打印动作，不打开串口真实运动。

## 只规划动作序列

```python
from arm_api import ArmGrabPlanner

planner = ArmGrabPlanner()
steps = planner.plan_grab((0.0, 0.42, 0.15), rotation_deg=20.0, include_home=True)

for step in steps:
    print(step.to_command())
```

每一步的 `servos` 是 BusLinker 执行层直接使用的 `(舵机 ID, pulse)` 序列。

## 端面靠近抓取脚本

输入一个机械臂基座坐标系下的目标点，脚本自动生成水平端面靠近路径：

```bash
python3 scripts/face_approach_grab.py 0 0.42 0.15 --steps 8
```

默认只 dry-run。确认路径和 pulse 合理后再真实执行：

```bash
python3 scripts/face_approach_grab.py 0 0.42 0.15 --execute --read-before --duration-scale 2.0
```

如果目标太近，水平姿态约束可能无解。可以先减小 `--pre-distance`，或调整目标点高度/水平距离。

## 执行动作序列

```python
from arm_api import BusLinkerExecutor

executor = BusLinkerExecutor("/dev/ttyACM0")
executor.execute_steps(steps, dry_run=True, scan_first=False)

with executor:
    executor.execute_steps(steps, dry_run=False, scan_first=True)
```

第一次真机测试必须先 dry-run，并确认舵机 ID、方向、目标点和周围环境安全。

抓取预备张开、抓取末尾闭合和放置末尾张开都不会直接跳到最终 ID1 pulse。
当前抓取张开目标为 `900`，抓取闭合目标为 `10`，放置张开目标为 `400`。
执行器会在每个包含 ID1 的步骤开始时读取当前反馈，再按
`gripper_ramp_step_pulse`（当前为 `100`）生成中间目标并逐个发送，任意相邻
命令与当前反馈的差值都不超过 `100`。若读取失败，动作返回失败，不发送
目标跳变命令。

## 固定姿态动作

`arm_api.posture` 提供不依赖 ROS 和串口的固定姿态规划：

```python
from arm_api import plan_lie_down, plan_stand_up

stand_steps = plan_stand_up()
lie_steps = plan_lie_down()
```

两个动作均只生成 ID2 至 ID6 的逐舵机步骤，ID1 夹爪保持原位。ROS 部署时
由唯一的 `arm_motion_node` 通过 `/arm/stand_up` 和 `/arm/lie_down` 服务执行，
不能再由独立脚本同时打开 `/dev/ttyACM0`。

## 直接放置测试

输入 ArmPi 基座坐标系下的 TCP 放置点，机械臂直接到位后张开夹爪。默认
dry-run，不打开串口：

```bash
python3 scripts/direct_place.py 0 0.42 0.06 --duration-scale 2.0
```

确认 pulse 和空间路径后，使用实际串口进行低速执行：

```bash
python3 scripts/direct_place.py 0 0.42 0.06 \
  --port /dev/ttyACM0 --execute --read-before --duration-scale 2.0
```

`x/y/z` 是机械臂基座坐标系下的 TCP 放置点，不是 `camera_link` 坐标。真实
视觉接入前必须先完成 camera_link 到机械臂基座的外参标定。

## 当前不包含的内容

- 不包含点云到抓取位姿估计。
- 机械臂纯 Python API 本身不读取或发布 ROS TF；该职责由 ROS 适配节点承担。
- 只保留一个轻量端面靠近抓取脚本。

后续新增坐标转换 API 后，推荐接成：

```text
目标点相对相机坐标 -> 目标点相对机械臂坐标 -> ArmService.grab_from_pose()
```
