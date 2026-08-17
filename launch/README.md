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
  enable_task_manager:=true \
  enable_placeholders:=true
```

---

## 启动参数一览

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `enable_gauge` | `true` | 仪表检测节点 |
| `enable_task_manager` | `false` | 任务管理状态机 |
| `enable_speech` | `false` | 语音播报（待实现） |
| `enable_placeholders` | `false` | 全部占位节点（测试用） |

---

## 架构层次

```text
感知层 →  gauge_status_node (D455 仪表)

定位层 →  cuVSLAM (Docker 容器, 不由此 launch 管理)

决策层 →  task_manager_node (状态机)
          speech_node (语音, 待实现)

执行层 →  Nav2 (导航, 待集成)
          Arm Control (机械臂, 外部)
```
