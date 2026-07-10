# 四足机器人国赛系统技术栈

本仓库面向 **2026 年中国高校智能机器人创意大赛 足式机器人挑战赛 四足机器人大型组**，目标是在绝影 Lite 系列四足机器人和 Jetson Xavier NX 级别 AI 主机上，完成国赛线下挑战中的自主避障、巡检识别、语音播报、长条识别与导航搬运流程。

当前 README 只覆盖本仓库已经承担或正在集成的部分：视觉、SLAM、导航、任务管理和语音播报接口。机械臂抓取硬件与控制逻辑暂不在本仓库实现范围内，只保留任务状态机中的接口位置。

## 比赛任务理解

国赛线下挑战由三类任务组成：

| 任务 | 比赛要求 | 本仓库对应模块 |
|---|---|---|
| 避障任务 | 从出发区自主穿越障碍区域，避开随机放置的 2 个锥形桶 | D455 + YOLO / 深度点云 + Nav2 local costmap |
| 巡检识别 | 自主前往检测区域，识别 A/B/C/D 区域与仪表盘状态，并进行语音播报 | YOLO 字母/目标检测 + OpenCV 仪表识别 + task_manager + speech |
| 长条抓取任务 | 找到红色异常长条，搬运到异常仪表对应的 A/B/C/D 放置区 | YOLO 红/绿长条检测 + Nav2 到点；机械臂控制另行接入 |

比赛规则约束：

- 禁止使用激光雷达。
- AI 主机算力不可高于 Jetson Xavier NX。
- 可加装相机、扬声器、AI 主机和一个机械臂。
- 线下挑战中需要全程自主完成。
- 仪表盘颜色语义：
  - 黄色：偏低，异常
  - 绿色：正常，正常
  - 红色：偏高，异常
- 若没有语音播报但终端输出正确，巡检识别得分减半。

## 总体架构

```text
Intel RealSense D455
  ├─ RGB 图像
  │   ├─ OpenCV 仪表盘识别 -> /gauge/status
  │   └─ YOLOv8 实例分割  -> /yolo/detections
  ├─ Depth 图像
  │   └─ depth_publisher -> PointCloud2 -> Nav2 costmap
  └─ IR 双目 + IMU
      └─ Isaac ROS Visual SLAM / cuVSLAM -> odom / TF

cuVSLAM 定位
  -> cuvslam_bridge
  -> /odom + odom -> base_link

Nav2
  -> map_server / planner_server / controller_server
  -> NavigateToPose action
  -> /cmd_vel

Task Manager
  -> 按比赛阶段调用导航
  -> 汇总仪表、YOLO、SLAM 状态
  -> 发布 /speech/text
  -> 预留机械臂抓取/放置反馈接口
```

系统分层：

| 层级 | 技术路线 | 当前状态 |
|---|---|---|
| 相机与传感器 | Intel RealSense D455，RGB / Depth / IR stereo / IMU | 已有 Python 封装和输入检查脚本 |
| SLAM / 定位 | NVIDIA Isaac ROS Visual SLAM / cuVSLAM，D455 IR 双目 + IMU | 已跑通容器启动、topic/RViz、初步 loop metrics；仍在调精度和 TF 语义 |
| 导航 | ROS2 Nav2，PGM 静态地图 + D455 点云局部避障 | 参数、地图、launch 和节点已建；需继续实车联调 |
| 目标识别 | YOLOv8 实例分割 | 已有训练/推理工作区和 ROS2 publisher；类别映射仍需统一 |
| 仪表识别 | OpenCV 传统视觉，Hough 圆/线 + HSV 颜色判定 | 已实现并接入 ROS2 `/gauge/status` |
| 任务管理 | ROS2 状态机 | 已实现主流程和导航客户端调用 |
| 语音播报 | `/speech/text` 接口，TTS 节点占位 | 接口已有，实际 TTS 待实现 |
| 机械臂 | 外部抓取系统 | 本仓库暂不实现 |

## 技术栈

### 运行平台

- Jetson Xavier NX / Ubuntu 20.04 / L4T 35.x
- Python 3.8
- ROS2 Foxy 作为主机比赛系统环境
- Isaac ROS Humble 容器运行 cuVSLAM
- Intel RealSense D455

相关文件：

- `docs/deployment_jetson.md`
- `requirements-jetson.txt`
- `scripts/tools/check_jetson_env.sh`
- `src/cv/realsense_camera/`

### 相机封装

D455 由 `src/cv/realsense_camera/` 封装，提供三类常用预设：

| 预设 | 输入流 | 用途 |
|---|---|---|
| `for_gauge()` | RGB | OpenCV 仪表盘识别 |
| `for_yolo()` | RGB + aligned depth | YOLO 检测和目标距离估计 |
| `for_cuvslam()` | IR1 + IR2 + IMU，关闭 projector | cuVSLAM 视觉惯性定位 |

