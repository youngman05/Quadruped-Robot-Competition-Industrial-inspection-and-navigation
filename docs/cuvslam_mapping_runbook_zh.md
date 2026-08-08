# cuVSLAM 真机建图操作规程

本文用于在 Jetson 上采集一张可验收的比赛场地 cuVSLAM 视觉地图。它只启动 D455、cuVSLAM 和轻量 recorder，不启动 Nav2、cmd_vel bridge、速度仲裁器、final bridge 或运动发送器。

## 0. 目标与硬门禁

本轮目标不是“走过一遍路线”，而是得到一张能够在起点闭环的视觉地图。

只有同时满足以下条件，才允许调用 `save_map`：

- 机器狗已经停稳，遥控器摇杆回中，现场人员可以立即急停。
- `/visual_slam/status` 最终仍为健康状态，过程中没有持续 `Visual tracking is lost`。
- `/logs/loop_metrics_latest.txt` 显示 `robot_base_ready: True`，并且 `child_frame_id: base_link`。
- 停稳后执行一次 `/visual_slam/get_all_poses`，报告 `service_success: true`、`service_calls: 1`。
- `postrun_metrics_full/loop_metrics_latest.txt` 的 `xy_path_length_m >= 5.0`。低于此值只能说明工具工作，不能判断闭环。
- `xy_closure_error_m < 0.20` 才能保存候选地图；项目正式目标是 `<= 0.10 m`。

任一条件不满足，都不要保存地图，不要用对齐器吸收误差，直接按第 8 节收尾。

## 1. 现场准备

在 Jetson 桌面、VNC、NoMachine 或 SSH 终端执行以下检查。所有命令都在 Jetson 上执行。

```bash
cd /home/superwfx666/quadruped-robot-competition-nav2-dwb

# D455 必须能枚举
lsusb | grep -Eiq '8086:0b5c|realsense' \
  && echo 'D455_OK' \
  || { echo 'D455_NOT_FOUND'; exit 1; }

# 本轮只允许空的导航/运动环境
docker ps --format '{{.Names}}'
ps -eo comm= | grep -E '^(nav2|bt_navigator|controller_server|planner_server|behavior_server|waypoint_follower|cmd_vel_arbiter|cmd_vel_bridge|final_bridge|motion_sender)$' || true
```

如果已经有旧的 `cuvslam_gui_*` 容器，先记录其名称和日志，再只停止这个精确容器：

```bash
OLD_CN="$(docker ps --filter name='cuvslam_gui_' --format '{{.Names}}' | head -1)"
if [ -n "$OLD_CN" ]; then
  docker stop --time 15 "$OLD_CN" || docker rm -f "$OLD_CN"
fi
```

现场同时确认：

1. 机器狗已人工放在官方起点，机身站稳，D455 支架和线缆不会晃动。
2. 起点、障碍区、箱体两侧、仪表区、抓取区和 A/B/C/D 放置区路线净空。
3. 一名人员专门负责急停，另一名人员负责遥控器；不要让遥控器摇杆长时间处于输入状态。
4. 相机视野中有稳定墙面、箱体边缘或高纹理物体；不要从大片空白地面开始移动。
5. 本轮不运行 `start_competition.sh`，不运行 `lite3_udp_smoke.py --armed`，不手工向 `/cmd_vel` 发布命令。

## 2. 启动 cuVSLAM

保持这个终端为“终端 A”，启动后不要关闭。命令会在前台跟随 Docker 日志，直到最后按 `Ctrl+C` 收尾。

```bash
cd /home/superwfx666/quadruped-robot-competition-nav2-dwb

PROJECT_DIR="$PWD" \
CUVSLAM_MOUNT_MODE=robot \
CUVSLAM_PROFILE=planar_60fps \
CUVSLAM_ENABLE_LOCALIZATION_N_MAPPING=true \
CUVSLAM_PUBLISH_MAP_TO_ODOM_TF=false \
CUVSLAM_PUBLISH_ODOM_TO_BASE_TF=false \
CUVSLAM_ENABLE_IMU_FUSION=true \
CUVSLAM_FORCE_PLANAR_MODE=true \
ENABLE_SLAM_VISUALIZATION=false \
ENABLE_LANDMARKS_VIEW=false \
ENABLE_OBSERVATIONS_VIEW=false \
bash scripts/start_cuvslam_rviz_gui.sh --no-rviz
```

等待终端出现下面两类信息后再移动：

```text
Loop metrics live summary: .../loop_metrics_latest.txt
cuVSLAM odometry and status are publishing.
```

如果出现 `D455_NOT_FOUND`、odometry 超时、recorder failed to stay running，立即停止，不要移动机器狗。

