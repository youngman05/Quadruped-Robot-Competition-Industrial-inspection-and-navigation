# Navigation System — 交接文档

## 1. 系统总览

### 1.1 你在做什么

把 `motion/motion_controller.py`（已封装好的狗运动控制 API）集成到 `navigator.py`，替换里面重复的 odom 读取和 UDP 发送代码。

### 1.2 整体层级

```
task_manager (决策层)
  │  state machine: START → PASS_OBSTACLE → INSPECT → GRASP → FINISH
  │
  ├─ navigator.navigate_to_waypoint("pos1_middle")
  │     ├─ A* 规划: map_grid + astar_planner → path
  │     ├─ 10Hz 控制: pure_pursuit.compute_velocity() → (vx, az)
  │     └─ 发指令: self._mc.set_velocity(vx, az)    ← 你的任务
  │
  └─ navigator.is_done() / succeeded() → 推进状态机

MotionController (运动层)  ← 已封装好，直接用
  ├─ .pose              → 获取 cuVSLAM 里程计 (x, y, yaw_deg)
  ├─ .set_velocity()    → 发送速度指令到狗 (UDP)
  ├─ .move_forward()    → PID 前进 N 米
  ├─ .turn_to()         → PID 转向 N 度
  └─ .initialize()      → 心跳 + 自动模式 + yaw 标定

final_bridge.py (桥接层)
  └─ cuVSLAM Docker → UDP → /tmp/odom_latest.json
```

### 1.3 当前状态（2026-07-03）

| 模块 | 状态 | 备注 |
|------|------|------|
| cuVSLAM odom 文件桥接 | ✅ 工作 | `/tmp/odom_latest.json`, ~25Hz |
| SDK 协议 (320/321/325) | ✅ 工作 | MotionComplexCMD, `<3id` |
| 狗前进/转向 | ✅ 工作 | 手动测试通过 |
| MotionController API | ✅ 工作 | `navi/test/test_api_route.py` 验证 |
| Pure Pursuit | ✅ 工作 | 输出正确 vx/az |
| A* 规划 | ✅ 工作 | 路径正确 |
| Navigator odom 读取 | ⚠️ 有重复 | 需要换成 MotionController.pose |
| Navigator UDP 发送 | ⚠️ 有重复 | 需要换成 MotionController.set_velocity |
| DDS / ROS2 /cmd_vel | ❌ 不通 | Jetson 跨进程 DDS 故障，已绕过 |
| cuVSLAM 定位 | ⚠️ 有延迟 | ~1-2s 延迟, 转弯后可能冻住 |
| 腿里程计 | ❌ 不可用 | 解析偏移未解决 |
| Odom 冻结看门狗 | ✅ 已封装 | MotionController 内置 |

---

## 2. 文件关系

```
src/navigation/
│
├── navigator.py              ← 【核心，你需要改的文件】
│   │   主控类 Navigator，被 task_manager 调用
│   │   约 560 行，其中 ~150 行跟 MotionController 重复
│   │
│   ├── 外部依赖:
│   │   ├── map_grid.py        — 场地栅格
│   │   ├── astar_planner.py   — A* 搜索
│   │   ├── pure_pursuit.py    — 纯追踪控制器  
│   │   └── local_obstacle.py  — 点云局部避障
│   │
│   └── 需要引入:
│       └── motion/motion_controller.py  ← 你的任务
│
├── motion/                   ← 【封装好的 API，不动它】
│   ├── __init__.py
│   ├── motion_controller.py  ← MotionController 实现
│   └── README.md
│
├── astar_planner.py          ← A* 8邻域搜索
├── pure_pursuit.py           ← 纯追踪速度计算
├── map_grid.py               ← 场地→栅格
└── local_obstacle.py         ← 深度点云避障

navi/motion/                  ← 【原始 API 副本，不动它】
navi/test/                    ← 测试脚本
  ├── test_api_route.py       ← API 路线测试
  ├── test_route.py           ← 综合路线测试
  ├── test_pid_abs.py         ← 绝对坐标测试
  └── test_turn.py            ← 纯转向测试
```

---

## 3. 你的任务：集成 MotionController 到 Navigator

### 3.1 替换清单

在 `navigator.py` 中：

