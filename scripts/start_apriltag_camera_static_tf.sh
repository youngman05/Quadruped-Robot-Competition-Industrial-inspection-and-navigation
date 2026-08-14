#!/usr/bin/env bash
set -Eeo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PID_FILE=/tmp/apriltag_camera_static_tf.pid
LOG_FILE=/tmp/apriltag_camera_static_tf.log

source /opt/ros/foxy/setup.bash
source "$ROOT/install/setup.bash"
set -u
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0}
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}
export FASTRTPS_DEFAULT_PROFILES_FILE="$ROOT/configs/ros/fastrtps_no_shm.xml"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  kill "$(cat "$PID_FILE")"
fi

nohup ros2 run quadruped_robot_competition project_static_transform_publisher \
  --ros-args \
  -p parent_frame:=base_link \
  -p child_frame:=camera_link \
  -p translation_m:='[0.231724440,0.077561412,0.503275873]' \
  -p rotation_xyzw:='[0.000900958,0.240529563,-0.013474058,0.970547870]' \
  >"$LOG_FILE" 2>&1 </dev/null &
echo $! >"$PID_FILE"

sleep 2
cat "$LOG_FILE"