cuVSLAM 使用红外双目时需要关闭 D455 红外投影器，避免散斑干扰立体视觉跟踪。

### cuVSLAM / SLAM

本项目导航定位主线是 **NVIDIA Isaac ROS Visual SLAM / cuVSLAM**：

```text
D455 IR stereo + IMU
  -> Isaac ROS Visual SLAM / cuVSLAM
  -> /visual_slam/status
  -> /visual_slam/tracking/odometry
  -> /visual_slam/tracking/vo_path
  -> /visual_slam/tracking/slam_path
  -> /tf
```

仓库内相关文件：

- `scripts/start_cuvslam_rviz_gui.sh`
- `scripts/cuvslam_loop_metrics_recorder.py`
- `scripts/camera/realsense_cuvslam_input_test.py`
- `src/nodes/navigation/cuvslam_bridge.py`
- `src/slam/README.md`

当前已知状态：

- D455 RGB/depth/IR/IMU 输入链路已验证过。
- Isaac ROS Visual SLAM / cuVSLAM 已能在 Humble 容器中启动。
- RViz/topic 可视化链路已打通。
- 已有 loop metrics recorder，用于记录 `odometry`、`vo_path`、`slam_path` 的路径长度和闭合误差。
- 最新 L1 记录显示，当前阻塞点不是启动，而是比赛级定位精度和 TF 语义：
  - 最近一次回环里 odometry 约 `37.303 m` 路径，闭合误差约 `2.719 m`，不能直接作为比赛稳定定位基线。
  - 当前 cuVSLAM 曾以 `base_frame=camera_link` 输出，且缺少可靠的 `base_link -> camera_link` 静态外参。
  - 下一步应修正 recorder 的 primary source 选择、补齐 base_link/camera_link 外参入口，再做固定路线 A/B 测试。

目标 TF 链路：

```text
map -> odom -> base_link -> camera_link -> camera_infra*
```

其中：

- `map -> odom`：由初始位姿或定位校正给出。
- `odom -> base_link`：由 cuVSLAM 通过桥接节点输出给 Nav2。
- `base_link -> camera_link`：由实测相机安装外参静态发布。

### Nav2 导航

导航主线是 **Nav2 + PGM 静态地图 + D455 深度点云局部避障**。

仓库内相关文件：

- `launch/navigation.launch.py`
- `configs/navigation/nav2_params.yaml`
- `navi/map/navi_map_data.py`
- `navi/map/generate_nav2_map.py`
- `navi/map/competition_field.yaml`
- `navi/map/competition_field.pgm`
- `src/nodes/navigation/navigation_client.py`
- `src/nodes/navigation/depth_publisher.py`
- `src/nodes/navigation/initial_pose_publisher.py`

Nav2 配置要点：

| 模块 | 当前选择 |
|---|---|
| 地图 | `navi/map/competition_field.pgm` |
| 定位 | cuVSLAM，不使用 AMCL |
| 全局规划器 | NavFn，`use_astar: true` |
| 局部控制器 | DWB |
| 局部避障 | D455 depth -> PointCloud2 -> VoxelLayer（第一轮先验证静态地图+DWB闭环） |
| 机器人 footprint | 约 `1.0 m x 0.5 m` |

导航任务点定义在 `navigation_client.py` 和 `navi/map/navi_map_data.py` 中，包括：

- `start`
- `obstacle_entry`
- `obstacle_exit`
- `pos1_middle`
- `pos1_middle_turned`
- `pos2a_upper_right`
- `pos2b_lower_right`
- `grab_area`
- `placement_A/B/C/D`

### YOLO 实例分割

YOLO 用于国赛中的语义目标识别：

- 锥桶 / obstacle：避障任务中的障碍物识别。
- 红/绿长条：抓取任务中区分异常/正常长条。
- A/B/C/D 字母和仪表 ROI：巡检任务中辅助把仪表状态与区域字母对应起来。
- 物块识别：后续抓取流程中的目标候选输入。

仓库内相关文件：

- `InstanceSegmentation/`
- `src/cv/yolo_detector/`
- `src/nodes/perception/yolo_detect_publisher.py`
- `configs/yolo/classes.yaml`
- `scripts/cv/verify_yolo.py`

当前注意点：

- `InstanceSegmentation/projects/combined/README.md` 描述的 combined 模型类别为 `red / green / obstacle`。
- `configs/yolo/classes.yaml` 当前写的是 `gauge / A / B / C / D / red_bar / green_bar`。
- `src/nodes/perception/yolo_detect_publisher.py` 中的注释也需要和实际模型类别进一步统一。

