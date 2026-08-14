#!/usr/bin/env bash
# Start and verify the D455 AprilTag Docker-to-Host data path. No motion nodes.
set -Eeo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
FRAMES=${APRILTAG_HEALTH_FRAMES:-8}
TIMEOUT_S=${APRILTAG_HEALTH_TIMEOUT_S:-20}
MAX_ATTEMPTS=${APRILTAG_HEALTH_ATTEMPTS:-3}
MAX_INTERVAL_S=${APRILTAG_HEALTH_MAX_INTERVAL_S:-2}

if ! [[ $FRAMES =~ ^[1-9][0-9]*$ && $TIMEOUT_S =~ ^[1-9][0-9]*$ && $MAX_ATTEMPTS =~ ^[1-9][0-9]*$ && $MAX_INTERVAL_S =~ ^[1-9][0-9]*$ ]]; then
  echo "AprilTag health-check environment values must be positive integers" >&2
  exit 2
fi

source /opt/ros/foxy/setup.bash
source "$ROOT/install/setup.bash"
set -u
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0}
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTRTPS_DEFAULT_PROFILES_FILE="$ROOT/configs/ros/fastrtps_no_shm.xml"

"$ROOT/scripts/start_d455_apriltag.sh"
"$ROOT/scripts/start_apriltag_camera_static_tf.sh"

for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  "$ROOT/scripts/start_apriltag_host_bridge.sh"
  echo "AprilTag host health check ${attempt}/${MAX_ATTEMPTS}"
  if python3 "$ROOT/scripts/probe_apriltag_bridge.py" \
    --frames "$FRAMES" --timeout "$TIMEOUT_S" --max-interval "$MAX_INTERVAL_S"; then
    echo "AprilTag Docker-to-Host link is healthy."
    exit 0
  fi
  echo "AprilTag health check failed; restarting only the Host UDP bridge." >&2
done

echo "AprilTag Docker-to-Host link did not become healthy." >&2
echo "Docker detector log:" >&2
docker exec "${D455_CONTAINER:-d455_yolo_repro_20260811}" \
  tail -50 /tmp/d455_apriltag_pose.log >&2 || true
echo "Host bridge log:" >&2
tail -50 /tmp/apriltag_udp_bridge.log >&2 || true
exit 1
