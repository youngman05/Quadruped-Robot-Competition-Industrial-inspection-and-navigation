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

exec ros2 run whz inspection_node --ros-args \
    -p rtsp_url:=rtsp://192.168.1.120:8554/test \
    -p model_path:="$PROJECT_ROOT/whz/assets/models/gauge_best.pt" \
    -p device:=0 \
    -p required_frames:=3 \
    -p min_agree_frames:=2