## 3. 起点稳定与小环

启动成功后，机器狗先完全静止 10 秒。此时不要做后验 `GetAllPoses` 查询，因为完整 pose graph 是重型服务，在线反复查询会挤占 tracking。

打开“终端 B”，检查轻量报告。`CN` 只代表当前容器名称，不要手填旧名称：

```bash
cd /home/superwfx666/quadruped-robot-competition-nav2-dwb
CN="$(docker ps --filter name='cuvslam_gui_' --format '{{.Names}}' | head -1)"
test -n "$CN" || { echo 'CUVSLAM_CONTAINER_NOT_FOUND'; exit 1; }
docker exec "$CN" cat /logs/loop_metrics_latest.txt
```

必须看到：

```text
robot_base_ready: True
all_poses_service: disabled_online
child_frame_id: base_link
```

然后做起点小环，目的是让相机在起始位置建立正前、左侧、右侧三组可重复视角：

1. 以官方起点和正式路线朝向为起始姿态，停 3 秒。
2. 用遥控器低速向正式路线方向前进约 `0.4-0.5 m`，停 2 秒。
3. 沿半径约 `0.25-0.35 m` 的小弧线缓慢扫过左侧或右侧纹理，避免快速原地旋转。
4. 回到起点附近，位置误差尽量小于 `0.05 m`，朝向误差尽量小于 `5°`，再停 5 秒。

如果小环过程中出现明显抖动、图像模糊、tracking lost 或机身碰撞，立即停在当前位置，记录时间，不要继续把坏数据接到正式地图上。

## 4. 正式路线采集

采用“一次单向覆盖、尽量形成闭环”的路线。速度以画面清晰为准，建议人工遥控保持约 `0.04-0.06 m/s`，不要超过当前已验证的 `0.10 m/s` 导航速度上限。

### 行走规则

- 直线段保持平稳、少停顿；每次停顿至少 1 秒再改变方向。
- 转角前先减速，转角中不要同时快速前进和快速旋转。
- 每个关键转角停 2-3 秒，缓慢向左、向右各观察约 `20-30°`，让相机看到侧面结构。
- 不要贴着箱体或柜体擦边；与障碍物保持足够净距，避免相机只看到近距离单一表面。
- 不要长时间对着空白地面；必要时稍微改变机身朝向，让墙面、箱体边缘或支架进入视野。
- 每完成一个区域，只在终端 B 查看轻量报告，不要调用 `GetAllPoses`。

### 覆盖顺序

按现场实际路线依次覆盖以下区域，顺序中途不要反复折返：

1. 官方起点及起点前方通道。
2. 障碍穿越区和障碍出口。
3. 箱体/柜体左侧、上方观察位及其转角。
4. 箱体/柜体右侧、下方观察位及其转角。
5. 抓取区和放置区 A/B/C/D 的外部接近位置。
6. 沿场地可通行边缘回到起点附近，最后用小弧线恢复起点的正前、左侧、右侧视角。

如果场地几何不允许自然闭环，不要原路倒着走回起点后直接保存；必须在起点附近额外做一次小环，使最终相机视角与开头一致。

### 中途暂停条件

出现以下任一情况，立刻停止运动并保持当前姿态：

- 现场人员报告障碍物、急停或路线安全异常。
- 机器狗打滑、碰撞、姿态不稳或遥控器失控。
- `Visual tracking is lost` 持续出现，或 `/visual_slam/status` 不再更新。
- 终端日志连续出现 frame-delta 大峰值，且轻量报告不再增长。
- D455 线缆/支架松动，或相机画面冻结。

暂停后不要继续拼接不确定的数据。先保存日志，按第 8 节清理，再重新冷启动。

## 5. 回到起点后的后验查询

完成正式路线后：

1. 让机器狗回到官方起点，最终位置误差尽量小于 `0.05 m`，朝向误差尽量小于 `5°`。
2. 遥控器回中，机器狗静止等待 10 秒。
3. 确认没有任何运动进程，再在终端 B 执行下面的唯一一次后验查询。

```bash
CN="$(docker ps --filter name='cuvslam_gui_' --format '{{.Names}}' | head -1)"
test -n "$CN" || { echo 'CUVSLAM_CONTAINER_NOT_FOUND'; exit 1; }

docker exec "$CN" bash -lc \
  'source /opt/ros/humble/setup.bash && \
   source /workspaces/isaac_ros-dev/install/setup.bash && \
   python3 /logs/cuvslam_get_all_poses_once.py \
     --log-dir /logs/postrun_metrics_full \
     --max-count 100000 \
     --request-timeout 120'
```

读取判定报告：

