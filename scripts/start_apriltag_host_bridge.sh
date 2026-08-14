#!/usr/bin/env bash
set -Eeo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PID_FILE=/tmp/apriltag_udp_bridge_launch.pid
LOG_FILE=/tmp/apriltag_udp_bridge.log

source /opt/ros/foxy/setup.bash
source "$ROOT/install/setup.bash"
set -u
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0}
export RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}
# Foxy Fast DDS SHM isolates this publisher from other Host processes when
# Docker participants share /dev/shm. Use the project's validated UDP profile.
export ROS_LOCALHOST_ONLY=0
export FASTRTPS_DEFAULT_PROFILES_FILE="$ROOT/configs/ros/fastrtps_no_shm.xml"

if [[ -f "$PID_FILE" ]]; then
  previous_pid=$(cat "$PID_FILE")
  if kill -0 "$previous_pid" 2>/dev/null; then
    kill -- -"$previous_pid"
    for _ in {1..20}; do
      kill -0 "$previous_pid" 2>/dev/null || break
      sleep 0.1
    done
  fi
fi

nohup setsid ros2 launch quadruped_robot_competition apriltag_udp_bridge.launch.py \
  >"$LOG_FILE" 2>&1 </dev/null &
echo $! >"$PID_FILE"

sleep 3
launch_pid=$(cat "$PID_FILE")
if ! kill -0 "$launch_pid" 2>/dev/null; then
  cat "$LOG_FILE"
  exit 1
fi
tail -20 "$LOG_FILE"
