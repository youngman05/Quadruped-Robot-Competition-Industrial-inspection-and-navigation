# 配置文件 (configs)

所有 ROS2 节点参数集中管理。

---

## 文件一览

| 文件 | 用途 |
|------|------|
| `ros/competition_params.yaml` | 所有 ROS2 节点参数（主配置） |
| `yolo/classes.yaml` | YOLO 类别映射 |
| `camera/d455.yaml` | D455 相机流参数 |
| `navigation/` | Nav2 导航参数 |
| `transforms/static_extrinsics.yaml` | 项目拥有的静态外参（`base_link -> camera_link` 等） |
| `calibration/yolo_xyz_test_points.yaml` | D455 YOLO XYZ 标定测试点与验收阈值模板 |
| `yolo/host_detection_v1.schema.json` | Host UDP bridge 透传的 `camera_link` 检测 JSON 协议 |

---

## 主配置文件: ros/competition_params.yaml

每个节点的 `ros__parameters` 段对应一个节点。参数在节点启动时通过 launch 文件传入。

### 已配置节点

| 节点段 | 状态 |
|--------|------|
| `gauge_status_node` | ✅ 已配置 |
| `yolo_detect_node` | ✅ 已配置 |
| `task_manager_node` | ✅ 已配置 |
| `speech_node` | ⏳ 已注释 |

### 修改参数

> **平台: 均可 (Windows 开发机编辑，Git 同步到 Jetson)**

编辑 `configs/ros/competition_params.yaml` 后重新启动节点即可，无需重新编译。

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
