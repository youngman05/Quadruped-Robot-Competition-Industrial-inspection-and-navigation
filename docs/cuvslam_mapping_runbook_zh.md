# cuVSLAM 最终遥控建图验收规程

> 当前状态（2026-08-09）：两次独立短闭环均未证明有效全局 XY 纠偏，旧日志也没有原生回环边证据。第三次短环、半程和完整路线继续冻结。当前唯一允许的下一步是构建原生 diagnostics exporter 后执行静止负载 A/B；在 A/B 通过且用户另行决定前，不得移动机器人。

本文用于执行一次有判别力的 cuVSLAM 比赛路线验收。它不是“再走一遍看看”，也不允许失败后继续绕圈补拍。

## 当前唯一允许步骤：原生 diagnostics 静止 A/B

此步骤只验证 exporter 的负载和落盘契约，不判断回环质量。机器人保持当前姿态完全静止；禁止遥控、站起、趴下、调用 `GetAllPoses` 或启动任何路线。A/B 必须分别独立冷启动，唯一变量是 `ENABLE_SLAM_DIAGNOSTICS`：

| 轮次 | `ENABLE_SLAM_DIAGNOSTICS` | 预期 |
|---|---|---|
| A | `false` | 不生成 diagnostics JSONL，保持原生产行为 |
| B | `true` | 生成 `/logs/cuvslam_slam_diagnostics.jsonl` |

每轮均使用以下命令。先执行 A，完全停止并确认 Docker/相关进程为空后，将 `AB_MODE=A` 与 `DIAGNOSTICS_ENABLED=false` 分别改为 `B` 与 `true`，再执行 B：

```bash
cd /home/superwfx666/quadruped-robot-competition-nav2-dwb

AB_MODE=A
DIAGNOSTICS_ENABLED=false

CONTAINER_NAME="cuvslam_diag_${AB_MODE,,}" \
LOG_ROOT="$HOME/cuvslam_slam_diagnostics_ab/$AB_MODE" \
PROJECT_DIR="$PWD" \
CUVSLAM_MOUNT_MODE=robot \
CUVSLAM_PROFILE=custom \
CUVSLAM_CAMERA_PROFILE=640x360x30 \
CUVSLAM_IMAGE_JITTER_THRESHOLD_MS=40.0 \
CUVSLAM_ENABLE_LOCALIZATION_N_MAPPING=true \
CUVSLAM_ENABLE_IMU_FUSION=true \
CUVSLAM_FORCE_PLANAR_MODE=true \
CUVSLAM_PUBLISH_MAP_TO_ODOM_TF=false \
CUVSLAM_PUBLISH_ODOM_TO_BASE_TF=false \
ENABLE_SLAM_VISUALIZATION=false \
ENABLE_LANDMARKS_VIEW=false \
ENABLE_OBSERVATIONS_VIEW=false \
ENABLE_SLAM_DIAGNOSTICS="$DIAGNOSTICS_ENABLED" \
SLAM_DIAGNOSTICS_METRICS_PERIOD_MS=33 \
SLAM_DIAGNOSTICS_GRAPH_PERIOD_MS=1000 \
SLAM_DIAGNOSTICS_MAX_ITEMS_COUNT=8192 \
ENABLE_LOOP_METRICS_RECORDER=false \
STARTUP_TOPIC_CHECKS=false \
STARTUP_RATE_PROBES=false \
RVIZ_HEAVY_DISPLAYS=0 \
bash scripts/start_cuvslam_rviz_gui.sh --skip-input-test --no-rviz
```

diagnostics 采集契约固定为：正常运行期间的原生 pose graph 全图读取硬上限为 `1 Hz`（停机 final 快照除外）；每个独立 metrics 事件保留两次受限频器约束的关联 graph attempt，以覆盖异步图更新；快照写 `possibly_truncated=true` 时必须同时写 `edge_diff_valid=false`，且不得更新上一份可靠 edge baseline。

