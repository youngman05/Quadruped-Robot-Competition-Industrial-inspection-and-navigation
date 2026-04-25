# System Design

## 总体架构

```text
D455 RGB-D Camera
  -> CV
      -> YOLO detector
      -> OpenCV gauge state detector
      -> depth position estimator
  -> SLAM/VIO
  -> Navigation
  -> Task Manager
      -> Speech
      -> Arm Control
      -> Robot Control
```

## 模块职责

### CV

- 从 D455 获取 RGB-D 图像。
- 检测仪表盘、A/B/C/D 字母、红色/绿色长条。
- 对仪表盘 ROI 判断偏低、正常、偏高。
- 使用深度图输出目标距离或三维坐标。

第一阶段建议使用混合方案：

```text
YOLO 检测仪表盘 ROI -> OpenCV 判断指针落区
```

### SLAM/VIO

- 不使用激光雷达。
- 优先考虑 VIO 路线，例如 VINS-Fusion、ORB-SLAM3 + IMU，或融合机器人自身里程计。
- 输出机器人位姿，供 navigation 使用。

### Navigation

- 初赛阶段优先使用稳定方案，例如 ROS `move_base` 或厂商 SDK 的到点控制。
- 先跑通固定路线，再逐步接入动态定位和局部避障。

### Task Manager

比赛流程状态机：

```text
START
  -> PASS_OBSTACLE
  -> INSPECT_GAUGES
  -> REPORT_STATUS
  -> FIND_RED_BAR
  -> GRASP_BAR
  -> PLACE_TO_ABNORMAL_ZONE
  -> FINISH
```

### Speech

- 输出中文终端结果。
- 播报类似：“A 区域仪表盘显示偏低，状态异常”。
- 预录音频可作为离线兜底方案。

### Arm Control

- 接收目标三维坐标。
- 执行抓取、搬运、放置。
- 返回动作成功/失败状态。

