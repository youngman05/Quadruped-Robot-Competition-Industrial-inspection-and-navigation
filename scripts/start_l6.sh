#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

export TASK_EXPECTED_MAP_ID=competition_field_phase1
export TASK_PASS_OBSTACLE_TIMEOUT_SEC=180.0
export TASK_PASS_OBSTACLE_WAYPOINT_TIMEOUT_SEC=120.0
export TASK_INSPECTION_TIMEOUT_SEC=300.0
export PURE_L6_START=true

exec bash "$PROJECT_ROOT/scripts/start_competition.sh" \
    --cone-to-whz-l6 \
    --dog \
    --cmd-vel-bridge \
    --prepare-lite3-motion
