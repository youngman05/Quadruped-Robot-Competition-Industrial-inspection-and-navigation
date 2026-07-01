#!/bin/bash
# Rebuild Docker cuVSLAM -> UDP localhost -> Host /odom bridge.
set -e
cd ~/quadruped-robot-competition

find_cuvslam_container() {
  docker ps --format '{{.Names}}' 2>/dev/null | grep cuvslam | head -1 || true
}

cleanup_bridge_processes() {
  local cn="$1"
  if [ -n "$cn" ]; then
    docker exec "$cn" pkill -f '[c]uvslam_odometry_udp_exporter.py' 2>/dev/null || true
  fi
  pkill -f '[f]inal_bridge.py' 2>/dev/null || true
}

CN="$(find_cuvslam_container)"

echo 'Cleaning old UDP exporter / Host bridge...'
cleanup_bridge_processes "$CN"
sleep 2

if [ -z "$CN" ]; then
  echo 'ERROR: no running cuVSLAM container found. Start cuVSLAM first.' >&2
  exit 1
fi
echo "Docker: $CN"

source /opt/ros/foxy/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_DOMAIN_ID=0
export FASTRTPS_DEFAULT_PROFILES_FILE=~/quadruped-robot-competition/configs/ros/fastrtps_no_shm.xml
export PYTHONPATH=/opt/ros/foxy/lib/python3.8/site-packages

nohup python3 scripts/final_bridge.py > /tmp/fb.log 2>&1 &
echo "Bridge PID: $!"
BRIDGED=false
for _ in $(seq 1 45); do
  if grep -q 'bridged .* UDP msgs' /tmp/fb.log 2>/dev/null; then
    BRIDGED=true
    break
  fi
  sleep 1
done

echo 'Bridge log:'
tail -8 /tmp/fb.log || true
if [ "$BRIDGED" != true ]; then
  echo 'ERROR: bridge did not receive UDP odometry within 45s.' >&2
  echo 'Exporter log:' >&2
  docker exec "$CN" tail -20 /tmp/cuvslam_odometry_udp_exporter.log 2>/dev/null || true
  exit 2
fi

echo ''
echo 'Testing /odom with BEST_EFFORT probe...'
python3 scripts/probe_odom_best_effort.py --duration 5 --first-timeout 2 --no-color
