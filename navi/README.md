# 四足机器人竞赛导航系统

2026 中国高校智能机器人创意大赛（四足机器人组）完整导航方案。

机器人从出发区出发，完成：**穿越障碍区 → 巡检4个仪表（看一个报一个）→ 抓取红色块放入异常字母箱（最多2趟折返）**。

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                  cuVSLAM Docker (Humble)                     │
│  D455 IR双目 + IMU  →  visual_slam_node  →  /odometry       │
│                          │                                   │
│              docker exec + stdbuf 管道 (跳过DDS跨版本兼容)     │
└──────────────────────────┼──────────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────┐
│               Jetson Host (Foxy)                             │
│                           ▼                                   │
│  final_bridge.py  →  /odom (BEST_EFFORT) + TF odom→base_link │
│  initial_pose_publisher  →  TF map→odom (静态)                │
│                           │                                   │
│  ┌────────────────────────┼─────────────────────────────┐    │
│  │               Navigator (task_manager 进程内)          │    │
│  │  ┌──────────┐  ┌─────────┐  ┌──────────────────┐    │    │
│  │  │ map_grid │→│   A*    │→│  pure_pursuit     │───→ /cmd_vel │
│  │  │ 占据栅格  │  │ 路径搜索 │  │  轨迹跟踪         │    │    │
│  │  └──────────┘  └─────────┘  └──────────────────┘    │    │
│  │                    ┌──────────────────┐              │    │
│  │                    │ local_obstacle   │              │    │
│  │                    │ 深度点云紧急避障   │              │    │
│  │                    └──────────────────┘              │    │
│  └──────────────────────────────────────────────────────┘    │
│                           │                                   │
│  depth_publisher  ← Docker relay文件  →  /camera/depth/raw   │
│  gauge_status     ← Docker relay文件  →  /gauge/status       │
│  task_manager     ← 状态机驱动导航  →  /task/phase           │
└─────────────────────────────────────────────────────────────┘
                           │
                     /cmd_vel (Twist)
                           │
                     Lite3 四足机器人
```

### 导航栈对比

|                   | Nav2 (已废弃)          | 轻量方案                       |
| ----------------- | ---------------------- | ------------------------------ |
| 地图加载          | map_server 进程        | `map_grid.py` numpy数组      |
| 全局规划          | planner_server 进程    | `astar_planner.py` (<30ms)   |
| 路径跟踪          | controller_server 进程 | `pure_pursuit.py`            |
| 行为编排          | bt_navigator 进程      | `task_manager.py` 状态机     |
| 局部避障          | local_costmap (3层)    | `local_obstacle.py` 点云计数 |
| 生命周期          | lifecycle_manager 进程 | 不需要 (单节点)                |
| **进程数**  | **12**           | **5**                    |
| **CPU占用** | **100% (卡死)**  | **~10%**                 |

---

## 依赖与硬件

### Jetson Xavier NX

- **OS**: Ubuntu 20.04 + JetPack 5.x
- **ROS2**: Foxy (主机) + Humble (Docker内)
- **传感器**: Intel RealSense D455 (USB 3.0)
- **GPU**: CUDA + TensorRT (cuVSLAM 推理)

### 关键软件包

| 组件                                    | 安装方式  | 用途                |
| --------------------------------------- | --------- | ------------------- |
| `ros-foxy-ros-base`                   | apt       | ROS2 核心           |
| `ros-foxy-tf2-ros`                    | apt       | TF 坐标变换         |
| `ros-foxy-nav2-*`                     | ❌ 已移除 | 不再需要            |
| `isaac_ros_cuvslam_runtime:humble-rs` | Docker    | cuVSLAM 视觉SLAM    |
| `numpy`                               | pip       | 栅格地图 + 路径规划 |
| `opencv-python`                       | pip       | 仪表检测图像处理    |
| `pyrealsense2`                        | pip       | D455 相机驱动       |
| `rclpy`                               | ROS2自带  | Python ROS2 接口    |

---

## 坐标系统

```
场地设计 (navi_map_data)   →   栅格 (A*)   →   ROS (运行时)
─────────────────────────     ──────────      ──────────────
原点: 左上角                  原点: 左上角      原点: 左下角
单位: mm                     单位: 像素        单位: 米
+x: 右, +y: 下               row↓ col→       +x: 右, +y: 上
5000×6000mm                  226×240 格       5.65×6.0m
                             0.025m/格