```bash
docker exec "$CN" cat /logs/postrun_metrics_full/loop_metrics_latest.txt
```

确认输出中只有：

```text
service: /visual_slam/get_all_poses
service_calls: 1
service_success: true
```

## 6. 判定是否成功

### 允许保存候选地图

至少满足：

- `interpretation` 不是 `poor_optimized_pose_graph_return_to_start`。
- `xy_path_length_m >= 5.0`，且与实际走过的路线长度同量级。
- `xy_closure_error_m < 0.20`。
- launch log 中没有持续 tracking lost，最终 status 仍健康。

### 正式推荐标准

优先使用 `xy_closure_error_m <= 0.10` 的结果。`0.10-0.20 m` 只能作为候选地图，不能直接进入比赛全局定位。

### 直接判失败

- `xy_path_length_m < 5.0`：没有足够运动，不能判断闭环。
- `xy_closure_error_m >= 0.20`：不要保存。
- 返回物理起点但 pose graph 仍出现米级误差：不要保存，不要用 alignment 吸收。

## 7. 通过门禁后保存地图

只有第 6 节通过后执行本节。先把 action client 复制到当前容器；它不会自动运行，只在下面的命令中显式调用：

```bash
test -f scripts/cuvslam_map_action_client.py \
  || { echo 'MAP_ACTION_CLIENT_NOT_FOUND'; exit 1; }
docker cp scripts/cuvslam_map_action_client.py \
  "$CN:/logs/cuvslam_map_action_client.py"
docker exec "$CN" mkdir -p /logs/maps

MAP_URL="/logs/maps/cuvslam_competition_$(date +%Y%m%d_%H%M%S)"
echo "MAP_URL=$MAP_URL"

docker exec "$CN" bash -lc \
  "source /opt/ros/humble/setup.bash && \
   source /workspaces/isaac_ros-dev/install/setup.bash && \
   python3 /logs/cuvslam_map_action_client.py --timeout 120 save --map-url '$MAP_URL' \
   | tee /logs/maps/save_result.json"
```

保存命令必须输出 JSON 且包含 `"success": true`。随后确认文件已经落在挂载日志目录：

```bash
docker exec "$CN" test -e "$MAP_URL" \
  && echo 'SAVED_MAP_EXISTS' \
  || { echo 'SAVED_MAP_MISSING'; exit 1; }

docker exec "$CN" bash -lc \
  "find '$MAP_URL' -type f -print0 | sort -z | xargs -0 sha256sum > '$MAP_URL.sha256'"
docker exec "$CN" du -sh "$MAP_URL" "$MAP_URL.sha256"
```

记录 `MAP_URL`、`save_result.json`、`loop_metrics_latest.json`、`postrun_metrics_full/` 和地图文件的 SHA-256。当前不要执行 `load_map_and_localize`，因为 `T_nav_map_vslam_map` 和正式 alignment bundle 尚未完成验收。

## 8. 收尾与失败清理

无论成功还是失败，都先保持机器狗静止，再在终端 A 按 `Ctrl+C`，等待脚本完成 cleanup。随后在终端 B 验证：

```bash
docker ps --format '{{.Names}}'
ps -eo comm= | grep -E '^(nav2|bt_navigator|controller_server|planner_server|behavior_server|waypoint_follower|cmd_vel_arbiter|cmd_vel_bridge|final_bridge|motion_sender|cuvslam_loop_metrics_recorder)$' || true
test ! -e /tmp/cuvslam_loop_metrics_recorder.pid \
  && echo 'PID_CLEAN' \
  || echo 'STALE_RECORDER_PID'
```

如果终端 A 已断开，只针对本轮名称清理，不使用 broad `pkill`：

```bash
CN="$(docker ps --filter name='cuvslam_gui_' --format '{{.Names}}' | head -1)"
if [ -n "$CN" ]; then
  docker stop --time 15 "$CN" || docker rm -f "$CN"
fi
rm -f /tmp/cuvslam_loop_metrics_recorder.pid
```

日志目录不要删除。失败原因、最终报告和地图是否生成必须保留，供下一轮比较。

## 9. 建图记录表

每轮完成后记录以下字段：

```text
日期/时间:
Jetson 日志目录:
起点是否人工确认:
路线是否完整覆盖:
中途 tracking lost 次数:
最终 vo_state:
GetAllPoses service_calls:
优化 pose 数量:
xy_path_length_m:
xy_closure_error_m:
是否保存地图:
MAP_URL:
save_result.json:
异常与现场观察:
```

本规程的核心约束是：在线只记录轻量 topic，机器狗停稳后完整 pose graph 只查询一次；闭环门禁不通过时不保存、不对齐、不进入 Nav2 全局定位。
