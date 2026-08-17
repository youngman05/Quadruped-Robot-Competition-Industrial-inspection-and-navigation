#!/usr/bin/env bash

# One-shot L6 pick-place launcher with on-demand heavy perception.
#
# Lifecycle implemented by task_manager:
#   PASS_OBSTACLE (cone avoidance)
#     -> at obstacle_cross_target: depth/cone is disabled, color enabled, YOLO started
#   INSPECT_GAUGES
#     -> WHZ is started on demand
#   FIND_RED_BAR
#     -> YOLO is stopped, Docker AprilTag is started
#   GRASP_BAR -> PLACE_TO_ABNORMAL_ZONE
#
# This script deliberately does NOT start the heavy WHZ/YOLO/AprilTag detectors
# at launch time. It starts only their lightweight host UDP bridges plus the
# core navigation/manipulation nodes.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

FAST_MODE=false
for arg in "$@"; do
    case "$arg" in
        --fast|-f) FAST_MODE=true ;;
        --help|-h)
            cat <<'USAGE'
Usage: bash scripts/start_l6_ondemand.sh [--fast]

Default mode starts all necessary nodes and waits for cuVSLAM/odom readiness.
--fast reduces the readiness waits for a quicker on-site start.

Heavy on-demand nodes:
  WHZ       starts at INSPECT_GAUGES
  YOLO      starts after cone avoidance, stops at FIND_RED_BAR
  AprilTag  starts at FIND_RED_BAR
USAGE
            exit 0
            ;;
        *)
            echo "unknown argument: $arg" >&2
            exit 64
            ;;
    esac
done

log_step() {
    printf '\n[%s] STEP %s: %s\n' "$(date '+%H:%M:%S')" "$1" "$2"
}

if $FAST_MODE; then
    CUVSLAM_WAIT_TIMEOUT_SEC="${FAST_CUVSLAM_WAIT_TIMEOUT_SEC:-60}"
    ODOM_WAIT_TIMEOUT_SEC="${FAST_ODOM_WAIT_TIMEOUT_SEC:-30}"
else
    CUVSLAM_WAIT_TIMEOUT_SEC="${CUVSLAM_WAIT_TIMEOUT_SEC:-120}"
    ODOM_WAIT_TIMEOUT_SEC="${ODOM_WAIT_TIMEOUT_SEC:-120}"
fi

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
export TASK_WAYPOINT_FILE="$PROJECT_ROOT/configs/navigation/waypoints_real.yaml"
export DEPTH_SHARED_DIR="${DEPTH_SHARED_DIR:-$HOME/workspaces/isaac_ros-dev/camera_frames}"
mkdir -p "$DEPTH_SHARED_DIR"

log_step 3 "停止旧比赛进程并清理旧 cuVSLAM 容器"
bash "$PROJECT_ROOT/scripts/stop_all.sh" >/tmp/start_l6_ondemand_stop.log 2>&1 || true
for container in $(docker ps -aq --filter name=cuvslam 2>/dev/null); do
    docker rm -f "$container" >/dev/null 2>&1 || true
done
rm -f "$DEPTH_SHARED_DIR/depth_control_request.json" \
      "$DEPTH_SHARED_DIR/depth_controller_status.json"

log_step 4 "后台启动 cuVSLAM/D455：深度开、颜色关（避障后再开颜色）"
nohup env \
    PROJECT_DIR="$PROJECT_ROOT" \
    IMAGE=isaac_ros_cuvslam_runtime:humble-rs-cone-pick-place \
    ROS_DOMAIN_ID=0 \
    CUVSLAM_ENABLE_DEPTH=true \
    CONE_AVOIDANCE_ENABLE=true \
    CUVSLAM_ENABLE_COLOR=false \
    CUVSLAM_MOUNT_MODE=robot \
    CUVSLAM_PROFILE=custom \
    CUVSLAM_PUBLISH_MAP_TO_ODOM_TF=false \
    CUVSLAM_PUBLISH_ODOM_TO_BASE_TF=false \
    CUVSLAM_CAMERA_PROFILE=640x360x30 \
    CUVSLAM_IMAGE_JITTER_THRESHOLD_MS=40.0 \
    ENABLE_SLAM_VISUALIZATION=false \
    ENABLE_LOOP_METRICS_RECORDER=false \
    STARTUP_TOPIC_CHECKS=false \
    bash "$PROJECT_ROOT/scripts/start_cuvslam_rviz_gui.sh" --no-rviz --skip-input-test \
    >/tmp/start_l6_ondemand_cuvslam.log 2>&1 &
disown || true

