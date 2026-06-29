# 导航系统 (navi)

比赛机器人的**导航大脑**——地图生成、定位融合、路径规划、深度避障、比赛状态机联动。

---

## 你要解决什么问题？

机器人从**出发区**（右下角）出发，完成三件事：

```
出发 ──→ ① 穿越障碍区（D455 实时避锥桶）
        ② 巡检 4 个仪表（两柜体, 看一个报一个）
        ③ 抓取异常区红色块, 放到对应字母箱（折返两趟）
```

**导航系统回答三个问题：**

| 问题           | 谁来解决          | 怎么做                          |
| -------------- | ----------------- | ------------------------------- |
| 世界长什么样？ | 两张 PGM 地图     | Phase1 可穿障碍区 / Phase2 封堵 |
| 我在哪？       | cuVSLAM           | D455 红外双目 + IMU 视觉里程计   |
| 怎么走到目标？ | Nav2 + A\* + D455 | 全局路径 + 实时避障             |

---

## 三层架构

```
┌─ 地图层 ───────────────────────────────────────────────────┐
│ navi_map_data.py → generate_nav2_map.py → phase1/2.pgm    │
│   (场地数据)         (PGM生成器)           (栅格地图×2)    │
└──────────────────────────┬─────────────────────────────────┘
                           │ map_server 加载 phase1
┌─ 节点层 ─────────────────┼─────────────────────────────────┐
│  定位: cuVSLAM → cuvslam_bridge → /odom + TF               │
│  感知: depth_publisher → pointcloud → Nav2 local_costmap   │
│  规划: Nav2 (A* planner + RPP controller)                  │
│  对齐: initial_pose_publisher (map→odom TF)                │
│  对齐: initial_pose_publisher (map→odom TF)                │
│                           │                                │
│  输出: /cmd_vel → Lite3_ROS → UDP → 狗运动主机             │
└───────────────────────────┼────────────────────────────────┘
                            │
┌─ 决策层 ─────────────────┼─────────────────────────────────┐
│  navigation_client ←→ Nav2 action server                   │
│  task_manager: 状态机 → 切换地图 → 航点导航 → 折返循环     │
└────────────────────────────────────────────────────────────┘
```

---

## 核心概念（给没学过导航的人）

### 代价地图 (Costmap) — "哪里能走"

场地切为 2.5cm × 2.5cm 格子，每格有一个**代价分数**：

```
  0  — 不能走（墙、柜体）
  1~254 — 能走但代价不同（越靠障碍越高）
  255 — 完全自由
```

机器人视为 **1m × 0.5m 长方形**，找不碰任何障碍的最短路径。

### A\* 算法 — "怎么绕开墙最快到目标"

> 你在迷宫里找路。朝大致方向走，遇死胡同退一步换方向。A\* 同时评两条信息：
>
> - **已经走了多远** (g)
> - **离目标还有多远** (h)
>   两者加起来最小的方向优先。

四足能原地转向 → 不需要 Hybrid-A\*（汽车模型），A\* 足够。

### 全局规划 vs 局部控制

```
全局规划 (Planner / A*)      局部控制 (Controller / RPP)
┌──────────────────┐         ┌──────────────────┐
│ 静态地图上画路线   │  ──→   │ 沿路线走 + 实时   │
│ 例: 绕过检测区墙   │        │ 躲开锥桶/D455探测  │
└──────────────────┘         └──────────────────┘
```

- **NavFn (A\*)** — 全局规划器
- **RegulatedPurePursuit** — 控制器，追前方 0.5m 路径点
- **TEB** — 可选高级控制器（需编译），同时优化轨迹+速度+避障

### cuVSLAM 定位 — "看路就知道自己走了多远"

```
D455 红外双目 + IMU → cuVSLAM (Docker) → /visual_slam/tracking/odometry
                                                    │
                                         cuvslam_bridge → /odom + TF
```

纯视觉里程计，不依赖腿里程计。比赛场地 5×6m，光照可控，漂移可接受。