| 删除 | 替换为 | 原因 |
|------|--------|------|
| `_read_odom_file()` (整个方法) | `self._mc.pose` | odom 读取 |
| `_apply_odom_pose()` (整个方法) | MotionController 内部处理 | yaw 标定 |
| `_odom_callback()` (ROS2 odom) | 删除 | DDS 从来不通 |
| `_publish_cmd_vel()` 中 UDP 部分 | `self._mc.set_velocity(vx, az)` | 狗指令 |
| `_has_odom` | `self._mc.has_odom` | odom 状态 |
| yaw 校准逻辑 | `mc.initialize(desired_start_yaw_deg=180)` | 初始化 |
| socket 创建 (`_udp_sock`) | MotionController 内部 | socket 管理 |

**保留不变项**：
- `_publish_cmd_vel()` 中 **ROS2 /cmd_vel pub** 和 **CSV 日志** — 可以保留用于调试
- A* 规划、Pure Pursuit、障碍检测 — 不动
- Public API (`navigate_to_waypoint`, `is_done`, `succeeded`) — 不动

### 3.2 集成步骤

#### Step 1: 导入

```python
# navigator.py 顶部
from .motion import MotionController
```

#### Step 2: 初始化 (在 `__init__` 中)

```python
# 替换原来 socket 创建 + yaw 校准部分

# 原来:
# self._odom_offset_yaw = ...
# self._odom_cos = ...
# self._yaw_calibrated = False

# 改为:
self._mc = MotionController()
self._mc.initialize(
    desired_start_yaw_deg=ROBOT_START_POSE["yaw_deg"]  # 比赛起点 180度
)
```

`initialize()` 自动完成：心跳脉冲、自动模式(0x21010C03)、yaw 标定。

#### Step 3: 替换 odom 读取 (在 `_control_loop` 中)

```python
def _control_loop(self):
    # 原来: self._read_odom_file()
    # 改为:
    x, y, yaw_deg = self._mc.pose
    self._current_x = x + self._odom_offset_x   # map 偏移
    self._current_y = y + self._odom_offset_y
    self._current_yaw = math.radians(yaw_deg)
    self._has_odom = self._mc.has_odom
    
    # 原来: if not self._has_odom: return
    # 改为同时检查:
    if not self._has_odom:
        return
```

注意：`_mc.pose` 返回的是**相对里程计起始位置**的坐标。需要加上 `_odom_offset_x/y` 变成 map 坐标。

#### Step 4: 替换 UDP 发送 (在 `_publish_cmd_vel` 中)

```python
def _publish_cmd_vel(self, vx, az):
    # ROS2 pub 保留（调试用）
    msg = Twist()
    msg.linear.x = float(vx)
    msg.angular.z = float(az)
    self._cmd_vel_pub.publish(msg)
    
    # CSV 日志保留（调试用）
    self._cmd_log_file.write(f'{time.time():.3f},{vx:.4f},{az:.4f}\n')
    self._cmd_log_file.flush()
    
    # UDP 发送 — 用 MotionController 替代
    self._mc.set_velocity(vx, az)
```

#### Step 5: 清理 (在 shutdown 中)

```python
def shutdown(self):
    self._mc.shutdown()  # 停狗 + 关 socket
```

### 3.3 MotionController API 速查

```python
mc = MotionController(
    dog_ip="192.168.1.120",  # 狗 IP
    dog_port=43893,           # 狗 UDP 端口
)
mc.initialize(desired_start_yaw_deg=180)  # 必调用

# ── Navigator 用 ──────────────────
# 位置 (每 10Hz 控制循环读):
x, y, yaw_deg = mc.pose           # (m, m, deg), 已标定
mc.has_odom                        # bool

# 速度指令 (每 10Hz 控制循环发):
mc.set_velocity(vx, az)            # vx: m/s, az: rad/s (ROS 惯例)
mc.stop()                          # 停狗

# ── task_manager 可以选用的高层 API ──
mc.move_forward(3.0)               # 前进 3m (PID, 阻塞)
mc.turn_to(90)                     # 转向 90° (PID, 阻塞)

# ── 生命周期 ──
mc.shutdown()                      # 停狗 + 关 socket + 停线程
```

### 3.4 代码量变化预估

```
改动前 navigator.py:  ~560 行
改动后 navigator.py:  ~420 行  (净减 ~140 行重复代码)
MotionController:     ~310 行  (封装好的，不动)
```

---

## 4. 调试指南

### 4.1 硬件连接

```
Jetson Xavier NX (192.168.1.111) ──eth0── 狗 (192.168.1.120)
                                    │
                              D455i USB3
```

### 4.2 启动完整系统

