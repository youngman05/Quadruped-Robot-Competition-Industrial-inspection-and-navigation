#!/usr/bin/env bash
# Run the production nearest-red AprilTag selector from an operator-set I0.
# This starts only the manager and cmd_vel bridge; it does not start Nav2 or the arm.
set -Eeo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PID_FILE=/tmp/pick_nearest_red_i0_to_i2.pid
LOG_FILE=/tmp/pick_nearest_red_i0_to_i2.log

source /opt/ros/foxy/setup.bash
source "$ROOT/install/setup.bash"
set -u
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0}
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTRTPS_DEFAULT_PROFILES_FILE="$ROOT/configs/ros/fastrtps_no_shm.xml"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "test process already running: $(cat "$PID_FILE")" >&2
  exit 1
fi

"$ROOT/scripts/start_lite3_control.sh"

nohup bash -lc "
  source /opt/ros/foxy/setup.bash
  source '$ROOT/install/setup.bash'
  export ROS_DOMAIN_ID='$ROS_DOMAIN_ID'
  export ROS_LOCALHOST_ONLY=0
  export RMW_IMPLEMENTATION='$RMW_IMPLEMENTATION'
  export FASTRTPS_DEFAULT_PROFILES_FILE='$FASTRTPS_DEFAULT_PROFILES_FILE'
  ros2 run quadruped_robot_competition competition_manager --ros-args \
    --params-file '$ROOT/configs/ros/competition_route_params.yaml' \
    --params-file '$ROOT/configs/calibration/pick_i2_apriltag.yaml' \
    --params-file '$ROOT/configs/test/pick_nearest_red_i0_to_i2_params.yaml' &
  manager_pid=\$!
  trap 'kill \$manager_pid 2>/dev/null || true; "$ROOT/scripts/stop_lite3_control.sh" >/dev/null 2>&1 || true' EXIT
  wait \$manager_pid
" >"$LOG_FILE" 2>&1 </dev/null &
echo $! >"$PID_FILE"

sleep 3
cat "$LOG_FILE"
