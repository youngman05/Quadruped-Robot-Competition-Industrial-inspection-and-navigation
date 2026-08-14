# AprilTag 抓取交接与分段验收

本文是当前 AprilTag 抓取流程的现场调试交接文档。进入新对话时，直接提供本文件、
`docs/pickup_qr_implementation.md` 和当前 Xavier 日志即可继续。

## 当前结论

- 抓取阶段已改为 AprilTag，不使用二维码或 YOLO 做目标颜色识别。
- 四个 `tag36h11` Tag 固定贴在四个固定物块槽位下方的纸箱上；Tag 与红/绿物块的
  对应关系在贴码时固定。
- Docker 用 D455 的彩色图和 CameraInfo 检测 ID `0..3`，每张图将所有检测结果装入
  一个 UDP JSON 包，发送到 Host `127.0.0.1:19003`。
- Host 将 `camera_link` 检测结果用
  `configs/transforms/static_extrinsics.yaml` 中唯一的 `base_link -> camera_link`
  标定外参直接转换并发布到 `/apriltag/detections_base`。这条路径不依赖 Xavier 上
  不稳定的运行时 TF 发现。
- 在 I0，任务从 `pick_red_tag_ids` 中选择平面距离最近的可见 Tag，锁定其 ID；
  已成功抓取的 ID 在本条 route 内会被排除，避免纸箱上残留 Tag 被再次选中。
- I2 不是地图位姿，而是“机器人站在该槽位抓取姿态时，目标 Tag 在 `base_link`
  下的 `[x, y, yaw]`”。每个 ID 单独示教。
- I0 -> I2 使用离散、单轴的 `yaw -> x -> y` 脉冲控制：一次只下发一个非零轴，
  每次脉冲后停车、站稳并读取新帧。确认阶段不满足时回到第一个越界轴。
- 三个连续新帧满足 `|x| <= 0.03 m`、`|y| <= 0.03 m`、`|yaw| <= 3 deg` 才认为 I2
  对齐成功；内部超时为 80 s，route 外层超时为 90 s。
- I2 成功后，`pick_one` 直接调用已有 `/arm/execute_grasp_fixed` 服务。当前不做
  Tag 到 TCP 的在线计算；`pick_grasp_target_arm_base` 是既有机械臂服务需要的固定
  兼容参数。
- 放置阶段不在本次范围内。

## 坐标和接口

`base_link` 使用 ROS REP-103：`+X` 前、`+Y` 左、`+Z` 上；四元数顺序恒为 `xyzw`。

Docker UDP 输入输出约定：

```text
D455 image + CameraInfo
  -> AprilTag pose in camera_link
  -> UDP 127.0.0.1:19003
  -> /apriltag/detections_base (std_msgs/msg/String JSON)
  -> pose in base_link
```

Host 话题的 `String.data` 是 JSON，重要字段为：

```json
{
  "sequence": 42,
  "frame_id": "base_link",
  "detections": [{
    "tag_id": 0,
    "position_m": [0.70, 0.07, 1.39],
    "orientation_xyzw": [0.001, 0.241, -0.013, 0.971]
  }]
}
```

打印物理参数：Tag 黑色方块为 `72 mm`，白色裁切方块为 `90 mm`，Docker 检测参数
`tag_size_m=0.100`。已生成的补偿打印文件应使打印后的 100 mm 校验线为 100 mm。

## 已完成的实现与真机静态验收

核心实现文件：

- `docker/d455_perception/d455_apriltag_pose_node.py`
- `src/nodes/perception/apriltag_udp_bridge.py`
- `src/nodes/decision/pick_alignment_core.py`
- `src/nodes/decision/competition_manager.py`
- `configs/calibration/pick_i2_apriltag.yaml`

Xavier 信息：

```text
SSH:       superwfx666@100.126.48.49
worktree:  /home/superwfx666/worktrees/quadruped-vision-yolo-refactor
Docker:    d455_yolo_repro_20260811
Host ROS:  Foxy
Docker ROS: Humble
```

已在 Xavier 验收：

