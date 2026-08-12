# 锥桶避障 L2/L3 无执行器验收规程

> 状态：L0/L1、Jetson L2、L3-S 与 L3-D 均已完成，结论为 L3-D GO。L2 证据目录为 `/home/superwfx666/competition_logs/cone_l2_l3/20260812_164907_phase94_l2`，L3-S 证据目录为 `/home/superwfx666/competition_logs/cone_l2_l3/20260812_183742_phase95_l3s`，L3-D 证据目录为 `/home/superwfx666/competition_logs/cone_l2_l3/20260812_185325_phase96_l3d/B3_reconnect_20260812_222610`。

本文用于在不连接 Lite3 执行链路、不发送导航目标的条件下，依次验证 Foxy 插件加载、隔离 UDP/ROS 故障注入、D455 实际扫描、速度门、local costmap 标记/清除和资源开销。L4 机器狗运动不在本文范围内。

## 1. 验收分层

| 层级 | 内容 | 允许的输出 | 通过后允许进入 |
|---|---|---|---|
| L2 | provenance、依赖、插件发现、controller configure-only | 无速度话题测试命令 | 隔离 L3 |
| L3-S | 测试域 93、loopback UDP 19012、`/cone_l3/*` 合成扫描 | 仅 `/cone_l3/cmd_out`，且唯一订阅者是探针 | D455 静态 L3-D |
| L3-D | 真实 D455、Nav2、local costmap，Lite3 驱动保持关闭 | `/cmd_vel` 可以存在，但订阅者必须为 0，不发送 goal | 单独审批 L4 |

任何一级失败都停止，不得用后一级结果覆盖前一级失败。

## 2. 硬安全边界

执行前同时满足：

1. 机器狗断电，或 Jetson 到 Lite3 的控制网络物理断开。
2. 不启动 `transfer`、`motion_sender`、`cmd_vel_bridge`、TaskManager 或任何 Lite3 UDP 发送器。
3. 本文所有 `start_competition.sh` 命令都不带 `--dog`、`--cmd-vel-bridge`、`--task-manager`、`--auto-advance`。
4. 不调用 `/navigate_to_pose`，不发布 `/cmd_vel_nav2`、`/cmd_vel_precision` 或 `/cmd_vel_selected`。
5. L3-S 固定使用 loopback、UDP `19012`、ROS domain `93` 和 `/cone_l3/*`；生产端口 `19002` 与生产 domain `0` 会被探针拒绝。
6. 只有现场人员确认物理隔离后，才允许加入 `--confirm-isolated-no-actuator`。

## 3. 证据目录与代码来源

以下命令均在 Jetson 执行。正式仓库路径如有变化，只改 `REPO`，不要在旧 worktree 验收。

```bash
export REPO=/home/superwfx666/quadruped-robot-competition-nav2-dwb-deploy
cd "$REPO" || exit 1
export EVIDENCE="$REPO/evidence/cone_l2_l3_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$EVIDENCE"

git rev-parse HEAD | tee "$EVIDENCE/git_head.txt"
git status --short | tee "$EVIDENCE/git_status.txt"
test ! -s "$EVIDENCE/git_status.txt" || { echo "STOP: working tree is dirty"; exit 1; }

sha256sum \
  scripts/cone_scan_udp_exporter.py \
  scripts/cone_scan_l2_l3_probe.py \
  src/nodes/navigation/cone_scan_protocol.py \
  src/nodes/navigation/cone_scan_udp_bridge.py \
  src/nodes/navigation/cone_scan_safety_gate.py \
  configs/navigation/nav2_cone_obstacles.yaml \
  | tee "$EVIDENCE/source_sha256.txt"
```

### 3.1 固定 Humble 锥桶镜像

基础 cuVSLAM 镜像不包含 `pointcloud_to_laserscan`。首次部署或 Dockerfile 变化后构建固定派生镜像：

```bash
export CONE_IMAGE=isaac_ros_cuvslam_runtime:humble-rs-cone
docker build --pull=false --no-cache \
  -f docker/Dockerfile.cuvslam-cone \
  -t "$CONE_IMAGE" .

# 不挂载 /dev、不加入 ROS 图，仅验证镜像内依赖。
docker run --rm --network none "$CONE_IMAGE" bash -lc \
  'source /opt/ros/humble/setup.bash && \
   ros2 pkg prefix pointcloud_to_laserscan && \
   ros2 pkg executables pointcloud_to_laserscan | \
     grep -F "pointcloud_to_laserscan pointcloud_to_laserscan_node"'

docker image inspect --format '{{.Id}} {{.Created}} {{.Size}}' "$CONE_IMAGE" \
  | tee "$EVIDENCE/cone_image.txt"
```

