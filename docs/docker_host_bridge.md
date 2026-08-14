# Docker YOLO -> Host Bridge Startup

本文记录 2026-08-12 在 Xavier 真机上已经验收通过的启动方法。目标链路为：

```text
D455 (Docker ROS 2 Humble)
  -> /d455_object_yolo_3d
  -> UDP JSON, camera_link, 127.0.0.1:19002
  -> Host yolo_udp_bridge (ROS 2 Foxy)
  -> TF: base_link <- camera_link
  -> /yolo/detections, std_msgs/msg/String, JSON, base_link
```

下游需要“类别 + 三维坐标”时，只使用 `/yolo/detections`。`/block/detections`
是 `geometry_msgs/msg/PoseArray`，不保留 `red`/`green` 类别，不能作为抓取任务的正式接口。

## 固定环境

```text
Xavier SSH:       superwfx666@100.126.48.49
Xavier hostname:  superwfx666-desktop
Host ROS:         Foxy
Docker ROS:       Humble
Worktree:         /home/superwfx666/worktrees/quadruped-vision-yolo-refactor
Container:        d455_yolo_repro_20260811
Image:            d455-yolo:pick-test-20260811
UDP endpoint:     127.0.0.1:19002
```

容器已经配置 `network=host`、NVIDIA runtime、代码/模型/Host Python 包挂载。
其 restart policy 为 `no`，Xavier 或 Docker 重启后必须手动执行本文流程。

远程连接较慢时使用：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=30 superwfx666@100.126.48.49
```

以下命令均应在 **Xavier 本机终端或 SSH 登录后的 Xavier shell** 中执行，
不要再嵌套一层 SSH 命令字符串。

## 1. 恢复容器和 D455

```bash
docker start d455_yolo_repro_20260811
docker inspect -f '{{.State.Status}}' d455_yolo_repro_20260811
docker top d455_yolo_repro_20260811
docker logs --tail 50 d455_yolo_repro_20260811
```

预期状态为 `running`，日志中应看到：

```text
RGB 640x360 @ 30 FPS
Raw Depth 640x360 Z16 @ 60 FPS
```

不要另外启动第二个 RealSense 进程。YOLO 节点与相机 ROS 节点在同一容器内，
直接复用容器中的相机 topic。

## 2. 启动 Docker YOLO 3D

先通过 `docker top` 确认没有已有的 `d455_yolo_3d_node.py`。若没有，执行：

```bash
docker exec -d \
  -e PYTHONPATH=/opt/host-python:/opt/quadruped/perception/bin \
  -e LD_LIBRARY_PATH=/usr/local/cuda-11.4/targets/aarch64-linux/lib \
  d455_yolo_repro_20260811 \
  /bin/bash /opt/quadruped/perception/bin/run_yolo_3d_node.sh \
  --ros-args \
  -p max_fps:=5.0 \
  -p udp_host:=127.0.0.1 \
  -p udp_port:=19002
```

检查进程：

```bash
docker top d455_yolo_repro_20260811
```

预期出现：

```text
python3 /opt/quadruped/perception/bin/d455_yolo_3d_node.py ...
```

可在启动 Host bridge **之前**直接检查 UDP：

```bash
timeout 8 nc -u -l 127.0.0.1 19002
```

预期收到类似数据：

```json
{
  "frame_id": "camera_link",
  "detections": [
    {
      "class_name": "red",
      "position_valid": true,
      "position_m": [0.844, -0.232, 0.106]
    }
  ]
}
```

`nc` 和 bridge 不能同时监听 UDP 19002；看到数据后让 `timeout` 正常结束，
再启动 bridge。

## 3. 启动 Host 静态 TF

D455 标定外参来自 `configs/transforms/static_extrinsics.yaml`：

```text
base_link -> camera_link
translation xyz: [0.231724440, 0.077561412, 0.503275873]
quaternion xyzw: [0.000900958, 0.240529563, -0.013474058, 0.970547870]
```

真机测试中，Foxy C++ `static_transform_publisher` 进程虽然存在，但 Python
bridge 在 Xavier 的 Fast DDS 环境中看不到该 TF。已验证可用的方法是让静态 TF
和 bridge 都使用 Host 的 `rclpy`/Fast DDS。

每次 Xavier 重启后创建临时脚本：

```bash
cat >/tmp/yolo_camera_static_tf.py <<'PY'
#!/usr/bin/python3
import rclpy
from geometry_msgs.msg import TransformStamped
from rclpy.node import Node
from tf2_ros.static_transform_broadcaster import StaticTransformBroadcaster

