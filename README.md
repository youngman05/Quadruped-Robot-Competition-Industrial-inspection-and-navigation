# Quadruped Robot Competition

2026 中国高校智能机器人创意大赛 — 足式机器人挑战赛（四足大型组）项目仓库。

目标平台：NVIDIA Jetson Xavier NX (Ubuntu 20.04 / ROS2 Foxy)
主传感器：Intel RealSense D455
机器人：绝影 Lite 系列四足机器人

---

## 目录结构

```text
navi/                 导航地图 — 场地数据、预览、PGM 生成
  map/                  地图数据定义 + 渲染预览
launch/               ROS2 启动文件
configs/              参数配置 (ROS2 params / YOLO / 相机 / 导航)
  navigation/           Nav2 参数
scripts/              独立脚本 (环境检查、D455 测试、仪表检测节点)
src/
  nodes/               ROS2 节点 (task_manager, yolo_detect, gauge_status, speech)
  cv/                  视觉模块 (gauge_detector, realsense_camera, yolo_detector)
  navigation/          导航模块 (待实现)
  slam/                SLAM/VIO 模块
  task_manager/        任务调度模块
  speech/              语音播报模块
  arm_control/         机械臂控制模块
InstanceSegmentation/ YOLOv8 实例分割训练+推理工作区
docs/                 项目设计、部署、测试文档
```

---

## 2026-06-24 更新

### 任务管理状态机 ✅
- [src/nodes/task_manager.py](src/nodes/task_manager.py) 从占位实现为完整状态机
- 8 阶段流程：START → PASS_OBSTACLE → INSPECT_GAUGES → REPORT_STATUS → FIND_RED_BAR → GRASP_BAR → PLACE_TO_ABNORMAL_ZONE → FINISH
- 订阅 `/gauge/status`、`/yolo/detections`、`/visual_slam/status`
- 发布 `/task/phase`、`/task/status`
- 入口点已注册：`task_manager`，YAML 参数已配置
- 详见 [src/nodes/README.md](src/nodes/README.md)

### 导航地图方案 ✅
- [navi/map/navi_map_data.py](navi/map/navi_map_data.py) 新增巡检柜体标签面、观察位、锥桶、起始位姿数据
- [navi/map/render_navi_map_preview.py](navi/map/render_navi_map_preview.py) 重写渲染 — 柜体标签面、FOV 观察扇形、墙区斜线、锥桶位置
- `WALL_REGION_IDS` 标记 inspection_upper/lower/obstacle 为不可进入墙区
- 确定方案：Nav2 + PGM 栅格地图 (0.025m/px)，cuVSLAM 定位
- 详见 [navi/map/README.md](navi/map/README.md)

### 巡检柜体理解确认 ✅
- 上柜体 (1500,1500)：底面 + 右侧面贴标签
- 下柜体 (1500,4000)：顶面 + 右侧面贴标签
- 狗需 3 个观察位：①中间走廊(看上下面) ②a上中通道(看上柜右面) ②b下中通道(看下柜右面)
- 哪面贴字母哪面贴仪表由裁判随机决定

### 其他
- `verify_yolo.py` 从根目录移到 [scripts/verify_yolo.py](scripts/verify_yolo.py)，路径改为项目相对路径

---

## 2026-06-23 及之前进展

- D455 相机 Python 封装：`src/cv/realsense_camera/`，RGB、深度、红外双目、IMU、cuVSLAM 预设
- D455 输入链路已通过 Jetson 实机短测（RGB/depth、IR 双目+深度、accel/gyro IMU）
- IMU IIO 权限已通过 RealSense udev rules 修复
- Isaac ROS Visual SLAM/cuVSLAM 在独立 ROS2 Humble 容器中短测通过，输出 `/visual_slam/status`、`/visual_slam/tracking/odometry`、TF
- YOLOv8 实例分割工作区：`InstanceSegmentation/`，支持图片/视频/摄像头/D455 实时推理
- Lite3_ROS 只读状态链路已打通（`/imu/data`、`/joint_states`、`/leg_odom` 等）
- D455 OpenCV 仪表识别 ROS2 节点：`scripts/gauge_status_node.py`
- 发布 `/gauge/status`（JSON）和 `/gauge/detected`（Bool）
- 预赛已完成

---

## Linux (Jetson) 完整部署指南

> **平台: Linux (Jetson Xavier NX, Ubuntu 20.04, ROS2 Foxy)**
> 以下命令从零开始部署，可直接复制逐行执行。

### 前置条件

```bash
# [Linux] 确认系统环境
cat /etc/nv_tegra_release          # 确认是 Jetson Xavier NX
python3 --version                   # 应为 3.8+
ros2 --version                      # 应为 Foxy
```

### 1. 克隆项目

```bash
# [Linux]
cd ~
git clone https://github.com/<your-org>/quadruped-robot-competition.git
cd quadruped-robot-competition
```

### 2. 安装 Python 依赖

```bash
# [Linux]
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
python3 -m pip install --upgrade pip
python3 -m pip install -e .                # 注册包入口点
python3 -m pip install numpy opencv-python pyrealsense2 pypdf
python3 -m pip install Pillow              # 地图预览渲染（可选用）
```

### 3. YOLO 依赖（可选，仅需 YOLO 节点时安装）

```bash
# [Linux]
cd ~/quadruped-robot-competition
python3 -m pip install ultralytics torch torchvision
python3 scripts/verify_yolo.py             # 验证 YOLO 安装
```

### 4. 检查基础环境

```bash
# [Linux]
cd ~/quadruped-robot-competition
bash scripts/check_jetson_env.sh
```

### 5. 测试 D455 相机

```bash
# [Linux]
cd ~/quadruped-robot-competition
python3 scripts/realsense_smoke_test.py            # 冒烟测试
python3 scripts/realsense_cuvslam_input_test.py    # cuVSLAM 输入链路检查
```

### 6. 启动系统

详见各子模块 README（均已标注平台）：
- [src/nodes/README.md](src/nodes/README.md) — 各节点单独启动
- [launch/README.md](launch/README.md) — 一键启动全系统
- [navi/map/README.md](navi/map/README.md) — 生成导航地图

---

## 安全边界

当前阶段以只读感知和状态订阅为主。**没有现场安全确认前，不要发布非零 `/cmd_vel`。**

后续如需测试运动控制，必须先确认：
- 有人现场看护机器人
- 急停或手动接管可用
- 机器人处在空旷安全区域
- 只读状态 topic 正常

---

## 开发原则

1. Windows/开发机上修改代码，通过 GitHub 私有仓库同步
2. Jetson 只负责 `git pull`、部署和实机测试
3. 一个分支只做一个功能
4. 大模型、数据集、rosbag、视频不提交到 Git
5. 每个子模块有独立 README，方便维护