`start_competition.sh --cone-avoidance` 默认使用上述 tag。验收若显式传入 `IMAGE`，必须把实际 image ID 记录到证据目录。

先清理旧栈，再确认没有执行器进程。此时机器狗仍须保持物理隔离。

```bash
bash scripts/stop_all.sh
pgrep -af 'transfer|motion_sender|cmd_vel_bridge|lite3|task_manager' \
  | tee "$EVIDENCE/forbidden_processes_before.txt"
test ! -s "$EVIDENCE/forbidden_processes_before.txt" \
  || { echo "STOP: actuator-capable process exists"; exit 1; }
```

## 4. L2：依赖、构建与插件加载

本次验收使用固定的独立插件 overlay。不得 source 现有的 `nav2_foxy_overlay_ws/install/setup.bash`，因为它可能把旧仓库 install 前缀重新注入 `AMENT_PREFIX_PATH`。

```bash
export CONE_PLUGIN_WS="$HOME/cone_l2_plugin_ws_2_2_1"
test -f "$CONE_PLUGIN_WS/install/local_setup.bash" \
  || { echo "STOP: pinned NonPersistentVoxelLayer overlay is missing"; exit 1; }
```

### 4.1 记录 Foxy 与插件来源

```bash
export CONE_PLUGIN_WS="$HOME/cone_l2_plugin_ws_2_2_1"
source /opt/ros/foxy/setup.bash
source "$CONE_PLUGIN_WS/install/local_setup.bash"

ros2 pkg prefix nav2_costmap_2d | tee "$EVIDENCE/nav2_costmap_prefix.txt"
ros2 pkg prefix nonpersistent_voxel_layer \
  | tee "$EVIDENCE/nonpersistent_voxel_layer_prefix.txt"
dpkg-query -W 'ros-foxy-nav2-*' 2>/dev/null \
  | sort | tee "$EVIDENCE/nav2_packages.txt"

PLUGIN_PREFIX="$(ros2 pkg prefix nonpersistent_voxel_layer)"
grep -R -n 'nav2_costmap_2d/NonPersistentVoxelLayer' \
  "$PLUGIN_PREFIX/share/nonpersistent_voxel_layer" \
  | tee "$EVIDENCE/nonpersistent_plugin.txt"
test -s "$EVIDENCE/nonpersistent_plugin.txt" \
  || { echo "STOP: NonPersistentVoxelLayer is not installed"; exit 1; }
```

`nonpersistent_voxel_layer` 是独立 ROS 包，不是 `nav2_costmap_2d` share 目录中的内置类。这里以独立包的插件 XML 中实际存在 `nav2_costmap_2d/NonPersistentVoxelLayer` 为准，不能只根据 apt 包名或系统 `nav2_costmap_2d` 版本推断已安装。

### 4.2 构建并核对安装路径

```bash
cd "$REPO"
export CONE_PLUGIN_WS="$HOME/cone_l2_plugin_ws_2_2_1"
source /opt/ros/foxy/setup.bash
source "$CONE_PLUGIN_WS/install/local_setup.bash"
colcon build --symlink-install --packages-select quadruped_robot_competition \
  2>&1 | tee "$EVIDENCE/colcon_build.log"
source install/local_setup.bash

ros2 pkg executables quadruped_robot_competition \
  | tee "$EVIDENCE/package_executables.txt"
grep -E 'cone_scan_udp_bridge|cone_scan_safety_gate' \
  "$EVIDENCE/package_executables.txt"

python3 - <<'PY' | tee "$EVIDENCE/python_provenance.txt"
from nodes.navigation import cone_scan_protocol
from nodes.navigation import cone_scan_safety
print(cone_scan_protocol.__file__)
print(cone_scan_safety.__file__)
PY
```

两个模块都必须解析到当前 `$REPO` 对应的 `src` 或 `install`，不得落到旧 checkout。

### 4.3 configure-only 加载

此步骤只配置 controller/local costmap，不得执行 `activate`。使用独立 domain 93，避免和生产 domain 0 混图。

终端 A：