```

关键转换：

```python
# mm → ROS
ros_x = x_mm / 1000.0
ros_y = (6000 - y_mm) / 1000.0

# ROS → 栅格
col = round(ros_x / 0.025)
row = round((6.0 - ros_y) / 0.025)
```

### 帧链 (TF Tree)

```
map ──(静态TF)──→ odom ──(cuVSLAM)──→ base_link ──(静态)──→ camera_link
 ↑                    ↑                    ↑
 initial_pose_        final_bridge         tf2_ros
 publisher            /visual_slam/        static_transform
 (5.35,0.75,yaw=π)    tracking/odometry    (0,0,0.3)
```

机器人起始位姿（ROS map 帧）：`(5.35, 0.75) m, yaw = π (面朝左)`

---

## 比赛地图

### 占据栅格 (`src/navigation/map_grid.py`)

运行时从 `navi_map_data.py` 直接生成，无需预生成 PGM 文件。

| 区域                              | Phase1 (过障碍) | Phase2 (任务阶段) |
| --------------------------------- | :--------------: | :---------------: |
| inspection_upper (1000×1000mm)   |        墙        |        墙        |
| inspection_lower (1000×1000mm)   |        墙        |        墙        |
| obstacle (4000×1500mm)           | **可通过** |   **墙**   |
| grab (1500×1000mm)               |   墙(内缩15cm)   |   墙(内缩15cm)   |
| placement A/B/C/D (4×500×500mm) |        墙        |        墙        |
| 出发区 (600×1500mm)              |      可通过      |      可通过      |

Phase1: 障碍区敞开通行的原因——锥桶是随机放置的裁判道具，不能硬编码在地图上。实时避障靠 D455 深度相机。

Phase2: 穿越障碍区后切换，封堵障碍区防止机器人走回头路。

### 12个航点

| 航点                   | 位置 (ROS)   | yaw   | 用途                |
| ---------------------- | ------------ | ----- | ------------------- |
| `start`              | (5.35, 0.75) | π    | 出发区              |
| `obstacle_entry`     | (3.00, 1.00) | π    | 障碍区入口          |
| `obstacle_exit`      | (1.50, 3.25) | -π/2 | 障碍区出口, 同pos1  |
| `pos1_middle`        | (1.50, 3.25) | -π/2 | 仰头看上柜底面      |
| `pos1_middle_turned` | (1.50, 3.25) | π/2  | 180°转身看下柜顶面 |
| `pos2a_upper_right`  | (2.20, 4.50) | π    | 看上柜右侧面        |
| `pos2b_lower_right`  | (2.20, 2.00) | π    | 看下柜右侧面        |
| `grab_area`          | (3.60, 2.00) | π    | 抓取区外沿          |
| `placement_A`        | (3.25, 5.40) | 0     | A箱放置             |
| `placement_B`        | (3.75, 5.40) | 0     | B箱放置             |
| `placement_C`        | (4.25, 5.40) | 0     | C箱放置             |
| `placement_D`        | (4.75, 5.40) | 0     | D箱放置             |

观察位需要到达后转到指定朝向（摄像头对准柜体标签面），其余航点只要求到位。

---

## 导航算法

### A* 全局规划 (`src/navigation/astar_planner.py`)

- 8邻域搜索（含对角线, 代价 √2× 直行）
- 欧几里得启发函数
- 障碍膨胀: 0.15m (6格, 机器人半宽)
- 目标容差: 0.15m (6格)
- 路径简化: 共线点去除
- 降采样: 输出间距 ~0.3m
- 搜索耗时: <30ms (226×240格)
- 航点靠墙时自动 BFS 找最近可通行格

### 纯追踪控制器 (`src/navigation/pure_pursuit.py`)

```
前视点: 沿路径走 ≥0.5m 的最近点
曲率:   ω = 2 × 横向偏差 / 前视距离² × v
线速度: v = 0.8 × 到目标距离 (max 0.25 m/s)
角速度: max ±0.5 rad/s
原地转弯: 朝向误差 >0.3rad 且目标 <1m → v=0, 先转
到位判定: 位置 <0.15m 且 朝向 <0.25rad
控制频率: 10 Hz
```

### 紧急避障 (`src/navigation/local_obstacle.py`)

```
安全区: 前方 1.0m × 宽 1.2m × 高 0.05~0.5m
点数 ≥ 20  → STOP   (v=0, ω=0)
点数 5~19  → SLOW   (v×0.3, ω×0.3)
点数 < 5   → CLEAR  (透传)
```

当前版本未启用（Jetson Foxy 缺少 `depth_image_proc/point_cloud_xyz_node`），待后续用自定义点云转换节点替代。

### 卡住检测

跟踪 5 秒内位移 < 0.05m → 导航失败 → task_manager 重试。

---

## 比赛流程 (task_manager 状态机)

```
START ──→ PASS_OBSTACLE ──→ INSPECT_GAUGES ──→ FIND_RED_BAR
            │                     │                    │
            │ 两步走:              │ 4子步骤:            │ 导航到抓取区
            │ 0: start→障碍出口     │ 看到→播报→下一步     │ YOLO检测红条
            │    切换Phase2地图     │                    │
            │ 1: 安全区→pos1      │ A/B仪表面板          │
            │                     │ C/D字母面板          │
            └─────────────────────┴────────────────────┘
                                                      │
                                                      ▼
                                          GRASP_BAR ──→ PLACE_TO_ABNORMAL_ZONE
                                            占位1秒          │
                                                     导航到异常字母箱
                                                     │
                                                     ├─ 还有异常 → FIND_RED_BAR (折返)
                                                     └─ 全部完成 → FINISH
