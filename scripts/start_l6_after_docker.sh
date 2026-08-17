#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

log_step() {
  printf '\n[%s] STEP %s: %s\n' "$(date '+%H:%M:%S')" "$1" "$2"
}

log_step 0 "进入工程目录: $PROJECT_ROOT"

export AMENT_TRACE_SETUP_FILES="${AMENT_TRACE_SETUP_FILES:-}"
log_step 1 "加载 ROS2 Foxy 与项目 workspace"
set +u
source /opt/ros/foxy/setup.bash
source "$HOME/cone_l2_plugin_ws_2_2_1/install/local_setup.bash"
source "$HOME/nav2_foxy_overlay_ws/install/local_setup.bash"
source "$PROJECT_ROOT/install/local_setup.bash"
set -u

log_step 2 "设置比赛环境变量"
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_DOMAIN_ID=0
export FASTRTPS_DEFAULT_PROFILES_FILE="$PROJECT_ROOT/configs/ros/fastrtps_no_shm.xml"
export PYTHONPATH="$PROJECT_ROOT/src:$PROJECT_ROOT/arm_new/arm_new_ros:${PYTHONPATH:-}"

export TASK_MANIPULATION_PARAMS_FILE=/home/superwfx666/competition_configs/pick_place_competition_v1.yaml
export ARM_MOTION_PARAMS_FILE=/home/superwfx666/competition_configs/arm_motion_competition_v1.yaml
export TASK_EXPECTED_MAP_ID=competition_field_phase1
export TASK_WAYPOINT_FILE="$PROJECT_ROOT/configs/navigation/waypoints_real.yaml"
export TASK_WAYPOINT_ROUTE=full_interleaved
export TASK_PASS_OBSTACLE_TIMEOUT_SEC=180.0
export TASK_PASS_OBSTACLE_WAYPOINT_TIMEOUT_SEC=120.0
export TASK_INSPECTION_TIMEOUT_SEC=300.0
export TASK_MISSION_START_ARMED=true
export ARM_MOTION_AUTHORIZED=true
export DEPTH_SHARED_DIR="${DEPTH_SHARED_DIR:-$HOME/workspaces/isaac_ros-dev/camera_frames}"

ENABLE_APRILTAG=false
if [ -f "$TASK_MANIPULATION_PARAMS_FILE" ]; then
    ENABLE_APRILTAG="$(grep -E '^[[:space:]]*enable_pick_i2_alignment:' "$TASK_MANIPULATION_PARAMS_FILE" | head -n 1 | awk '{print $2}')"
fi
case "${ENABLE_APRILTAG,,}" in
    true|1|yes|on) ENABLE_APRILTAG=true ;;
    *) ENABLE_APRILTAG=false ;;
esac

log_step 3 "确认 cuVSLAM Docker 已运行"
CUVSLAM_CONTAINER="$(docker ps --format '{{.Names}}' --filter name=cuvslam | head -n 1)"
if [ -z "$CUVSLAM_CONTAINER" ]; then
    echo "ERROR: cuVSLAM container not running. Run scripts/start_l6_docker_prepare.sh first." >&2
    exit 1
fi
echo "cuVSLAM container ready: $CUVSLAM_CONTAINER"

log_step 4 "启动 host final_bridge (DDS 直连)"
pkill -f '[f]inal_bridge_dds.py' 2>/dev/null || true
nohup python3 "$PROJECT_ROOT/scripts/final_bridge_dds.py" \
    --camera-world-rebase base_start \
    --planarize-output \
    --stale-drop-ms 1000 \
    >/tmp/final_bridge_unchecked.log 2>&1 &

log_step 5 "等待 host /odom 桥接成功"
ODOM_WAIT_TIMEOUT_SEC="${ODOM_WAIT_TIMEOUT_SEC:-120}"
ODOM_READY=0
for _ in $(seq 1 "$((ODOM_WAIT_TIMEOUT_SEC / 2))"); do
    if timeout 10 ros2 topic list 2>/dev/null | grep -Fx /odom >/dev/null; then
        ODOM_READY=1
        break
    fi
    sleep 2
done
if [ "$ODOM_READY" -ne 1 ]; then
    echo "WARNING: host /odom did not appear within ${ODOM_WAIT_TIMEOUT_SEC}s" >&2
else
    echo "host /odom ready"
fi

log_step 5b "等待 /odom 连续稳定输出"
ODOM_STABLE=0
ODOM_SUCCESS=0
for _ in $(seq 1 2); do
    ECHO_OUT="$(timeout 2 ros2 topic echo /odom --once --qos-reliability best_effort 2>&1 || true)"
    if printf '%s' "$ECHO_OUT" | grep -q 'x:'; then
        ODOM_SUCCESS=$((ODOM_SUCCESS + 1))
    else
        ODOM_SUCCESS=0
    fi
    if [ "$ODOM_SUCCESS" -ge 3 ]; then
        ODOM_STABLE=1
        break
    fi
    sleep 1
done
if [ "$ODOM_STABLE" -ne 1 ]; then
    echo "WARNING: /odom did not become stable; continuing anyway" >&2
else
    echo "/odom is publishing continuously"
fi

log_step 6 "准备 Lite3 motion mode"
python3 "$PROJECT_ROOT/scripts/prepare_lite3_motion_mode.py" \
    >/tmp/prepare_lite3_motion_mode_unchecked.log 2>&1 || true

log_step 7 "启动 ROS2 比赛 launch"
exec ros2 launch "$PROJECT_ROOT/launch/competition.launch.py" \
    enable_task_manager:=true \
    enable_navigation:=true \
    enable_cmd_vel_bridge:=true \
    cmd_vel_bridge_init_dog:=false \
    enable_cone_avoidance:=true \
    enable_cone_mode_control:=true \
    require_cone_layer_startup_ready:=false \
    enable_apriltag_bridge:="$ENABLE_APRILTAG" \
    enable_arm_motion:=false \
    arm_motion_authorized:=true \
    enable_manipulation:=true \
    manipulation_params_file:="$TASK_MANIPULATION_PARAMS_FILE" \
    arm_motion_params_file:="$ARM_MOTION_PARAMS_FILE" \
    arm_max_sequence_sec:=20.0 \
    depth_frames_dir:="$DEPTH_SHARED_DIR" \
    verify_depth_disable_localization:=true \
    cone_params_file:="$PROJECT_ROOT/configs/navigation/nav2_cone_obstacles.yaml" \
    enable_whz:=false \
    max_nav_retries:=2 \
    max_inspection_retries:=2 \
    finish_after_inspection:=false \
    allow_placeholder_manipulation:=false \
    pass_obstacle_timeout_sec:=180.0 \
    pass_obstacle_waypoint_timeout_sec:=120.0 \
    inspection_timeout_sec:=300.0 \
    mission_start_armed:=true \
    waypoint_file:="$TASK_WAYPOINT_FILE" \
    waypoint_route:=full_interleaved \
    expected_map_id:=competition_field_phase1 \
    auto_advance:=false