```bash
cd "$REPO"
export CONE_PLUGIN_WS="$HOME/cone_l2_plugin_ws_2_2_1"
source /opt/ros/foxy/setup.bash
source "$CONE_PLUGIN_WS/install/local_setup.bash"
source install/local_setup.bash
export ROS_DOMAIN_ID=93
export ROS_LOCALHOST_ONLY=1
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

ros2 run nav2_controller controller_server --ros-args \
  --params-file "$REPO/configs/navigation/nav2_params.yaml" \
  --params-file "$REPO/configs/navigation/nav2_cone_obstacles.yaml" \
  -r /cmd_vel:=/cone_l2/cmd_vel \
  2>&1 | tee "$EVIDENCE/l2_controller_configure.log"
```

终端 B：

```bash
export CONE_PLUGIN_WS="$HOME/cone_l2_plugin_ws_2_2_1"
source /opt/ros/foxy/setup.bash
source "$CONE_PLUGIN_WS/install/local_setup.bash"
source "$REPO/install/local_setup.bash"
export ROS_DOMAIN_ID=93
export ROS_LOCALHOST_ONLY=1
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

ros2 lifecycle get /controller_server
ros2 lifecycle set /controller_server configure
ros2 lifecycle get /controller_server | tee "$EVIDENCE/l2_lifecycle_state.txt"
ros2 param get /local_costmap/local_costmap plugins \
  | tee "$EVIDENCE/l2_local_plugins.txt"
```

通过条件：

- lifecycle 状态是 `inactive`；严禁执行 `activate`。
- `plugins` 顺序为 `static_layer`、`cone_obstacle_layer`、`inflation_layer`。
- 终端 A 没有 pluginlib 类不存在、参数类型错误或进程崩溃。
- `ros2 topic info /cone_l2/cmd_vel --verbose` 不得出现执行器订阅者。

记录后在终端 B 执行 `ros2 lifecycle set /controller_server shutdown`，再在终端 A 按 `Ctrl+C`。确认 domain 93 中无节点后进入 L3-S。

## 5. L3-S：隔离合成扫描验收

探针会自行强制 `ROS_LOCALHOST_ONLY=1`、ROS domain 93、UDP `127.0.0.1:19012`，启动已安装的 Foxy bridge/gate，并在退出时清理整个子进程组。

```bash
cd "$REPO"
source /opt/ros/foxy/setup.bash
source install/setup.bash

python3 scripts/cone_scan_l2_l3_probe.py \
  --ros-domain-id 93 \
  --confirm-isolated-no-actuator \
  --output "$EVIDENCE/l3_synthetic.json"
```

探针必须返回 0，JSON 中 `passed=true`，并包含以下通过步骤：

- `graph_isolation`
- `three_frame_warmup`
- `healthy_clear_scan`
- `fail_closed_isolated_point`
- `fail_closed_short_run`
- `fail_closed_unhealthy_depth`
- `fail_closed_stale`
- `fail_closed_future`
- `fail_closed_bad_crc`
- `fail_closed_sequence_regression`
- `latest_only_backlog`
- `stream_restart_warmup`
- `silence_deadline`

用独立检查拒绝“脚本退出码为 0但证据不完整”：

```bash
python3 - "$EVIDENCE/l3_synthetic.json" <<'PY'
import json
import sys

path = sys.argv[1]
data = json.load(open(path, encoding="utf-8"))
assert data["schema"] == "cone_scan_l2_l3_acceptance/v1"
assert data["passed"] is True
assert data["ros_domain_id"] == 93
assert data["ros_localhost_only"] is True
assert data["udp"] == {"host": "127.0.0.1", "port": 19012}
assert all(step["passed"] for step in data["steps"])
assert all(proc["exit_code"] in (0, -2, 130) for proc in data["processes"].values())
latencies = [
    step["evidence"]["fail_closed_latency_ms"]
    for step in data["steps"]
    if "fail_closed_latency_ms" in step.get("evidence", {})
]
assert latencies and max(latencies) <= 250.0
print("L3-S PASS; max_fail_closed_latency_ms=%.3f" % max(latencies))
PY

pgrep -af 'cone_scan_udp_bridge|cone_scan_safety_gate|cone_scan_l3_acceptance_probe' \
  | tee "$EVIDENCE/l3_leftover_processes.txt"
test ! -s "$EVIDENCE/l3_leftover_processes.txt" \
  || { echo "STOP: L3 probe left a process behind"; exit 1; }
```