因此 README 中把 YOLO 定位为“实例分割工作区和 ROS2 publisher 已存在，但比赛最终类别映射仍需统一验证”。

### OpenCV 仪表盘识别

仪表盘状态识别采用传统 OpenCV，不依赖深度学习。

仓库内相关文件：

- `src/cv/gauge_detector/gauge_detector.py`
- `src/cv/gauge_detector/live_validation.py`
- `src/nodes/perception/gauge_status.py`
- `scripts/camera/realsense_gauge_live.py`
- `scripts/cv/run_gauge_sample.py`

算法流程：

```text
RGB 图像
  -> CLAHE 增强 / 双边滤波 / 高斯平滑
  -> HoughCircles 定位表盘圆
  -> HoughLinesP 或暗色像素质心估计指针方向
  -> 沿指针方向在刻度弧带采样 HSV 颜色
  -> yellow / green / red
  -> 偏低 / 正常 / 偏高
  -> 异常 / 正常
```

ROS2 输出：

| Topic | 类型 | 说明 |
|---|---|---|
| `/gauge/status` | `std_msgs/String` JSON | 仪表检测完整状态 |
| `/gauge/detected` | `std_msgs/Bool` | 单帧是否通过校验 |

下游任务管理应优先使用 `stable_*` 字段：

- `stable_detected`
- `stable_color`
- `stable_level`
- `stable_status`
- `stable_angle`

### 任务管理与语音播报

比赛流程由 `TaskManagerNode` 串联。

仓库内相关文件：

- `src/nodes/decision/task_manager.py`
- `src/nodes/decision/speech.py`
- `configs/ros/competition_params.yaml`
- `launch/competition.launch.py`

当前状态机：

```text
START
  -> PASS_OBSTACLE
  -> INSPECT_GAUGES
  -> FIND_RED_BAR
  -> GRASP_BAR
  -> PLACE_TO_ABNORMAL_ZONE
  -> FINISH
```

状态机订阅：

| Topic | 用途 |
|---|---|
| `/gauge/status` | 获取仪表稳定状态 |
| `/yolo/detections` | 获取仪表/字母/红条/绿条/障碍物检测 |
| `/visual_slam/status` | 判断 SLAM 跟踪状态 |

状态机发布：

| Topic | 用途 |
|---|---|
| `/task/phase` | 当前比赛阶段 |
| `/task/status` | 完整 JSON 状态 |
| `/speech/text` | 需要播报的中文文本 |

语音节点目前是占位实现。比赛可行路线有两种：

1. 离线 TTS：订阅 `/speech/text` 后实时合成。
2. 预录音频片段：把“A 区域”“偏低”“状态异常”等片段拼接播放。

## 目录结构

```text
configs/
  camera/                 D455 相机参数
  navigation/             Nav2 参数
  ros/                    比赛节点统一参数
  yolo/                   YOLO 类别映射

docs/
  deployment_jetson.md    Jetson 部署记录
  system_design.md        系统架构笔记
  test_checklist.md       测试清单

InstanceSegmentation/     YOLOv8 实例分割训练与推理工作区

launch/
  competition.launch.py   比赛总启动入口
  navigation.launch.py    Nav2 导航启动入口

navi/
  map/                    场地地图、航点、PGM 生成

scripts/
  camera/                 D455 相机测试脚本
  cv/                     CV/YOLO 测试脚本
  tools/                  Jetson/Nav2 环境脚本
  start_cuvslam_rviz_gui.sh
  cuvslam_loop_metrics_recorder.py

src/
  cv/                     D455、OpenCV 仪表、YOLO 推理模块
  nodes/
    perception/           gauge + YOLO publisher
    navigation/           cuVSLAM bridge + Nav2 helper nodes
    decision/             task_manager + speech placeholder
  slam/                   SLAM/VIO 文档入口
  speech/                 语音模块规划
  arm_control/            机械臂接口规划
```

## 典型启动顺序

### 1. 安装本仓库 Python 包

```bash
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
python3 -m pip install -e .
```

### 2. 检查 Jetson / D455 环境

```bash
bash scripts/tools/check_jetson_env.sh
python3 scripts/camera/realsense_cuvslam_input_test.py --seconds 2.0
```

### 3. 启动 cuVSLAM RViz / loop metrics

从 Jetson 桌面、VNC 或 NoMachine 终端运行：

```bash
bash scripts/start_cuvslam_rviz_gui.sh
```

无 RViz 烟测：

```bash
bash scripts/start_cuvslam_rviz_gui.sh --no-rviz --skip-input-test
```

重点查看：

- `/visual_slam/status`
- `/visual_slam/tracking/odometry`
- `/visual_slam/tracking/vo_path`
- `/visual_slam/tracking/slam_path`
- `loop_metrics_latest.txt`
- `launch.log` 中的 `Visual tracking is lost` 和 frame delta warning