---

## 目录结构

```
navi/                                    ← 导航模块根
├── README.md                            ← 本文档
├── navigation_client.py                 ← 导航 API + 12 航点
├── map/
│   ├── navi_map_data.py                 ← ★ 场地数据唯一源
│   ├── generate_nav2_map.py             ← PGM 生成器(双地图)
│   ├── competition_field_phase1.pgm     ← 越障用: 障碍区可通行
│   ├── competition_field_phase1.yaml    ← phase1 元数据
│   ├── competition_field_phase2.pgm     ← 任务用: 障碍区封堵
│   ├── competition_field_phase2.yaml    ← phase2 元数据
│   ├── render_navi_map_preview.py       ← 场地预览渲染
│   └── navi_map_preview.png             ← 预览图
```

实际 ROS2 节点已迁移到 `src/nodes/navigation/`（按功能分层）：

```
src/nodes/navigation/
├── depth_publisher.py                   ← D455 深度 → PointCloud2
├── cuvslam_bridge.py                    ← cuVSLAM → /odom + TF + 状态翻译
├── initial_pose_publisher.py            ← 初始位姿 + map→odom TF
└── navigation_client.py                 ← 导航 API (navi/ 的副本)
```

配套文件：

```
configs/navigation/nav2_params.yaml      ← Nav2 全局参数
launch/navigation.launch.py              ← 一键启动导航栈
launch/competition.launch.py             ← 比赛总启动
src/nodes/decision/task_manager.py       ← 状态机(地图切换+导航+折返)
lite3_ros-ros2-foxy/                     ← 云深处 Lite3 ROS2 SDK
```

---

## 坐标系

mm 坐标系 (navi_map_data, 设计用) → ROS 坐标系 (Nav2, 运行用)：

```
mm:  原点=左上角, +x右 +y下, 单位mm
ROS: 原点=左下角, +x右 +y上, 单位m

转换:
  ros_x = mm_x / 1000.0
  ros_y = (6000 - mm_y) / 1000.0
```

**出发位姿**: ROS (5.35, 0.75) m, yaw=180°（面朝左）。

yaw 约定（mm 坐标系, 0°=面朝右）：

| yaw  | 含义   | yaw   | 含义   |
| ---- | ------ | ----- | ------ |
| 0°  | 面朝右 | 180° | 面朝左 |
| 90° | 面朝下 | -90° | 面朝上 |

---

## 各文件与节点详解

### 地图层

**`navi/map/navi_map_data.py`** — 唯一数据源

所有坐标、区域、柜体位置在此定义。其他模块通过 import 使用，不重复定义。

```python
FIELD       = 5000×6000 mm
REGIONS     = {inspection_upper, inspection_lower, grab, obstacle, placement}
WALL_REGION_IDS = {inspection_upper, inspection_lower}   # 始终是墙
INSPECTION_CABINETS = 两个 500×500×500mm 柜体, 各有两个标签面
OBSERVATION_POSITIONS = 3 个观察位, 含朝向(yaw)
ROBOT_START_POSE = (5350, 5250)mm, yaw=180°
```

**`navi/map/generate_nav2_map.py`** — PGM 生成器

读 `navi_map_data` → 输出两张地图：

| 地图          |      障碍区      |     抓取区     | 放置区(A/B/C/D) | 检测区 |
| ------------- | :--------------: | :------------: | :-------------: | :----: |
| Phase1 (越障) |    ⬜ 可通行    | ⬛ 膨胀墙 15cm |    ⬛ 严格墙    | ⬛ 墙 |
| Phase2 (任务) | ⬛**封堵** | ⬛ 膨胀墙 15cm |    ⬛ 严格墙    | ⬛ 墙 |

膨胀墙：区域向内缩 15cm 作为墙体，外围边缘狗可站立，机械臂伸入。放置区不膨胀——狗完全不入内。两张 YAML 告诉 map_server 分辨率(0.025m/px)和原点。

