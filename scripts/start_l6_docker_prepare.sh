#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

log_step() {
  printf '\n[%s] STEP %s: %s\n' "$(date '+%H:%M:%S')" "$1" "$2"
}

DEPTH_SHARED_DIR="${DEPTH_SHARED_DIR:-$HOME/workspaces/isaac_ros-dev/camera_frames}"

log_step 0 "准备 cuVSLAM Docker（不启动 Host ROS2）"

log_step 1 "清理旧 cuVSLAM 容器与共享深度控制文件"
for container in $(docker ps -aq --filter name=cuvslam 2>/dev/null); do
    docker rm -f "$container" >/dev/null 2>&1 || true
done
rm -f "$DEPTH_SHARED_DIR/depth_control_request.json" \
      "$DEPTH_SHARED_DIR/depth_controller_status.json"

log_step 2 "后台启动 cuVSLAM / D455 锥桶感知"
nohup env \
  PROJECT_DIR="$PROJECT_ROOT" \
  IMAGE=isaac_ros_cuvslam_runtime:humble-rs-cone-pick-place \
  ROS_DOMAIN_ID=0 \
  CUVSLAM_ENABLE_DEPTH=true \
  CONE_AVOIDANCE_ENABLE=true \
  CUVSLAM_MOUNT_MODE=robot \
  CUVSLAM_PROFILE=custom \
  CUVSLAM_PUBLISH_MAP_TO_ODOM_TF=false \
  CUVSLAM_PUBLISH_ODOM_TO_BASE_TF=false \
  CUVSLAM_CAMERA_PROFILE=640x360x30 \
  ENABLE_LOOP_METRICS_RECORDER=false \
  STARTUP_TOPIC_CHECKS=false \
  bash "$PROJECT_ROOT/scripts/start_cuvslam_rviz_gui.sh" --no-rviz --skip-input-test \
  >/tmp/cuvslam_docker_prepare.log 2>&1 &
disown || true

log_step 3 "等待 cuVSLAM 容器与 /visual_slam/tracking/odometry"
CUVSLAM_WAIT_TIMEOUT_SEC="${CUVSLAM_WAIT_TIMEOUT_SEC:-120}"
CUVSLAM_CONTAINER=""
for _ in $(seq 1 "$((CUVSLAM_WAIT_TIMEOUT_SEC / 2))"); do
    CUVSLAM_CONTAINER="$(docker ps --format '{{.Names}}' --filter name=cuvslam | head -n 1)"
    if [ -n "$CUVSLAM_CONTAINER" ]; then
        if docker exec "$CUVSLAM_CONTAINER" bash -lc \
            'source /opt/ros/humble/setup.bash && \
             source /workspaces/isaac_ros-dev/install/setup.bash && \
             timeout 10 ros2 topic list 2>/dev/null | grep -Fx /visual_slam/tracking/odometry >/dev/null'; then
            break
        fi
    fi
    sleep 2
done
if [ -z "$CUVSLAM_CONTAINER" ]; then
    echo "ERROR: cuVSLAM container did not become ready within ${CUVSLAM_WAIT_TIMEOUT_SEC}s" >&2
    exit 1
fi
echo "cuVSLAM container ready: $CUVSLAM_CONTAINER"

log_step 4 "启动 Docker depth relay"
docker cp "$PROJECT_ROOT/scripts/depth_relay_docker.py" \
    "$CUVSLAM_CONTAINER:/tmp/depth_relay_docker.py" >/dev/null 2>&1 || true
docker cp "$PROJECT_ROOT/src/nodes/navigation/depth_contract.py" \
    "$CUVSLAM_CONTAINER:/tmp/depth_contract.py" >/dev/null 2>&1 || true
docker exec -d "$CUVSLAM_CONTAINER" bash -lc \
    'source /opt/ros/humble/setup.bash &&
     source /workspaces/isaac_ros-dev/install/setup.bash &&
     python3 /tmp/depth_relay_docker.py \
       --control-strategy parameter \
       --manage-cone-pipeline-parameters \
       --verify-localization-after-disable \
       >/tmp/dep.log 2>&1' >/dev/null 2>&1 || true

log_step 5 "启动 AprilTag 位姿节点"
docker cp "$PROJECT_ROOT/docker/d455_perception/d455_apriltag_pose_node.py" \
    "$CUVSLAM_CONTAINER":/opt/quadruped/perception/bin/d455_apriltag_pose_node.py \
    >/dev/null 2>&1 || true
docker exec -d \
    -e APRILTAG_TAG_IDS='[0,1]' \
    -e APRILTAG_TAG_SIZE_M=0.100 \
    "$CUVSLAM_CONTAINER" bash -lc \
    '/opt/quadruped/perception/bin/run_apriltag_pose_node.sh >/tmp/apriltag_pose.log 2>&1' \
    >/dev/null 2>&1 || true

log_step 6 "Docker 准备完成"
echo "cuVSLAM 容器名: $CUVSLAM_CONTAINER"
echo "日志: /tmp/cuvslam_docker_prepare.log"
