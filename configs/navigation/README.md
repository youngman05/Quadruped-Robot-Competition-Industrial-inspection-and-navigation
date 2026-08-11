# Navigation Configs

Nav2 导航参数配置。

## 文件

| 文件 | 用途 |
|------|------|
| `nav2_params.yaml` | 已验证的静态地图 Nav2 参数，默认使用 |
| `nav2_depth_obstacles.yaml` | 可选 D455 点云动态障碍层 overlay，默认不加载 |
| `navigate_terminal_no_replanning.xml` | 终点邻域单次规划 BT；无周期重规划和运动恢复 |

完整航点 probe 默认在距离目标 `0.35m` 时取消周期重规划目标，确认
`/cmd_vel` 连续归零后，以 `navigate_terminal_no_replanning.xml` 重发同一目标。
这样 Foxy 0.4.7 不会在最终位置/朝向收敛期间反复重置 goal checker 和
`RotateToGoal` critic。

## 关键参数

- `global_costmap`：静态层加载 PGM 地图，分辨率 0.025m
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
# Real-field waypoint calibration

`waypoints_real.yaml` is a JSON-compatible YAML document so it can be read with
the Python standard library on the Foxy Jetson. The recorder also accepts normal
block-style YAML when PyYAML is installed.

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

## Staged D455 depth pipeline

The competition launch keeps the validated static-only Nav2 path by default.
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