### 4. 启动导航栈

```bash
source /opt/ros/foxy/setup.bash
ros2 launch launch/navigation.launch.py
```

完整比赛入口：

```bash
source /opt/ros/foxy/setup.bash
ros2 launch launch/competition.launch.py \
  enable_yolo:=true \
  enable_task_manager:=true \
  enable_navigation:=true
```

### 5. 单模块测试

仪表检测：

```bash
ros2 run quadruped_robot_competition gauge_status_publisher
ros2 topic echo /gauge/status
```

YOLO 检测：

```bash
python3 scripts/cv/verify_yolo.py
ros2 run quadruped_robot_competition yolo_detect_publisher
ros2 topic echo /yolo/detections
```

任务管理：

```bash
ros2 run quadruped_robot_competition task_manager
ros2 topic echo /task/status
```

## 当前最重要的 SLAM 下一步

根据 L1 记录，当前 cuVSLAM 已经从“启动链路调试”转入“比赛级定位稳定性/精度调试”。下一步优先级：

1. 修正 `scripts/cuvslam_loop_metrics_recorder.py`：
   - 明确输出 `primary_source`
   - 在 `slam_path/vo_path` 静态但 odometry 移动时给出提示
   - 输出 `frame_id` / `child_frame_id`
2. 修正 `scripts/start_cuvslam_rviz_gui.sh`：
   - 显式支持 `CUVSLAM_BASE_FRAME`
   - 加入可配置 `base_link -> camera_link` 静态外参
   - 显式设置 localization/mapping、TF 发布和地面机器人相关参数
3. 测量 D455 安装外参：
   - `x/y/z`，单位 m
   - `roll/pitch/yaw`，单位 rad 或 deg
4. 在 Jetson 上做固定路线 A/B 测试：
   - closure error
   - closure ratio
   - delta warning/min
   - `vo_state`
   - tracking lost count
   - CPU/GPU 负载
5. 选定比赛默认 profile 和启动命令。

## 当前工程风险

| 风险 | 影响 | 处理方式 |
|---|---|---|
| cuVSLAM 输出仍可能是 camera pose 而非 robot base pose | Nav2 控制会把相机位置当机器人位置 | 必须补 `base_link -> camera_link` 外参和 frame 检查 |
| loop metrics 仍需修正 primary source 选择 | 会误判回环结果 | 先修 recorder，再用固定路线复测 |
| YOLO 类别映射存在两套描述 | task_manager 可能解析不到红条/字母/障碍 | 统一训练模型、`classes.yaml` 和 publisher class_name |
| 语音节点未实现 | 巡检识别语音得分会受影响 | 先做 `/speech/text` 到离线 TTS 或预录音频 |
| 机械臂未接入 | 长条抓取闭环未完成 | 本仓只保留状态机接口，等待机械臂系统对接 |
| ROS2 topic/QoS/TF 名称不一致 | 节点看似启动但数据不流动 | 所有联调必须检查 `ros2 topic list/info` 和 TF tree |

## 代码入口索引

| 目标 | 入口 |
|---|---|
| 比赛总启动 | `launch/competition.launch.py` |
| Nav2 启动 | `launch/navigation.launch.py` |
| Nav2 参数 | `configs/navigation/nav2_params.yaml` |
| 场地地图定义 | `navi/map/navi_map_data.py` |
| cuVSLAM RViz 启动 | `scripts/start_cuvslam_rviz_gui.sh` |
| cuVSLAM 指标记录 | `scripts/cuvslam_loop_metrics_recorder.py` |
| cuVSLAM -> Nav2 桥接 | `src/nodes/navigation/cuvslam_bridge.py` |
| D455 深度发布 | `src/nodes/navigation/depth_publisher.py` |
| 导航客户端 | `src/nodes/navigation/navigation_client.py` |
| YOLO ROS2 节点 | `src/nodes/perception/yolo_detect_publisher.py` |
| 仪表 ROS2 节点 | `src/nodes/perception/gauge_status.py` |
| OpenCV 仪表算法 | `src/cv/gauge_detector/gauge_detector.py` |
| D455 相机封装 | `src/cv/realsense_camera/camera.py` |
| 任务状态机 | `src/nodes/decision/task_manager.py` |
| 语音占位节点 | `src/nodes/decision/speech.py` |

## 推荐阅读顺序

1. `2026年中国高校智能机器人创意大赛（四足大型组）(2).pdf`
2. `navi/README.md`
3. `configs/navigation/README.md`
4. `src/nodes/README.md`
5. `src/cv/README.md`
6. `docs/system_design.md`
7. `docs/test_checklist.md`