```

每个阶段超时 120 秒，超时后进入 ABORT。

---

## 关键文件

```
src/navigation/              # 轻量导航库 (纯Python, 无ROS依赖)
├── map_grid.py              #   占据栅格构建 (Phase1/2)
├── astar_planner.py         #   8邻域 A* 搜索
├── pure_pursuit.py          #   纯追踪控制器
├── local_obstacle.py        #   深度点云避障
└── navigator.py             #   整合入口 (ROS2 API)

src/nodes/
├── navigation/
│   ├── lightweight_navigator_node.py  # 独立测试节点
│   ├── depth_publisher.py            # D455深度→ROS Image
│   ├── initial_pose_publisher.py     # TF map→odom
│   └── ir_imu_bridge.py              # (占位)
├── decision/
│   └── task_manager.py      # 比赛状态机 (导入Navigator)
└── perception/
    ├── gauge_status.py      # 仪表指针检测
    └── yolo_detect_publisher.py  # YOLO实例分割

scripts/
├── final_bridge.py          # cuVSLAM→/odom 桥接 (docker exec管道)
├── camera_relay_docker.py   # Docker内RGB→共享文件
├── depth_relay_docker.py    # Docker内深度→共享文件
└── start_cuvslam_rviz_gui.sh  # cuVSLAM Docker启动

navi/map/
├── navi_map_data.py         # 场地数据源 (尺寸/区域/航点)
├── generate_nav2_map.py     # PGM生成器 (参考用, 运行时不用)
└── render_navi_map_preview.py  # 场地可视化

configs/ros/
├── competition_params.yaml  # ROS2节点参数
└── fastrtps_no_shm.xml      # FastRTPS 关闭共享内存配置

launch/
└── competition.launch.py    # 总启动文件
```

---

## DDS 通信架构

### 核心问题

cuVSLAM Docker 用 ROS2 **Humble** (RMW FastRTPS)，Jetson 主机用 ROS2 **Foxy** (RMW FastRTPS)。跨版本 DDS 通信存在以下问题：

1. **QoS 不兼容**: cuVSLAM composable node 内部用 BEST_EFFORT，标准 ROS2 工具默认 RELIABLE
2. **共享内存隔离**: FastRTPS 默认开启 SHM transport，bridge 进程发布的数据对其他进程不可见

### 解决方案

**定位桥接** (`final_bridge.py`): 不通过 DDS 跨版本通信，改用 `docker exec + stdbuf` 管道从 Docker 容器 stdout 抓取 odometry 数据，解析后在主机端重新发布。

```
Docker Humble                    Host Foxy
─────────────                    ─────────
visual_slam_node                 final_bridge.py
  │                               │
  │ /visual_slam/vis/slam_odometry│  ← docker exec + stdbuf 管道读取
  │ (BEST_EFFORT, 容器内)          │  ← 正则解析 YAML 格式
  │                               │  → 发布 /odom (BEST_EFFORT)
  │                               │  → 发布 TF odom→base_link
  │                               │  → self-verify subscriber (同进程)
