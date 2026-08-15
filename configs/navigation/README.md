# Navigation Configs

Nav2 导航参数配置。

## 文件

| 文件 | 用途 |
|------|------|
| `nav2_params.yaml` | 已验证的静态地图 Nav2 参数，默认使用 |
| `nav2_depth_obstacles.yaml` | 可选 D455 点云动态障碍层 overlay，默认不加载 |
| `nav2_cone_obstacles.yaml` | 锥桶模式正式 controller + 双 costmap overlay，保留最近 1.5 s 观测 |
| `nav2_cone_obstacles_experimental.yaml` | L4 单锥调参实验 overlay，默认不加载 |
| `navigate_terminal_no_replanning.xml` | 终点邻域单次规划 BT；无周期重规划和运动恢复 |

完整航点 probe 默认在距离目标 `0.35m` 时取消周期重规划目标，确认
`/cmd_vel` 连续归零后，以 `navigate_terminal_no_replanning.xml` 重发同一目标。
这样 Foxy 0.4.7 不会在最终位置/朝向收敛期间反复重置 goal checker 和
`RotateToGoal` critic。

## 关键参数

- `global_costmap`：基础模式由静态层加载 PGM 地图，分辨率 0.025m；锥桶模式同时加载锥桶层，使 NavFn 直接规划绕行
- `local_costmap`：默认仅静态层和膨胀层；启用深度 overlay 后增加 VoxelLayer
- `planner`：NavFn 全局路径规划
- `controller`：RegulatedPurePursuit 路径跟踪（适合四足）
- `goal tolerance`：goal checker 与 DWB 的 XY 容差同步为 0.30m，朝向容差为 0.30rad
- **不使用 AMCL**：定位由 cuVSLAM 提供

## 使用

```bash
# map_server 加载 PGM 地图
ros2 run nav2_map_server map_server \
  --ros-args -p yaml_filename:=navi/map/competition_field.yaml

# Nav2 导航栈
ros2 launch nav2_bringup navigation_launch.py \
  params_file:=configs/navigation/nav2_params.yaml
```

锥桶实验 overlay 只能在正式配置出现抵近急停或振荡、且现场已满足 L4 安全门后显式选择：

```bash
CONE_NAV2_PARAMS_FILE="$PWD/configs/navigation/nav2_cone_obstacles_experimental.yaml" \
  bash scripts/start_competition.sh --cone-avoidance
```

正式锥桶 overlay 在 local/global costmap 中加载同一锥桶层，并新增专用
`FollowPathCone`：`ObstacleFootprint=1.0`、`vtheta_samples=21`；仍保持
`min_vel_x=0`、`max_vel_y=0`，不在未经真机验证时引入倒退或横移。只有
`obstacle_cross_target` 通过 `navigate_cone_w_replanning_and_recovery.xml`
选择该 controller；后续目标恢复基础 `FollowPath`。Phase 106 起锥桶档面向
"提前绕行"：`obstacle_range=3.00`（顶到 scan 链路上限）、锥桶内部 inflation
`0.60/2.0`、`sim_time=2.5`，并设置 `PathAlign=16.0`、`PathDist=16.0`，使
NavFn 提前弯出、DWB 允许提前偏离直线。实验文件保留相同的双 costmap 和 DWB
安全基线，是更激进的独立档位：锥桶 inflation `0.75/1.5`、
`PathAlign=12.0`、`PathDist=12.0`、`sim_time=3.0`。未设置
`CONE_NAV2_PARAMS_FILE` 时始终加载正式 `nav2_cone_obstacles.yaml`；静态和
depth 模式不读取这两个 cone overlay。

`CONE_SCAN_MIN_HEIGHT` 默认保持已验收的 `0.05 m`。`0.12 m` 只作为 L4
动态清场候选：先遥控原地踏步和低速直行 30 秒，记录 `/cone_obstacle/scan` 与
local costmap；清场致命格不得超过静止基线 `+10%`，且前方不得出现连续横向标记带。
同时确认约 `0.75 m` 的 `67 x 32 x 32 cm` 赛题锥桶仍有连续有效 beams，scan
不低于 8 Hz、health 合同不退化。满足现场安全门后才可这样启动：

