#!/usr/bin/env bash

# Deliberately minimal field launcher. It performs no preflight, readiness,
# source-cleanliness, image, calibration, or build checks.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

source /opt/ros/foxy/setup.bash
source "$HOME/cone_l2_plugin_ws_2_2_1/install/local_setup.bash"
source "$HOME/nav2_foxy_overlay_ws/install/local_setup.bash"
source "$PROJECT_ROOT/install/local_setup.bash"

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

bash "$PROJECT_ROOT/scripts/stop_all.sh" >/tmp/start_l6_pick_place_unchecked_stop.log 2>&1 || true
for container in $(docker ps -aq --filter name=cuvslam 2>/dev/null); do
    docker rm -f "$container" >/dev/null 2>&1 || true
done
rm -f "$DEPTH_SHARED_DIR/depth_control_request.json" \
      "$DEPTH_SHARED_DIR/depth_controller_status.json"

export IMAGE=isaac_ros_cuvslam_runtime:humble-rs-cone-pick-place
PROJECT_DIR="$PROJECT_ROOT" \
ROS_DOMAIN_ID=42 \
CUVSLAM_ENABLE_DEPTH=true \
CONE_AVOIDANCE_ENABLE=true \
CUVSLAM_MOUNT_MODE=robot \
CUVSLAM_PROFILE=custom \
bash "$PROJECT_ROOT/scripts/start_cuvslam_rviz_gui.sh" --no-rviz \
    >/tmp/cuvslam_start_unchecked.log 2>&1 &

sleep "${CUVSLAM_BOOT_DELAY_SEC:-90}"
CUVSLAM_CONTAINER="$(docker ps --format '{{.Names}}' --filter name=cuvslam | head -n 1)"

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
       --verify-localization-after-disable \
       >/tmp/dep.log 2>&1' >/dev/null 2>&1 || true

docker exec -d \
    -e APRILTAG_TAG_IDS='[0,1]' \
    -e APRILTAG_TAG_SIZE_M=0.100 \
    "$CUVSLAM_CONTAINER" bash -lc \
    '/opt/quadruped/perception/bin/run_apriltag_pose_node.sh >/tmp/apriltag_pose.log 2>&1' \
    >/dev/null 2>&1 || true

nohup python3 "$PROJECT_ROOT/scripts/final_bridge.py" \
    --camera-world-rebase base_start \
    --planarize-output \
    >/tmp/final_bridge_unchecked.log 2>&1 &

python3 "$PROJECT_ROOT/scripts/prepare_lite3_motion_mode.py" \
    >/tmp/prepare_lite3_motion_mode_unchecked.log 2>&1 || true

exec ros2 launch "$PROJECT_ROOT/launch/competition.launch.py" \
    enable_task_manager:=true \
    enable_navigation:=true \
    enable_cmd_vel_bridge:=true \
    cmd_vel_bridge_init_dog:=false \
    enable_depth_publisher:=false \
    enable_depth_pipeline:=false \
    enable_cone_avoidance:=true \
    enable_cone_mode_control:=true \
    enable_apriltag_bridge:=true \
    enable_yolo_udp_bridge:=false \
    enable_arm_motion:=true \
    arm_motion_authorized:=true \
    enable_manipulation:=true \
    manipulation_params_file:="$TASK_MANIPULATION_PARAMS_FILE" \
    arm_motion_params_file:="$ARM_MOTION_PARAMS_FILE" \
    arm_max_sequence_sec:=20.0 \
    depth_frames_dir:="$DEPTH_SHARED_DIR" \
    verify_depth_disable_localization:=true \
    cone_params_file:="$PROJECT_ROOT/configs/navigation/nav2_cone_obstacles.yaml" \
    enable_yolo:=false \
    enable_whz:=true \
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