rclpy.init()
node = Node("yolo_camera_static_tf_py")
broadcaster = StaticTransformBroadcaster(node)

msg = TransformStamped()
msg.header.stamp = node.get_clock().now().to_msg()
msg.header.frame_id = "base_link"
msg.child_frame_id = "camera_link"
msg.transform.translation.x = 0.231724440
msg.transform.translation.y = 0.077561412
msg.transform.translation.z = 0.503275873
msg.transform.rotation.x = 0.000900958
msg.transform.rotation.y = 0.240529563
msg.transform.rotation.z = -0.013474058
msg.transform.rotation.w = 0.970547870

broadcaster.sendTransform(msg)
rclpy.spin(node)
PY
```

设置 Host ROS 环境并启动 TF：

```bash
source /opt/ros/foxy/setup.bash
source /home/superwfx666/worktrees/quadruped-vision-yolo-refactor/install/setup.bash

export ROS_DOMAIN_ID=0
export ROS_LOCALHOST_ONLY=1
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

nohup python3 /tmp/yolo_camera_static_tf.py \
  >/tmp/yolo_camera_static_tf.log 2>&1 </dev/null &
echo $! >/tmp/yolo_camera_static_tf.pid
```

在启动 bridge 前必须先确认 TF 可见：

```bash
ros2 node list --no-daemon
timeout 5 ros2 run tf2_ros tf2_echo base_link camera_link
```

预期包含：

```text
/yolo_camera_static_tf_py
Translation: [0.232, 0.078, 0.503]
Quaternion: [0.001, 0.241, -0.013, 0.971]
```

`/tmp/yolo_camera_static_tf.py` 会在系统重启后丢失，因此重启后需要重新执行本节。

## 4. 启动 Host Bridge

继续使用第 3 节已经设置好的 Host ROS 环境：

```bash
nohup ros2 run quadruped_robot_competition yolo_udp_bridge \
  --ros-args \
  -p udp_bind_host:=127.0.0.1 \
  -p udp_port:=19002 \
  -p source_frame:=camera_link \
  -p target_frame:=base_link \
  -p max_packet_age_s:=0.5 \
  -p min_depth_valid_ratio:=0.60 \
  >/tmp/yolo_udp_bridge.log 2>&1 </dev/null &
echo $! >/tmp/yolo_udp_bridge.pid
```

必须先启动并验收 TF，再启动 bridge。测试中 bridge 在 TF 缺失时启动后，Foxy
TF buffer 不能稳定恢复；发生这种情况时应先恢复 TF，然后重启 bridge。

## 5. 链路验收

检查 UDP listener 和 bridge 日志：

```bash
ss -lunp | grep ':19002'
tail -n 30 /tmp/yolo_udp_bridge.log
```

日志预期持续出现：

```text
UDP 127.0.0.1:19002 -> base_link
Published base_link detections=6 valid=5/6 sequence=...
```

检查正式 ROS 接口：

```bash
ros2 topic type /yolo/detections
timeout 8 ros2 topic echo /yolo/detections
```

topic 类型必须是：

```text
std_msgs/msg/String
```

其 `data` 字段是 JSON。验收通过的数据应满足：

- `frame_id` 为 `base_link`；
- `sequence` 持续增长；
- 检测结果保留 `class_name`；
- 有效目标的 `position_valid` 为 `true`，`position_m` 为 base_link 下的 XYZ 米制坐标。

真机验收时实际得到过以下有效目标。下面是从正式消息的 `detections` 中提取的
类别和坐标简表，不是完整线上报文；完整字段定义以
`configs/yolo/host_detection_v1.schema.json` 为准：

```json
{
  "sequence": 1348,
  "frame_id": "base_link",
  "inference_ms": 345.597,
  "detections": [
    {"class_name": "obstacle", "position_m": [3.5650, -0.1578, -0.0558]},
    {"class_name": "green", "position_m": [1.0247, 0.0235, 0.1999]},
    {"class_name": "green", "position_m": [0.9845, -0.3073, 0.2104]},
    {"class_name": "red", "position_m": [1.0329, -0.1765, 0.2115]},
    {"class_name": "red", "position_m": [1.0754, 0.2462, 0.2064]}
  ]
}
```

以上数值只证明链路与坐标变换正常，不是抓取阶段的固定目标值。

## 快速启动清单

在 Xavier shell 中按顺序执行：

```bash
# 1. Container and camera
docker start d455_yolo_repro_20260811
docker top d455_yolo_repro_20260811

