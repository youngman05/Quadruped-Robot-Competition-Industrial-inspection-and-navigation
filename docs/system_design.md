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

- 从 D455 获取 RGB-D 图像（封装 API：`src/cv/realsense_camera/`）。
- 使用 YOLOv8 实例分割工作区（`InstanceSegmentation/`）检测比赛场地物体。
- 使用 OpenCV 仪表检测模块（`src/cv/gauge_detector/`）判断指针角度、颜色区域和表计状态。
- 检测 A/B/C/D 字母、红色/绿色长条。
- 使用深度图输出目标距离或三维坐标。

第一阶段建议使用混合方案：

```text
YOLOv8 实例分割检测物体 ROI -> OpenCV 判断仪表指针落区
                                  -> 深度图计算三维坐标
```

### SLAM/VIO

- 不使用激光雷达。
- 推荐路线：NVIDIA Isaac ROS Visual SLAM / cuVSLAM。
- D455 红外双目 + IMU 作为视觉里程计输入；D455 红外投影仪在 VIO 模式下应关闭，避免散斑干扰立体匹配。
- 当前 Jetson 是 Ubuntu 20.04 / ROS2 Foxy 环境，不能直接使用最新 Isaac ROS Visual SLAM；应先在独立 Isaac ROS Humble/Jazzy 或容器环境验证。
- 当前 D455 视觉流已验证，IMU 流受 IIO 权限阻塞，需要 udev/root 权限处理后复测。
- 备选方案：VINS-Fusion、ORB-SLAM3 + IMU、Lite3 自身里程计融合。
- 输出机器人位姿和 TF，供 navigation 使用。

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