tracker 稳定后保持 `130s`，期间不运行 RViz、PointCloud 显示、rosbag、ROS CLI topic/rate 探针、全量系统日志扫描或在线 recorder。两轮都只允许一次相同的 `docker stats --no-stream` 采样，用于粗略比较容器 CPU；随后停止会话，离线统计 `launch.log` 的 frame delta/tracking lost、JSONL 行数和文件增长。B 轮只在以下条件全部满足时通过：没有相对 A 新增 frame delta/tracking lost，CPU 没有持续异常增量，JSONL 每行可独立解析，且终止前包含 final graph snapshot。

A/B 通过只说明 exporter 具备低负载采集条件，不解冻任何路线，也不等于 cuVSLAM 已建立有效回环边。

验收固定采用三个相互独立的冷启动会话：

```text
短闭环
  ↓ 通过后完全停止并冷启动
半程路线
  ↓ 通过后完全停止并冷启动
完整比赛路线
```

每个会话只启动 D455 和 cuVSLAM。禁止启动 Nav2、bridge、速度仲裁、感知模块、recorder、ROS topic/rate 探针或重型系统探针。每个会话停稳后只调用一次 `GetAllPoses`；调用失败也不得重试，本级直接判失败。

## 0. 最终判定边界

每一级同时满足以下条件才算通过：

- 机器狗物理回到有标记的起点，位置误差尽量 `<=0.05m`，朝向误差尽量 `<=5deg`。
- 运动前后各获取一条 `/visual_slam/tracking/odometry`，用于计算 tracking odometry 的累计漂移。
- 停稳后唯一一次 `GetAllPoses` 返回成功，用完整优化 pose graph 计算后端闭环误差。
- 后端 `xy_closure_error_m <0.20m`；正式推荐值为 `<=0.10m`。
- 运动窗口内没有 `Visual tracking is lost`，原生 launch log 没有新的图像时间断档或大帧间隔。
- tracking odometry 漂移较大时，后端闭环误差必须明显更小；否则不能声称后端完成了全局纠偏。

分级最低运动长度：

| 级别 | `--min-path-length` | 通过后动作 |
|---|---:|---|
| 短闭环 | `1.0m` | 停止本会话；冷启动半程路线 |
| 半程路线 | `5.0m` | 停止本会话；冷启动完整路线 |
| 完整比赛路线 | `5.0m`，且应与真实路线长度同量级 | `<0.20m` 才允许保存地图 |

短闭环或半程路线不得保存地图。任一级失败都停止、保留日志、不继续补拍、不进入下一级。

如果完整路线在本规程的 30fps、无 recorder、无重型探针条件下仍出现 `0.5-0.9m` 后端闭环误差，停止继续优化 cuVSLAM 建图，转入其他全局定位方案。

## 1. 只读预检

所有命令均在 Jetson 执行。预检只读；发现占用或配置错误时先停止验收，不在本步骤自动清理进程。

```bash
cd /home/superwfx666/quadruped-robot-competition-nav2-dwb

# D455
lsusb | grep -E '8086:0b5c|RealSense'

# 功耗档和在线 CPU
nvpmodel -q
cat /sys/devices/system/cpu/online

# 六核 CPU 必须全部 min=max=1420800；GPU 必须 min=max=cur=1109250000
for cpu in /sys/devices/system/cpu/cpu{0..5}; do
  printf '%s ' "${cpu##*/}"
  cat "$cpu/cpufreq/scaling_min_freq" \
      "$cpu/cpufreq/scaling_max_freq" \
      "$cpu/cpufreq/scaling_cur_freq" | paste -sd ' ' -
done
cat /sys/devices/17000000.gv11b/devfreq/17000000.gv11b/min_freq
cat /sys/devices/17000000.gv11b/devfreq/17000000.gv11b/max_freq
cat /sys/devices/17000000.gv11b/devfreq/17000000.gv11b/cur_freq

# 必须没有运行中的容器
docker ps --format '{{.Names}}'

# 必须没有 ROS、cuVSLAM、导航、bridge、recorder、探针或运动发送进程
ps -eo pid=,comm=,args= | grep -E \
  'visual_slam_node|realsense2_camera|cuvslam|nav2|bt_navigator|controller_server|planner_server|behavior_server|waypoint_follower|cmd_vel|final_bridge|motion_sender|lite3_udp|_ros2_daemon|tegrastats|rviz2|recorder' \
  | grep -v grep || true

# Ubuntu“设置”窗口必须关闭；只检查，不在 runbook 内自动终止桌面进程
if pgrep -u "$(id -u)" -f '^gnome-control-center($| )' >/dev/null; then
  echo 'GNOME_CONTROL_CENTER_RUNNING'
  exit 1
else
  echo 'GNOME_CONTROL_CENTER_OFF'
fi
```

