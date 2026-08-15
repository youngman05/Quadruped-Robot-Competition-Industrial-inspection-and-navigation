#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

: "${TASK_MANIPULATION_PARAMS_FILE:?set TASK_MANIPULATION_PARAMS_FILE to the competition_v1 TaskManager preset YAML}"
: "${ARM_MOTION_PARAMS_FILE:?set ARM_MOTION_PARAMS_FILE to the competition_v1 arm preset YAML}"
: "${PICK_PLACE_SOURCE_COMMIT:?set PICK_PLACE_SOURCE_COMMIT to the approved formal deploy commit}"

export TASK_EXPECTED_MAP_ID=competition_field_phase1
export TASK_WAYPOINT_FILE="${TASK_WAYPOINT_FILE:-$PROJECT_ROOT/configs/navigation/waypoints_real.yaml}"
export TASK_WAYPOINT_ROUTE=full_interleaved
export ARM_MOTION_AUTHORIZED=false
export PURE_L6_START=false
export IMAGE="${IMAGE:-isaac_ros_cuvslam_runtime:humble-rs-cone-pick-place}"
export PICK_PLACE_IMAGE_ID="${PICK_PLACE_IMAGE_ID:-sha256:f7384634ab69256558415a074d4ad53774f2399390ddcdc7135f2c33415fb5a0}"

exec bash "$PROJECT_ROOT/scripts/start_competition.sh" --pick-place-preflight-only
