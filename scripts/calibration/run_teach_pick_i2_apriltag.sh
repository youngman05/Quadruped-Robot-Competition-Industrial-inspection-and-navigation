#!/usr/bin/env bash
set -Eeo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

source /opt/ros/foxy/setup.bash
set -u
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTRTPS_DEFAULT_PROFILES_FILE="$ROOT/configs/ros/fastrtps_no_shm.xml"

cd "$ROOT"
exec python3 scripts/calibration/teach_pick_i2_apriltag.py 0 \
  --samples 60 \
  --copy-to-all-tags \
  "$@"