本机单变量 A/B 中，关闭 `gnome-control-center` 后，原先稳定复现的约 `30.5s` 周期图像断档在 `130s` 稳定窗口内消失，因此将其视为当前环境已确认的周期触发源。测试前正常关闭 Ubuntu“设置”窗口即可；不要停止 `systemd-timedated` 或 `iio-sensor-proxy`，它们不是本规程要修改的变量。窗口结束后执行一次全量 `journalctl` 又触发了 `167.64ms` 瞬态，说明底层机制仍是系统调度或资源竞争；关闭设置窗口是运行门禁，不代表已经解释历史运动漂移的全部原因。

现场必须另行确认：

1. 官方起点已有可重复的物理位置和朝向标记。
2. 机器狗站稳，D455 支架和线缆无松动。
3. 本级路线净空，遥控器回中可靠，急停人员就位。
4. 不运行 `start_competition.sh`、`lite3_udp_smoke.py --armed`，不发布 `/cmd_vel`。
5. cuVSLAM 运行期间不要执行全量 `journalctl`、`systemctl status` 或桌面设置查询；如需读取系统日志，先结束本级 cuVSLAM 会话。

## 2. 固定低负载启动配置

每一级都从 Docker 为空的状态执行同一启动命令。只修改 `STAGE`，禁止修改其他参数。

```bash
cd /home/superwfx666/quadruped-robot-competition-nav2-dwb

# short / half / full 三选一
STAGE=short

CONTAINER_NAME="cuvslam_accept_${STAGE}_$(date +%Y%m%d_%H%M%S)" \
LOG_ROOT="$HOME/cuvslam_final_acceptance_logs" \
PROJECT_DIR="$PWD" \
CUVSLAM_MOUNT_MODE=robot \
CUVSLAM_PROFILE=custom \
CUVSLAM_CAMERA_PROFILE=640x360x30 \
CUVSLAM_IMAGE_JITTER_THRESHOLD_MS=40.0 \
CUVSLAM_ENABLE_LOCALIZATION_N_MAPPING=true \
CUVSLAM_ENABLE_IMU_FUSION=true \
CUVSLAM_FORCE_PLANAR_MODE=true \
CUVSLAM_PUBLISH_MAP_TO_ODOM_TF=false \
CUVSLAM_PUBLISH_ODOM_TO_BASE_TF=false \
ENABLE_SLAM_VISUALIZATION=false \
ENABLE_LANDMARKS_VIEW=false \
ENABLE_OBSERVATIONS_VIEW=false \
ENABLE_LOOP_METRICS_RECORDER=false \
STARTUP_TOPIC_CHECKS=false \
STARTUP_RATE_PROBES=false \
bash scripts/start_cuvslam_rviz_gui.sh --skip-input-test --no-rviz
```

终端 A 保持前台运行。`--skip-input-test` 只用于本次最终验收，因为静止输入门禁已完成；不要在此时重新加入诊断负载。

启动后静止 10 秒，在终端 B 验证实际运行配置：

```bash
cd /home/superwfx666/quadruped-robot-competition-nav2-dwb
CN="$(docker ps --filter name='cuvslam_accept_' --format '{{.Names}}' | head -1)"
test -n "$CN" || { echo 'CUVSLAM_CONTAINER_NOT_FOUND'; exit 1; }

HOST_LOG_DIR="$(docker inspect "$CN" --format '{{range .Mounts}}{{if eq .Destination "/logs"}}{{.Source}}{{end}}{{end}}')"
test -d "$HOST_LOG_DIR" || { echo 'LOG_DIR_NOT_FOUND'; exit 1; }
echo "CN=$CN"
echo "HOST_LOG_DIR=$HOST_LOG_DIR"

docker exec "$CN" cat /logs/runtime_config.env
if docker exec "$CN" pgrep -a -f _ros2_daemon; then
  echo 'ROS_DAEMON_RUNNING_FAIL'
  exit 1
else
  echo 'ROS_DAEMON_OFF'
fi
```