`/cone_l3/cmd_out` 的非零值只证明门控逻辑放行，不能解释为向机器人发送过命令。JSON 的图证据必须显示该 topic 唯一订阅者为探针自身。

## 6. L3-D：真实 D455 静态加载

### 6.1 启动前门禁

本阶段回到生产 ROS domain 0，但仍不连接执行器。先确认命令链没有订阅者：

```bash
source /opt/ros/foxy/setup.bash
source "$REPO/install/setup.bash"
export ROS_DOMAIN_ID=0
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

pgrep -af 'transfer|motion_sender|cmd_vel_bridge|lite3|task_manager' \
  | tee "$EVIDENCE/l3d_forbidden_processes_before.txt"
test ! -s "$EVIDENCE/l3d_forbidden_processes_before.txt" || exit 1
ros2 topic info /cmd_vel --verbose 2>&1 \
  | tee "$EVIDENCE/cmd_vel_before.txt"
```

终端 A 只运行以下命令，禁止添加 `--dog` 或其他执行器参数：

```bash
cd "$REPO"
bash scripts/start_competition.sh --cone-avoidance
```

### 6.2 ROS 图、QoS、TF 与频率

终端 B：

```bash
export CONE_PLUGIN_WS="$HOME/cone_l2_plugin_ws_2_2_1"
source /opt/ros/foxy/setup.bash
source "$CONE_PLUGIN_WS/install/local_setup.bash"
source "$REPO/install/local_setup.bash"
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

ros2 node list | sort | tee "$EVIDENCE/l3d_nodes.txt"
ros2 topic info /cone_obstacle/scan --verbose \
  | tee "$EVIDENCE/l3d_scan_qos.txt"
ros2 topic info /cone_obstacle/health --verbose \
  | tee "$EVIDENCE/l3d_health_qos.txt"
ros2 topic info /cmd_vel --verbose \
  | tee "$EVIDENCE/l3d_cmd_vel_qos.txt"
timeout 20 ros2 topic hz /cone_obstacle/scan \
  | tee "$EVIDENCE/l3d_scan_hz.txt"
timeout 3 ros2 topic echo /cone_obstacle/scan \
  | tee "$EVIDENCE/l3d_scan_once.txt"
timeout 3 ros2 topic echo /cone_obstacle/health \
  | tee "$EVIDENCE/l3d_health_once.txt"
```

同时在 Humble 容器记录 owner 和原始频率：

```bash
CN="$(docker ps --format '{{.Names}}' | grep cuvslam | head -1)"
test -n "$CN" || { echo "STOP: cuVSLAM container missing"; exit 1; }
docker exec "$CN" pgrep -af 'realsense|pointcloud_to_laserscan|cone_scan_udp_exporter' \
  | tee "$EVIDENCE/l3d_container_processes.txt"
docker exec "$CN" bash -lc \
  'source /opt/ros/humble/setup.bash && source /workspaces/isaac_ros-dev/install/setup.bash && timeout 20 ros2 topic hz /cone_obstacle/scan_humble' \
  | tee "$EVIDENCE/l3d_humble_scan_hz.txt"
```

通过条件：

- 只有一个 RealSense/D455 owner；不得出现第二个 D455 驱动进程。
- Humble 侧存在一个 `pointcloud_to_laserscan` 和一个 exporter；Foxy 侧各有一个 bridge 和 gate。
- Foxy `/cone_obstacle/scan` 为 180 束、`frame_id=base_link`、实际稳定频率不低于 8 Hz；不要求 Host 具有相机 TF。
- scan QoS 为 `BEST_EFFORT + KEEP_LAST`，health 为可靠 QoS。
- health 连续为 `healthy=true`，`source_age_ms < 250`；静态净空时允许 `finite_count=0`。
- `/cmd_vel` 的 `Subscription count` 必须为 0。存在任何执行器订阅者立即停止。

## 7. local/global costmap 与时序

整个过程机器狗、D455 和支架保持静止。锥桶只由现场人员移入或移出视野，不发送导航目标。

先记录净空基线，并开始 rosbag：

