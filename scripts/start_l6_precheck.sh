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

log_step 3 "预检完成；cuVSLAM 暂不启动，进入场地后再启动"
echo "下一步（进入场地后）：bash scripts/start_l6_docker_prepare.sh"
