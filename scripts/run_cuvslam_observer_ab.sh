#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONTAINER_NAME=""
HOST_OUTPUT_ROOT=""
CONTAINER_OUTPUT_ROOT="/logs/observer_ab"
DURATION_S="120.0"
ROUNDS="3"
ROUND_WARMUP_S="3.0"
REST_S="5.0"
READY_SETTLE_S="10.0"

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/run_cuvslam_observer_ab.sh \
    --container-name NAME \
    --host-output-root /path/to/current/cuvslam/log/observer_ab

The cuVSLAM container must already be running via:
  bash scripts/start_cuvslam_observer_stack.sh

Options:
  --container-name NAME       Exact running cuVSLAM container name (required).
  --host-output-root PATH     Host path corresponding to /logs/observer_ab (required).
  --duration SECONDS          Timed duration for every A or B window. Default: 120.
  --rounds COUNT              Number of A/B pairs. Default: 3.
  --round-warmup SECONDS      Probe graph-settle time before each timed window. Default: 3.
  --rest SECONDS              Untimed rest between windows. Default: 5.
  --ready-settle SECONDS      Untimed settle after first odometry message. Default: 10.

This script never starts Nav2, a bridge, tegrastats, or a motion sender.
USAGE
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --container-name) CONTAINER_NAME="${2:-}"; shift 2 ;;
    --host-output-root) HOST_OUTPUT_ROOT="${2:-}"; shift 2 ;;
    --duration) DURATION_S="${2:-}"; shift 2 ;;
    --rounds) ROUNDS="${2:-}"; shift 2 ;;
    --round-warmup) ROUND_WARMUP_S="${2:-}"; shift 2 ;;
    --rest) REST_S="${2:-}"; shift 2 ;;
    --ready-settle) READY_SETTLE_S="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[[ -n "$CONTAINER_NAME" ]] || die "--container-name is required"
[[ -n "$HOST_OUTPUT_ROOT" ]] || die "--host-output-root is required"
[[ "$ROUNDS" =~ ^[1-9][0-9]*$ ]] || die "--rounds must be a positive integer"
command -v docker >/dev/null || die "docker is unavailable"
command -v python3 >/dev/null || die "python3 is unavailable"
docker inspect "$CONTAINER_NAME" >/dev/null 2>&1 || die "container not found: $CONTAINER_NAME"
mkdir -p "$HOST_OUTPUT_ROOT"
LOG_MOUNT_SOURCE="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/logs"}}{{.Source}}{{end}}{{end}}' "$CONTAINER_NAME")"
[[ -n "$LOG_MOUNT_SOURCE" ]] || die "container has no /logs bind mount"
EXPECTED_OUTPUT_ROOT="$(readlink -f "$LOG_MOUNT_SOURCE/observer_ab")"
ACTUAL_OUTPUT_ROOT="$(readlink -f "$HOST_OUTPUT_ROOT")"
[[ "$ACTUAL_OUTPUT_ROOT" == "$EXPECTED_OUTPUT_ROOT" ]] || \
  die "--host-output-root must map to /logs/observer_ab: expected $EXPECTED_OUTPUT_ROOT"

container_ros() {
  docker exec "$CONTAINER_NAME" bash -lc \
    "source /opt/ros/humble/setup.bash && \
     source /workspaces/isaac_ros-dev/install/setup.bash && \
     source /workspaces/isaac_ros-dev/install_observer_probe/setup.bash && $*"
}

container_ros "test -f /workspaces/isaac_ros-dev/install_observer_probe/setup.bash" || \
  die "isolated observer overlay is missing; run scripts/build_cuvslam_lightweight_probe.sh first"
container_ros "ros2 pkg prefix cuvslam_lightweight_probe >/dev/null" || \
  die "cuvslam_lightweight_probe is not built in the container overlay"

for required_setting in \
  ENABLE_SLAM_VISUALIZATION=false \
  ENABLE_LANDMARKS_VIEW=false \
  ENABLE_OBSERVATIONS_VIEW=false \
  ENABLE_LOOP_METRICS_RECORDER=false \
  STARTUP_TOPIC_CHECKS=false \
  STARTUP_RATE_PROBES=false \
  SKIP_RVIZ=1 \
  CUVSLAM_MOUNT_MODE=robot \
  CUVSLAM_PROFILE=custom \
  CUVSLAM_BASE_FRAME=base_link \
  CUVSLAM_INPUT_BASE_FRAME=base_link \
  CUVSLAM_INPUT_LEFT_CAMERA_FRAME=camera_infra1_frame \
  CUVSLAM_INPUT_RIGHT_CAMERA_FRAME= \
  CUVSLAM_INPUT_IMU_FRAME=camera_gyro_optical_frame \
  CUVSLAM_CAMERA_PROFILE=640x360x30 \
  CUVSLAM_IMAGE_JITTER_THRESHOLD_MS=40.0 \
  CUVSLAM_FORCE_PLANAR_MODE=true \
  CUVSLAM_DENOISE_INPUT_IMAGES=false \
  CUVSLAM_ENABLE_IMU_FUSION=true \
  CUVSLAM_REALSENSE_PUBLISH_TF=true; do
  container_ros "grep -Fx '$required_setting' /logs/runtime_config.env >/dev/null" || \
    die "low-load runtime setting is missing: $required_setting"
done

echo "Preflight: wait for the first BEST_EFFORT odometry sample (outside timed windows)."
container_ros \
  "timeout 120 ros2 topic echo --qos-reliability best_effort --once /visual_slam/tracking/odometry nav_msgs/msg/Odometry >/logs/observer_ab_odom_ready.txt"

echo "Preflight: record actual /visual_slam/status type and publisher QoS."
container_ros \
  "ros2 topic info --verbose /visual_slam/status >$CONTAINER_OUTPUT_ROOT/status_topic_info.txt 2>&1 || true; ros2 daemon stop >/dev/null 2>&1 || true"
sleep "$READY_SETTLE_S"

run_window() {
  local label="$1"
  local subscribe="$2"
  local output_dir="$CONTAINER_OUTPUT_ROOT/$label"
  mkdir -p "$HOST_OUTPUT_ROOT/$label"
  echo "Starting $label: subscribe_topics=$subscribe duration=${DURATION_S}s"
  container_ros \
    "ros2 run cuvslam_lightweight_probe cuvslam_lightweight_probe --ros-args \
      -p subscribe_topics:=$subscribe \
      -p duration_s:=$DURATION_S \
      -p warmup_s:=$ROUND_WARMUP_S \
      -p sample_interval_s:=1.0 \
      -p qos_depth:=16 \
      -p output_json:=$output_dir/report.json \
      -p launch_log_path:=/logs/launch.log"
}

for index in $(seq 1 "$ROUNDS"); do
  run_window "A$index" false
  sleep "$REST_S"
  run_window "B$index" true
  if [[ "$index" -lt "$ROUNDS" ]]; then
    sleep "$REST_S"
  fi
done

python3 "$PROJECT_DIR/scripts/analyze_cuvslam_observer_ab.py" \
  --input-root "$HOST_OUTPUT_ROOT" \
  --expected-rounds "$ROUNDS" \
  --self-cpu-limit 5.0 \
  --aggregate-delta-limit 2.0