```bash
python3 scripts/cone_costmap_snapshot.py \
  --topic /local_costmap/costmap_raw \
  --output "$EVIDENCE/local_clear_before.json"
python3 scripts/cone_costmap_snapshot.py \
  --topic /global_costmap/costmap_raw \
  --output "$EVIDENCE/global_before.json"

ros2 bag record -o "$EVIDENCE/cone_costmap_timing" \
  --qos-profile-overrides-path configs/ros/cone_rosbag_qos.yaml \
  /cone_acceptance/marker \
  /cone_obstacle/scan \
  /cone_obstacle/health \
  /cone_obstacle/safety_gate_status \
  /local_costmap/costmap_raw \
  /global_costmap/costmap_raw
```

`/cone_obstacle/scan` 发布端使用 `BEST_EFFORT`。必须显式加载上述 QoS 覆盖；否则 Foxy rosbag2 可能创建该话题但实际记录 0 条消息。停止录包后用 `ros2 bag info` 核对六个话题的消息数均大于 0，并对 SQLite 执行 `PRAGMA integrity_check`。

另开终端，按下列顺序操作，每次保持至少 5 秒：

```bash
ros2 topic pub --once /cone_acceptance/marker std_msgs/msg/String "{data: CLEAR_BEFORE}"
# 现场人员把单个锥桶放到 D455 正前方约 0.75 m，禁止移动机器人。
ros2 topic pub --once /cone_acceptance/marker std_msgs/msg/String "{data: CONE_IN}"
# 保持 5 秒后，把锥桶完全移出视野。
ros2 topic pub --once /cone_acceptance/marker std_msgs/msg/String "{data: CONE_OUT}"
```

停止 rosbag 后保存最终快照：

```bash
python3 scripts/cone_costmap_snapshot.py \
  --topic /local_costmap/costmap_raw \
  --output "$EVIDENCE/local_clear_after.json"
python3 scripts/cone_costmap_snapshot.py \
  --topic /global_costmap/costmap_raw \
  --output "$EVIDENCE/global_after.json"

python3 - \
  "$EVIDENCE/local_clear_before.json" "$EVIDENCE/local_clear_after.json" \
  "$EVIDENCE/global_before.json" "$EVIDENCE/global_after.json" <<'PY'
import json
import sys

local_before, local_after, global_before, global_after = (
    json.load(open(path, encoding="utf-8")) for path in sys.argv[1:]
)
assert local_before["data_sha256"] == local_after["data_sha256"], \
    "stationary local costmap did not return to its clear baseline"
assert global_before["data_sha256"] == global_after["data_sha256"], \
    "global costmap data changed"
print("local_clear_data_sha256=%s" % local_before["data_sha256"])
print("global_data_sha256=%s" % global_before["data_sha256"])
PY
```

必须从 bag/RViz 同时确认：

- 锥桶进入后，local costmap 在对应方向产生致命/膨胀代价；global costmap 不新增锥桶。
- `CONE_OUT` 只是人工操作标记，不作为清除计时起点。离线从 bag 中找出最后一帧仍含锥桶聚类的 `/cone_obstacle/scan` source timestamp，并用对应 `/cone_obstacle/health` 的 `sequence/source_timestamp_ns` 交叉确认；从该时刻计到第一帧不再含该锥桶动态连通区的已发布 local costmap。
- 正式 `observation_persistence=1.5 s`；初始清除合同为上述实测间隔不超过 `2.5 s`，其中包含 5 Hz costmap 更新、2 Hz 发布和调度余量。至少记录实测值，积累重复数据后才能收紧阈值，不能从首个 clear scan 或 `CONE_OUT` 直接推算通过。
- `NonPersistentVoxelLayer` 仍每周期重置；1.5 s 缓冲中的观测会在重置后重新标记，完全过期后才消失，不依赖 raytrace clearing。
- 首次 `healthy=true` 到第三个连续健康帧之前，gate 不得 `allowed=true`。
- 记录首次 local 标记与首次 `allowed=true` 的时间差。若存在锥桶时 gate 已放行，但 local costmap 在随后一个 5 Hz 更新周期内仍未标记，判 NO-GO。
- `global_before.json` 与 `global_after.json` 的 `data_sha256` 一致；header 时间不参与哈希。
- 在机器狗和相机全程静止、且 observation buffer 完全过期后，`local_clear_before.json` 与 `local_clear_after.json` 的 `data_sha256` 也必须一致。后续运动中的 rolling local costmap 不使用逐字节哈希，应改看致命格数量、连通区域和空间位置。

## 8. D455 静态 A/B 资源对比

A、B 两轮均不带 RViz、不发 goal、等待 cuVSLAM 热身 90 秒，再采样 60 秒。现场、功耗模式、风扇、频率锁定和 D455 视野必须相同。

