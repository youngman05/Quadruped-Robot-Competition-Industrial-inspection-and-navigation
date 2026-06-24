# Task Manager

比赛任务状态机 — 串联巡检、播报、抓取、放置全流程。

## 节点

[`src/nodes/task_manager.py`](../nodes/task_manager.py) — `TaskManagerNode`

## 启动

```bash
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
ros2 run quadruped_robot_competition task_manager
```

详见 [src/nodes/README.md](../nodes/README.md)。

## 状态机

```
START → PASS_OBSTACLE → INSPECT_GAUGES → REPORT_STATUS
      → FIND_RED_BAR → GRASP_BAR → PLACE_TO_ABNORMAL_ZONE → FINISH
```

每阶段默认超时 120 秒，超时进入 ABORT。

## 订阅

| Topic | 消息类型 | 用途 |
|-------|----------|------|
| `/gauge/status` | String (JSON) | 仪表检测结果（使用 stable_* 字段） |
| `/yolo/detections` | String (JSON) | YOLO 目标检测 |
| `/visual_slam/status` | String | 定位状态 |

## 发布

| Topic | 消息类型 | 用途 |
|-------|----------|------|
| `/task/phase` | String | 当前阶段名 |
| `/task/status` | String (JSON) | 完整状态 |
