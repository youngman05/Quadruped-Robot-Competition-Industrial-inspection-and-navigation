# Navigation Bridge README

本文档给导航同学使用，说明当前 cuVSLAM 数据如何从 Docker 透传到 Host，以及导航栈应该接哪个接口。

## 当前结论

Docker 到 Host 的穿透问题已经基本解决。现在数据链路是：

```text
D455
  -> Docker / Humble: realsense2_camera + Isaac ROS Visual SLAM
  -> Docker topic: /visual_slam/vis/slam_odometry
  -> Docker exporter: scripts/cuvslam_odometry_udp_exporter.py
  -> UDP localhost: 127.0.0.1:19001
  -> Host / Foxy bridge: scripts/final_bridge.py
  -> Host topic: /odom
  -> Host TF: odom -> base_link
  -> Navigation / Nav2 / custom navigator
```

导航同学正常只需要接 Host 侧的 `/odom` 和 TF，不需要直接进入 Docker 订阅 cuVSLAM 原始话题。

## 导航应该接哪里

### 必接接口

Host ROS 2 Foxy 侧：

```text
/odom
```

消息类型：

```text
nav_msgs/msg/Odometry
```

TF：

```text
odom -> base_link
```

当前 `scripts/final_bridge.py` 会同时发布 `/odom` 和 `odom -> base_link` TF。导航栈如果只做基础接入，应直接消费这两个接口。

### /odom 数据内容

`/odom` 是从 Docker 内 cuVSLAM odometry 转出来的，包含：

```text
header.stamp
header.frame_id
child_frame_id
pose.pose.position
pose.pose.orientation
pose.covariance
twist.twist.linear
twist.twist.angular
twist.covariance
```

当前 Host 侧 frame contract 固定为：

```text
header.frame_id: odom
child_frame_id: base_link
```

重要：`header.stamp` 使用 cuVSLAM 原始 source timestamp，不是 Host 收到数据时临时生成的时间。导航侧可以用它判断数据是否过期。

## Docker 里面原始数据是什么

Docker 内部原始 topic：

```text
/visual_slam/vis/slam_odometry
```

消息类型：

```text
nav_msgs/msg/Odometry
```

这个 topic 由 Isaac ROS Visual SLAM / cuVSLAM 发布。Docker exporter 订阅它后，把以下字段打包成 JSON，通过 UDP 发给 Host：

```text
stamp.sec
stamp.nanosec
frame_id
child_frame_id
pose.position
pose.orientation
pose_covariance
twist.linear
twist.angular
twist_covariance
seq
```

导航同学一般不要直接依赖这个 Docker topic，因为 Host Foxy 和 Docker Humble 跨环境 DDS 数据面之前不稳定。当前正式穿透路径是 UDP bridge。

## 启动方式

### 方式一：只修复 / 重建 bridge

如果 cuVSLAM Docker 已经在跑，只需要重建 Host `/odom`：

```bash
cd ~/quadruped-robot-competition
bash scripts/fix_bridge.sh
```

成功标志：

```text
Bridge log:
... bridged ... UDP msgs | stamp=... (source)

[OK] /odom BEST_EFFORT probe
```

如果 probe 是 `[WARN]`，说明数据通了，但实时性可能不好；导航可以先接入，但不要认为定位质量已经合格。

### 方式二：比赛一键启动

```bash
cd ~/quadruped-robot-competition
bash scripts/start_competition.sh
```

可选：

```bash
bash scripts/start_competition.sh --whz
bash scripts/start_competition.sh --yolo
bash scripts/start_competition.sh --log
```

该脚本会启动：

```text
cuVSLAM Docker
camera/depth relay
UDP bridge
/odom probe
competition launch
```

## 导航侧验证命令

在 Host 上：

```bash
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_DOMAIN_ID=0
export FASTRTPS_DEFAULT_PROFILES_FILE=~/quadruped-robot-competition/configs/ros/fastrtps_no_shm.xml
```

检查 `/odom`：

```bash
python3 scripts/probe_odom_best_effort.py --duration 5 --first-timeout 2 --no-color
```

优先看这些字段：

```text
count
rate_host
rate_source_stamp
latency_p95
latency_max
latency_status
```

不要把 `ros2 topic echo /odom` 当唯一判断标准。当前 Foxy CLI 在这个环境下可能因为 QoS / CLI 行为问题看不到数据，而 Python BEST_EFFORT probe 能正常收到。

检查 TF：

```bash
ros2 run tf2_ros tf2_echo odom base_link
```

检查 topic 存在：

```bash
ros2 topic list | grep -E '^/odom$|^/tf$'
```

## 导航代码怎么订阅

Python 节点建议使用 BEST_EFFORT QoS：

```python
from nav_msgs.msg import Odometry
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy

odom_qos = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)

self.odom_sub = self.create_subscription(
    Odometry,
    "/odom",
    self.odom_callback,
    odom_qos,
)
```

