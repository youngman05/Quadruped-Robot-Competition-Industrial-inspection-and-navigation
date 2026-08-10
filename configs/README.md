# 配置文件 (configs)

项目配置按空间标定、节点行为、导航和静态 TF 分层管理。

---

## 文件一览

| 文件 | 用途 |
|------|------|
| `ros/competition_params.yaml` | 感知等共享比赛节点参数 |
| `yolo/classes.yaml` | YOLO 类别映射 |
| `camera/d455.yaml` | D455 相机流参数 |
| `navigation/` | Nav2 导航参数 |
| `transforms/static_extrinsics.yaml` | 项目拥有的静态外参（`base_link -> camera_link` 等） |
| `calibration/yolo_xyz_test_points.yaml` | D455 YOLO XYZ 标定测试点与验收阈值模板 |
| `calibration/competition_sites.yaml` | I0/I1、固定狗位姿与机械臂释放点的联合标定集合 |
| `ros/task_manager_params.yaml` | 状态机行为、超时和 ROS 接口参数 |
| `yolo/host_detection_v1.schema.json` | Host UDP bridge 转换后的 `base_link` 检测 JSON 协议 |

---

## ROS 节点参数

每个节点的 `ros__parameters` 段对应一个节点。感知节点使用
`ros/competition_params.yaml`，状态机使用 `ros/task_manager_params.yaml`，参数在
节点启动时通过 launch 文件传入。

空间标定不放在 ROS 行为参数中。固定站位和机械臂相对点统一维护在
`calibration/competition_sites.yaml`；机械臂动作参数继续由
`arm_new/config/arm_motion_params.yaml` 管理。详细规则见
`docs/state_machine_design.md` 的“参数维护方案”。

### 已配置节点

| 节点段 | 状态 |
|--------|------|
| `gauge_status_node` | ✅ 已配置 |
| `yolo_detect_node` | ✅ 已配置 |
| `task_manager_node` | ✅ 独立文件 |
| `speech_node` | ⏳ 已注释 |

### 修改参数

> **平台: 均可 (Windows 开发机编辑，Git 同步到 Jetson)**

编辑源码配置后重新执行对应 `colcon build`，再 source install 空间并重启节点。
不要直接修改 `install/*/share/` 中的副本。

### 在 Jetson 上直接用参数覆盖

```bash
# [Linux] 运行时覆盖单个参数
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
ros2 run quadruped_robot_competition task_manager \
  --ros-args -p timeout_per_phase:=60.0
```

---

## YOLO 类别映射: yolo/classes.yaml

```yaml
names:
  0: gauge
  1: A
  2: B
  3: C
  4: D
  5: red_bar
  6: green_bar
```

修改后需确保 YOLO 模型的实际类别顺序与此一致。

---

## D455 相机: camera/d455.yaml

包含 D455 的 RGB/深度/红外流分辨率和帧率配置，供相机 wrapper 使用。

---

## Navigation: navigation/

Nav2 导航参数。详见 [configs/navigation/README.md](navigation/README.md)。

---

## Static transforms: transforms/

`transforms/static_extrinsics.yaml` 是静态外参的唯一真值来源。它不包含
RealSense 内部 optical TF、机械臂关节 TF 或 `map`/`odom` 动态 TF。启动时由
`launch/static_transforms.launch.py` 使用标准 `static_transform_publisher` 发布。

详情见 [configs/transforms/README.md](transforms/README.md)。
后续 agent 的交接说明见
[docs/static_transform_config_handover.md](../docs/static_transform_config_handover.md)。