### A：基线

终端 A：

```bash
cd "$REPO"
bash scripts/start_competition.sh
```

终端 B 在热身后：

```bash
timeout 60 tegrastats --interval 1000 \
  | tee "$EVIDENCE/resources_A_tegrastats.txt"
docker stats --no-stream \
  | tee "$EVIDENCE/resources_A_docker.txt"
```

执行 `bash "$REPO/scripts/stop_all.sh"`，确认相关进程为 0，静置 30 秒。

### B：锥桶避障

终端 A：

```bash
cd "$REPO"
bash scripts/start_competition.sh --cone-avoidance
```

终端 B 在热身后：

```bash
timeout 60 tegrastats --interval 1000 \
  | tee "$EVIDENCE/resources_B_tegrastats.txt"
docker stats --no-stream \
  | tee "$EVIDENCE/resources_B_docker.txt"
```

两轮还需各记录 20 秒 `/visual_slam/tracking/odometry` 频率。若 B 相比 A 平均频率下降超过 10%、出现持续降频/OOM、scan 低于 8 Hz、health 间歇失效，均判 NO-GO。CPU/内存只记录同机 A/B 差值，不以单次瞬时峰值代替 60 秒证据。

## 9. 清理

L3-D 不调用通用 `stop_all.sh`，因为该脚本会向速度话题短暂发布零 `Twist`，不符合本验收的“完全不发布速度”证据边界。应在启动终端对本轮 launcher 发送 `Ctrl+C`/`SIGINT`，等待其子节点退出；随后只停止本轮新建的精确容器名，并恢复验收前暂时停止的 D455 服务。

```bash
# STACK_PID 是启动 L3-D 时保存的本轮 launcher PID。
kill -INT "$STACK_PID"
wait "$STACK_PID" || true

# 只处理启动前后容器差集确认出的本轮容器，不使用模糊名称批量删除。
docker stop -t 20 "$L3D_CONTAINER" 2>/dev/null || true
docker rm "$L3D_CONTAINER" 2>/dev/null || true

# 如果验收前临时停止了历史 D455 服务，恢复同一个既有容器。
docker start d455_yolo_repro_20260811

pgrep -af 'cone_scan|pointcloud_to_laserscan|transfer|motion_sender|cmd_vel_bridge|task_manager' \
  | tee "$EVIDENCE/processes_after_cleanup.txt"
docker ps --format '{{.Names}}' | grep -F "$L3D_CONTAINER" \
  | tee "$EVIDENCE/containers_after_cleanup.txt"
```

两个 cleanup 文件都应为空。然后验证历史 D455 容器 ID、镜像、命令、网络模式和 restart policy 与验收前一致，并分别测量 color/depth 频率。若不为空或恢复校验失败，先保存 PID/日志并人工处理，不能直接进入运动测试。

## 10. Go/No-Go

只有以下证据全部成立，才可把 Phase 93 标为“L2/L3 通过”：

| 项目 | GO 条件 |
|---|---|
| 来源 | clean HEAD、SHA、build/install/import 路径一致 |
| 插件 | configure-only 成功，`NonPersistentVoxelLayer` 实际加载 |
| 隔离探针 | 全部步骤通过，失败也写 JSON，无残留子进程 |
| 故障关闭 | CRC、时间戳、序号、几何、深度、断流均归零，最大延迟不超过 250 ms |
| 恢复 | 新 stream 与初始 stream 都必须重新累计 3 个健康帧 |
| D455 图 | 单一 owner，180 束 `base_link` scan 不低于 8 Hz，source age 小于 250 ms |
| costmap | local 正确标记；从最后一帧含锥 source timestamp 起不超过 2.5 秒清除；静止 local clear hash 回归基线；global data 不变 |
| 时序 | 3 帧前不放行；存在锥桶时 local 标记不得落后放行超过一个 5 Hz 更新周期 |
| 资源 | 无 OOM/持续降频，cuVSLAM 频率下降不超过 10%，scan/health 稳定 |
| 执行器 | 全程无 Lite3 驱动、无 goal、`/cmd_vel` 无执行器订阅者 |
| 清理 | ROS 进程与 cuVSLAM 容器无残留 |

任何一项缺证据都按 NO-GO 处理。L2/L3 通过也不自动授权 L4；L4 仍需单独的现场路线、急停和低速运动审批。