`runtime_config.env` 必须明确显示：

```text
CUVSLAM_CAMERA_PROFILE=640x360x30
ENABLE_SLAM_VISUALIZATION=false
ENABLE_LANDMARKS_VIEW=false
ENABLE_OBSERVATIONS_VIEW=false
ENABLE_LOOP_METRICS_RECORDER=false
STARTUP_TOPIC_CHECKS=false
STARTUP_RATE_PROBES=false
SKIP_RVIZ=1
```

任一值不符都停止本级，不移动机器狗。

## 3. 抓取 tracking odometry 起点

把轻量单样本工具复制到容器。它只订阅到一条 odometry 后退出，不持续录制，也不调用 ROS CLI daemon。

```bash
docker cp scripts/cuvslam_get_odometry_once.py \
  "$CN:/logs/cuvslam_get_odometry_once.py"

docker exec "$CN" mkdir -p "/logs/acceptance/$STAGE"
docker exec "$CN" bash -lc \
  "source /opt/ros/humble/setup.bash && \
   source /workspaces/isaac_ros-dev/install/setup.bash && \
   python3 /logs/cuvslam_get_odometry_once.py capture \
     --output '/logs/acceptance/$STAGE/tracking_start.json' \
     --timeout 5"
```

确认输出的 `frame_id`、`child_frame_id` 分别为 `odom`、`base_link`。失败时本级停止，不改用持续 recorder。

## 4. 分级遥控路线

每次开始移动前记录运动窗口起点，便于把原生 launch log 的告警与真实运动对齐：

```bash
date '+%s.%N %FT%T%z' \
  > "$HOST_LOG_DIR/acceptance/$STAGE/motion_start_wall.txt"
```

### 4.1 短闭环

- 从标记起点和原始朝向出发，低速走一个可重复小环。
- 建议速度约 `0.04-0.06m/s`；避免快速原地旋转和急停急转。
- 回到同一物理标记和原始朝向，遥控器回中，停稳 10 秒。

### 4.2 半程路线

- 只有短闭环会话通过并完全停止后，才冷启动 `STAGE=half`。
- 覆盖完整比赛路线前半段及一条自然回起点的路径。
- 不得沿失败轨迹继续加圈，也不得加载短闭环会话的数据。

### 4.3 完整比赛路线

- 只有半程会话通过并完全停止后，才冷启动 `STAGE=full`。
- 单向覆盖既定比赛建图路线，在关键转角低速、短暂停留并保持画面清晰。
- 最终回到同一物理标记和原始朝向，遥控器回中，停稳 10 秒。

任一级运动过程中出现 tracking lost、图像冻结、机身打滑、碰撞、支架/线缆松动或现场急停，都立即停下。本级判失败，不继续补拍。

物理回到起点、遥控器回中并停稳后，先记录运动窗口终点，再进入后验判定：

```bash
date '+%s.%N %FT%T%z' \
  > "$HOST_LOG_DIR/acceptance/$STAGE/motion_end_wall.txt"
```

## 5. 停稳后的唯一一次后验判定

先抓取 tracking odometry 终点并计算累计漂移：

```bash
docker exec "$CN" bash -lc \
  "source /opt/ros/humble/setup.bash && \
   source /workspaces/isaac_ros-dev/install/setup.bash && \
   python3 /logs/cuvslam_get_odometry_once.py capture \
     --output '/logs/acceptance/$STAGE/tracking_end.json' \
     --timeout 5 && \
   python3 /logs/cuvslam_get_odometry_once.py compare \
     --start '/logs/acceptance/$STAGE/tracking_start.json' \
     --end '/logs/acceptance/$STAGE/tracking_end.json' \
     --output '/logs/acceptance/$STAGE/tracking_delta.json'"
```

然后设置本级最短路径，只执行一次 `GetAllPoses`：

