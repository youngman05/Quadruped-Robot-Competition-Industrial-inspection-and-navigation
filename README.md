# Quadruped Robot Competition

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
scripts/              环境检查、相机测试、演示脚本
src/cv/               视觉识别模块
src/slam/             VIO/SLAM 模块
src/navigation/       导航模块
src/task_manager/     比赛流程调度模块
src/speech/           中文播报模块
src/arm_control/      机械臂/夹爪控制模块
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

测试 OpenCV 仪表盘识别样例：

```bash
python3 scripts/run_gauge_sample.py
```

## 当前状态

- Jetson 已验证可访问 D455。
- Jetson 已安装 OpenCV、pyrealsense2、TensorRT。
- 已迁入一个 OpenCV 仪表盘状态识别原型。
- YOLO/TensorRT 检测链路待补齐。