log_step 5 "等待 cuVSLAM 容器与 /visual_slam/tracking/odometry"
CUVSLAM_CONTAINER=""
for _ in $(seq 1 "$((CUVSLAM_WAIT_TIMEOUT_SEC / 2))"); do
    CUVSLAM_CONTAINER="$(docker ps --format '{{.Names}}' --filter name=cuvslam | head -n 1)"
    if [ -n "$CUVSLAM_CONTAINER" ]; then
        if docker exec "$CUVSLAM_CONTAINER" bash -lc \
            'source /opt/ros/humble/setup.bash && \
             source /workspaces/isaac_ros-dev/install/setup.bash && \
             timeout 10 ros2 topic list 2>/dev/null | grep -Fx /visual_slam/tracking/odometry >/dev/null'; then
            break
        fi
    fi
    sleep 2
done
if [ -z "$CUVSLAM_CONTAINER" ]; then
    echo "WARNING: cuVSLAM container did not become ready within ${CUVSLAM_WAIT_TIMEOUT_SEC}s" >&2
else
    echo "cuVSLAM container ready: $CUVSLAM_CONTAINER"
fi

if [ -n "$CUVSLAM_CONTAINER" ]; then
    log_step 6 "注入修复后的 AprilTag pose core"
    docker cp "$PROJECT_ROOT/docker/d455_perception/apriltag_pose_core.py" \
        "$CUVSLAM_CONTAINER":/opt/quadruped/perception/bin/apriltag_pose_core.py \
        >/dev/null 2>&1 || true
    docker cp "$PROJECT_ROOT/docker/d455_perception/d455_apriltag_pose_node.py" \
        "$CUVSLAM_CONTAINER":/opt/quadruped/perception/bin/d455_apriltag_pose_node.py \
        >/dev/null 2>&1 || true
fi

if [ -n "$CUVSLAM_CONTAINER" ]; then
    log_step 7 "复制并启动 Docker depth relay"
    docker cp "$PROJECT_ROOT/scripts/depth_relay_docker.py" \
        "$CUVSLAM_CONTAINER:/tmp/depth_relay_docker.py" >/dev/null 2>&1 || true
    docker cp "$PROJECT_ROOT/src/nodes/navigation/depth_contract.py" \
        "$CUVSLAM_CONTAINER:/tmp/depth_contract.py" >/dev/null 2>&1 || true
    docker exec -d "$CUVSLAM_CONTAINER" bash -lc \
        'source /opt/ros/humble/setup.bash &&
         source /workspaces/isaac_ros-dev/install/setup.bash &&
         python3 /tmp/depth_relay_docker.py \
           --control-strategy parameter \
           --manage-cone-pipeline-parameters \
           --poll-rate-hz 2 \
           >/tmp/depth_relay_ondemand.log 2>&1' \
        >/dev/null 2>&1 || true
fi

log_step 8 "启动 host final_bridge (/odom, DDS 直连)"
nohup python3 "$PROJECT_ROOT/scripts/final_bridge_dds.py" \
    --camera-world-rebase base_start \
    --planarize-output \
    --stale-drop-ms 1000 \
    >/tmp/final_bridge_ondemand.log 2>&1 &
disown || true

log_step 9 "等待 host /odom 桥接成功"
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

log_step 10 "准备 Lite3 motion mode"
python3 "$PROJECT_ROOT/scripts/prepare_lite3_motion_mode.py" \
    >/tmp/prepare_lite3_motion_mode_ondemand.log 2>&1 || true

log_step 11 "启动 ROS2 比赛 launch（WHZ/YOLO/AprilTag 按需启动）"
exec ros2 launch "$PROJECT_ROOT/launch/competition.launch.py" \
    enable_task_manager:=true \
    enable_navigation:=true \
    enable_speech:=false \
    enable_cmd_vel_bridge:=true \
    cmd_vel_bridge_init_dog:=false \
    enable_depth_publisher:=false \
    enable_depth_pipeline:=false \
    enable_cone_avoidance:=true \
    enable_cone_mode_control:=true \
    require_cone_layer_startup_ready:=false \
    enable_apriltag_bridge:=true \
    enable_arm_motion:=true \
    arm_motion_authorized:=true \
    enable_manipulation:=true \
    manipulation_params_file:="$TASK_MANIPULATION_PARAMS_FILE" \
    arm_motion_params_file:="$ARM_MOTION_PARAMS_FILE" \
    arm_max_sequence_sec:=20.0 \
    depth_frames_dir:="$DEPTH_SHARED_DIR" \
    verify_depth_disable_localization:=false \
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
    auto_advance:=false \
    start_phase:=start \
    skip_pick_navigation:=false