### 定位层

**`initial_pose_publisher`** (`src/nodes/navigation/initial_pose_publisher.py`)

启动时发布静态 TF：`map → odom = (5.35, 0.75, yaw=180°)`。

cuVSLAM 从 (0,0,0) 起步。这个 TF 告诉 Nav2："cuVSLAM 原点 = 地图上出发区的位置和朝向"。同时发 `/initialpose` 话题。**不删除**——没有它 Nav2 不知道狗在地图上的位置。

**`cuvslam_bridge`** (`src/nodes/navigation/cuvslam_bridge.py`)

订阅 cuVSLAM Docker 的 `/visual_slam/tracking/odometry` 和 `/visual_slam/status`，转为 Nav2 可用的格式：

```
/visual_slam/tracking/odometry  →  /odom (child_frame_id=base_link)
                                 →  TF: odom → base_link
/visual_slam/status             →  /slam/status (ok/lost)
```

完全信任 cuVSLAM 视觉里程计结果。

**Lite3_ROS SDK** (`lite3_ros-ros2-foxy/`)

云深处官方 ROS2↔UDP 桥接。发布 `/leg_odom`、`/imu/data`、`/joint_states`。订阅 `/cmd_vel`（这是 Nav2 的输出 → 狗移动）。需 APP 切到"自动模式"才生效。

### 感知层

**`depth_publisher`** (`src/nodes/navigation/depth_publisher.py`)

D455 深度图 → `/camera/depth/image_raw` + `/camera/depth/camera_info` → `point_cloud_xyz` → `/camera/depth/points` (PointCloud2) → Nav2 local_costmap。Jetson 上 10Hz 发布。

### 规划控制层

**`nav2_params.yaml`** — 全部 Nav2 参数

| 组件         | 配置                                                           |
| ------------ | -------------------------------------------------------------- |
| 全局代价地图 | StaticLayer(PGM) + ObstacleLayer(PointCloud2) + InflationLayer |
| 局部代价地图 | VoxelLayer 2m×2m 滚动窗口                                     |
| 全局规划器   | A\* (NavFn, `use_astar: true`)                               |
| 控制器       | RegulatedPurePursuit (TEB 注释供选)                            |
| 机器人       | 1m×0.5m 长方形足迹, 膨胀半径 0.2m                             |
| 速度         | 线速度 0.25m/s, 角速度 0.5rad/s                                |

### 决策层

**`navigation_client`** (`navi/navigation_client.py`)

封装 Nav2 action 为 Python API：

```python
nav.navigate_to_waypoint("pos1_middle")  # 12 个命名航点之一
nav.is_done()   # 到了没
nav.succeeded() # 成功了吗
nav.cancel()    # 取消
```

12 个航点坐标从 `navi_map_data` mm 自动转 ROS。观察位设 yaw（强制转到看柜体方向），其余不强制朝向。

**`task_manager`** (`src/nodes/decision/task_manager.py`)

状态机通过 `navigation_client` 驱动导航。关键逻辑：

```
PASS_OBSTACLE (两步):
  ① start → obstacle_cross_target (A* + D455 实时绕锥桶, 无固定入口)
     ↓ 到达安全走廊 → _switch_to_phase2_map() → 障碍区封堵
  ② obstacle_cross_target → pos1_middle (安全走廊 A*)

INSPECT_GAUGES (4 子步骤):
  pos1_middle (yaw=-90)     → 看上柜底面 → 测 A → 播报
  pos1_middle_turned (+90°) → 原地转 180° → 测 B → 播报
  pos2a_upper_right         → 看上柜右侧 → 测 C → 播报
  pos2b_lower_right         → 看下柜右侧 → 测 D → 播报
  收集异常区 [如 A,C] → 推进

FIND_RED_BAR → GRASP_BAR → PLACE_to_placement_X
  ↓ 还有未处理异常? → 跳回 FIND_RED_BAR (折返)
  ↓ 全处理完 → FINISH
```

