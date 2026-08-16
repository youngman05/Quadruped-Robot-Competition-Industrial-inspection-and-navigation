#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

: "${TASK_MANIPULATION_PARAMS_FILE:?set TASK_MANIPULATION_PARAMS_FILE to the competition_v1 TaskManager preset YAML}"
: "${ARM_MOTION_PARAMS_FILE:?set ARM_MOTION_PARAMS_FILE to the competition_v1 arm preset YAML}"
: "${PICK_PLACE_SOURCE_COMMIT:?set PICK_PLACE_SOURCE_COMMIT to the approved formal deploy commit}"

if [[ "${ARM_MOTION_AUTHORIZED:-false}" != "true" ]]; then
    echo "NO-GO: full pick/place requires explicit ARM_MOTION_AUTHORIZED=true" >&2
    exit 2
fi
export ARM_MOTION_AUTHORIZED=true

export TASK_EXPECTED_MAP_ID=competition_field_phase1
export TASK_WAYPOINT_FILE="$PROJECT_ROOT/configs/navigation/waypoints_real.yaml"
export TASK_WAYPOINT_ROUTE=full_interleaved
export TASK_PASS_OBSTACLE_TIMEOUT_SEC=180.0
export TASK_PASS_OBSTACLE_WAYPOINT_TIMEOUT_SEC=120.0
export TASK_INSPECTION_TIMEOUT_SEC=300.0
export PURE_L6_START=false
export IMAGE="${IMAGE:-isaac_ros_cuvslam_runtime:humble-rs-cone-pick-place}"
export PICK_PLACE_IMAGE_ID="${PICK_PLACE_IMAGE_ID:-sha256:aafbc91a7e7169fe3b6b87f7dd1caf639fbc0ff3c9fbfef6150b1b8b09fa5966}"

exec bash "$PROJECT_ROOT/scripts/start_competition.sh" \
    --pick-place-l6 \
    --dog \
    --cmd-vel-bridge \
    --prepare-lite3-motion