```bash
CONE_SCAN_MIN_HEIGHT=0.12 bash scripts/start_competition.sh --cone-avoidance
```

地面误检可能仍被视为健康有限回波，因此不能只用
`/cone_obstacle/safety_gate_status` 的 `allowed` 翻转频次判断是否通过。
# Real-field waypoint calibration

`waypoints_real.yaml` is a JSON-compatible YAML document so it can be read with
the Python standard library on the Foxy Jetson. It now contains the Phase 71
field-run route against `competition_field_phase1`: segments 1-12 succeeded,
segment 13 (`placement_C_approach`) aborted, and segment 14 was not sent. The
map YAML and PGM SHA-256 values are recorded in the calibration metadata.

Use the recorder below only when the physical course, phase-1 map, official
start convention, or accepted waypoint poses change. The recorder also accepts
normal block-style YAML when PyYAML is installed.

Start the localization/TF stack without a Nav2 motion output, drive the robot by
remote control, then run:

```bash
python3 scripts/waypoint_calibration_recorder.py \
  --map-id competition-field-2026-08 \
  --output configs/navigation/waypoints_real.yaml
```

The recorder never publishes `cmd_vel`. At each prompt, stop the robot at the
desired task pose and press Enter. It samples `map -> base_link`, rejects an
unstable window, asks for confirmation, and saves accepted points atomically.
An existing calibration file is backed up once at session start under the
ignored `configs/navigation/calibration_backups/` directory.

`upper_corner_clear` and `lower_corner_clear` are captured as separate prompts.
Their preview coordinates currently match, but the real-field calibration keeps
them independent so the upper and lower corridor clearances can be adjusted
without changing the other route.

## Reordered route preview

`waypoints_reordered_preview.yaml` contains the existing PGM-based coordinates
with the four observation poses reordered as:

```text
pos1_middle -> upper_corner_clear -> pos2a_upper_right
  -> upper_corner_clear -> pos1_middle_turned
  -> lower_corner_clear -> pos2b_lower_right
```

This separates the two opposite-yaw poses at the same middle XY position and
forces both the entry to and exit from `pos2a_upper_right` through the same
wall-clear transition. It also routes the lower observation leg through the
independently calibratable `lower_corner_clear` point instead of allowing a
diagonal shortcut into the lower cabinet corner. The inspection route contains
9 goals and the full route contains 14 goals. The file is intentionally marked
`calibration.status: preview`; it is for local route inspection only. Normal
execution refuses it; it must not replace remote-control calibration against
the current real-field map.

Inspect the local sequence without initializing ROS navigation:

```bash
python3 scripts/nav2_waypoint_sequence_probe.py \
  --waypoint-file configs/navigation/waypoints_reordered_preview.yaml \
  --waypoint-route inspection_interleaved \
  --describe-route
```

For one explicitly authorized legacy-PGM trial only, the preview gate can be
overridden with `--allow-preview-route`. This flag is not for competition runs:

```bash
python3 scripts/nav2_waypoint_sequence_probe.py \
  --waypoint-file configs/navigation/waypoints_reordered_preview.yaml \
  --waypoint-route inspection_interleaved \
  --allow-preview-route \
  --stop-on-failure
```

After every required point is captured, enter `finish`. Validate a route without
initializing ROS navigation:

```bash
python3 scripts/nav2_waypoint_sequence_probe.py \
  --waypoint-file configs/navigation/waypoints_real.yaml \
  --waypoint-route inspection_interleaved \
  --describe-route
```

Run only the inspection route first. The full calibrated route is selected with
`--waypoint-route full_interleaved` after inspection and physical-clearance
validation succeeds. Calibration and competition runs must use the same map,
official physical start, cuVSLAM cold-start procedure, and `map -> base_link`
frame convention. The `action` fields are calibration metadata; this Nav-only
probe records them in output but does not execute grasp, placement, or vision
tasks.