如果导航栈或 Nav2 参数默认用 RELIABLE 订阅传感器类数据，可能出现 topic 存在但收不到数据的 QoS mismatch。遇到这种情况，先查 QoS，不要先怀疑 Docker 穿透。

## Nav2 / 自研导航接入建议

### 最小接入

先让导航直接消费：

```text
odom topic: /odom
base frame: base_link
odom frame: odom
```

此时 `final_bridge.py` 已经发布：

```text
odom -> base_link
```

不要再让另一个节点同时发布同一条 TF，否则 TF 树会冲突。

### 如果要用 robot_localization / EKF

当前仓库有：

```text
configs/navigation/ekf_cuvslam_planar.yaml
launch/ekf_cuvslam_planar.launch.py
```

但注意：这份 EKF 配置是骨架，不应不改就直接用于当前 UDP bridge。

如果 EKF 要融合当前 bridge 输出，应把输入改为：

```yaml
odom0: /odom
```

并且必须解决 TF 所有权：

```text
方案 A：final_bridge.py 发布 odom -> base_link，EKF publish_tf=false
方案 B：final_bridge.py 只发布视觉 odom，不发布 TF；EKF publish_tf=true
```

当前代码默认是方案 A 的基础模式：`final_bridge.py` 已经发布 `/odom` 和 `odom -> base_link`。如果没有改 bridge，不要再让 EKF 发布同一条 `odom -> base_link`。

长期更推荐方案 B：把 cuVSLAM 作为观测输入，例如 `/cuvslam/odom`，由 EKF 融合机身 odom / IMU 后统一发布 `/odom` 和 TF。但这需要额外改 bridge，目前不是最小接入路径。

## 当前已知风险

### 1. 穿透已通，但实时性还在优化

最近一次远端验证：

```text
count: 251
rate_host: 50.13 Hz
rate_source_stamp: 48.11 Hz
latency_mean_host_now_minus_source: 141.10 ms
latency_p95: 213.60 ms
latency_max: 433.36 ms
latency_status: unstable_or_backlogged
```

这说明数据能稳定从 Docker 到 Host，但当前 `planar_60fps` 链路可能有排队延迟。导航接入可以继续做，但实车闭环前必须优化为 latest-only：

```text
QoS KEEP_LAST depth=1
UDP drain to latest
stale odom drop
```

目标是让 `latency_p95` 降到几十毫秒级。

### 2. 不能让机器人直接运动

现场安全确认前，只允许观察 `/cmd_vel`，不要把非零 `/cmd_vel` 接到底盘。

### 3. frame 必须统一

导航侧统一使用：

```text
map -> odom -> base_link
```

当前 bridge 提供：

```text
odom -> base_link
```

如果 Nav2 的 `global_frame` 使用 `map`，还需要由定位系统提供 `map -> odom`。临时接口测试可以用 identity 静态 TF，但正式比赛不能长期用假的 `map -> odom`。

### 4. 相机外参仍要实测

最终精度取决于 D455 到机器人本体的外参：

```text
base_link -> camera_link
```

当前 bridge 已经把输出整理成 `base_link` 接口，但机器人上最终比赛精度仍需要确认实际安装位置、俯仰角、左右偏移和高度。

## 常见问题

### Q: 我应该订阅 Docker 内的 /visual_slam/vis/slam_odometry 吗？

不建议。导航接 Host 侧 `/odom`。Docker 内 topic 只作为 bridge 输入。

### Q: /odom 有数据但 ros2 topic echo 看不到，怎么办？

先用：

```bash
python3 scripts/probe_odom_best_effort.py --duration 5 --first-timeout 2 --no-color
```

如果 probe 能收到，说明数据通。问题大概率是 CLI echo 的 QoS / Foxy 行为，不是穿透断了。

### Q: 导航需要哪些最小数据？

最小需要：

```text
/odom
odom -> base_link TF
```

如果做完整 Nav2，还需要地图、costmap、障碍物输入和目标点接口。

### Q: bridge 出问题先看哪里？

Host：

```bash
tail -80 /tmp/fb.log
```

Docker exporter：

```bash
CN=$(docker ps --format '{{.Names}}' | grep cuvslam | head -1)
docker exec "$CN" tail -80 /tmp/cuvslam_odometry_udp_exporter.log
```

一键修复：

```bash
cd ~/quadruped-robot-competition
bash scripts/fix_bridge.sh
```

## 给导航同学的接入顺序

1. 启动 cuVSLAM 和 bridge，确认 `/odom` probe 能收到数据。
2. 让导航节点订阅 `/odom`，读取 `x/y/yaw`。
3. 用 `tf2_echo odom base_link` 确认 TF 正常。
4. 只在仿真或安全架空条件下观察 `/cmd_vel`。
5. 再接地图、路径规划和局部避障。
6. 实车前检查 latency、TF 冲突、frame 命名和 `/cmd_vel` 安全开关。