- Docker OpenCV 带 `cv2.aruco` 和 `DICT_APRILTAG_36h11`。
- 合成图可检测 IDs `0,1,2,3`。
- Docker AprilTag 节点、Host UDP bridge 可重复启动；UDP 19003 仅允许一个 bridge。
- 合成 UDP 的 `camera_link [0,0,1]` 被 Host 正确发布为 `base_link`
  `[0.699,0.069,1.388] m`。
- 相关单元测试在 Xavier 通过（16 项）。

尚未完成的现场工作：实际打印码识别、坐标方向确认、ID 0--3 的 I2 示教、底盘对齐、
以及抓取服务的整段验收。

## 每次断电后的恢复

以下命令在 Xavier 的工作区内执行。它们只恢复视觉和 Host bridge，不启动底盘或机械臂。

```bash
cd ~/worktrees/quadruped-vision-yolo-refactor
bash scripts/start_d455_apriltag.sh
bash scripts/start_apriltag_host_bridge.sh

source /opt/ros/foxy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=0
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

python3 scripts/probe_apriltag_bridge.py --frames 10 --timeout 15
```

预期：探针输出每帧的 `sequence`、可见 ID、`base_link xyz`、yaw 和帧间隔。
探针只订阅，不会控制狗或机械臂。

不要以 `ros2 topic echo` 作为 Xavier 上的唯一依据：Foxy/Fast DDS 的 CLI 图发现曾不稳定。
`probe_apriltag_bridge.py` 使用与任务节点相同的 rclpy 订阅方式，是正式验收工具。
Host bridge 启动脚本会加载 `configs/ros/fastrtps_no_shm.xml`，强制 Fast DDS 使用
UDPv4。Xavier 上 Docker 和 Host 共享 `/dev/shm` 时，默认 SHM transport 会导致
bridge 日志显示持续发布、其他 Host rclpy 进程却收不到消息。Host 订阅进程使用
`ROS_LOCALHOST_ONLY=0`；不要与旧命令中的 `ROS_LOCALHOST_ONLY=1` 混用。

常用日志：

```bash
docker exec d455_yolo_repro_20260811 tail -50 /tmp/d455_apriltag_pose.log
tail -50 /tmp/apriltag_udp_bridge.log
ss -lunp | grep 19003
```

若 bridge 日志没有 `Published tags=[...]`，先检查画面中是否真的有可见的 IDs 0--3、
Tag 黑边是否完整、以及是否有另一个进程占用 19003。

## 分段验收

### 0. 视觉与坐标链路

前置条件：四张实际打印的 Tag 已贴好，D455 能看到至少一个完整码。

运行“每次断电后的恢复”命令。验收：

- `/apriltag/detections_base` 中出现预期 `tag_id`；
- `frame_id` 恒为 `base_link`；
- 静止时 XYZ、yaw 没有明显跳变；
- 手持 Tag 向狗前方移动时 `x` 增大，向狗左侧移动时 `y` 增大；
- 向左旋转 Tag 时 yaw 的正负号与现场观察一致。

若坐标方向不符合这一约定，先停止在本段，核实 D455 `camera_link` 外参；不要进行 I2
示教或底盘运动。

### 1. I2 示教

前置条件：第 0 段通过。人工将狗摆在某个物块槽位的最终抓取站位，保持不动，且该槽位
Tag 可稳定可见。

```bash
cd ~/worktrees/quadruped-vision-yolo-refactor
source /opt/ros/foxy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=0
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

python3 scripts/calibration/teach_pick_i2_apriltag.py 0 --samples 30
```

对 IDs `0..3` 分别重复。脚本只写
`configs/calibration/pick_i2_apriltag.yaml` 中对应的 `taught` 和 `xyyaw`，不会移动机器。

验收：示教打印出的 `[x,y,yaw]` 合理；YAML 中该 ID 的 `taught: true`；重新运行探针时，
该站位的 Tag pose 与示教值在 3 cm / 3 deg 内。

贴码颜色映射完成后，确认 `pick_red_tag_ids` 只包含红色槽位对应的 ID。例如当前默认
`[0, 1]`，不应靠 YOLO 自动推断颜色。

### 2. 单独 I0 -> I2 底盘对齐

