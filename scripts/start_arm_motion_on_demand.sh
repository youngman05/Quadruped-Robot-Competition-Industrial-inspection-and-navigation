#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

export AMENT_TRACE_SETUP_FILES="${AMENT_TRACE_SETUP_FILES:-}"
set +u
source /opt/ros/foxy/setup.bash
source "$HOME/cone_l2_plugin_ws_2_2_1/install/local_setup.bash"
source "$HOME/nav2_foxy_overlay_ws/install/local_setup.bash"
source "$PROJECT_ROOT/install/local_setup.bash"
set -u

export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_DOMAIN_ID=0
export FASTRTPS_DEFAULT_PROFILES_FILE="$PROJECT_ROOT/configs/ros/fastrtps_no_shm.xml"

ARM_MOTION_PARAMS_FILE="${ARM_MOTION_PARAMS_FILE:-/home/superwfx666/competition_configs/arm_motion_competition_v1.yaml}"

exec ros2 run arm_new_ros arm_motion_node --ros-args \
    --params-file "$ARM_MOTION_PARAMS_FILE" \
    -p enable_motion:=true \
    -p transform_calibrated:=true
