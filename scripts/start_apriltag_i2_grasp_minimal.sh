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
export PYTHONPATH="$PROJECT_ROOT/src:$PROJECT_ROOT/arm_new/arm_new_ros:${PYTHONPATH:-}"

ARM_MOTION_PARAMS_FILE="${ARM_MOTION_PARAMS_FILE:-/home/superwfx666/competition_configs/arm_motion_competition_v1.yaml}"

echo "[minimal] stopping old competition processes and cuVSLAM containers"
bash "$PROJECT_ROOT/scripts/stop_all.sh" >/tmp/start_apriltag_i2_grasp_minimal_stop.log 2>&1 || true
for container in $(docker ps -aq --filter name=cuvslam 2>/dev/null); do
  docker rm -f "$container" >/dev/null 2>&1 || true
done

echo "[minimal] starting cuVSLAM/color for AprilTag"
nohup env \
  PROJECT_DIR="$PROJECT_ROOT" \
  IMAGE=isaac_ros_cuvslam_runtime:humble-rs-cone-pick-place \
  ROS_DOMAIN_ID=0 \
  CUVSLAM_ENABLE_DEPTH=false \
  CONE_AVOIDANCE_ENABLE=false \
  CUVSLAM_ENABLE_COLOR=true \
  CUVSLAM_MOUNT_MODE=robot \
  CUVSLAM_PROFILE=custom \
  CUVSLAM_CAMERA_PROFILE=640x360x30 \
  ENABLE_LOOP_METRICS_RECORDER=false \
  STARTUP_TOPIC_CHECKS=false \
  bash "$PROJECT_ROOT/scripts/start_cuvslam_rviz_gui.sh" --no-rviz --skip-input-test \
  >/tmp/cuvslam_minimal.log 2>&1 &
disown || true

echo "[minimal] waiting for cuVSLAM container"
CUVSLAM_CONTAINER=""
for _ in $(seq 1 60); do
  CUVSLAM_CONTAINER="$(docker ps --format '{{.Names}}' --filter name=cuvslam | head -n 1)"
  if [ -n "$CUVSLAM_CONTAINER" ]; then
    if docker exec "$CUVSLAM_CONTAINER" bash -lc \
      'source /opt/ros/humble/setup.bash && ros2 topic list 2>/dev/null | grep -Fx /camera/color/image_raw >/dev/null'; then
      break
    fi
  fi
  sleep 1
done
[ -n "$CUVSLAM_CONTAINER" ] || { echo "cuVSLAM container not ready" >&2; exit 1; }
echo "[minimal] cuVSLAM container: $CUVSLAM_CONTAINER"

echo "[minimal] injecting fixed AprilTag pose core"
docker cp "$PROJECT_ROOT/docker/d455_perception/apriltag_pose_core.py" \
  "$CUVSLAM_CONTAINER":/opt/quadruped/perception/bin/apriltag_pose_core.py
docker cp "$PROJECT_ROOT/docker/d455_perception/d455_apriltag_pose_node.py" \
  "$CUVSLAM_CONTAINER":/opt/quadruped/perception/bin/d455_apriltag_pose_node.py

echo "[minimal] starting Docker AprilTag"
docker exec -d -e APRILTAG_TAG_IDS='[0,1]' -e APRILTAG_TAG_SIZE_M=0.100 \
  "$CUVSLAM_CONTAINER" bash -lc \
  '/opt/quadruped/perception/bin/run_apriltag_pose_node.sh >/tmp/apriltag_pose.log 2>&1' \
  >/dev/null 2>&1 || true

echo "[minimal] starting host bridges"
nohup ros2 run quadruped_robot_competition apriltag_udp_bridge \
  >/tmp/apriltag_bridge_minimal.log 2>&1 &
nohup ros2 run quadruped_robot_competition cmd_vel_arbiter \
  --ros-args -p output_topic:=/cmd_vel \
  >/tmp/cmd_vel_arbiter_minimal.log 2>&1 &
nohup ros2 run quadruped_robot_competition cmd_vel_bridge \
  --ros-args -p init_dog:=false \
  >/tmp/cmd_vel_bridge_minimal.log 2>&1 &

echo "[minimal] starting arm_motion_node"
nohup ros2 run arm_new_ros arm_motion_node --ros-args \
  --params-file "$ARM_MOTION_PARAMS_FILE" \
  -p enable_motion:=true \
  -p transform_calibrated:=true \
  >/tmp/arm_motion_minimal.log 2>&1 &

echo "[minimal] starting task_manager in direct I2 mode"
exec ros2 run quadruped_robot_competition task_manager --ros-args \
  --params-file "$PROJECT_ROOT/configs/ros/competition_params.yaml" \
  --params-file /home/superwfx666/competition_configs/pick_place_competition_v1.yaml \
  -p enable_manipulation:=true \
  -p enable_pick_i2_alignment:=true \
  -p start_phase:=find_red_bar \
  -p skip_pick_navigation:=true \
  -p start_zone:=A \
  -p skip_odom_requirement:=true \
  -p enable_depth_milestones:=false \
  -p require_cone_layer_startup_ready:=false \
  -p enable_cone_controller:=false
