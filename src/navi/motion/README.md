# Motion Controller API

统一的 Lite3 机器狗运动控制接口，供 Navigator 和 task_manager 调用。

## 架构

```
Navigator / task_manager
        │
        ▼
┌───────────────────┐
│  MotionController │  ← 本模块
│                   │
│  set_velocity()   │──→ UDP MotionComplexCMD (320/321) ──→ 狗
│  turn_to()        │──→ PID 闭环转向
│  move_forward()   │──→ PID 闭环前进
│  pose             │←── cuVSLAM odom (/tmp/odom_latest.json)
│  watchdog         │←── odom 冻结检测 → 自动趴下
└───────────────────┘
```

**数据流**：
- **出站**：`set_velocity(vx, az)` → 心跳(SimpleCMD) + 运动(MotionComplexCMD) → UDP `192.168.1.120:43893`
- **入站**：`pose` 属性 ← 读取 `/tmp/odom_latest.json`（final_bridge 写入）← cuVSLAM Docker

## 快速开始

```python
from navi.motion import MotionController, OdomFreezeError

mc = MotionController()
mc.initialize()  # 自动：心跳 + 自动模式 + yaw标定

# 前进 2 米
mc.move_forward(2.0)

# 左转 90 度
mc.turn_to(90)

# 关闭
mc.shutdown()
```

## API 参考

### 初始化

```python
mc = MotionController(
    dog_ip="192.168.1.120",   # 狗 IP
    dog_port=43893,            # 狗 UDP 端口
    odom_file="/tmp/odom_latest.json"  # cuVSLAM odom 文件
)

mc.initialize(
    desired_start_yaw_deg=0.0,  # 当前物理朝向对应的偏航角（0=前方是+X）
    calibrate_yaw=True           # 自动标定偏航角
)
```

`initialize()` 自动完成：
1. 启动 odom 读取线程（~25Hz）
2. 等待首帧里程计数据
3. 发送心跳脉冲
4. 设置自动模式 + 移动模式
5. 标定偏航角偏移（补偿 cuVSLAM 初始朝向偏差）

### 位置查询

```python
x, y, yaw = mc.pose      # (m, m, deg)，已标定，相对起始位置
mc.has_odom               # bool，是否收到过里程计
mc.odom_stale_sec         # float，距上次 odom 更新秒数
```

### 低层速度控制（Navigator 纯追踪用）

```python
mc.set_velocity(vx, az)
```

- `vx`: 前进速度 (m/s)，正值=前进，范围 [-1.0, 1.0]
- `az`: 角速度 (rad/s)，正值=左转（ROS 惯例），范围 [-1.5, 1.5]
- 内部自动处理：心跳、SDK 角速度符号取反、只发一种运动指令
- 非阻塞，适合 10Hz 控制循环
- 如果 `vx≈0` 且 `az≈0`，发送停止指令

### 高层 PID 控制（task_manager 用）

```python
# 原地转向到绝对偏航角
ok = mc.turn_to(target_yaw_deg=180, timeout=20.0)
# 返回 True=到达（误差 <5°），False=超时

# 前进指定距离
ok = mc.move_forward(distance_m=3.0, timeout=60.0)
# 返回 True=到达（误差 <6cm），False=超时
```

内部实现：
- **转向**：P 控制器，Kp=0.03，限幅 ±0.8 rad/s，死区 5°，最低转速 0.08 rad/s
- **前进**：P 控制器，全速 0.35 m/s，距目标 30cm 开始线性减速至 0.08 m/s，死区 6cm

### 看门狗

```python
# 手动检查
mc._check_watchdog()  # odom 冻结 >0.4s 暂停，>5s 自动趴下 + 抛异常

# 或捕获异常
try:
    mc.move_forward(3.0)
except OdomFreezeError:
    print("odom lost, dog laid down")
```

`turn_to()` 和 `move_forward()` 内部每次循环都调用 `_check_watchdog()`。

### 清理

```python
mc.stop()        # 发送零速
mc.lie_down()    # 软急停（趴下）
mc.shutdown()    # 停狗 + 关 socket + 停线程
```

## 狗通信协议

### 命令格式

| 指令 | 码 | 格式 | 范围 |
|------|-----|------|------|
| 心跳 | 0x21040001 | SimpleCMD `<3i` | — |
| 前进速度 | 320 (0x0140) | ComplexCMD `<3id` | [-1.0, 1.0] m/s |
| 角速度 | 321 (0x0141) | ComplexCMD `<3id` | [-1.5, 1.5] rad/s |

### 关键规则

1. **心跳必须同源**：运动指令和心跳从同一 socket 发出
2. **每周期一种指令**：狗固件以最后收到的 MotionComplexCMD 为准
3. **自动模式必须**：需先发送 `0x21010C03` + `0x21010D06`
4. **角速度取反**：ROS 惯例 +az=左转 → 狗协议取反 → `data = -az`
5. **超时**：狗 250ms 无指令自动停止

## Navigator 集成示例

替换原有的 `_publish_cmd_vel` 和 odom 回调：

```python
from navi.motion import MotionController

class Navigator:
    def __init__(self, node):
        self._mc = MotionController()
        self._mc.initialize(
            desired_start_yaw_deg=180  # 比赛起点朝向后场
        )

    def _control_loop(self):
        # 用 mc.pose 替代 _read_odom_file
        self._current_x, self._current_y, yaw_deg = self._mc.pose
        self._current_yaw = math.radians(yaw_deg)
        self._has_odom = self._mc.has_odom

        # ... A* + Pure Pursuit ...

        # 用 mc.set_velocity 替代 _publish_cmd_vel
        self._mc.set_velocity(vx, az)

    def shutdown(self):
        self._mc.shutdown()
```

## 测试脚本

原独立调试目录已移除；保留的导航/里程计调试入口在 `scripts/`：

```bash
python3 scripts/test_leg_odom_pid.py --route "5,0; 0,-1"
```
