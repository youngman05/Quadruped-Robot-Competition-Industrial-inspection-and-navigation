#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

: "${TASK_MANIPULATION_PARAMS_FILE:?set TASK_MANIPULATION_PARAMS_FILE to the accepted TaskManager calibration YAML}"
: "${ARM_MOTION_PARAMS_FILE:?set ARM_MOTION_PARAMS_FILE to the accepted arm calibration YAML}"
: "${APRILTAG_TAG_IDS:?set APRILTAG_TAG_IDS to the accepted JSON list, for example [0,1,2,3]}"
: "${APRILTAG_TAG_SIZE_M:?set APRILTAG_TAG_SIZE_M to the measured black-square side length in metres}"

if [[ "${PICK_PLACE_CALIBRATION_APPROVED:-false}" != "true" ]]; then
    echo "NO-GO: set PICK_PLACE_CALIBRATION_APPROVED=true only after all segmented calibration gates pass" >&2
    exit 2
fi
if [[ "${TASK_MANIPULATION_CALIBRATED:-false}" != "true" ]]; then
    echo "NO-GO: set TASK_MANIPULATION_CALIBRATED=true only for an accepted calibration file" >&2
    exit 2
fi

export TASK_EXPECTED_MAP_ID=competition_field_phase1
export TASK_PASS_OBSTACLE_TIMEOUT_SEC=180.0
export TASK_PASS_OBSTACLE_WAYPOINT_TIMEOUT_SEC=120.0
export TASK_INSPECTION_TIMEOUT_SEC=300.0
export PURE_L6_START=false
export IMAGE="${IMAGE:-isaac_ros_cuvslam_runtime:humble-rs-cone-pick-place}"

exec bash "$PROJECT_ROOT/scripts/start_competition.sh" \
    --pick-place-l6 \
    --dog \
    --cmd-vel-bridge \
    --prepare-lite3-motion