## Phase 113 Cone-to-WHZ route

The supervised Cone-to-WHZ acceptance uses the dedicated
`--cone-to-whz-l6` preset. The preset does not enable a Lite3 actuator path by
itself. Before any runtime cleanup, Docker start, or ROS launch, it requires:

- `configs/navigation/waypoints_real.yaml` with `calibration.status=complete`;
- all named `inspection_interleaved` route waypoints present;
- a non-empty file `map_id` matching `TASK_EXPECTED_MAP_ID`;
- TaskManager navigation and WHZ retries fixed at zero;
- completion after the four WHZ observations, without entering manipulation.

The repository file currently satisfies the waypoint gate with
`TASK_EXPECTED_MAP_ID=competition_field_phase1`. This does not claim that the
complete 14-goal route has passed: Phase 113 consumes only the 9-goal inspection
route and still requires one supervised moving acceptance run.

No-actuation startup gate:

```bash
TASK_EXPECTED_MAP_ID=competition_field_phase1 \
  bash scripts/start_competition.sh --cone-to-whz-l6
```

The later supervised motion run requires the same map and waypoint file plus
the separately authorized Lite3 arguments. A failed Nav2 goal or WHZ request
ends the attempt; TaskManager does not submit it again.

For the clean operator-run L6 path, with no rosbag or external supervisor:

```bash
bash scripts/start_l6.sh
```

This entrypoint fixes the formal map ID and timeout contract, then delegates to
the existing fail-closed startup acceptance chain. Stop the runtime with:

```bash
bash scripts/stop_all.sh
```

## Staged D455 depth pipeline

The competition launch keeps the validated static-only Nav2 path when neither
depth nor cone mode is enabled. Cone mode adds the buffered obstacle layer to
both costmaps so the global planner can route around cones.
`enable_depth_pipeline:=true` is an explicit opt-in that changes the velocity
chain to:

```text
/cmd_vel_nav2 + /cmd_vel_precision
  -> cmd_vel_arbiter -> /cmd_vel_selected
  -> depth_safety_gate -> /cmd_vel
```

It also starts `depth_relay_publisher`, publishes a decimated optical-frame
PointCloud2, and loads `nav2_depth_obstacles.yaml` after `nav2_params.yaml`.
The legacy `depth_publisher` is not part of this chain because it opens the
D455 again and would contend with the RealSense owner inside the cuVSLAM
container.

Mission modes follow three route milestones:

- `AVOIDANCE`: before mission motion through `obstacle_cross_target`.
- `DISABLED`: after `obstacle_cross_target` through the inspection route.
- `MANIPULATION`: after `pos2b_lower_right`, before `grab_area_approach`, and
  through grasp and placement.
- `BOOTING` and `FAULT`: fail-closed modes that publish zero velocity.

Every transition requires a stopped robot and a matching request ID from the
Docker controller. Enabling a mode also requires fresh depth, PointCloud2,
optical TF, and a local costmap update after the current mode's first cloud
before non-zero velocity is released. Controller process IDs, monotonic ages,
file mtimes, frame sequence numbers, and CRC32 prevent persisted or torn shared
files from satisfying a new mission.
Entering `DISABLED` still requires an explicit healthy ACK; disappearance of
frames is not treated as success.

The Docker relay defaults to `consumer_only`. This leaves the validated
infrared/IMU/cuVSLAM owner untouched and disables relay/downstream work.
`DEPTH_CONTROL_STRATEGY=parameter` additionally changes the RealSense
`enable_depth` parameter, but must not be used until a stationary Jetson A/B
test proves infrared, IMU, cuVSLAM tracking, and `/odom` remain healthy.

The local implementation is selected from the stack launcher with
`--depth-pipeline`; the existing `run_full_navigation.sh` intentionally does
not pass this flag. Hardware deployment and motion validation remain separate
gates.
