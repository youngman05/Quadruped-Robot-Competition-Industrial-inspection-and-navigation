# 导航模块 (navi)

本目录是四足机器人竞赛的**导航大脑**——负责地图生成、视觉定位桥接、深度传感器数据处理、路径规划，以及与比赛状态机的联动。

---

## 目录

- [你要解决什么问题？](#你要解决什么问题)
- [核心概念（给没学过导航的人）](#核心概念给没学过导航的人)
- [算法简介](#算法简介)
- [目录结构](#目录结构)
- [数据流全景图](#数据流全景图)
- [坐标系](#坐标系)
- [关键文件详解](#关键文件详解)
- [ROS2 节点说明](#ros2-节点说明)
- [航点参考](#航点参考)
- [使用方法](#使用方法)
- [比赛流程对应](#比赛流程对应)

---

## 你要解决什么问题？

机器人要从 **出发区**（右下角）出发，完成三件事：

```
出发 ──→ ① 穿越障碍区（不能碰锥桶）
        ② 巡检 4 个仪表（分别在两个柜体的不同面上）
        ③ 抓取异常仪表对应的红色块，放到对应字母箱
```

**导航系统回答三个问题：**

| 问题 | 谁来解决 | 怎么做 |
|------|---------|--------|
| 世界长什么样？ | PGM 地图 | 一张黑白格栅图，黑色=墙，白色=路 |
| 我现在在哪？ | cuVSLAM | D455 红外双目 + IMU 推算位置 |
| 怎么走到目标？ | Nav2 + A\* | 在地图上找最短路径，控制速度转向 |

---

## 核心概念（给没学过导航的人）

### 1. 代价地图 (Costmap) — "哪里能走、哪里不能走"

把场地切成 2.5cm × 2.5cm 的小格子，每个格子有一个**代价分数**：

```
 0  — 完全不能走（墙、柜体）
 1~254 — 可以走但代价不同（越靠近障碍代价越高）
 255 — 完全自由
```

机器人把自己当成 **1m × 0.5m 的长方形**，计算不碰到任何障碍的最佳路径。

### 2. A\* 算法 — "怎么绕开墙最快到目标"

> **类比**：你在一个迷宫里，想知道从门口到卫生间的最短路线。你会先朝大致方向走，遇到死胡同就往回退一步换个方向。A\* 就是这样做，但它同时评估两条信息：
> - **已经走了多远**（实际代价）
> - **距离目标还有多远**（启发式估计）
>
> 两者加起来最小的方向优先探索。

A\* 的三个特点：
- **保证找到最短路径**
- **可以原地转向**的机器人不需要更复杂的算法（如 Hybrid-A\*）
- **速度快**，迷宫规模越大越明显

### 3. cuVSLAM — "闭着眼也知道自己走了多远"

> **类比**：你闭着眼睛从教室门口走到窗边，大脑同时感知两件事：脚踩了几步（IMU / 加速度计）、经过的墙/桌椅边缘（视觉特征）。综合这些信息，你大概知道自己移动了多远、转了多大角度。

cuVSLAM = **CU**DA **V**isual **S**imultaneous **L**ocalization **A**nd **M**apping

- 运行在 Docker 容器里（独立环境，ROS2 Humble）
- 输入：D455 红外双目（左右红外图）+ IMU（加速度+陀螺仪）
- 输出：机器人当前位姿 (x, y, yaw)
- **注意**：红外投射器必须**关闭**，否则红外点的干扰会让立体匹配失效

### 4. 全局规划 vs 局部控制

```
全局规划 (Planner)          局部控制 (Controller / TEB)
┌──────────────────┐       ┌──────────────────┐
│ 在地图上画一条     │       │ 沿着线走，同时      │
│ "理想路线"        │  ──→  │ 躲开突然出现的      │
│ (静态，不变)      │       │ 障碍物              │
│                  │       │ (动态，每秒10次)    │
│ 例: 绕过检测区墙  │       │ 例: 锥桶突然出现    │
└──────────────────┘       └──────────────────┘
```

- **NavFn (A\*)** = 全局规划器，用 A\* 在地图上找路
- **RegulatedPurePursuit** = 控制器，盯着前方 0.5m 的路径点追过去
- **TEB** = 更聪明的控制器（可选），同时优化轨迹形状、速度、与障碍物的距离

---

## 算法简介

### 全局规划

| 算法 | 原理 | 适用场景 | 本项目使用 |
|------|------|---------|-----------|
| **A\***（本项目） | 启发式搜索，f(n) = g(n) + h(n) | 栅格地图，任意方向移动 | ✅ 默认 |
| Dijkstra | A\* 的特例，h(n)=0 | 无目标信息时 | 可通过 `use_astar: false` 切换 |
| Hybrid-A\* (SmacPlanner2D) | A\* + 运动学约束（Dubins曲线） | 汽车/阿克曼转向 | ❌ 不需要。四足可原地转向 |

```
A* 搜索过程示意:

   S · · · ·           S = 起点
   · # # · ·           # = 墙
   · # G · ·           G = 目标
   · · · · ·           · = 探索过的格子

每一步展开"代价最小"的格子 → 最终回溯出最短路径
```

### 局部控制

| 算法 | 原理 | 特点 |
|------|------|------|
| **RegulatedPurePursuit**（默认） | 在路径上选一个"胡萝卜"点（前方 0.5m），追过去 | 简单、稳定、适合四足 |
| **TEB**（可选） | 将路径离散成"时间-位姿"序列，用图优化同时解速度+轨迹+避障 | 更精细、但需要从源码编译 |

---

## 目录结构

```
navi/                                   ← 导航模块根目录
│
├── README.md                           ← 本文档
├── 2026年...赛规.pdf                   ← 官方比赛规则 PDF
│
├── map/                                ← 地图子模块
│   ├── navi_map_data.py                ← ★ 场地数据权威定义
│   │                                     （所有区域、柜体、锥桶、观察位、航点坐标）
│   ├── generate_nav2_map.py            ← PGM 栅格地图生成器
│   ├── competition_field.pgm           ← 输出的 Nav2 地图（226×240 px）
│   ├── competition_field.yaml          ← 地图元数据（分辨率、原点等）
│   ├── render_navi_map_preview.py      ← 场地可视化预览渲染
│   ├── navi_map_preview.png            ← 生成的预览图
│   ├── 区域图.png / 尺寸图.png / ...   ← 比赛规则中的参考图
│   └── README.md                       ← 地图子模块文档
│
├── depth_publisher.py                  ← ★ D455 深度图 → ROS Image → PointCloud2
├── cuvslam_bridge.py                   ← ★ cuVSLAM Docker → Nav2 TF/odom 桥接
├── initial_pose_publisher.py           ← ★ 初始位姿 + map→odom 变换发布
└── navigation_client.py                ← ★ 导航 API + 12 个命名航点
```

配套文件（在其他目录）:

```
configs/navigation/nav2_params.yaml     ← Nav2 全局/局部代价地图、规划器、控制器参数
launch/navigation.launch.py             ← 一键启动整个导航栈
launch/competition.launch.py            ← 比赛总启动（含 enable_navigation 参数）
scripts/install_nav2_deps.sh            ← Jetson Nav2 依赖安装脚本
src/nodes/task_manager.py               ← 比赛状态机（已集成导航客户端）
```

---

## 数据流全景图

```
                         D455 深度相机
                              │
                    ┌─────────┼─────────┐
                    │                   │
              [IR双目+IMU]         [深度图像]
                    │                   │
                    ▼                   ▼
            ┌──────────────┐    ┌────────────────┐
            │ cuVSLAM       │    │ depth_publisher │
            │ (Docker Humble)│    │ .py             │
            │               │    │                 │
            │ 输出:         │    │ 输出:           │
            │ /odom + TF    │    │ /camera/depth/  │
            └──────┬────────┘    │ points (点云)   │
                   │             └───────┬────────┘
                   ▼                     │
            ┌──────────────┐             │
            │ cuvslam_bridge│            │
            │ .py           │            │
            │               │            │
            │ 桥接 Humble   │            │
            │ → Foxy        │            │
            └──────┬────────┘            │
                   │                     │
                   ▼                     ▼
            ┌──────────────────────────────────┐
            │         Nav2 导航栈               │
            │                                  │
            │  map_server  ← competition_field │
            │  planner      ← A* (NavFn)       │
            │  controller   ← RegulatedP.P.    │
            │  costmap      ← 静态地图+深度点云 │
            │                                  │
            │  输出: /cmd_vel (速度指令)        │
            └──────────────┬───────────────────┘
                           │
                           ▼
            ┌──────────────────────────┐
            │  navigation_client.py    │
            │  12 个命名航点            │
            │  navigate_to_waypoint()  │
            └──────────────┬───────────┘
                           │
                           ▼
            ┌──────────────────────────┐
            │  task_manager.py         │
            │  比赛状态机               │
            │  决定"什么时候去哪"       │
            └──────────────────────────┘
```

## 坐标系

本模块涉及 **两套坐标系**，转换关系：

```
mm 坐标系 (navi_map_data)          ROS 坐标系 (Nav2)
─────────────────────────          ─────────────────
原点: 场地左上角                   原点: 场地左下角
+x → 右                           +x → 右
+y → 下                           +y → 上
单位: mm                          单位: m

转换:
  ros_x = mm_x / 1000.0
  ros_y = (6000 - mm_y) / 1000.0
```

```
mm 坐标                       ROS 坐标

(0,0)──→ x                    (0,6)──→ x
│ 左上角                       │ 左上角
│                             │
│    场地 5000×6000            │    场地 5×6m
│                             │
│              (5050,5250)    │              (5.35,0.75)
│              🐕出发          │              🐕出发
└──── y ↓                     └──── y ↑
  右下角                         左下角 (0,0)
```

**为什么选择左上角为原点？** 因为比赛 PDF 里的场地图是图片，左上角是图片的自然原点。直接在图上标尺寸不容易出错。生成 ROS 地图时再转换。

**机器人朝向约定：**

| yaw (mm坐标系) | 含义 | ROS quaternion (qz, qw) |
|---------------|------|------------------------|
| 0° | 面朝右 (+x) | (0, 1) |
| 90° | 面朝下 (+y) | (0.707, 0.707) |
| 180° | 面朝左 (-x) | (1, 0) |
| -90° | 面朝上 (-y) | (-0.707, 0.707) |

**出发位姿**：位置 (5.35, 0.75)m，yaw=180°（面朝左，向场地内部前进）。

---

## 关键文件详解

### 1. `navi/map/navi_map_data.py` — 场地数据权威定义

这是整个导航系统的**单一数据源** (Single Source of Truth)。所有场地信息都在这里定义，其他模块通过 import 使用。

#### 核心数据结构

```python
@dataclass(frozen=True)
class Region:
    id: str              # 唯一标识，如 "inspection_upper"
    label_zh: str        # 中文名称
    category: str        # 类别: inspection / grab / obstacle / placement
    rect: Rect           # (x_mm, y_mm, width_mm, height_mm)
    polygon              # 四个顶点坐标（计算属性）
    center               # 中心点坐标（计算属性）
```

```python
@dataclass(frozen=True)
class InspectionCabinet:
    id: str                    # 柜体标识
    center_mm: Point           # 柜体中心坐标
    size_mm: (宽, 深, 高)       # 500×500×500mm
    labeled_faces: tuple[...]  # 贴了标签的面（底面/顶面/侧面）
```

```python
@dataclass(frozen=True)
class ObservationPosition:
    id: str                # 观察位标识
    center_mm: Point       # 机器人站立位置
    look_directions: tuple # 观察方向列表 [{yaw_deg, sees, label}, ...]
```

#### 关键常量

| 常量 | 含义 | 值 |
|------|------|-----|
| `FIELD` | 场地尺寸 | 5000×6000 mm |
| `REGIONS` | 5 个官方区域 | inspection_upper, inspection_lower, grab, obstacle, placement |
| `WALL_REGION_IDS` | 标记为墙的区域 | {inspection_upper, inspection_lower} |
| `INSPECTION_CABINETS` | 2 个巡检柜体 | upper (1500,1500), lower (1500,4000) |
| `OBSERVATION_POSITIONS` | 3 个观察站立点 | 中间走廊 + 上下中通道 |
| `ROBOT_START_POSE` | 出发位姿 | (5350, 5250) mm, yaw=180° |

#### 为什么障碍区不在 WALL_REGION_IDS 中？

障碍区地面是**可通行**的。只有两个随机放置的锥桶是障碍物，锥桶由 D455 深度相机实时检测（放进局部代价地图），不需要在静态地图中标为墙。如果整片障碍区标墙，机器人永远绕不过去。

### 2. `navi/map/generate_nav2_map.py` — PGM 地图生成器

**输入**: `navi_map_data.py` 中的场地数据
**输出**: `competition_field.pgm` (226×240 像素) + `competition_field.yaml`

#### 生成逻辑

```
1. 创建 226×240 网格，全部标记为 UNKNOWN (205=灰)
2. 填充场地内部 5000×6000mm → FREE (254=白)
3. 填充出发区 5050~5650 × 4500~6000mm → FREE
4. 填充 WALL_REGION_IDS 中区域 → OCCUPIED (0=黑)
5. 写入 PGM P5 二进制格式 + YAML 元数据
```

#### PGM 像素值含义

| 数值 | 颜色 | 含义 |
|------|------|------|
| 0 | 黑 | 墙/障碍 — 机器人不能进入 |
| 254 | 白 | 空地 — 可以自由通行 |
| 205 | 灰 | 未知 — 场地外，不去 |

### 3. `navi/navigation_client.py` — 导航 API

提供给 `task_manager.py` 的高级接口。

#### 关键类

```python
class NavigationClient:
    def navigate_to_waypoint(name)  # 导航到命名航点
    def navigate_to_pose(x,y,q...)  # 导航到自定义位姿
    def is_done()                   # 是否到达
    def succeeded()                 # 是否成功
    def cancel()                    # 取消
    def reset()                     # 重置以发送新目标
```

#### 航点列表

所有航点都在 `navi_map_data.py` 中定义（mm 坐标），`navigation_client.py` 自动转为 ROS 坐标。

### 4. `navi/cuvslam_bridge.py` — cuVSLAM 桥接

**为什么需要桥接？** cuVSLAM 跑在 ROS2 **Humble** Docker 容器里，但主机是 ROS2 **Foxy**。ROS2 不同版本间 DDS 通信需要桥接。

**关键参数**（可通过 ROS2 param 覆盖）:

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `slam_odom_topic` | `/visual_slam/tracking/odometry` | cuVSLAM 输出的话题 |
| `camera_frame` | `camera_link` | 相机坐标系 |
| `base_frame` | `base_link` | 机器人基座坐标系 |

### 5. `navi/depth_publisher.py` — 深度发布

从 D455 深度流中获取深度图，发布为 ROS Image。`depth_image_proc/point_cloud_xyz_node` 将深度图转为 PointCloud2，供 Nav2 局部代价地图使用。

**性能调优**：Jetson 上深度图以 10Hz 发布（相机内部 15fps），减少 CPU 负载。

### 6. `navi/initial_pose_publisher.py` — 初始位姿

**关键 TF 变换**：

```
map → odom = (5.35m, 0.75m, yaw=180°)
```

含义：cuVSLAM 从 (0,0,0) 起步，但这个点在真实场地中对应 (5.35, 0.75) 且面朝左。此变换告诉 Nav2 机器人在地图上的真实位置。

---

## ROS2 节点说明

| 节点名 | 源文件 | 订阅 | 发布 | 作用 |
|--------|--------|------|------|------|
| `d455_depth_publisher` | `depth_publisher.py` | — | `/camera/depth/image_raw`, `/camera/depth/camera_info` | D455 深度数据成为 ROS 话题 |
| `cuvslam_bridge` | `cuvslam_bridge.py` | `/visual_slam/tracking/odometry`, `/visual_slam/status` | `/odom`, `/slam/status`, TF | cuVSLAM Docker → Nav2 |
| `initial_pose_publisher` | `initial_pose_publisher.py` | — | `/initialpose`, TF: map→odom | 告知 Robot 起始位姿 |
| `point_cloud_xyz_node` | ROS 内置 | `/camera/depth/image_raw`, `/camera/depth/camera_info` | `/camera/depth/points` | 深度图→3D点云 |
| `map_server` | Nav2 内置 | — | `/map` | 加载 PGM 地图 |
| `planner_server` | Nav2 内置 | `/map`, `/tf` | `/plan` | A* 全局规划 |
| `controller_server` | Nav2 内置 | `/plan`, `/odom`, `/tf` | `/cmd_vel` | 路径跟踪控制 |
| `bt_navigator` | Nav2 内置 | action 请求 | action 结果 | 行为树导航 |

### 节点关系图

```
initial_pose_publisher ──→ TF: map→odom
cuvslam_bridge ──→ /odom + TF: odom→base_link
depth_publisher ──→ /camera/depth/image_raw
point_cloud_xyz ──→ /camera/depth/points
                          │
map_server ──→ /map       │
              │           │
              ▼           ▼
         planner_server (A*)
              │
              ▼
         controller_server
              │
              ▼
         /cmd_vel (机器人速度指令)
```

---

## 航点参考

所有坐标单位为 ROS 米制 (map 帧)：

| 航点名 | 位置 (x, y) m | 朝向 | 用途 |
|--------|--------------|------|------|
| `start` | (5.35, 0.75) | 180° | 出发区 |
| `obstacle_entry` | (3.00, 1.00) | 180° | 障碍区入口 |
| `pos1_middle` | (1.50, 3.25) | -90° | 观察位① 仰头看上柜底面 |
| `pos1_middle_turned` | (1.50, 3.25) | 90° | 观察位① 180°转身看下柜顶面 |
| `pos2a_upper_right` | (2.20, 4.50) | 180° | 观察位②a 看上柜右侧面 |
| `pos2b_lower_right` | (2.20, 2.00) | 180° | 观察位②b 看下柜右侧面 |
| `obstacle_exit` | (1.50, 3.25) | -90° | 障碍区出口→观察位① |
| `grab_area` | (4.25, 2.00) | 180° | 抓取区中心 |
| `placement_A` | (3.25, 5.75) | 0° | A 放置区 |
| `placement_B` | (3.75, 5.75) | 0° | B 放置区 |
| `placement_C` | (4.25, 5.75) | 0° | C 放置区 |
| `placement_D` | (4.75, 5.75) | 0° | D 放置区 |

---

## 使用方法

### 前置准备

```bash
# 1. 在 Jetson 上安装 Nav2 依赖（仅需一次）
cd ~/quadruped-robot-competition
chmod +x scripts/install_nav2_deps.sh
./scripts/install_nav2_deps.sh

# 2. 安装 Python 包
pip3 install -e .

# 3. 生成 PGM 地图（如果还没生成）
cd navi/map
python3 generate_nav2_map.py

# 4. 启动 cuVSLAM Docker（单独终端）
docker run --rm --gpus all --network host \
  -v ~/workspaces/isaac_ros-dev:/workspaces/isaac_ros-dev \
  isaac_ros_cuvslam_runtime:humble-rs \
  ros2 launch isaac_ros_visual_slam isaac_ros_visual_slam_realsense.launch.py

# 5. source ROS2
source /opt/ros/foxy/setup.bash
```

### 启动导航栈

```bash
# 仅导航（单独测试）
ros2 launch launch/navigation.launch.py

# 切换规划器
ros2 launch launch/navigation.launch.py planner:=navfn    # A* (默认)

# 完整比赛系统
ros2 launch launch/competition.launch.py \
  enable_task_manager:=true \
  enable_navigation:=true
```

### 调试命令

```bash
# 查看 TF 树
ros2 run tf2_tools view_frames

# 查看当前代价地图
ros2 topic echo /global_costmap/costmap_raw

# 查看 A* 规划结果
ros2 topic echo /plan

# 查看机器人位姿
ros2 topic echo /odom

# 查看 cuVSLAM 状态
ros2 topic echo /visual_slam/status

# 查看任务状态
ros2 topic echo /task/status
```

---

## 比赛流程对应

状态机 (task_manager.py) 的阶段与导航模块的关系：

```
Phase                   导航动作                       航点
──────────────────────  ────────────────────────────   ──────────────────
START                   等待 SLAM OK                   —
PASS_OBSTACLE           导航到第一观察位                pos1_middle
INSPECT_GAUGES
  ├─ 子步骤 0           仰头看上柜底面 → 播报①          pos1_middle
  ├─ 子步骤 1           180°转身看下柜顶面 → 播报②      pos1_middle_turned
  ├─ 子步骤 2           看上柜右侧面 → 播报③            pos2a_upper_right
  └─ 子步骤 3           看下柜右侧面 → 播报④            pos2b_lower_right
                         收集异常区列表
FIND_RED_BAR (×N)      导航到抓取区 + 找红色块          grab_area
GRASP_BAR (×N)         等待机械臂抓取                   —
PLACE (×N)             导航到对应字母放置区               placement_X
                         如还有异常 → 回到 FIND_RED_BAR
FINISH                  比赛结束                        —
```

**N = 异常仪表数量**（通常是 2）。每个异常需要一趟往返：抓取区→对应放置区。

---

## 参数调优速查

`configs/navigation/nav2_params.yaml` 关键参数：

| 参数 | 值 | 调整方向 |
|------|-----|---------|
| `footprint` | 1m×0.5m 长方形 | 根据实际机器人尺寸修改 |
| `desired_linear_vel` | 0.25 m/s | 太慢→加，不稳→减 |
| `lookahead_dist` | 0.5m | 转向不足→加，过冲→减 |
| `inflation_radius` (global) | 0.2m | 离墙太近→加，通道太窄→减 |
| `xy_goal_tolerance` | 0.15m | 停不准→减，效率低→加 |

---

## 相关文档

- [map/README.md](map/README.md) — 地图子模块详细文档
- [../configs/navigation/README.md](../configs/navigation/README.md) — Nav2 参数说明
- [../src/navigation/README.md](../src/navigation/README.md) — 导航架构设计（规划中）
- [../src/nodes/README.md](../src/nodes/README.md) — ROS2 节点总览
- [../launch/README.md](../launch/README.md) — 启动文件使用指南