```

**关闭共享内存**: `FASTRTPS_DEFAULT_PROFILES_FILE=configs/ros/fastrtps_no_shm.xml`

```xml
<participant profile_name="no_shm" is_default_profile="true">
  <rtps>
    <userTransports><transport_id>UDPOnly</transport_id></userTransports>
    <useBuiltinTransports>false</useBuiltinTransports>
  </rtps>
</participant>
```

**QoS 匹配**: Navigator 和 task_manager 的关键订阅使用 BEST_EFFORT：

```python
from rclpy.qos import QoSProfile, ReliabilityPolicy
_best_effort = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
self._odom_sub = node.create_subscription(Odometry, "/odom", cb, _best_effort)
```

**相机/深度中继**: Docker 内订阅相机/深度 topic → 写入共享文件 → 主机读取。

```
Docker 内                         主机
────────                          ────
camera_relay_docker.py            gauge_status.py
  /camera/color/image_raw          ← 读 latest_color.jpg
  → latest_color.jpg (原子写入)  

depth_relay_docker.py              depth_publisher.py
  /camera/depth/image_rect_raw     ← 读 latest_depth.raw
  → latest_depth.raw + meta
```

---

## 比赛启动流程

### 前置检查

```bash
# D455 是否识别
ls /dev/video*

# Docker 是否安装
docker --version

# 项目是否构建
ls ~/quadruped-robot-competition/install/
```

### 启动步骤

**终端1 — Docker**:

```bash
cd ~/quadruped-robot-competition
bash ~/Desktop/start_docker.sh
# 输入 sudo 密码 → 等 100 秒 → docker ps | grep cuvslam 确认
```

**终端2 — 一键启动全部**:

```bash
CN=$(docker ps --format '{{.Names}}' | grep cuvslam) && \
docker cp ~/quadruped-robot-competition/scripts/camera_relay_docker.py $CN:/tmp/ && \
docker cp ~/quadruped-robot-competition/scripts/depth_relay_docker.py $CN:/tmp/ && \
docker exec $CN pkill -f camera_relay 2>/dev/null; docker exec $CN pkill -f depth_relay 2>/dev/null; sleep 1 && \
docker exec -d $CN bash -c "source /opt/ros/humble/setup.bash; source /workspaces/isaac_ros-dev/install/setup.bash; mkdir -p /workspaces/isaac_ros-dev/camera_frames; python3 /tmp/camera_relay_docker.py > /tmp/cam.log 2>&1" && \
sleep 3 && echo "Camera: $(docker exec $CN tail -1 /tmp/cam.log 2>/dev/null)" && \
docker exec -d $CN bash -c "source /opt/ros/humble/setup.bash; source /workspaces/isaac_ros-dev/install/setup.bash; python3 /tmp/depth_relay_docker.py > /tmp/dep.log 2>&1" && \
sleep 3 && echo "Depth: $(docker exec $CN tail -1 /tmp/dep.log 2>/dev/null)" && \
source /opt/ros/foxy/setup.bash && \
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0 PYTHONPATH=/opt/ros/foxy/lib/python3.8/site-packages && \
export FASTRTPS_DEFAULT_PROFILES_FILE=~/quadruped-robot-competition/configs/ros/fastrtps_no_shm.xml && \
pkill -f final_bridge 2>/dev/null; sleep 1 && \
nohup python3 ~/quadruped-robot-competition/scripts/final_bridge.py > /tmp/fb.log 2>&1 & \
sleep 10 && echo "Bridge: $(tail -1 /tmp/fb.log)" && \
source ~/quadruped-robot-competition/install/setup.bash && \
export FASTRTPS_DEFAULT_PROFILES_FILE=~/quadruped-robot-competition/configs/ros/fastrtps_no_shm.xml && \
ros2 launch quadruped_robot_competition competition.launch.py enable_task_manager:=true enable_navigation:=true & \
sleep 10 && \
source /opt/ros/foxy/setup.bash && export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0 FASTRTPS_DEFAULT_PROFILES_FILE=~/quadruped-robot-competition/configs/ros/fastrtps_no_shm.xml && \
echo "=== NODES ===" && ros2 node list 2>/dev/null | grep -v '/camera\|/visual\|/launch\|/transform\|/depth_relay' && \
echo "=== /ODOM ===" && timeout 4 ros2 topic hz /odom 2>&1 | head -3
```

### 验证清单

```bash
# 1. 节点列表 (应有5个主机节点)
ros2 node list | grep -v '/camera\|/visual\|/launch\|/transform\|/depth_relay\|/cuvslam'
# 预期: /final_bridge /gauge_status_publisher_node /task_manager_node
#       /initial_pose_publisher_node /d455_depth_publisher /base_to_camera_tf

