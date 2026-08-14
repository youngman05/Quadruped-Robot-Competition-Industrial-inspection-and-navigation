#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CONTAINER=${D455_CONTAINER:-d455_yolo_repro_20260811}
UDP_HOST=${APRILTAG_UDP_HOST:-127.0.0.1}
UDP_PORT=${APRILTAG_UDP_PORT:-19003}
TAG_SIZE_M=${APRILTAG_TAG_SIZE_M:-0.100}

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "container not found: $CONTAINER" >&2
  exit 1
fi
if [[ $(docker inspect -f '{{.State.Running}}' "$CONTAINER") != true ]]; then
  docker start "$CONTAINER" >/dev/null
fi

RUNTIME_DIR=/tmp/d455_apriltag
docker exec "$CONTAINER" mkdir -p "$RUNTIME_DIR"
docker cp "$ROOT/docker/d455_perception/apriltag_pose_core.py" \
  "$CONTAINER:$RUNTIME_DIR/apriltag_pose_core.py"
docker cp "$ROOT/docker/d455_perception/d455_apriltag_pose_node.py" \
  "$CONTAINER:$RUNTIME_DIR/d455_apriltag_pose_node.py"

docker exec "$CONTAINER" bash -lc '
  pkill -f "[d]455_apriltag_pose_node.py" 2>/dev/null || true
  for _ in {1..10}; do
    pgrep -f "[d]455_apriltag_pose_node.py" >/dev/null || break
    sleep 0.1
  done
  rm -f /tmp/d455_apriltag_pose.pid'
docker exec "$CONTAINER" bash -lc \
  "source /opt/ros/humble/setup.bash; \
   export PYTHONPATH=/opt/host-python:$RUNTIME_DIR:\${PYTHONPATH:-}; \
   export LD_LIBRARY_PATH=/usr/local/cuda-11.4/targets/aarch64-linux/lib:\${LD_LIBRARY_PATH:-}; \
   nohup /usr/bin/python3 $RUNTIME_DIR/d455_apriltag_pose_node.py \
      --ros-args -p udp_host:=$UDP_HOST -p udp_port:=$UDP_PORT -p tag_size_m:=$TAG_SIZE_M \
     >/tmp/d455_apriltag_pose.log 2>&1 & \
   echo \$! >/tmp/d455_apriltag_pose.pid"

sleep 2
docker exec "$CONTAINER" bash -lc \
  "pgrep -af d455_apriltag_pose_node.py; tail -20 /tmp/d455_apriltag_pose.log"