前置条件：第 0、1 段通过；狗已手动或 Nav2 放到粗定位 I0；测试区域清空；目标红色
Tag 已示教。此段不走 Nav2，也不调用机械臂。

```bash
cd ~/worktrees/quadruped-vision-yolo-refactor
source /opt/ros/foxy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=0
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

ros2 launch quadruped_robot_competition competition.launch.py \
  enable_apriltag_udp_bridge:=false \
  enable_competition_manager:=true \
  enable_navigation:=true \
  route_mode:=segment \
  segment_name:=pick_i0_to_i2 \
  enable_route_execution:=true
```

`enable_apriltag_udp_bridge:=false` 是因为“每次断电后的恢复”已经启动了唯一的
Host bridge。不要同时起两个 19003 UDP listener；任务管理器直接订阅该 bridge
已经发布的 `/apriltag/detections_base`。

确认实时 Tag 输出和现场安全后，另一个终端执行：

```bash
ros2 service call /task/start_route std_srvs/srv/Trigger '{}'
```

验收：

- 最近的可见红色 Tag 被选中并锁定；对齐过程中不切换 ID；
- 顺序为 yaw、x、y，单次只有一个底盘控制轴非零；每次脉冲后有停车和站稳；
- 80 s 内得到 `alignment_success`，最终连续三帧满足 3 cm / 3 cm / 3 deg；
- 不调用 `/arm/execute_grasp_fixed`。

若启动时返回 `route execution is disabled`，说明漏传
`enable_route_execution:=true`，不是对齐故障。

### 3. Nav2 I0 + I0 -> I2 累积验收

前置条件：第 2 段通过。狗可从任意安全起点交给 Nav2。

启动命令与第 2 段相同，只替换：

```text
segment_name:=pick_until_i2
```

验收：Nav2 先报告到达粗定位 `grasp_i0`，随后 AprilTag 对齐至 I2；结束状态为
`alignment_success`。本段仍不调用机械臂。

### 4. 单次抓取验收

前置条件：第 3 段通过；机械臂节点已按其自身安全配置启动；固定
`pick_grasp_target_arm_base` 已由机械臂侧确认；机械臂运动空间清空。

第 3 段命令增加 `enable_arm:=true`，并替换：

```text
segment_name:=pick_one
```

验收：Nav2 I0 -> Tag I2 对齐 -> 调用一次 `/arm/execute_grasp_fixed` -> 服务成功 ->
route 返回 `grasp_success`。成功后同一路由中的目标 ID 被记为已抓取，不会再次选择。

## 调试要点

- `configs/calibration/pick_i2_apriltag.yaml` 当前初始值均为 `taught: false`。未示教直接
  运行会以 `I2_NOT_TAUGHT` 结束，属于预期保护。
- 路径 `scripts/run_pick_i0_to_i2_test.py` 是旧的 Lite3 前置相机二维码测试工具，订阅
  `/box/qr_pose`；不要用于当前 AprilTag 流程。
- Docker 容器的仓库目录是只读挂载。`start_d455_apriltag.sh` 已把运行时文件复制到
  `/tmp/d455_apriltag`，不要改回 `docker cp` 到 `/opt/quadruped/perception/bin`。
- AprilTag bridge 的外参来源仅为
  `configs/transforms/static_extrinsics.yaml`。不要为了本流程再手填第二份外参。
- 当前 D455 是抓取视觉唯一相机。狗自身前置广角相机和旧 QR 检测不是本流程输入。
- 对齐速度刻意慢：线速度最大 `0.025 m/s`、角速度最大 `0.10 rad/s`；脉冲时长由当前
  误差的类似 PD 比例计算，范围 `0.15--0.40 s`，随后固定 `0.70 s` 站稳。
- 当实际码持续不可见时，执行器保持底盘停车并在 80 s 总超时内等待新帧。

## 新对话建议输入

```text
请先阅读 docs/apriltag_pickup_handoff.md。
当前阶段：<填写视觉 / I2示教 / I0到I2 / Nav2累积 / 抓取之一>。
Xavier 日志：<粘贴 docker 和 host bridge 日志>。
现场现象：<填写狗是否移动、Tag 是否可见、探针输出>。
```
