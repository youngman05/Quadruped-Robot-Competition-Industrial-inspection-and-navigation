#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(dirname -- "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd -- "$SCRIPT_DIR"; pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.."; pwd)"
cd "$PROJECT_ROOT"
SOURCE_COMMIT="$(git rev-parse HEAD)"

exec env \
    TASK_MANIPULATION_PARAMS_FILE=/home/superwfx666/competition_configs/pick_place_competition_v1.yaml \
    ARM_MOTION_PARAMS_FILE=/home/superwfx666/competition_configs/arm_motion_competition_v1.yaml \
    PICK_PLACE_SOURCE_COMMIT="$SOURCE_COMMIT" \
    IMAGE=isaac_ros_cuvslam_runtime:humble-rs-cone-pick-place \
    PICK_PLACE_IMAGE_ID=sha256:f7384634ab69256558415a074d4ad53774f2399390ddcdc7135f2c33415fb5a0 \
    ARM_MOTION_AUTHORIZED=true \
    PURE_L6_START=true \
    TASK_EXPECTED_MAP_ID=competition_field_phase1 \
    TASK_WAYPOINT_FILE="$PROJECT_ROOT/configs/navigation/waypoints_real.yaml" \
    TASK_WAYPOINT_ROUTE=full_interleaved \
    TASK_PASS_OBSTACLE_TIMEOUT_SEC=180.0 \
    TASK_PASS_OBSTACLE_WAYPOINT_TIMEOUT_SEC=120.0 \
    TASK_INSPECTION_TIMEOUT_SEC=300.0 \
    bash scripts/start_competition.sh \
        --pick-place-l6 \
        --dog \
        --cmd-vel-bridge \
        --prepare-lite3-motion