**地图切换**：`task_manager` 内建 `LoadMap` 客户端。到达安全走廊后自动调 `/map_server/load_map`，从 phase1 切到 phase2（障碍区封堵），后续 A\* 不再穿障碍区。

### 数据流全景

```
D455 ──┬── IR+IMU → cuVSLAM → cuvslam_bridge → /odom + TF
       │
       └── depth → depth_pub → 点云 → Nav2 local_costmap
                │
         ┌──────┴──────────┐
         │   Nav2 导航栈    │
         │                 │
         │ map_server      │ ← phase1/2
         │ planner (A*)    │
         │ controller (RPP)│
         │ costmap         │ ← 深度点云
         └────────┬────────┘
                  │
             /cmd_vel
                  │
            Lite3_ROS → UDP → 狗运动主机
```

---

## 航点参考

所有坐标 ROS 米制 (map 帧)。yaw=None 表示到了就算，不管朝向。

| 航点                      | (x, y) m     | yaw   | 用途                   |
| ------------------------- | ------------ | ----- | ---------------------- |
| `start`                 | (5.35, 0.75) | —    | 出发区                 |
| `obstacle_cross_target` | (0.50, 0.75) | —    | 穿障碍→安全走廊(x<1m) |
| `pos1_middle`           | (1.50, 3.25) | -90° | 看上柜底面             |
| `pos1_middle_turned`    | (1.50, 3.25) | 90°  | 转身看下柜顶面         |
| `pos2a_upper_right`     | (2.20, 4.50) | 180° | 看上柜右侧面           |
| `pos2b_lower_right`     | (2.20, 2.00) | 180° | 看下柜右侧面           |
| `grab_area`             | (4.25, 2.00) | —    | 抓取区                 |
| `placement_A`           | (3.25, 5.75) | —    | A 放置区               |
| `placement_B`           | (3.75, 5.75) | —    | B 放置区               |
| `placement_C`           | (4.25, 5.75) | —    | C 放置区               |
| `placement_D`           | (4.75, 5.75) | —    | D 放置区               |

障碍穿越不设固定入口——A\* + D455 实时避障自己找路穿过去。

坐标唯一来源：`navi/map/navi_map_data.py`

---

## 使用方法

### 前置准备（Jetson 一次性）

```bash
cd ~/quadruped-robot-competition
sudo apt-get install -y ros-foxy-nav2-bringup ros-foxy-nav2-map-server \
  ros-foxy-nav2-planner ros-foxy-nav2-controller ros-foxy-nav2-bt-navigator \
  ros-foxy-nav2-lifecycle-manager ros-foxy-nav2-costmap-2d ros-foxy-nav2-voxel-grid \
  ros-foxy-nav2-navfn-planner ros-foxy-nav2-regulated-pure-pursuit-controller \
  ros-foxy-nav2-behavior-tree ros-foxy-nav2-waypoint-follower \
  ros-foxy-depth-image-proc ros-foxy-image-pipeline
pip3 install -e .
cd navi/map && python3 generate_nav2_map.py
cd ~/lite3_ros2_ws && colcon build   # Lite3 SDK 编译
```

### 完整启动流程（3 个终端）

**终端 1 — cuVSLAM Docker**（定位数据源）：

```bash
cd ~/quadruped-robot-competition
CUVSLAM_MOUNT_MODE=robot CUVSLAM_PROFILE=planar_60fps \
  CUVSLAM_PUBLISH_ODOM_TO_BASE_TF=false \
  CUVSLAM_PUBLISH_MAP_TO_ODOM_TF=false \
  bash scripts/start_cuvslam_rviz_gui.sh --no-rviz
# 等待出现 "Loop metrics live summary"（约 90 秒 GPU 预热）
```

**终端 2 — 桥接**（Docker cuVSLAM → 宿主机 `/odom`）：

