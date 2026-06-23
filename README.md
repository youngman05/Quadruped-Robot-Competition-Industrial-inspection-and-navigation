# Quadruped Robot Competition

## 2026-06-23 最新进展

- D455 相机 Python 封装已导入：`src/cv/realsense_camera/`，支持 RGB、深度、红外双目、IMU 接口和 cuVSLAM 预设。
- D455 输入链路已通过 Jetson 实机短测：RGB/depth、IR 双目 + depth、accel/gyro IMU 和 `RealsenseCamera.for_cuvslam()` 均 PASS；IMU IIO 权限已通过 RealSense udev rules 修复。
- Isaac ROS Visual SLAM/cuVSLAM 已在隔离的 ROS2 Humble 容器中完成 runtime 短测：RealSense ROS 发布 D455 IR/IMU topic，cuVSLAM `vo_state=1`，并输出 `/visual_slam/status`、`/visual_slam/tracking/odometry` 和 TF。
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

一键验证 D455 输入链路：

```bash
python3 scripts/realsense_cuvslam_input_test.py --seconds 2.0
```

该脚本会检查 D455 枚举、RGB/depth、IR1/IR2 + depth、accel/gyro IMU，以及 `RealsenseCamera.for_cuvslam()` 预设。

## Isaac ROS Visual SLAM / cuVSLAM runtime

当前不把 Isaac ROS/cuVSLAM 安装进 Jetson host 的 ROS2 Foxy 主环境，而是使用独立 ROS2 Humble 容器验证，避免污染已有比赛环境。

已验证环境：

```text
Jetson: Xavier NX / Ubuntu 20.04 / L4T R35.6.4 / CUDA 11.4
Host ROS: Foxy
Container ROS: Humble
Isaac ROS source: release-2.1
D455: serial 235422300321, firmware 5.17.0.10, USB 3.2
```

Jetson 侧工作区：

```bash
~/workspaces/isaac_ros-dev
```

已构建的本地 runtime 镜像：

```text
isaac_ros_cuvslam_runtime:humble-rs
```

### 依赖补齐

Jetson host 需要提供 Isaac ROS 容器挂载用的 CUDA/NVTX runtime libraries。若构建 `isaac_ros_nitros` 或 `isaac_ros_visual_slam` 时出现 `nvToolsExt.h`、`-lnvToolsExt`、`libcusolver.so.11` 缺失，安装：

```bash
sudo apt-get install -y cuda-nvtx-11-4 cuda-libraries-11-4 cuda-cupti-11-4
```

关键文件应存在：

```text
/usr/local/cuda-11.4/targets/aarch64-linux/include/nvToolsExt.h
/usr/local/cuda-11.4/targets/aarch64-linux/lib/libnvToolsExt.so
/usr/local/cuda-11.4/targets/aarch64-linux/lib/libcusolver.so.11
/usr/local/cuda-11.4/targets/aarch64-linux/lib/libcusparse.so.11
/usr/local/cuda-11.4/targets/aarch64-linux/lib/libcurand.so.10
/usr/local/cuda-11.4/targets/aarch64-linux/lib/libcufft.so.10
/usr/local/cuda-11.4/targets/aarch64-linux/lib/libcupti.so.11.4
```

### 构建结果

在 Isaac ROS workspace 内构建：

```bash
cd ~/workspaces/isaac_ros-dev
source /opt/ros/humble/setup.bash
colcon build --symlink-install \
  --packages-up-to isaac_ros_visual_slam \
  --event-handlers console_direct+ \
  --parallel-workers 3 \
  --cmake-args -DCMAKE_BUILD_TYPE=Release
```

实测构建结果：

```text
Summary: 7 packages finished
```

关键产物：

```text
install/isaac_ros_visual_slam/lib/isaac_ros_visual_slam/isaac_ros_visual_slam
install/isaac_ros_visual_slam/lib/libvisual_slam_node.so
install/isaac_ros_visual_slam/share/cuvslam/libcuvslam.so
install/isaac_ros_visual_slam/share/isaac_ros_visual_slam/launch/isaac_ros_visual_slam_realsense.launch.py
```

### RealSense ROS 输入

runtime 镜像内已安装：

```text
ros-humble-realsense2-camera
ros-humble-realsense2-camera-msgs
ros-humble-realsense2-description
```

官方 RealSense launch 参数使用：

```text
enable_infra1=true
enable_infra2=true
enable_color=false
enable_depth=false
depth_module.emitter_enabled=0
depth_module.profile=640x360x90
enable_gyro=true
enable_accel=true
gyro_fps=200
accel_fps=200
unite_imu_method=2
```

实测 RealSense ROS 输出：

```text
/camera/infra1/image_rect_raw   about 90 Hz, 640x360
/camera/infra2/image_rect_raw   about 90 Hz, 640x360
/camera/imu                     about 200 Hz
/camera/infra1/camera_info
/camera/infra2/camera_info
/tf_static
```

### cuVSLAM 启动与结果

启动命令：

```bash
cd ~/workspaces/isaac_ros-dev
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch isaac_ros_visual_slam isaac_ros_visual_slam_realsense.launch.py
```

关键日志：

```text
cuVSLAM version: 11.4
Time taken by CUVSLAM_WarmUpGPU()
Baseline is : 0.095029
left_camera_pose_imu reading from TF Tree
Use use_gpu: true
Enable IMU Fusion: true
Time taken by CUVSLAM_CreateTracker()
```

cuVSLAM 节点发布：

```text
/visual_slam/status
/visual_slam/tracking/odometry
/visual_slam/tracking/slam_path
/visual_slam/tracking/vo_pose
/tf
/tf_static
```

GPU warmup 后 20 秒采样结果：

```text
infra1: 1732
infra2: 1730
imu: 3724
status: 1739
odom: 1735
last_status.vo_state: 1
last_odom.frame_id: odom
last_odom.child_frame_id: camera_link
```

`vo_state=1` 表示 visual odometry 成功。静止短测中 odom 位姿为零属于预期结果。

### 当前限制

本次只证明 cuVSLAM runtime 能启动并持续输出 status/odom/TF，还不能等同于完整自主导航已经完成。后续仍需：

- 做 3-5 分钟手持或装车运动稳定性测试。
- 观察 image delta 超过 22ms warning 是否持续出现或导致失跟。
- 标定并发布 `base_link -> camera_link` 静态外参。
- 接入 nvblox / Nav2 / safety gate。
- 在现场安全确认前保持 `/cmd_vel` 零输出。

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

- Jetson 已验证可访问 D455，RGB/depth、IR 双目 + depth、accel/gyro IMU 和 `for_cuvslam()` 均已短测通过。
- D455 IMU IIO 权限已通过 RealSense udev rules 修复，普通用户可启动 accel/gyro。
- Jetson 已安装 OpenCV、pyrealsense2、TensorRT。
- 已迁入一个 OpenCV 仪表盘状态识别原型。
- 已导入 YOLOv8 实例分割工作区，TensorRT 部署待补齐。
- cuVSLAM runtime 已在独立 Isaac ROS Humble 容器中短测通过，能输出 `/visual_slam/status`、`/visual_slam/tracking/odometry` 和 TF；下一步是运动稳定性与导航栈集成。
- 预赛已经完成，接下来等狗。