# 2. Docker YOLO (skip this command if docker top already shows the node)
docker exec -d \
  -e PYTHONPATH=/opt/host-python:/opt/quadruped/perception/bin \
  -e LD_LIBRARY_PATH=/usr/local/cuda-11.4/targets/aarch64-linux/lib \
  d455_yolo_repro_20260811 \
  /bin/bash /opt/quadruped/perception/bin/run_yolo_3d_node.sh \
  --ros-args -p max_fps:=5.0 -p udp_host:=127.0.0.1 -p udp_port:=19002

# 3. Host environment; create the /tmp TF script from section 3 first
source /opt/ros/foxy/setup.bash
source /home/superwfx666/worktrees/quadruped-vision-yolo-refactor/install/setup.bash
export ROS_DOMAIN_ID=0
export ROS_LOCALHOST_ONLY=1
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

nohup python3 /tmp/yolo_camera_static_tf.py \
  >/tmp/yolo_camera_static_tf.log 2>&1 </dev/null &
echo $! >/tmp/yolo_camera_static_tf.pid
timeout 5 ros2 run tf2_ros tf2_echo base_link camera_link

# 4. Bridge (only after tf2_echo succeeds)
nohup ros2 run quadruped_robot_competition yolo_udp_bridge \
  --ros-args \
  -p udp_bind_host:=127.0.0.1 -p udp_port:=19002 \
  -p source_frame:=camera_link -p target_frame:=base_link \
  -p max_packet_age_s:=0.5 -p min_depth_valid_ratio:=0.60 \
  >/tmp/yolo_udp_bridge.log 2>&1 </dev/null &
echo $! >/tmp/yolo_udp_bridge.pid

# 5. Acceptance
tail -n 30 /tmp/yolo_udp_bridge.log
timeout 8 ros2 topic echo /yolo/detections
```

## 停止和重启

本文启动命令会记录 Host 进程 PID。先查看 PID 对应的命令，再停止：

```bash
ps -fp "$(cat /tmp/yolo_udp_bridge.pid)" "$(cat /tmp/yolo_camera_static_tf.pid)"

# ros2 run is a wrapper; stop its direct child first, then the wrapper.
bridge_pid=$(cat /tmp/yolo_udp_bridge.pid)
bridge_child=$(pgrep -P "$bridge_pid")
[ -z "$bridge_child" ] || kill $bridge_child
kill "$bridge_pid" 2>/dev/null || true

tf_pid=$(cat /tmp/yolo_camera_static_tf.pid)
kill "$tf_pid" 2>/dev/null || true
```

停止整个 Docker 感知容器（同时停止 RealSense 和 YOLO）：

```bash
docker stop d455_yolo_repro_20260811
```

只重启 Host 侧时，按“TF -> `tf2_echo` 验收 -> bridge”的顺序重新执行第 3、4 节。
若 PID 文件不存在，先用以下命令查看实际进程，再对明确 PID 执行 `kill PID`：

```bash
pgrep -af 'yolo_udp_bridge|yolo_camera_static_tf.py'
```

不要使用宽泛的 `pkill -f`，尤其不要把它放在包含同一匹配字符串的嵌套 SSH
命令中，否则可能杀掉当前 SSH shell。

## 故障定位

### Bridge 日志停在 `waiting_for_udp`

依次检查：

```bash
docker top d455_yolo_repro_20260811
docker logs --tail 50 d455_yolo_repro_20260811
ss -lunp | grep ':19002'
```

常见原因是 YOLO 进程未启动、容器不是 host network，或已有 bridge/`nc` 占用
19002。一个时刻只保留一个 UDP listener。

### 日志提示 `base_link does not exist`

Host 没有收到 `base_link -> camera_link`。确认第 3 节的环境变量和 Python TF
进程，直到 `tf2_echo base_link camera_link` 成功；然后停止并重启 bridge。

### Docker 内出现 `ros2cli DistributionNotFound`

Host Python 包没有进入容器的模块搜索路径。不要省略
`PYTHONPATH=/opt/host-python:/opt/quadruped/perception/bin`，使用第 2 节完整的
`docker exec -e ...` 命令。

### 脚本报告 `No such file`

此前在嵌套 SSH 引号中直接执行脚本遇到过该错误。登录 Xavier 后执行本文命令，
并保留显式形式：

```bash
/bin/bash /opt/quadruped/perception/bin/run_yolo_3d_node.sh
```

### ROS 节点或 TF 在 Host 不可见

Xavier 有多个网卡，Host 侧已验证需要：

```bash
export ROS_DOMAIN_ID=0
export ROS_LOCALHOST_ONLY=1
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
```

同时不要启动旧的 `yolo_detect_publisher`，它不能与当前 bridge 同时发布
`/yolo/detections`。