```bash
source /opt/ros/foxy/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0 \
  PYTHONPATH=/opt/ros/foxy/lib/python3.8/site-packages
python3 /tmp/final_bridge.py
# 成功标志: bridged 301 msgs | self-verify: ~150
```

**终端 3 — 验证**（bridge 启动 30 秒后）：

```bash
source /opt/ros/foxy/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0 \
  PYTHONPATH=/opt/ros/foxy/lib/python3.8/site-packages
python3 /tmp/test_odom_sub.py
# 收到消息即定位链路通
```

一键启动+验证（终端 1 就绪后，终端 2 跑）：

```bash
source /opt/ros/foxy/setup.bash && export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0 PYTHONPATH=/opt/ros/foxy/lib/python3.8/site-packages && python3 /tmp/final_bridge.py & sleep 30 && python3 /tmp/test_odom_sub.py
```

### 定位链路架构

```
D455 IR+IMU → Docker cuVSLAM (Humble, 44Hz)
                    │ /visual_slam/vis/slam_odometry
                    ▼ docker exec + stdbuf 管道
              final_bridge.py (宿主机 Foxy)
                    │ 订阅: best_effort QoS
                    │ 发布: /odom (best_effort, 60Hz)
                    │ TF: odom → base_link
                    ▼
              Nav2 / 其他消费者
```

> **QoS 要点**: cuVSLAM composable node 使用 BEST_EFFORT 发布。宿主机订阅必须匹配 BEST_EFFORT，RELIABLE 默认订阅无法接收。`final_bridge.py` 已内置正确的 QoS 配置和自验证订阅（self-verify 计数器）。

### 调试

```bash
ros2 topic hz /odom                    # 定位频率
ros2 topic echo /odom                  # 定位数据
ros2 topic echo /task/status           # 任务状态
ros2 run tf2_tools view_frames         # TF 树
docker logs <cuvslam_container>        # cuVSLAM 日志
```

---

## 比赛流程对应

```
Phase                    导航                             航点
START                    等 SLAM OK+各子系统就绪           —
PASS_OBSTACLE
  step 0                 穿障碍区 → 安全走廊 (无固定入口)  obstacle_cross_target
       ↓ 到达 → 切地图 phase2
  step 1                 安全区 → 观察位①                  pos1_middle
INSPECT_GAUGES
  子步骤 0               仰头看上柜底面 → 测A → 播报①      pos1_middle (-90°)
  子步骤 1               180°转身看下柜顶 → 测B → 播报②   pos1_middle_turned
  子步骤 2               看上柜右侧面 → 测C → 播报③        pos2a_upper_right
  子步骤 3               看下柜右侧面 → 测D → 播报④        pos2b_lower_right
                         收集异常区 [如 A,C]
FIND_RED_BAR ×N         导航到抓取区                       grab_area
GRASP_BAR ×N            等机械臂抓取                       —
PLACE ×N                导航到放置区 placement_{X}          placement_X
                         还有异常 → 跳回 FIND_RED_BAR
FINISH                   全部完成                          —
```

N = 异常仪表数（通常 2 趟往返）。

---

## 参数速查

`configs/navigation/nav2_params.yaml`:

| 参数                   | 值              | 作用       |
| ---------------------- | --------------- | ---------- |
| `footprint`          | 1m×0.5m 长方形 | 机器人外形 |
| `desired_linear_vel` | 0.25 m/s        | 行走速度   |
| `inflation_radius`   | 0.2m            | 安全距离   |
| `xy_goal_tolerance`  | 0.15m           | 到位精度   |
| `timeout_per_phase`  | 120s            | 每阶段超时 |

---

## 相关文档

- [map/README.md](map/README.md) — 地图数据详解
- [../docs/nodes_diagram.md](../docs/nodes_diagram.md) — 全项目节点关系图
- [../configs/navigation/README.md](../configs/navigation/README.md) — Nav2 参数
- [../src/nodes/README.md](../src/nodes/README.md) — ROS2 节点总览
