#!/usr/bin/env bash
# Start exactly one Lite3 /cmd_vel backend. Python is the proven single-packet default.
set -Eeo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BACKEND=python
[[ ${1:-} == "--official-transfer" ]] && BACKEND=transfer
PID_FILE=/tmp/lite3_control.pid
LOG_FILE=/tmp/lite3_control.log

source /opt/ros/foxy/setup.bash
source "$ROOT/install/setup.bash"
set -u
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0}
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTRTPS_DEFAULT_PROFILES_FILE="$ROOT/configs/ros/fastrtps_no_shm.xml"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Lite3 control already running: PID $(cat "$PID_FILE")" >&2
  exit 1
fi
existing=$(pgrep -af 'jetson2motion|cmd_vel_bridge' || true)
if [[ -n "$existing" ]]; then
  echo "Refusing to start a second Lite3 command source:" >&2
  echo "$existing" >&2
  exit 2
fi

if [[ "$BACKEND" == transfer ]]; then
  TRANSFER_SETUP="$ROOT/Lite3_ROS-ros2-foxy/install/setup.bash"
  [[ -f "$TRANSFER_SETUP" ]] || {
    echo "Official transfer is not built: $TRANSFER_SETUP" >&2
    echo "Build with: cd '$ROOT/Lite3_ROS-ros2-foxy' && colcon build --symlink-install" >&2
    exit 3
  }
  nohup bash -lc "
    source /opt/ros/foxy/setup.bash
    source '$TRANSFER_SETUP'
    export ROS_DOMAIN_ID='$ROS_DOMAIN_ID'
    export ROS_LOCALHOST_ONLY=0
    export RMW_IMPLEMENTATION='$RMW_IMPLEMENTATION'
    export FASTRTPS_DEFAULT_PROFILES_FILE='$FASTRTPS_DEFAULT_PROFILES_FILE'
    exec ros2 launch transfer transfer_launch.py
  " >"$LOG_FILE" 2>&1 </dev/null &
else
  nohup bash -lc "
    source /opt/ros/foxy/setup.bash
    source '$ROOT/install/setup.bash'
    export ROS_DOMAIN_ID='$ROS_DOMAIN_ID'
    export ROS_LOCALHOST_ONLY=0
    export RMW_IMPLEMENTATION='$RMW_IMPLEMENTATION'
    export FASTRTPS_DEFAULT_PROFILES_FILE='$FASTRTPS_DEFAULT_PROFILES_FILE'
    exec ros2 run quadruped_robot_competition cmd_vel_bridge --ros-args -p init_dog:=true
  " >"$LOG_FILE" 2>&1 </dev/null &
fi
pid=$!
echo "$pid" >"$PID_FILE"

for _ in $(seq 1 30); do
  if ! kill -0 "$pid" 2>/dev/null; then
    tail -40 "$LOG_FILE" >&2 || true
    rm -f "$PID_FILE"
    exit 4
  fi
  if [[ "$BACKEND" == transfer ]] && ros2 node list 2>/dev/null | grep -qx '/motion_sender'; then
    echo "Lite3 control ready: official transfer (PID $pid, log $LOG_FILE)"
    exit 0
  fi
  if [[ "$BACKEND" == python ]] && ros2 node list 2>/dev/null | grep -qx '/cmd_vel_bridge'; then
    echo "Lite3 control ready: Python fallback (PID $pid, log $LOG_FILE)"
    exit 0
  fi
  sleep 0.2
done

echo "Lite3 backend process started but ROS node was not discovered" >&2
tail -40 "$LOG_FILE" >&2 || true
"$ROOT/scripts/stop_lite3_control.sh" >/dev/null 2>&1 || true
exit 5
