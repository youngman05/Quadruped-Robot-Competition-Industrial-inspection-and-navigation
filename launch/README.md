# 启动文件 (launch)

> **平台: Linux (Jetson, ROS2 Foxy)**

使用 ROS2 launch 一键启动多个节点。

---

## 前置操作

```bash
# [Linux]
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
python3 -m pip install -e .
```

---

## 主启动文件: competition.launch.py

### 启动全部已实现节点（仪表检测）

```bash
# [Linux]
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
ros2 launch launch/competition.launch.py
```

### 加上 YOLO 检测

> `enable_yolo:=true` 启动的是旧 Host 调试 YOLO，不是当前 Docker D455 YOLO 三维节点。正式 D455 链路由 Docker 内 `/d455_object_yolo_3d` 输出 UDP `19002`；Host detection bridge 尚未接入，因此不要把该开关作为当前整机部署入口。

```bash
# [Linux]
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
ros2 launch launch/competition.launch.py enable_yolo:=true
```

### Docker D455 YOLO 三维 UDP bridge

该入口接收 Docker 的 UDP `19002` 检测，校验后原样发布 `camera_link`
数据，不查询静态外参 TF。默认不会启动旧 Host YOLO，二者不能同时启用。

```bash
ros2 launch launch/yolo_udp_bridge.launch.py
# 或：ros2 launch launch/competition.launch.py enable_yolo_udp_bridge:=true
```

### 加上任务管理器

```bash
# [Linux]
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
ros2 launch launch/competition.launch.py enable_task_manager:=true
```

### 启动全部（含占位节点）

```bash
# [Linux]
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
ros2 launch launch/competition.launch.py \
  enable_yolo:=true \
  enable_task_manager:=true \
  enable_placeholders:=true
```

---

## 启动参数一览

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `enable_gauge` | `true` | 仪表检测节点 |
| `enable_yolo` | `false` | YOLO 检测节点（需 ultralytics + torch） |
| `enable_task_manager` | `false` | 任务管理状态机 |
| `enable_speech` | `false` | 语音播报（待实现） |
| `enable_placeholders` | `false` | 全部占位节点（测试用） |

---

## 架构层次

```text
感知层 →  gauge_status_node (D455 仪表)
          yolo_detect_node  (YOLO 实例分割)

定位层 →  cuVSLAM (Docker 容器, 不由此 launch 管理)

决策层 →  task_manager_node (状态机)
          speech_node (语音, 待实现)

执行层 →  Nav2 (导航, 待集成)
          Arm Control (机械臂, 外部)
```
