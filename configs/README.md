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