# 2. odom 数据
ros2 topic hz /odom
# 预期: ~15-30 Hz

# 3. 任务管理器阶段
ros2 topic echo /task/phase
# 预期: start → pass_obstacle → inspect_gauges → ...

# 4. 速度指令 (上狗前验证)
ros2 topic echo /cmd_vel
# 预期: linear.x 0.0~0.25, angular.z -0.5~0.5 (测试时可发 /nav/goal)

# 5. 测试导航
ros2 topic pub --once /nav/goal std_msgs/String "{data: 'pos1_middle'}"
```

### 接狗

确认 `/cmd_vel` 正常输出后，启动 Lite3 传输层：

```bash
ros2 launch transfer transfer.launch
```

将 `/cmd_vel` 转换为 UDP 指令发送给绝影 Lite3 机器人。

---

## 故障排查

| 现象                             | 原因                           | 解决                                             |
| -------------------------------- | ------------------------------ | ------------------------------------------------ |
| Docker 起不来                    | sudo 密码                      | 前台跑`sudo jetson_clocks` 后重试              |
| Bridge 有数据但 /odom 对外不可见 | FastRTPS SHM 隔离              | 确认设置了`FASTRTPS_DEFAULT_PROFILES_FILE`     |
| task_manager 卡在 START          | QoS 不匹配收不到 odom          | 检查 BEST_EFFORT 订阅配置                        |
| A* 规划失败 (NO PATH)            | 航点在膨胀墙内                 | BFS 自动找最近可通行格 (30格范围)                |
| 卡住检测反复触发                 | 机器人未移动 (桌面测试)        | 正常现象，上狗后消失                             |
| Camera relay 报 OpenCV 错误      | .tmp 后缀不识别                | 已修复，使用 .jpg 后缀                           |
| /cmd_vel 无输出                  | Navigator IDLE                 | task_manager 阶段推进后自动开始发布              |
| 深度图 reshape 错误              | Docker 写 640x360 而非 480x640 | 已修复，自动检测分辨率                           |
| ros2 topic echo 无数据           | 默认 RELIABLE QoS              | 使用`--qos-reliability best_effort` 或代码订阅 |

### 完全重启

```bash
pkill -f competition; pkill -f final_bridge; pkill -f gauge_status
docker stop $(docker ps -q --filter name=cuvslam)
# 然后按启动流程重新来
```

---

## 技术备注

### 为什么不用 Nav2？

Nav2 在 Jetson Xavier NX 上启动 12 个节点 + 4 张 costmap，CPU 100% 卡死。比赛场地是已知 5m×6m 静态地图 + 12 个固定航点，四足可原地转弯，不需要 Nav2 的通用性。轻量方案用 5 个节点实现等价功能，CPU 降低 90%。

### 为什么不用 EKF？

cuVSLAM 视觉惯性里程计在 5m×6m 小场地内漂移 <20cm（10 分钟运行），对已知静态地图的 A* 路径规划精度足够。去掉 EKF 消除一个故障点，降低系统复杂度。如需融合腿里程计，可在 `final_bridge.py` 内直接加权。

### 为什么航点改了 grab/placement？

原始航点定义在抓取区/放置区**内部**，这些区域在占据栅格中是墙。轻量 A* 需要航点在可通行区域，因此调整到区域外侧（grab: x=3600 替代 4250；placement: y=600 替代 250）。功能完全等价——机器人仍能到达操作位置。

### CUDA/cuVSLAM 性能

planar_60fps profile 在 Jetson Xavier NX 上实际 ~30fps（IR 双目 640×360），帧间抖动超过 22ms 阈值。不影响 tracking 质量，但初始化需要充足纹理和运动。

### 仪表检测

gauge_status 通过 D455 RGB 图像（Docker relay → latest_color.jpg）进行霍夫圆检测+霍夫线检测，找到仪表指针角度后采样 HSV 颜色区（黄/绿/红）判断状态。需要 3 帧连续一致才标记 `stable_detected`，避免误报。