# Navigation Configs

Nav2 导航参数配置。

## 文件

| 文件 | 用途 |
|------|------|
| `nav2_params.yaml` | Nav2 全局/局部代价地图、规划器、控制器参数 |

## 关键参数

- `global_costmap`：静态层加载 PGM 地图，分辨率 0.025m
- `local_costmap`：D455 深度点云障碍物层，滚动窗口 2m × 2m
- `planner`：NavFn 全局路径规划
- `controller`：RegulatedPurePursuit 路径跟踪（适合四足）
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

## Reordered route preview

`waypoints_reordered_preview.yaml` contains the existing PGM-based coordinates
with the four observation poses reordered as:

```text
pos1_middle -> pos2a_upper_right -> pos1_middle_turned -> pos2b_lower_right
```

This separates the two opposite-yaw poses at the same middle XY position. The
file is intentionally marked `calibration.status: preview`; it is for local
route inspection only and the navigation probe refuses to execute it. It must
not replace remote-control calibration against the current real-field map.

Inspect the local sequence without initializing ROS navigation:

```bash
python3 scripts/nav2_waypoint_sequence_probe.py \
  --waypoint-file configs/navigation/waypoints_reordered_preview.yaml \
  --waypoint-route inspection_interleaved \
  --describe-route
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