```bash
# 一键启动（Docker + 桥接 + 狗 + 比赛）
bash scripts/start_competition.sh --dog

# 或分步：
# 1. Docker cuVSLAM
CUVSLAM_MOUNT_MODE=robot CUVSLAM_PROFILE=planar_60fps \
  bash scripts/start_cuvslam_rviz_gui.sh --no-rviz

# 2. 中继 + 桥接 + 狗
bash scripts/start_competition.sh --dog   # 会自动检测 Docker 已在跑

# 3. 仅重启比赛（不动 Docker/狗）
source install/setup.bash
ros2 launch quadruped_robot_competition competition.launch.py \
  enable_task_manager:=true enable_navigation:=true
```

### 4.3 常见问题

| 症状 | 检查 | 命令 |
|------|------|------|
| Navigator 不动 | odom 文件有数据？ | `cat /tmp/odom_latest.json` |
| Navigator 不动 | 狗网络通？ | `ping 192.168.1.120` |
| 狗不动 | 心跳在跑？ | `ps aux \| grep lite3_init` |
| 狗不动 | 自动模式？ | `tail /tmp/lite3_init.log` |
| 狗走歪/转圈 | yaw 校准值？ | 看 competition.log 的 "Yaw calibrated" |
| odom 冻住 | bridge 在跑？ | `ps aux \| grep final_bridge` |
| CPU 过高 | loop_metrics? | `docker exec <容器名> pkill loop_metrics` |
| 僵尸进程 | 清理 | `bash scripts/stop_all.sh` |

### 4.4 手动测试狗

```bash
# 验证狗能走（不依赖导航）
python3 -c "
import socket,struct,time
s=socket.socket(2,2); a=('192.168.1.120',43893)
for _ in range(5): s.sendto(struct.pack('<3i',0x21040001,0,0),a); time.sleep(0.1)
s.sendto(struct.pack('<3i',0x21010C03,0,0),a); time.sleep(1)
for _ in range(30): s.sendto(struct.pack('<3id',320,8,1,0.3),a); time.sleep(0.1)
s.sendto(struct.pack('<3id',320,8,1,0.0),a)
"
```

### 4.5 测试 MotionController API

```bash
cd ~/quadruped-robot-competition
python3 navi/test/test_api_route.py
```

### 4.6 关键日志位置

```
~/Desktop/logs/competition_*.log        # 比赛主日志
/tmp/competition.log                    # 比赛进程日志
/tmp/fb.log 或 /tmp/final_bridge.log    # Bridge 日志
/tmp/lite3_init.log                     # 狗初始化日志
/tmp/odom_latest.json                   # 最新 odom 数据
~/competition_logs/cmd_vel_direct.csv   # 速度指令 CSV
```

### 4.7 快速诊断命令

```bash
echo "=== 进程 ==="
ps aux | grep -E "task_manager|final_bridge|lite3_init" | grep -v grep

echo "=== 狗网络 ==="
ping -c 1 192.168.1.120

echo "=== Odom ==="
python3 -c "import json; d=json.load(open('/tmp/odom_latest.json')); print(f'x={d[\"x\"]:.2f} y={d[\"y\"]:.2f}')"

echo "=== 比赛阶段 ==="
grep -E "Yaw|A\*|Stuck|goal|timeout" /tmp/competition.log | tail -5
```

---

## 5. 狗通信协议速查

| 指令 | 码 | 格式 | 说明 |
|------|-----|------|------|
| 心跳 | 0x21040001 | SimpleCMD `<3i` | 狗 250ms 无心跳自动停 |
| 前进速度 | 320 (0x0140) | ComplexCMD `<3id` | [-1.0, 1.0] m/s |
| 转向速度 | 321 (0x0141) | ComplexCMD `<3id` | [-1.5, 1.5] rad/s, **取反** |
| 自动模式 | 0x21010C03 | SimpleCMD `<3i` | 必须！否则狗不响应速度指令 |
| 软急停 | 0x21010C0E | SimpleCMD `<3i` | 趴下 |

**关键规则**：
1. 心跳和运动指令必须**同一 socket** 发出
2. 每周期只发**一种**运动指令（后发的覆盖前者）
3. 必须先发 `0x21010C03`（自动模式）才能用速度指令
4. 角速度要取反：`data = -az`（ROS 惯例 +左 → 狗协议取反）

---

## 6. 联系人

- 原开发者: youngman05
- 代码分支: `refactor/sdk-protocol-fix`
- GitHub: https://github.com/youngman05/quadruped-robot-competition/tree/refactor/sdk-protocol-fix
- 文档: `docs/ARCHITECTURE.md`（完整架构文档）