```bash
case "$STAGE" in
  short) MIN_PATH=1.0 ;;
  half|full) MIN_PATH=5.0 ;;
  *) echo 'INVALID_STAGE'; exit 1 ;;
esac

docker exec "$CN" bash -lc \
  "source /opt/ros/humble/setup.bash && \
   source /workspaces/isaac_ros-dev/install/setup.bash && \
   python3 /logs/cuvslam_get_all_poses_once.py \
     --log-dir '/logs/acceptance/$STAGE/postrun' \
     --max-count 100000 \
     --request-timeout 120 \
     --pose-timestamp-scale 1000 \
     --tracking-start '/logs/acceptance/$STAGE/tracking_start.json' \
     --tracking-end '/logs/acceptance/$STAGE/tracking_end.json' \
     --min-path-length '$MIN_PATH' \
     --good-closure 0.20 \
     --usable-closure 0.50"
```

无论成功、超时还是返回失败，都不得再次调用。读取三份证据：

当前 cuVSLAM `GetAllPoses` 返回的 pose stamp 数值为 tracking UNIX 秒的 `1/1000`；工具必须显式使用 `--pose-timestamp-scale 1000`。通过/失败只使用 `tracking_window_*` 同窗字段，整图 `all_poses` 首末点仅保留作审计，不得替代同窗指标。

```bash
cat "$HOST_LOG_DIR/acceptance/$STAGE/tracking_delta.json"
cat "$HOST_LOG_DIR/acceptance/$STAGE/postrun/loop_metrics_latest.txt"
grep -Ein \
  'Visual tracking is lost|frame.?delta|image.*(gap|jitter)|timestamp.*(gap|jump)' \
  "$HOST_LOG_DIR/launch.log" || true
```

分层解释：

| 结果 | 解释 |
|---|---|
| tracking `xy_drift_m` 小，同窗后端闭环也 `<0.20m` | 前端本身稳定，后端结果可接受 |
| tracking 漂移较大，同窗后端闭环明显更小且 `<0.20m` | 后端 SLAM 已把累计误差拉回 |
| tracking 漂移较大，同窗后端仍 `>=0.20m` 或与 tracking 同量级 | 后端没有形成可用全局纠偏，本级失败 |
| 物理回到起点，但后端为 `0.5-0.9m` | 完整路线时终止 cuVSLAM 建图优化路线 |

不要用 tracking odometry 的终点误差代替后端 pose graph 闭环误差，也不要用 alignment 吸收本级误差。

## 6. 每一级收尾

短闭环和半程通过后也必须停止当前会话，不能在同一 pose graph 上继续下一路线。

在终端 A 按 `Ctrl+C`，等待 launcher cleanup。随后在终端 B 验证：

```bash
docker ps --format '{{.Names}}'
ps -eo pid=,comm=,args= | grep -E \
  'visual_slam_node|realsense2_camera|cuvslam|nav2|cmd_vel|final_bridge|motion_sender|_ros2_daemon|recorder' \
  | grep -v grep || true
```

结果非空时不要进入下一级。只保留日志，不删除失败会话。

## 7. 完整路线通过后保存地图

仅 `STAGE=full` 且 `xy_closure_error_m <0.20` 时执行。先记录 `HOST_LOG_DIR`，再调用一次 `save_map`：

```bash
MAP_NAME="cuvslam_competition_$(date +%Y%m%d_%H%M%S)"
docker cp scripts/cuvslam_map_action_client.py \
  "$CN:/logs/cuvslam_map_action_client.py"
docker exec "$CN" mkdir -p /logs/maps

docker exec "$CN" bash -lc \
  "source /opt/ros/humble/setup.bash && \
   source /workspaces/isaac_ros-dev/install/setup.bash && \
   python3 /logs/cuvslam_map_action_client.py --timeout 120 save \
     --map-url '/logs/maps/$MAP_NAME' \
     | tee '/logs/maps/${MAP_NAME}_save_result.json'"

docker exec "$CN" test -e "/logs/maps/$MAP_NAME"
docker exec "$CN" bash -lc \
  "find '/logs/maps/$MAP_NAME' -type f -print0 \
   | sort -z \
   | xargs -0 sha256sum \
   > '/logs/maps/${MAP_NAME}.sha256'"

SAVED_MAP_HOST="$HOST_LOG_DIR/maps/$MAP_NAME"
SAVE_RESULT_HOST="$HOST_LOG_DIR/maps/${MAP_NAME}_save_result.json"
test -e "$SAVED_MAP_HOST"
python3 -m json.tool "$SAVE_RESULT_HOST"
echo "SAVED_MAP_HOST=$SAVED_MAP_HOST"
```

