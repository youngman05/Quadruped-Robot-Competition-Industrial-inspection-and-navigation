# Quadruped Robot Competition

## 2026-06-23 最新进展

- D455 相机 Python 封装已导入：`src/cv/realsense_camera/`，支持 RGB、深度、红外双目、IMU 接口和 cuVSLAM 预设。
- cuVSLAM 方案调研完成：推荐用 D455 红外双目 + IMU 作为视觉里程计输入，再接 nvblox / Nav2；当前 Jetson 仍是 ROS2 Foxy 环境，需独立 Isaac ROS 环境验证。
- D455 当前枚举和视觉流验证通过；IR 双目和 depth 可出帧，IMU 受 Linux IIO 权限阻塞，需 udev/root 权限处理后复测。
- YOLOv8 实例分割工作区已导入：`InstanceSegmentation/`，支持图片、视频、普通摄像头和 D455 实时推理。
- Lite3_ROS 只读状态链路已打通，Jetson 能收到 Lite3 的 `/imu/data`、`/joint_states`、`/leg_odom`、`/leg_odom2`、超声波距离等状态 topic。
- D455 OpenCV 仪表识别已封装为 ROS2 只读节点：`scripts/gauge_status_node.py`。
- 节点发布：
  - `/gauge/status`：`std_msgs/msg/String`，内容是 JSON 字符串。
  - `/gauge/detected`：`std_msgs/msg/Bool`。
- 当前 `/gauge/status` 同时包含单帧识别结果和连续帧稳定判定结果。
- 目前没有向 Lite3 发布 `/cmd_vel` 运动控制命令。

## D455 仪表 ROS2 节点

在 Jetson 上启动：

```bash
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
python3 scripts/gauge_status_node.py
```

启动成功时应看到类似输出：

```text
D455 started: Intel RealSense D455, serial=...
Publishing gauge status on /gauge/status
```

另开一个终端查看 topic：

```bash
source /opt/ros/foxy/setup.bash
ros2 topic list | grep gauge
ros2 topic echo /gauge/status
```

如果只想输出通过校验的有效帧：

```bash
python3 scripts/gauge_status_node.py --ros-args -p publish_invalid:=false
```

`/gauge/status` 里重点看这些字段：

```text
detected
reason
color
level
angle
color_coverage_ratio
direction_scores
stable_detected
stable_reason
stable_count
stable_color
stable_level
stable_status
```

判断规则：

- `detected: false` 表示这一帧不可信，即使 `color` 有值也不要直接作为最终结果。
- `reason: low_color_ratio` 通常表示画面中有效彩色仪表区域太少。
- `reason: weak_color_zones` 通常表示三色区域识别不完整或置信度不足。
- `detected: true` 只表示这一帧通过当前校验。
- `stable_detected: true` 表示连续多帧都稳定识别为同一状态。
- 任务管理模块应优先使用 `stable_color`、`stable_level`、`stable_status`，不要直接用单帧 `color` 做最终决策。

## D455 相机 API

封装模块位于 `src/cv/realsense_camera/`。首次部署建议先注册项目包：

```bash
python3 -m pip install -e .
```

示例：

```python
from cv.realsense_camera import RealsenseCamera

# cuVSLAM 输入：红外双目 + IMU 接口
with RealsenseCamera.for_cuvslam() as cam:
    left_ir, right_ir = cam.get_infrared_frames()
    imu = cam.get_imu_data()

# 仪表识别输入：彩色图
with RealsenseCamera.for_gauge() as cam:
    color = cam.get_color_image()
```

注意：当前 Jetson 上 D455 视觉流已通过短测，IMU 流仍需处理 RealSense udev / IIO 权限后复测。

## YOLOv8 实例分割

实例分割工作区位于 `InstanceSegmentation/`：

```bash
cd InstanceSegmentation
pip install -r requirements.txt
python scripts/image_detect.py --model yolov8n-seg.pt --source bus.jpg --device cpu
python scripts/camera_detect.py --d455 --model yolov8n-seg.pt
```

`.pt` 权重文件不进入 Git；首次运行 Ultralytics 会下载官方模型，或将自训练权重放在本地 `InstanceSegmentation/models/` 后用 `--model models/best.pt` 指定。

## 安全边界

当前阶段以只读感知和状态订阅为主。没有现场安全确认前，不要发布非零 `/cmd_vel`。

后续如需测试运动控制，必须先确认：

- 有人现场看护机器人。
- 急停或手动接管可用。
- 机器人处在空旷安全区域。
- 只读状态 topic 正常。

2026 中国高校智能机器人创意大赛足式机器人挑战赛四足大型组项目仓库。

本仓库用于管理比赛的软件系统、部署脚本、测试流程和技术文档。目标平台是 NVIDIA Jetson Xavier NX，主要传感器是 Intel RealSense D455。

## 目标

- 使用 D455 获取 RGB-D 图像。
- 使用 YOLO 或 OpenCV 完成仪表盘、区域字母、红绿长条识别。
- 使用 VIO/SLAM 与 navigation 完成任务区域移动。
- 使用任务管理模块串联巡检、播报、抓取和放置流程。
- 使用 Git 分支和 PR 保持多人协作可追踪。

## 当前硬件

- Compute: Jetson Xavier NX
- Camera: Intel RealSense D455
- Robot: 绝影 Lite 系列四足机器人
- Optional: speaker, arm/gripper

## 目录结构

```text
docs/                 项目设计、部署、测试文档
scripts/              环境检查、D455 预览、仪表检测脚本
src/cv/
  realsense_camera/   D455 相机 Python API（含 IMU + 红外 + cuVSLAM 预设）
  gauge_detector/     OpenCV 仪表盘状态识别
  yolo_detector/      YOLO/TensorRT 检测（待实现）
src/slam/             VIO/SLAM 模块
src/navigation/       导航模块
src/task_manager/     比赛流程调度模块
src/speech/           中文播报模块
src/arm_control/      机械臂/夹爪控制模块
InstanceSegmentation/ YOLOv8 实例分割工作区（训练 + 实时推理）
configs/              相机、YOLO、导航配置
data/                 数据说明，不直接提交大数据集
models/               模型说明，不直接提交大模型
tests/                自动化和集成测试
```

## 开发原则

1. 不直接在 Jetson 上手改代码。
2. Windows/开发机上修改代码，通过 GitHub 私有仓库同步。
3. Jetson 只负责 `git pull`、构建、部署和实机测试。
4. 一个分支只做一个功能。
5. 大模型、数据集、rosbag、视频不要直接提交到 Git。

## 快速开始

在 Jetson 上检查基础环境：

```bash
bash scripts/check_jetson_env.sh
```

测试 D455 RGB-D 采集：

```bash
python3 scripts/realsense_smoke_test.py
```

测试 D455 wrapper 预览：

```bash
python3 scripts/realsense_viewer.py
```

测试 OpenCV 仪表盘识别样例：

```bash
python3 scripts/run_gauge_sample.py
```

## 当前状态

- Jetson 已验证可访问 D455，IR 双目和 depth 可短时出帧。
- D455 IMU 受 IIO 权限阻塞，需安装/生效 RealSense udev 规则或 root 权限复测。
- Jetson 已安装 OpenCV、pyrealsense2、TensorRT。
- 已迁入一个 OpenCV 仪表盘状态识别原型。
- 已导入 YOLOv8 实例分割工作区，TensorRT 部署待补齐。
- cuVSLAM 软件栈需在独立 Isaac ROS Humble/Jazzy 或容器环境验证。
- 预赛已经完成，接下来等狗。
