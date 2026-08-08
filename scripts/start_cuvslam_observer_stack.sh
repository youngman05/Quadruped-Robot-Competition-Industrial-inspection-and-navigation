#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Keep the observer qualification stack identical to the Phase 35 low-load baseline.
export ENABLE_SLAM_VISUALIZATION=false
export ENABLE_LANDMARKS_VIEW=false
export ENABLE_OBSERVATIONS_VIEW=false
export ENABLE_LOOP_METRICS_RECORDER=false
export STARTUP_TOPIC_CHECKS=false
export STARTUP_RATE_PROBES=false
export CUVSLAM_MOUNT_MODE=robot
export CUVSLAM_PROFILE=custom
export CUVSLAM_BASE_FRAME=base_link
export CUVSLAM_INPUT_BASE_FRAME=base_link
export CUVSLAM_INPUT_LEFT_CAMERA_FRAME=camera_infra1_frame
export CUVSLAM_INPUT_RIGHT_CAMERA_FRAME=
export CUVSLAM_INPUT_IMU_FRAME=camera_gyro_optical_frame
export CUVSLAM_CAMERA_PROFILE=640x360x30
export CUVSLAM_IMAGE_JITTER_THRESHOLD_MS=40.0
export CUVSLAM_FORCE_PLANAR_MODE=true
export CUVSLAM_DENOISE_INPUT_IMAGES=false
export CUVSLAM_ENABLE_IMU_FUSION=true
export CUVSLAM_REALSENSE_PUBLISH_TF=true

exec bash "$SCRIPT_DIR/start_cuvslam_rviz_gui.sh" --no-rviz --skip-input-test "$@"