保存结果必须包含 `"success": true`。失败时不重试、不换路径覆盖，保留日志并收尾。

## 8. 完全重启后验证 `load_map_and_localize`

保存成功后先按第 6 节完全停止 cuVSLAM。确认 Docker 和相关进程为空，再以第 2 节完全相同配置冷启动一个新会话，只把：

```bash
STAGE=reload
```

启动后取得新的 `CN` 和 `HOST_LOG_DIR`。把已保存地图复制到新容器，使用完整路线报告的起点作为 near point：

```bash
FULL_REPORT="$(dirname "$(dirname "$SAVED_MAP_HOST")")/acceptance/full/postrun/loop_metrics_latest.json"
read -r NEAR_X NEAR_Y NEAR_Z < <(
  python3 - "$FULL_REPORT" <<'PY'
import json
import sys

document = json.load(open(sys.argv[1], encoding="utf-8"))
print(*document["all_poses"]["first_position"])
PY
)

docker exec "$CN" mkdir -p "/logs/maps/$MAP_NAME"
docker cp "$SAVED_MAP_HOST/." "$CN:/logs/maps/$MAP_NAME/"
docker cp scripts/cuvslam_map_action_client.py \
  "$CN:/logs/cuvslam_map_action_client.py"

docker exec "$CN" bash -lc \
  "source /opt/ros/humble/setup.bash && \
   source /workspaces/isaac_ros-dev/install/setup.bash && \
   python3 /logs/cuvslam_map_action_client.py --timeout 120 load \
     --map-url '/logs/maps/$MAP_NAME' \
     --near-x '$NEAR_X' --near-y '$NEAR_Y' --near-z '$NEAR_Z' \
     | tee '/logs/maps/${MAP_NAME}_load_result.json'"

docker exec "$CN" cat "/logs/maps/${MAP_NAME}_load_result.json"
```

加载结果必须包含：

```json
{
  "action_name": "/visual_slam/load_map_and_localize",
  "command": "load",
  "success": true
}
```

保持机器狗在物理起点静止 10 秒，确认 tracking 健康且没有新时间断档。加载失败时地图不进入导航链路。

## 9. 最后才接回导航

地图保存和重新加载通过，只证明 cuVSLAM 地图生命周期可用，不等于比赛导航已纠漂。导航接回必须满足：

```text
/visual_slam/tracking/odometry
  -> 连续 odom -> base_link

后端 SLAM / 全局 pose
  -> 动态 map -> odom

Nav2
  -> 使用 map 全局坐标并实际消费上述动态校正
```

禁止用恒等或固定静态 `map -> odom` 冒充全局校正。接回 Nav2 前仍需单独验证 TF 唯一所有权、校正跳变门禁和导航目标闭环。

## 10. 验收记录表

每一级填写：

```text
级别: short / half / full / reload
日期/时间:
Jetson Git HEAD:
启动脚本 SHA-256:
HOST_LOG_DIR:
D455 / 六核 / GPU 锁频预检:
物理起点位置误差:
物理起点朝向误差:
tracking xy_drift_m:
tracking yaw_drift_deg:
GetAllPoses service_calls:
GetAllPoses service_success:
优化 pose 数量:
xy_path_length_m:
xy_closure_error_m:
tracking lost / 原生时间断档:
本级结论: pass / fail
是否保存地图:
MAP_NAME / SHA-256:
load_map_and_localize success:
异常与现场观察:
```

本规程的核心约束是：低负载、分级独立冷启动、运动前后各一次轻量 tracking 快照、停稳后每会话唯一一次完整 pose graph 查询、失败立即停止。
