# 四足机器人竞赛系统 — 架构与调试手册

## 目录
1. [整体架构](#1-整体架构)
2. [硬件拓扑](#2-硬件拓扑)
3. [Docker cuVSLAM 及数据穿透](#3-docker-cuvslam-及数据穿透)
4. [感知层：YOLO + WHZ](#4-感知层yolo--whz)
5. [决策层：Task Manager 状态机](#5-决策层task-manager-状态机)
6. [导航层：A* + Pure Pursuit + Navigator](#6-导航层a--pure-pursuit--navigator)
7. [狗通信协议：/cmd_vel → UDP → Dog](#7-狗通信协议cmd_vel--udp--dog)
8. [启动与停止脚本](#8-启动与停止脚本)
9. [调试技巧](#9-调试技巧)

---

## 1. 整体架构

```
┌──────────────────────────────────────────────────────┐
│                  Jetson Xavier NX                    │
│                                                      │
│  ┌─────────────────────────────────────────────┐    │
│  │          Docker: cuVSLAM (ROS2 Humble)       │    │
│  │  ┌──────────┐  ┌───────────┐  ┌──────────┐  │    │
│  │  │ D455i    │  │ cuVSLAM   │  │ Relay    │  │    │
│  │  │ Camera   │→│ Tracker   │→│ Scripts  │──┼──┼──→ JPEG files
│  │  └──────────┘  └───────────┘  │ (cam/dep)│  │    │   (shared volume)
│  │                               │ UDP exp. │──┼──┼──→ UDP :19001
│  │                               └──────────┘  │    │
│  └─────────────────────────────────────────────┘    │
│                    │                                 │
│  ┌─────────────────┴───────────────────────────┐    │
│  │          Host: Competition (ROS2 Foxy)       │    │
│  │                                              │    │
│  │  final_bridge.py ──→ /odom + /tmp/odom.json  │    │
│  │  depth_publisher ──→ /camera/depth/points    │    │
│  │                                              │    │
│  │  task_manager ──→ Navigator ──→ UDP ──→ Dog  │    │
│  │       │              │                        │    │
│  │       ├─ YOLO        ├─ A* Planner            │    │
│  │       └─ WHZ         ├─ Pure Pursuit          │    │
│  │                      └─ Local Obstacle        │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
└──────────────────────┬───────────────────────────────┘
                       │ eth0: 192.168.1.111
                       │ UDP :43893 (MotionComplexCMD)
                       ▼
              ┌────────────────┐
              │  Lite3 Robot   │
              │  192.168.1.120 │
              └────────────────┘
```

**ROS Domain**: ROS_DOMAIN_ID=0, RMW=rmw_fastrtps_cpp (no SHM)

---

## 2. 硬件拓扑

| 组件 | IP | 接口 | 说明 |
|------|-----|------|------|
| Jetson Xavier NX | 192.168.1.111 | eth0 | 运行 Foxy + Docker |
| D455i Camera | USB | Jetson USB3 | 深度相机，passthrough 到 Docker |
| Lite3 Robot Dog | 192.168.1.120 | eth0 直连 | 运动主机，接收 UDP :43893 |

**关键**: DDS 跨进程通信在 Jetson Foxy 上**完全不可用**（topic list 正常但 echo 永远收不到）。因此全部采用 UDP/文件桥接绕过 DDS。

---

## 3. Docker cuVSLAM 及数据穿透

### 3.1 为什么需要 Docker

cuVSLAM 只能在 ROS2 Humble + Isaac ROS 环境下运行。Jetson 主机是 Foxy。Docker 容器内运行完整的 Humble 环境。

### 3.2 启动命令

```bash
CUVSLAM_MOUNT_MODE=robot \
CUVSLAM_PROFILE=planar_60fps \
CUVSLAM_PUBLISH_ODOM_TO_BASE_TF=false \
CUVSLAM_PUBLISH_MAP_TO_ODOM_TF=false \
bash scripts/start_cuvslam_rviz_gui.sh --no-rviz
```

容器名格式: `cuvslam_gui_YYYYMMDD-HHMMSS`

### 3.3 数据穿透方案

Docker 内外 DDS 不互通，采用三种方式穿透：

#### A. 相机 RGB → JPEG 文件 (File Relay)

```
Docker 内: camera_relay_docker.py
  订阅 /camera/color/image_raw (Humble)
  → 保存 JPEG 到 /workspaces/isaac_ros-dev/camera_frames/
  (Docker volume mount → 主机可读写)

主机: depth_publisher.py
  读取 JPEG 文件 (用于 YOLO/WHZ 检测)
```

**文件路径**: `/workspaces/isaac_ros-dev/camera_frames/relay_*.jpg`
**频率**: ~60 FPS
**调试**: `docker exec <容器名> tail -5 /tmp/cam.log`

#### B. 深度图 → RAW 文件 (File Relay)

```
Docker 内: depth_relay_docker.py
  订阅 /camera/depth/image_rect_raw (Humble)
  → 保存 RAW 16-bit PNG + 元数据 JSON

主机: depth_publisher.py
  读取 depth 文件 → 发布 /camera/depth/image_raw (Foxy)
  depth_image_proc/point_cloud_xyz_node → /camera/depth/points
```

**文件路径**: `/workspaces/isaac_ros-dev/camera_frames/depth_*.raw`
**调试**: `docker exec <容器名> tail -5 /tmp/dep.log`

#### C. 里程计 → UDP → 文件 (UDP Bridge)

```
Docker 内: cuvslam_odometry_udp_exporter.py (由 final_bridge 自动部署)
  订阅 /visual_slam/vis/slam_odometry (Humble)
  → JSON 序列化 → UDP 127.0.0.1:19001

主机: final_bridge.py
  监听 UDP 127.0.0.1:19001
  → 发布 /odom (ROS2, BEST_EFFORT)     ← DDS 不可靠
  → 写入 /tmp/odom_latest.json         ← Navigator 读这个文件！
  → 发布 TF: odom → base_link
```

**文件格式** (`/tmp/odom_latest.json`):
```json
{
  "x": 0.123, "y": -0.045, "z": 0.0,
  "qx": -0.699, "qy": -0.088, "qz": 0.221, "qw": 0.675,
  "stamp": "source"
}
```

**调试**:
```bash
# 检查 bridge 是否收到 odom
grep "bridged" /tmp/fb.log | tail -1

# 检查最新 odom
cat /tmp/odom_latest.json

# 检查 stale drop (延迟过高被丢弃)
grep "stale" /tmp/fb.log | tail -3
```

**延迟要求**: < 150ms（超过则丢弃）。cuVSLAM 典型延迟 50-200ms。

### 3.4 Docker 常用操作

```bash
# 查看容器
docker ps | grep cuvslam

# 进入容器
docker exec -it <容器名> bash

# 查看 camera relay
docker exec <容器名> tail -5 /tmp/cam.log

# 查看 depth relay
docker exec <容器名> tail -5 /tmp/dep.log

# 杀掉高 CPU 进程
docker exec <容器名> pkill -f loop_metrics_recorder
```

---

## 4. 感知层：YOLO + WHZ

### 4.1 D455 锥桶局部避障

锥桶避障不再使用一次性 YOLO 检测，也不向全局 A* 注入障碍。启用 `--cone-avoidance` 后，现有 D455 owner 在 Humble 容器内增加以下 CPU-only 链路：

```text
D455 depth -> decimation x4 -> pointcloud
  -> pointcloud_to_laserscan(target_frame=base_link, height filtered)
  -> 180-beam CRC UDP (latest only)
  -> Foxy /cone_obstacle/scan
  -> local NonPersistentVoxelLayer -> DWB
```

UDP 包同时携带 `stream_id`、递增序号、源时间戳和深度有效率/左中右覆盖率。Host 会排空旧包并拒绝 CRC 错误、序号回退、超过 250 ms 的源数据、空深度和单飞点。速度链路中的独立 cone safety gate 需要至少连续 3 帧健康数据；断流或异常立即输出零速度。global costmap 继续只使用静态地图，Host 不接收点云也不依赖相机 TF。

### 4.2 WHZ 仪表检测

**工作方式**: 在 `INSPECT_GAUGES` 阶段，内联检测（不用 ROS2 service，直接用 Python import）。

**流程**:
```
task_manager._tick_inspect_gauges()
  → _run_whz_inline()
    → 读取 relay JPEG
    → WHZ 模型推理
    → 识别字母/仪表读数
    → 播放 MP3 语音
```

---

## 5. 决策层：Task Manager 状态机

### 5.1 状态机图

```
START → PASS_OBSTACLE → INSPECT_GAUGES(×4) → GRASP → FINISH
  │          │               │                    │        │
  └──────────┴───────────────┴────────────────────┴────────┘
                            ↓
                          ABORT (超时/故障)
```

### 5.2 阶段说明

| 阶段 | 子步骤 | 超时 | 说明 |
|------|--------|------|------|
| START | 等待 odom 就绪 | 无 | `_has_odom` 为 True 自动推进 |
| PASS_OBSTACLE | 0: YOLO检测 → 1: 导航到 exit | 300s | yaw 校准在此完成 |
| INSPECT_GAUGES | 0-3: 四个观察位 | 120s | 每个位姿 WHZ 检测一次 |
| GRASP | 拾取+放置 | 120s | 两个往返 |
| FINISH | 完成 | - | - |

### 5.3 关键参数

文件: `configs/ros/competition_params.yaml`
```yaml
timeout_per_phase: 300.0    # 每阶段超时 (秒)
tick_rate: 10.0             # 主循环频率 (Hz)
require_stable_gauge: true  # 仪表需稳定检测
auto_advance: false         # 调试模式：跳过 odom 等待
```

### 5.4 航点字典

定义在 `src/navigation/navigator.py` 的 `WAYPOINTS`:

| 航点名 | 坐标 (ROS map, m) | 朝向 | 用途 |
|--------|-------------------|------|------|
| start | (5.35, 0.75) | 180° | 起点 |
| obstacle_exit | (0.60, 0.75) | - | 障碍区出口 |
| pos1_middle | (3.45, 1.25) | 90° | 观察位1 |
| pos1_middle_turned | (3.45, 1.25) | 180° | 观察位1转向后 |
| pos2a_upper_right | (2.00, 3.50) | -90° | 观察位2a |
| pos2b_lower_right | (2.00, 1.25) | -90° | 观察位2b |
| grab_area | (4.25, 3.45) | - | 拾取区 |
| placement_A/B/C/D | ... | - | 放置点 |

---

## 6. 导航层：A* + Pure Pursuit + Navigator

### 6.1 模块结构

```
src/navigation/
  map_grid.py        ← 从 navi_map_data 构建占据栅格
  astar_planner.py   ← 8-邻域 A* 搜索
  pure_pursuit.py    ← 纯追踪控制器
  local_obstacle.py  ← 深度点云局部避障
  navigator.py       ← 整合类 (API 暴露给 task_manager)
```

### 6.2 坐标系统

| 坐标系 | 原点 | +X | +Y | 单位 |
|--------|------|----|----|------|
| navi_map_data | 左上角 | 右 | 下 | mm |
| Grid | row=0顶, col=0左 | col+ | row+ | 25mm/格 |
| ROS map | 左下角 | 右 | 上 | m |
| Odom (cuVSLAM) | 初始化位置 | - | - | m |

**转换**:
```
grid_col = round(x_mm / 25)
grid_row = round((6000 - y_mm) / 25)

ros_x = col * 0.025
ros_y = (240 - row) * 0.025
```

### 6.3 A* 规划器

- **8-邻域**: 含对角线移动
- **启发函数**: 欧几里得距离
- **障碍膨胀**: 0.05m (2格)
- **目标容差**: 0.05m
- **路径简化**: 共线点去除 + 0.3m 间距降采样

### 6.4 Pure Pursuit 控制器

| 参数 | 值 | 说明 |
|------|-----|------|
| lookahead | 0.5m | 前视距离 |
| max_linear | 0.3 m/s | 最大线速度 (狗上限 1.0) |
| max_angular | 0.4 rad/s | 最大角速度 (狗上限 1.5) |
| goal_tolerance | 0.05m | 到位判定 |
| yaw_tolerance | 0.25 rad | 朝向判定 |
| turn_in_place | 0.3 rad | 偏航误差 > 此值原地转向 |

### 6.5 Yaw 动态校准

**问题**: cuVSLAM 初始化时的朝向（视觉特征决定）与机器人物理朝向不一致。

**解决**: Navigator 收到第一个 odom 时自动计算偏移量。

```python
# 校准逻辑 (navigator.py _apply_odom_pose)
desired_start_yaw = 180°  # 来自 ROBOT_START_POSE
first_odom_yaw = <cuVSLAM 初始值, e.g. -98°>
offset = desired - first_odom = 180° - (-98°) = 278° → 规一化 -82°
current_yaw = offset + odom_yaw  # 后续每帧使用
```

**日志**: `Yaw calibrated: desired=180 odom=-98 offset=-82`

### 6.6 Odom 文件桥接

Navigator 优先从文件读取 odom（绕过 DDS）：

```python
# navigator.py _control_loop
self._read_odom_file()  # 读 /tmp/odom_latest.json
# fallback: ROS2 /odom callback (_odom_callback)
```

`_has_odom` 为 True 才启动导航。

### 6.7 卡住检测

| 参数 | 当前值 | 说明 |
|------|--------|------|
| timeout | 120s | 几乎禁用（cuVSLAM odom 噪声大） |
| dist_threshold | 0.05m | 位移阈值 |
| yaw_threshold | 0.2 rad | 转向阈值 |

---

## 7. 狗通信协议：/cmd_vel → UDP → Dog

### 7.1 协议发现历程

**错误尝试 1**: 直接 UDP SimpleCMD (`<3i`)
- 码: `0x21010130` (前进), `0x21010135` (转向) — 来自 GUI lite3_control.py
- 结果: 狗不响应（这是手柄操控码，只在手动/原控模式生效）

**错误尝试 2**: transfer SDK (`jetson2motion`)
- 端口 43897 冲突，进程崩溃
- DDS 跨进程不通

**正确方案**: SDK `MotionComplexCMD` (`<3id`)
- 参考 `Jetson2Motion.cpp` 和协议文档 §1.2.12
- 只在**自动模式** (`0x21010C03`) 下生效

### 7.2 命令格式

**MotionComplexCMD** (20 字节):
```
struct {
    int32_t cmd_code;  // 4 bytes — 命令码
    int32_t size;      // 4 bytes — 总是 8
    int32_t type;      // 4 bytes — 总是 1
    double  data;      // 8 bytes — 速度值 (m/s 或 rad/s)
};
// Python: struct.pack('<3id', code, 8, 1, value)
```

### 7.3 命令码表

| 指令 | 码 (hex) | 码 (dec) | data 范围 | data 含义 |
|------|---------|----------|-----------|-----------|
| 前后平移速度 | 0x0140 | **320** | [-1.0, 1.0] | m/s, 正值=前进 |
| 左右平移速度 | 0x0145 | **325** | [-0.5, 0.5] | m/s, 正值=左移 |
| 转向角速度 | 0x0141 | **321** | [-1.5, 1.5] | rad/s, **取反**: `data = -az` |

### 7.4 关键规则

1. **心跳必须同源**: 运动指令和心跳必须从**同一个 socket** 发出
2. **每周期只发一种指令**: 最后发的 MotionComplexCMD 覆盖前面的。不同时发前进+转向
3. **自动模式**: 必须先发 `0x21010C03` (自动模式) + `0x21010D06` (移动模式)
4. **频率**: 10Hz (每 100ms)
5. **超时**: 狗 250ms 无指令自动停止
6. **目标**: `192.168.1.120:43893` (UDP)

### 7.5 Navigator 发包逻辑

```python
# navigator.py _publish_cmd_vel
# 每周期 (10Hz) 执行:

# 1. 心跳 (SimpleCMD, 12 bytes)
udp.sendto(struct.pack('<3i', 0x21040001, 0, 0), dog_addr)

# 2. 运动指令 (只发一种!)
if abs(az) > 0.1:
    # 转向优先
    udp.sendto(struct.pack('<3id', 321, 8, 1, -az), dog_addr)
elif abs(vx) > 0.01:
    # 直线前进
    udp.sendto(struct.pack('<3id', 320, 8, 1, vx), dog_addr)
else:
    # 停止
    udp.sendto(struct.pack('<3id', 320, 8, 1, 0.0), dog_addr)
```

### 7.6 狗初始化序列

```python
# lite3_init.py (后台运行)
# 1. 心跳脉冲 (×10, 100ms间隔)
for _ in range(10): send(0x21040001)

# 2. 站立 (0x21010202 — 注意这是 toggle!)
send(0x21010202); sleep(3)

# 3. 自动模式 (0x21010C03) — 必须!
send(0x21010C03); sleep(1)

# 4. 移动模式 (0x21010D06)
send(0x21010D06); sleep(0.5)

# 5. 持续心跳 (500ms间隔)
while True: send(0x21040001); sleep(0.5)
```

### 7.7 调试狗指令

```bash
# 手动前进测试 (带心跳，单独发包)
python3 -c "
import socket,struct,time
s=socket.socket(2,2); a=('192.168.1.120',43893)
for _ in range(5): s.sendto(struct.pack('<3i',0x21040001,0,0),a); time.sleep(0.1)
s.sendto(struct.pack('<3i',0x21010C03,0,0),a); time.sleep(1)
for _ in range(30): s.sendto(struct.pack('<3id',320,8,1,0.3),a); time.sleep(0.1)
s.sendto(struct.pack('<3id',320,8,1,0.0),a)
"
```

### 7.8 ROS2 /cmd_vel 发布

Navigator 同时发布 ROS2 `/cmd_vel` (BEST_EFFORT QoS)，供日志记录和可能的 transfer SDK 使用：

```python
msg = Twist()
msg.linear.x = vx    # 前进速度
msg.angular.z = az   # 转向角速度
self._cmd_vel_pub.publish(msg)
```

---

## 8. 启动与停止脚本

### 8.1 一键启动

```bash
bash scripts/start_competition.sh --dog [--yolo] [--whz]
```

**流程**:
```
[0] stop_all → 清理旧进程
[1] Docker 检查 → 如需要则启动 (等待 cuVSLAM 追踪)
[2] 中继启动 → camera relay + depth relay → 验证输出
[3] UDP 桥接 → final_bridge → 等待第一个 odom
[4] 狗初始化 → lite3_init (自动模式+心跳, 不切换站立)
[5] 比赛系统 → ros2 launch (task_manager + navigator + depth_pub)
[6] 验证 → 节点列表 + odom 检查 + CPU 状态
```

**日志位置**: `~/Desktop/logs/competition_YYYYMMDD_HHMMSS.log`

### 8.2 一键停止

```bash
bash scripts/stop_all.sh
```

**顺序** (防止复活): launch → 比赛节点 → transfer SDK → 桥接 → Docker 内中继

### 8.3 仅重启比赛 (不动 Docker/桥接/狗)

```bash
# 杀掉比赛
pkill -9 -f competition.launch
pkill -9 -f task_manager
sleep 2

# 启动比赛
source /opt/ros/foxy/setup.bash
source install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0
ros2 launch quadruped_robot_competition competition.launch.py \
  enable_task_manager:=true enable_navigation:=true \
  enable_yolo:=false enable_whz:=false
```

---

## 9. 调试技巧

### 9.1 日志位置

| 组件 | 日志路径 | 关键字 |
|------|---------|--------|
| 比赛主日志 | `~/Desktop/logs/competition_*.log` | phase, goal, Stuck |
| 比赛进程 | `/tmp/competition.log` | Yaw calibrated, A* path |
| Bridge | `/tmp/fb.log` 或 `/tmp/final_bridge.log` | bridged, stale |
| 狗初始化 | `/tmp/lite3_init.log` | Heartbeat active |
| Camera relay | `docker exec <容器名> cat /tmp/cam.log` | Saved |
| Depth relay | `docker exec <容器名> cat /tmp/dep.log` | Depth |
| cmd_vel 直录 | `~/competition_logs/cmd_vel_direct.csv` | vx, az |
| Odom 文件 | `/tmp/odom_latest.json` | x, y, qx, qy, qz, qw |

### 9.2 常见问题诊断

| 症状 | 检查 | 命令 |
|------|------|------|
| 狗不动 | 心跳在跑? | `ps aux \| grep lite3_init` |
| 狗不动 | 自动模式? | `grep "auto mode" /tmp/lite3_init.log` |
| 狗不动 | 指令发出? | `tail -5 ~/competition_logs/cmd_vel_direct.csv` |
| 狗不走 | 心跳同源? | 检查 Navigator 发包含 hb |
| 狗原地转 | yaw 校准对? | `grep "calibrat" /tmp/competition.log` |
| 狗走反了 | 朝向 180°? | `cat /tmp/odom_latest.json` 手动算 yaw |
| 导航不启动 | odom 有数据? | `cat /tmp/odom_latest.json` |
| 导航不启动 | phase 卡在哪? | `tail /tmp/competition.log` |
| 阶段超时 | timeout 够长? | `grep timeout /tmp/competition.log` |
| 僵尸进程 | ros2 launch 在跑? | `ps aux \| grep "ros2 launch"` |
| CPU 过高 | loop_metrics 在跑? | `docker exec <容器名> ps aux \| grep loop` |
| 狗网络不通 | eth0 IP? | `ip addr show eth0` |
| 狗网络不通 | 狗在线? | `ping 192.168.1.120` |

### 9.3 快速诊断命令集

```bash
# 复制粘贴到 Jetson 终端，快速诊断

echo "=== 进程 ==="
ps aux | grep -E "task_manager|final_bridge|lite3_init|camera_relay|depth_relay" | grep -v grep

echo "=== 狗网络 ==="
ping -c 1 192.168.1.120 2>&1 | tail -1

echo "=== Odom ==="
python3 -c "import json; d=json.load(open('/tmp/odom_latest.json')); print(f'x={d[\"x\"]:.2f} y={d[\"y\"]:.2f}')" 2>/dev/null || echo "无odom"

echo "=== 最新 cmd_vel ==="
tail -3 ~/competition_logs/cmd_vel_direct.csv 2>/dev/null

echo "=== 比赛阶段 ==="
grep -E "phase|Yaw|A\*|Stuck|goal|timeout" /tmp/competition.log 2>/dev/null | tail -5

echo "=== Docker ==="
docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null | grep cuvslam

echo "=== CPU TOP3 ==="
ps -eo pcpu,pid,comm --sort=-pcpu | head -4
```

### 9.4 纯手动测试狗

```bash
# 完整手动测试流：站立 → 自动模式 → 前进
python3 -c "
import socket,struct,time
s=socket.socket(2,2); a=('192.168.1.120',43893)
# 心跳
for _ in range(10): s.sendto(struct.pack('<3i',0x21040001,0,0),a); time.sleep(0.1)
# 站立
s.sendto(struct.pack('<3i',0x21010202,0,0),a); time.sleep(3)
# 自动模式
s.sendto(struct.pack('<3i',0x21010C03,0,0),a); time.sleep(1)
# 前进 0.3 m/s
for _ in range(50): s.sendto(struct.pack('<3id',320,8,1,0.3),a); time.sleep(0.1)
# 停止
s.sendto(struct.pack('<3id',320,8,1,0.0),a)
print('DONE')
"
```
