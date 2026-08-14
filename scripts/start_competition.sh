#!/bin/bash
# ==============================================
#  四足机器人竞赛 — 鲁棒一键启动
#  用法: bash scripts/start_competition.sh [--dog] [--cmd-vel-bridge] [--prepare-lite3-motion] [--yolo] [--whz] [--task-manager] [--cone-to-whz-l6] [--auto-advance] [--camera-relay] [--depth-relay] [--depth-pipeline] [--cone-avoidance] [--skip-depth-disable-health-check]
# ==============================================
# 注意: 不用 set -e，每个步骤自行容错

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1
LOGDIR="$HOME/Desktop/logs"
mkdir -p "$LOGDIR"
STARTUP_TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOGFILE="$LOGDIR/competition_$STARTUP_TIMESTAMP.log"
STARTUP_SNAPSHOT="${STARTUP_SNAPSHOT:-$LOGDIR/competition_startup_$STARTUP_TIMESTAMP.txt}"
exec > >(tee -a "$LOGFILE") 2>&1
echo "日志: $LOGFILE"
trap 'echo ""; echo "Ctrl+C → 清理..."; bash scripts/stop_all.sh' INT TERM
STARTUP_RUNTIME_TOUCHED=false
RUNTIME_STARTED_CUVSLAM=false
RUNTIME_CUVSLAM_CONTAINER=""
RUNTIME_CUVSLAM_WRAPPER_PID=""

startup_no_go() {
    echo "NO-GO: $*"
    echo " 启动快照: $STARTUP_SNAPSHOT"
    if ${STARTUP_RUNTIME_TOUCHED:-false}; then
        echo " 清理已启动的正式栈..."
        bash scripts/stop_all.sh >/dev/null 2>&1 || true
    fi
    if ${RUNTIME_STARTED_CUVSLAM:-false} && [ -n "${RUNTIME_CUVSLAM_CONTAINER:-}" ]; then
        echo " 停止本轮 cuVSLAM 容器: $RUNTIME_CUVSLAM_CONTAINER"
        docker stop -t 10 "$RUNTIME_CUVSLAM_CONTAINER" >/dev/null 2>&1 || true
    fi
    if [ -n "${RUNTIME_CUVSLAM_WRAPPER_PID:-}" ]; then
        kill -TERM "$RUNTIME_CUVSLAM_WRAPPER_PID" >/dev/null 2>&1 || true
        sleep 1
        kill -KILL "$RUNTIME_CUVSLAM_WRAPPER_PID" >/dev/null 2>&1 || true
        wait "$RUNTIME_CUVSLAM_WRAPPER_PID" >/dev/null 2>&1 || true
    fi
    exit 1
}

# Supervisors may watch this path before the ROS launch starts. Remove stale
# motion/status lines from an earlier run before any long preflight work.
: > /tmp/competition.log || {
    echo "ERROR: cannot reset /tmp/competition.log"
    exit 1
}

snapshot_value() {
    printf '%s=%s\n' "$1" "$2" >> "$STARTUP_SNAPSHOT"
}

# ── 参数解析 ──────────────────────────────
ENABLE_YOLO=false; ENABLE_WHZ=false; ENABLE_DOG=false; ENABLE_CMD_VEL_BRIDGE=false; ENABLE_CMD_VEL_BRIDGE_INIT=false; PREPARE_LITE3_MOTION=false
ENABLE_CAMERA_RELAY=false; ENABLE_DEPTH_RELAY=false
ENABLE_DEPTH_PIPELINE=false
ENABLE_CONE_AVOIDANCE=false
ENABLE_CONE_MODE_CONTROL=false
VERIFY_DEPTH_DISABLE_LOCALIZATION=true
ENABLE_TASK_MANAGER=false; AUTO_ADVANCE=false; DO_STAND=false
CONE_TO_WHZ_L6=false
for arg in "$@"; do
    case $arg in
        --yolo)  ENABLE_YOLO=true ;;
        --whz)   ENABLE_WHZ=true ;;
        --dog)   ENABLE_DOG=true ;;
        --cmd-vel-bridge) ENABLE_CMD_VEL_BRIDGE=true ;;
        --bridge-init-dog|--init-dog) ENABLE_CMD_VEL_BRIDGE_INIT=true ;;
        --prepare-lite3-motion) PREPARE_LITE3_MOTION=true ;;
        --task-manager|--mission) ENABLE_TASK_MANAGER=true ;;
        --cone-to-whz-l6) CONE_TO_WHZ_L6=true ;;
        --auto-advance) ENABLE_TASK_MANAGER=true; AUTO_ADVANCE=true ;;
        --camera-relay) ENABLE_CAMERA_RELAY=true ;;
        --depth-relay) ENABLE_DEPTH_RELAY=true ;;
        --depth-pipeline) ENABLE_DEPTH_RELAY=true; ENABLE_DEPTH_PIPELINE=true ;;
        --cone-avoidance) ENABLE_CONE_AVOIDANCE=true ;;
        --skip-depth-disable-health-check) VERIFY_DEPTH_DISABLE_LOCALIZATION=false ;;
        --relays) ENABLE_CAMERA_RELAY=true; ENABLE_DEPTH_RELAY=true ;;
        --stand) DO_STAND=true ;;   # force stand toggle (dog lying down)
    esac
done

TASK_MAX_NAV_RETRIES="${TASK_MAX_NAV_RETRIES:-3}"
TASK_MAX_INSPECTION_RETRIES="${TASK_MAX_INSPECTION_RETRIES:-3}"
TASK_FINISH_AFTER_INSPECTION="${TASK_FINISH_AFTER_INSPECTION:-false}"
TASK_ALLOW_PLACEHOLDER_MANIPULATION="${TASK_ALLOW_PLACEHOLDER_MANIPULATION:-false}"
TASK_PASS_OBSTACLE_TIMEOUT_SEC="${TASK_PASS_OBSTACLE_TIMEOUT_SEC:-180.0}"
TASK_PASS_OBSTACLE_WAYPOINT_TIMEOUT_SEC="${TASK_PASS_OBSTACLE_WAYPOINT_TIMEOUT_SEC:-120.0}"
TASK_INSPECTION_TIMEOUT_SEC="${TASK_INSPECTION_TIMEOUT_SEC:-300.0}"
TASK_MISSION_START_ARMED="${TASK_MISSION_START_ARMED:-true}"
TASK_WAYPOINT_FILE="${TASK_WAYPOINT_FILE:-}"
TASK_WAYPOINT_ROUTE="${TASK_WAYPOINT_ROUTE:-inspection_interleaved}"
TASK_EXPECTED_MAP_ID="${TASK_EXPECTED_MAP_ID:-}"

if $CONE_TO_WHZ_L6; then
    ENABLE_CONE_AVOIDANCE=true
    ENABLE_TASK_MANAGER=true
    ENABLE_WHZ=true
    TASK_MAX_NAV_RETRIES=0
    TASK_MAX_INSPECTION_RETRIES=0
    TASK_FINISH_AFTER_INSPECTION=true
    TASK_ALLOW_PLACEHOLDER_MANIPULATION=false
    TASK_MISSION_START_ARMED=false
    TASK_WAYPOINT_FILE="${TASK_WAYPOINT_FILE:-$PROJECT_ROOT/configs/navigation/waypoints_real.yaml}"
fi

if $ENABLE_CONE_AVOIDANCE && $ENABLE_TASK_MANAGER; then
    ENABLE_CONE_MODE_CONTROL=true
    ENABLE_DEPTH_RELAY=true
fi

if $ENABLE_DEPTH_PIPELINE && $ENABLE_CONE_AVOIDANCE; then
    echo "ERROR: --depth-pipeline and --cone-avoidance are mutually exclusive"
    exit 2
fi

echo ''
echo '==================================='
echo ' 四足机器人竞赛系统 v2 — 鲁棒启动'
echo '==================================='
echo " DOG=$ENABLE_DOG  CMD_VEL_BRIDGE=$ENABLE_CMD_VEL_BRIDGE  BRIDGE_INIT_DOG=$ENABLE_CMD_VEL_BRIDGE_INIT  PREPARE_LITE3_MOTION=$PREPARE_LITE3_MOTION  YOLO=$ENABLE_YOLO  WHZ=$ENABLE_WHZ  CAMERA_RELAY=$ENABLE_CAMERA_RELAY  DEPTH_RELAY=$ENABLE_DEPTH_RELAY  DEPTH_PIPELINE=$ENABLE_DEPTH_PIPELINE  CONE_AVOIDANCE=$ENABLE_CONE_AVOIDANCE  CONE_MODE_CONTROL=$ENABLE_CONE_MODE_CONTROL  VERIFY_DEPTH_DISABLE_LOCALIZATION=$VERIFY_DEPTH_DISABLE_LOCALIZATION  TASK_MANAGER=$ENABLE_TASK_MANAGER  AUTO_ADVANCE=$AUTO_ADVANCE  CONE_TO_WHZ_L6=$CONE_TO_WHZ_L6"

export CUVSLAM_MOUNT_MODE="${CUVSLAM_MOUNT_MODE:-robot}"
export CUVSLAM_PROFILE="${CUVSLAM_PROFILE:-custom}"
export CUVSLAM_CAMERA_PROFILE="${CUVSLAM_CAMERA_PROFILE:-640x360x30}"
export CUVSLAM_IMAGE_JITTER_THRESHOLD_MS="${CUVSLAM_IMAGE_JITTER_THRESHOLD_MS:-40.0}"
export ENABLE_SLAM_VISUALIZATION="${ENABLE_SLAM_VISUALIZATION:-false}"
export ENABLE_LANDMARKS_VIEW="${ENABLE_LANDMARKS_VIEW:-false}"
export ENABLE_OBSERVATIONS_VIEW="${ENABLE_OBSERVATIONS_VIEW:-false}"
export ENABLE_SLAM_DIAGNOSTICS="${ENABLE_SLAM_DIAGNOSTICS:-false}"
export ENABLE_LOOP_METRICS_RECORDER="${ENABLE_LOOP_METRICS_RECORDER:-false}"
export STARTUP_TOPIC_CHECKS="${STARTUP_TOPIC_CHECKS:-false}"
export STARTUP_RATE_PROBES="${STARTUP_RATE_PROBES:-false}"
FINAL_BRIDGE_CAMERA_WORLD_REBASE="${FINAL_BRIDGE_CAMERA_WORLD_REBASE:-base_start}"
if $ENABLE_DEPTH_PIPELINE || $ENABLE_CONE_AVOIDANCE; then
    export CUVSLAM_ENABLE_DEPTH="${CUVSLAM_ENABLE_DEPTH:-true}"
fi
export CONE_AVOIDANCE_ENABLE="$ENABLE_CONE_AVOIDANCE"
OFFICIAL_CONE_NAV2_PARAMS_FILE="$PROJECT_ROOT/configs/navigation/nav2_cone_obstacles.yaml"
EXPERIMENTAL_CONE_NAV2_PARAMS_FILE="$PROJECT_ROOT/configs/navigation/nav2_cone_obstacles_experimental.yaml"
CONE_NAV2_PARAMS_FILE="${CONE_NAV2_PARAMS_FILE:-$OFFICIAL_CONE_NAV2_PARAMS_FILE}"
CONE_NAV2_PROFILE="formal"
CONE_EXPECTED_INFLATION_RADIUS="0.60"
CONE_EXPECTED_COST_SCALING_FACTOR="2.0"
CONE_EXPECTED_PATH_ALIGN_SCALE="16"
CONE_EXPECTED_PATH_DIST_SCALE="16"
CONE_EXPECTED_SIM_TIME="2.5"
if $ENABLE_CONE_AVOIDANCE && [ ! -f "$CONE_NAV2_PARAMS_FILE" ]; then
    echo "ERROR: cone Nav2 parameter overlay not found: $CONE_NAV2_PARAMS_FILE"
    exit 2
fi
if $ENABLE_CONE_AVOIDANCE; then
    CONE_NAV2_PARAMS_REAL="$(readlink -f "$CONE_NAV2_PARAMS_FILE")" \
        || startup_no_go "cannot resolve cone Nav2 parameter overlay: $CONE_NAV2_PARAMS_FILE"
    EXPERIMENTAL_CONE_NAV2_PARAMS_REAL="$(readlink -f "$EXPERIMENTAL_CONE_NAV2_PARAMS_FILE")" \
        || startup_no_go "cannot resolve experimental cone overlay"
    if [ "$CONE_NAV2_PARAMS_REAL" = "$EXPERIMENTAL_CONE_NAV2_PARAMS_REAL" ]; then
        CONE_NAV2_PROFILE="experimental"
        CONE_EXPECTED_INFLATION_RADIUS="0.75"
        CONE_EXPECTED_COST_SCALING_FACTOR="1.5"
        CONE_EXPECTED_PATH_ALIGN_SCALE="12"
        CONE_EXPECTED_PATH_DIST_SCALE="12"
        CONE_EXPECTED_SIM_TIME="3.0"
    fi
    echo " Cone Nav2 params: $CONE_NAV2_PARAMS_FILE"
    echo " Cone Nav2 profile: $CONE_NAV2_PROFILE"
fi
CUVSLAM_DOCKER_DOMAIN_ID="${CUVSLAM_DOCKER_DOMAIN_ID:-0}"
if $ENABLE_CONE_AVOIDANCE; then
    CUVSLAM_DOCKER_DOMAIN_ID="${CONE_DOCKER_ROS_DOMAIN_ID:-42}"
    export IMAGE="${IMAGE:-isaac_ros_cuvslam_runtime:humble-rs-cone}"
fi

# Assemble the formal Foxy environment before cleanup, Docker, or D455 access.
# local_setup.bash keeps each overlay independent instead of following a
# workspace setup.bash chain that may reintroduce a legacy deployment prefix.
FOXY_SETUP="${FOXY_SETUP:-/opt/ros/foxy/setup.bash}"
CONE_PLUGIN_WS="${CONE_PLUGIN_WS:-$HOME/cone_l2_plugin_ws_2_2_1}"
CONE_PLUGIN_OVERLAY_SETUP="${CONE_PLUGIN_OVERLAY_SETUP:-$CONE_PLUGIN_WS/install/local_setup.bash}"
NAV2_BT_OVERLAY_SETUP="${NAV2_BT_OVERLAY_SETUP:-$HOME/nav2_foxy_overlay_ws/install/local_setup.bash}"
FORMAL_DEPLOY_SETUP="${FORMAL_DEPLOY_SETUP:-$PROJECT_ROOT/install/local_setup.bash}"
BASE_NAV2_PARAMS_FILE="$PROJECT_ROOT/configs/navigation/nav2_params.yaml"
NONPERSISTENT_VOXEL_LAYER_SOURCE="$CONE_PLUGIN_WS/src/nonpersistent_voxel_layer"
NONPERSISTENT_VOXEL_LAYER_COMMIT="0704666393ef1747562a93d934923fa45a3a8d4b"
CONE_PLUGIN_SOURCE="$PROJECT_ROOT/ros2_plugins/cone_inflated_voxel_layer"

: > "$STARTUP_SNAPSHOT" || startup_no_go "cannot create startup snapshot: $STARTUP_SNAPSHOT"
snapshot_value "STARTUP_TIMESTAMP" "$STARTUP_TIMESTAMP"
snapshot_value "CONE_AVOIDANCE" "$ENABLE_CONE_AVOIDANCE"
snapshot_value "CONE_MODE_CONTROL" "$ENABLE_CONE_MODE_CONTROL"
snapshot_value "CONE_TO_WHZ_L6" "$CONE_TO_WHZ_L6"
snapshot_value "VERIFY_DEPTH_DISABLE_LOCALIZATION" "$VERIFY_DEPTH_DISABLE_LOCALIZATION"
snapshot_value "FOXY_SETUP" "$FOXY_SETUP"
snapshot_value "CONE_PLUGIN_WS" "$CONE_PLUGIN_WS"
snapshot_value "CONE_PLUGIN_OVERLAY_SETUP" "$CONE_PLUGIN_OVERLAY_SETUP"
snapshot_value "NAV2_BT_OVERLAY_SETUP" "$NAV2_BT_OVERLAY_SETUP"
snapshot_value "FORMAL_DEPLOY_SETUP" "$FORMAL_DEPLOY_SETUP"
snapshot_value "BASE_NAV2_PARAMS_FILE" "$BASE_NAV2_PARAMS_FILE"
snapshot_value "CONE_NAV2_PARAMS_FILE" "$CONE_NAV2_PARAMS_FILE"
snapshot_value "CONE_NAV2_PROFILE" "$CONE_NAV2_PROFILE"
snapshot_value "TASK_MAX_NAV_RETRIES" "$TASK_MAX_NAV_RETRIES"
snapshot_value "TASK_MAX_INSPECTION_RETRIES" "$TASK_MAX_INSPECTION_RETRIES"
snapshot_value "TASK_FINISH_AFTER_INSPECTION" "$TASK_FINISH_AFTER_INSPECTION"
snapshot_value "TASK_ALLOW_PLACEHOLDER_MANIPULATION" "$TASK_ALLOW_PLACEHOLDER_MANIPULATION"
snapshot_value "TASK_PASS_OBSTACLE_TIMEOUT_SEC" "$TASK_PASS_OBSTACLE_TIMEOUT_SEC"
snapshot_value "TASK_PASS_OBSTACLE_WAYPOINT_TIMEOUT_SEC" "$TASK_PASS_OBSTACLE_WAYPOINT_TIMEOUT_SEC"
snapshot_value "TASK_INSPECTION_TIMEOUT_SEC" "$TASK_INSPECTION_TIMEOUT_SEC"
snapshot_value "TASK_MISSION_START_ARMED" "$TASK_MISSION_START_ARMED"
snapshot_value "TASK_WAYPOINT_FILE" "$TASK_WAYPOINT_FILE"
snapshot_value "TASK_WAYPOINT_ROUTE" "$TASK_WAYPOINT_ROUTE"
snapshot_value "TASK_EXPECTED_MAP_ID" "$TASK_EXPECTED_MAP_ID"

[ -f "$FOXY_SETUP" ] || startup_no_go "Foxy setup is missing: $FOXY_SETUP"
[ -f "$BASE_NAV2_PARAMS_FILE" ] || startup_no_go "base Nav2 params are missing: $BASE_NAV2_PARAMS_FILE"
# shellcheck disable=SC1090
source "$FOXY_SETUP" || startup_no_go "failed to source Foxy setup: $FOXY_SETUP"

if $ENABLE_CONE_AVOIDANCE; then
    [ -f "$CONE_PLUGIN_OVERLAY_SETUP" ] \
        || startup_no_go "pinned cone plugin overlay is missing: $CONE_PLUGIN_OVERLAY_SETUP"
    [ -f "$CONE_PLUGIN_SOURCE/package.xml" ] \
        || startup_no_go "ConeInflatedVoxelLayer source package is missing: $CONE_PLUGIN_SOURCE"
    [ -f "$NONPERSISTENT_VOXEL_LAYER_SOURCE/include/nonpersistent_voxel_layer/nonpersistent_voxel_layer.hpp" ] \
        || startup_no_go "pinned NonPersistentVoxelLayer source header is missing"
    ACTUAL_NONPERSISTENT_COMMIT="$(git -C "$NONPERSISTENT_VOXEL_LAYER_SOURCE" rev-parse HEAD 2>/dev/null)" \
        || startup_no_go "cannot read pinned NonPersistentVoxelLayer source commit"
    [ "$ACTUAL_NONPERSISTENT_COMMIT" = "$NONPERSISTENT_VOXEL_LAYER_COMMIT" ] \
        || startup_no_go "NonPersistentVoxelLayer source commit is $ACTUAL_NONPERSISTENT_COMMIT; expected $NONPERSISTENT_VOXEL_LAYER_COMMIT"
    snapshot_value "nonpersistent_voxel_layer_source_commit" "$ACTUAL_NONPERSISTENT_COMMIT"
    # shellcheck disable=SC1090
    source "$CONE_PLUGIN_OVERLAY_SETUP" \
        || startup_no_go "failed to source cone plugin overlay: $CONE_PLUGIN_OVERLAY_SETUP"
    (
        cd "$CONE_PLUGIN_WS" &&
        colcon build \
            --symlink-install \
            --base-paths "$CONE_PLUGIN_WS/src" "$PROJECT_ROOT/ros2_plugins" \
            --packages-select cone_inflated_voxel_layer \
            --cmake-args \
                -DCMAKE_BUILD_TYPE=RelWithDebInfo \
                -DNONPERSISTENT_VOXEL_LAYER_SOURCE_INCLUDE="$NONPERSISTENT_VOXEL_LAYER_SOURCE/include"
    ) || startup_no_go "ConeInflatedVoxelLayer overlay build failed"
    # shellcheck disable=SC1090
    source "$CONE_PLUGIN_OVERLAY_SETUP" \
        || startup_no_go "failed to re-source rebuilt cone plugin overlay"
fi

[ -f "$NAV2_BT_OVERLAY_SETUP" ] \
    || startup_no_go "Nav2 BT overlay is missing: $NAV2_BT_OVERLAY_SETUP"
# shellcheck disable=SC1090
source "$NAV2_BT_OVERLAY_SETUP" \
    || startup_no_go "failed to source Nav2 BT overlay: $NAV2_BT_OVERLAY_SETUP"

[ -f "$FORMAL_DEPLOY_SETUP" ] \
    || startup_no_go "formal deploy install is missing: $FORMAL_DEPLOY_SETUP"
# shellcheck disable=SC1090
source "$FORMAL_DEPLOY_SETUP" \
    || startup_no_go "failed to source formal deploy install: $FORMAL_DEPLOY_SETUP"

NAV2_BT_PREFIX="$(ros2 pkg prefix nav2_bt_navigator 2>/dev/null)" \
    || startup_no_go "nav2_bt_navigator package is not resolvable"
FORMAL_PACKAGE_PREFIX="$(ros2 pkg prefix quadruped_robot_competition 2>/dev/null)" \
    || startup_no_go "quadruped_robot_competition package is not resolvable"
NAV2_BT_INSTALL_ROOT="$(cd "$(dirname "$NAV2_BT_OVERLAY_SETUP")" && pwd -P)"
FORMAL_INSTALL_ROOT="$(cd "$(dirname "$FORMAL_DEPLOY_SETUP")" && pwd -P)"
case "$NAV2_BT_PREFIX" in
    "$NAV2_BT_INSTALL_ROOT"/*) ;;
    *) startup_no_go "nav2_bt_navigator resolved outside the pinned BT overlay: $NAV2_BT_PREFIX" ;;
esac
case "$FORMAL_PACKAGE_PREFIX" in
    "$FORMAL_INSTALL_ROOT"/*) ;;
    *) startup_no_go "competition package resolved outside formal deploy install: $FORMAL_PACKAGE_PREFIX" ;;
esac
snapshot_value "nav2_bt_navigator_prefix" "$NAV2_BT_PREFIX"
snapshot_value "quadruped_robot_competition_prefix" "$FORMAL_PACKAGE_PREFIX"
FORMAL_CONE_BEHAVIOR_TREE="$FORMAL_PACKAGE_PREFIX/share/quadruped_robot_competition/configs/navigation/navigate_cone_w_replanning_and_recovery.xml"
if $ENABLE_CONE_AVOIDANCE; then
    [ -f "$FORMAL_CONE_BEHAVIOR_TREE" ] \
        || startup_no_go "installed cone behavior tree is missing: $FORMAL_CONE_BEHAVIOR_TREE"
    grep -Fq 'controller_id="FollowPathCone"' "$FORMAL_CONE_BEHAVIOR_TREE" \
        || startup_no_go "installed cone behavior tree does not select FollowPathCone"
fi
snapshot_value "cone_behavior_tree" "$FORMAL_CONE_BEHAVIOR_TREE"

PLUGIN_PREFIX="disabled"
PLUGIN_XML="disabled"
PLUGIN_LIBRARY="disabled"
if $ENABLE_CONE_AVOIDANCE; then
    PLUGIN_PREFIX="$(ros2 pkg prefix cone_inflated_voxel_layer 2>/dev/null)" \
        || startup_no_go "cone_inflated_voxel_layer package is not resolvable"
    CONE_PLUGIN_INSTALL_ROOT="$(cd "$(dirname "$CONE_PLUGIN_OVERLAY_SETUP")" && pwd -P)"
    case "$PLUGIN_PREFIX" in
        "$CONE_PLUGIN_INSTALL_ROOT"/*) ;;
        *) startup_no_go "cone_inflated_voxel_layer resolved outside the pinned overlay: $PLUGIN_PREFIX" ;;
    esac
    PLUGIN_SHARE="$PLUGIN_PREFIX/share/cone_inflated_voxel_layer"
    [ -d "$PLUGIN_SHARE" ] \
        || startup_no_go "cone_inflated_voxel_layer share directory is missing: $PLUGIN_SHARE"
    PLUGIN_XML="$(grep -R -l --include='*.xml' 'cone_inflated_voxel_layer/ConeInflatedVoxelLayer' "$PLUGIN_SHARE" 2>/dev/null | head -1)"
    [ -n "$PLUGIN_XML" ] && [ -f "$PLUGIN_XML" ] \
        || startup_no_go "ConeInflatedVoxelLayer plugin XML is missing under $PLUGIN_SHARE"
    PLUGIN_LIBRARY="$(find "$PLUGIN_PREFIX" -name 'libcone_inflated_voxel_layer_core.so' -print -quit 2>/dev/null)"
    [ -n "$PLUGIN_LIBRARY" ] && [ -e "$PLUGIN_LIBRARY" ] \
        || startup_no_go "ConeInflatedVoxelLayer shared library is missing under $PLUGIN_PREFIX"
fi
snapshot_value "cone_inflated_voxel_layer_prefix" "$PLUGIN_PREFIX"
snapshot_value "plugin_xml" "$PLUGIN_XML"
snapshot_value "plugin_library" "$PLUGIN_LIBRARY"
if $ENABLE_CONE_AVOIDANCE; then
    PLUGIN_LIBRARY_REAL="$(readlink -f "$PLUGIN_LIBRARY")" \
        || startup_no_go "cannot resolve the pinned plugin library identity"
    [ -n "$PLUGIN_LIBRARY_REAL" ] && [ -f "$PLUGIN_LIBRARY_REAL" ] \
        || startup_no_go "pinned plugin library target is missing: $PLUGIN_LIBRARY_REAL"
    snapshot_value "plugin_library_real" "$PLUGIN_LIBRARY_REAL"
fi
snapshot_value "PYTHONPATH" "${PYTHONPATH:-}"

if $CONE_TO_WHZ_L6; then
    [ -n "$TASK_WAYPOINT_FILE" ] \
        || startup_no_go "Phase 113 requires a calibrated waypoint file"
    [ -n "$TASK_EXPECTED_MAP_ID" ] \
        || startup_no_go "Phase 113 requires TASK_EXPECTED_MAP_ID"
    TASK_WAYPOINT_FILE_REAL="$(readlink -f "$TASK_WAYPOINT_FILE")" \
        || startup_no_go "cannot resolve Phase 113 waypoint file: $TASK_WAYPOINT_FILE"
    [ -f "$TASK_WAYPOINT_FILE_REAL" ] \
        || startup_no_go "Phase 113 waypoint file is missing: $TASK_WAYPOINT_FILE_REAL"
    TASK_WAYPOINT_FILE="$TASK_WAYPOINT_FILE_REAL"
    WAYPOINT_GATE_JSON="$(python3 - "$TASK_WAYPOINT_FILE" "$TASK_WAYPOINT_ROUTE" "$TASK_EXPECTED_MAP_ID" <<'PY'
import json
import sys

from nodes.navigation.mission_route import MISSION_NAV_WAYPOINTS
from nodes.navigation.navigation_client import load_calibrated_waypoints
from nodes.navigation.waypoint_calibration import (
    load_waypoint_document,
    resolve_waypoint_route,
)

path, route, expected_map_id = sys.argv[1:4]
waypoints = load_calibrated_waypoints(path, route, expected_map_id)
route_goals = resolve_waypoint_route(load_waypoint_document(path), route)
missing = sorted(set(MISSION_NAV_WAYPOINTS) - set(waypoints))
if missing:
    raise SystemExit("route missing required waypoints: %s" % ", ".join(missing))
print(json.dumps({
    "path": path,
    "route": route,
    "map_id": next(iter(waypoints.values()))["map_id"],
    "route_goal_count": len(route_goals),
    "unique_waypoint_count": len(waypoints),
}, sort_keys=True))
PY
    )" || startup_no_go "Phase 113 waypoint calibration gate failed"
    snapshot_value "phase113_waypoint_gate" "$WAYPOINT_GATE_JSON"
    echo " Phase 113 waypoint gate passed: $WAYPOINT_GATE_JSON"
fi

if $ENABLE_CONE_AVOIDANCE; then
    python3 - <<'PY' \
        || startup_no_go "formal cone Python entry points are not loadable"
import pkg_resources

for name in ("cmd_vel_arbiter", "cone_scan_udp_bridge", "cone_scan_safety_gate"):
    pkg_resources.load_entry_point(
        "quadruped-robot-competition", "console_scripts", name
    )
PY
fi

echo " Formal environment preflight passed"
echo "  Nav2 BT: $NAV2_BT_PREFIX"
echo "  Competition: $FORMAL_PACKAGE_PREFIX"
if $ENABLE_CONE_AVOIDANCE; then
    echo "  Cone plugin: $PLUGIN_PREFIX"
fi

# ═══════════════════════════════════════════
# [0] 清理旧进程
# ═══════════════════════════════════════════
STARTUP_RUNTIME_TOUCHED=true
echo ''
echo '[0/6] 清理旧进程...'
bash scripts/stop_all.sh 2>&1 | tail -3
sleep 1
if $ENABLE_CONE_MODE_CONTROL; then
    DEPTH_SHARED_DIR="${DEPTH_SHARED_DIR:-$HOME/workspaces/isaac_ros-dev/camera_frames}"
    DEPTH_CONTROL_REQUEST_FILE="$DEPTH_SHARED_DIR/depth_control_request.json"
    DEPTH_CONTROLLER_STATUS_FILE="$DEPTH_SHARED_DIR/depth_controller_status.json"
    rm -f -- "$DEPTH_CONTROL_REQUEST_FILE" "$DEPTH_CONTROLLER_STATUS_FILE" \
        || startup_no_go "cannot clear stale depth mode state under $DEPTH_SHARED_DIR"
    snapshot_value "depth_mode_state_reset_dir" "$DEPTH_SHARED_DIR"
    echo "  Cleared stale depth mode request/status state"
fi

# ═══════════════════════════════════════════
# [1] Docker cuVSLAM
# ═══════════════════════════════════════════
echo ''
echo '[1/6] Docker cuVSLAM...'
CN=$(docker ps --format '{{.Names}}' 2>/dev/null | grep cuvslam || true)
if [ -z "$CN" ]; then
    echo "  启动 Docker (需要 ~90s)..."
    PROJECT_DIR="$PROJECT_ROOT" \
    ROS_DOMAIN_ID="$CUVSLAM_DOCKER_DOMAIN_ID" \
    CONE_AVOIDANCE_ENABLE="$CONE_AVOIDANCE_ENABLE" \
    CUVSLAM_MOUNT_MODE="$CUVSLAM_MOUNT_MODE" CUVSLAM_PROFILE="$CUVSLAM_PROFILE" \
      CUVSLAM_PUBLISH_ODOM_TO_BASE_TF=false CUVSLAM_PUBLISH_MAP_TO_ODOM_TF=false \
      bash scripts/start_cuvslam_rviz_gui.sh --no-rviz > /tmp/cuvslam_start.log 2>&1 &
    RUNTIME_CUVSLAM_WRAPPER_PID=$!
    # 轮询等待 Docker 容器出现 + cuVSLAM 节点起来
    for i in $(seq 1 60); do
        sleep 3
        CN=$(docker ps --format '{{.Names}}' 2>/dev/null | grep cuvslam || true)
        if [ -n "$CN" ]; then break; fi
        echo -n "."
    done
    if [ -z "$CN" ]; then
        startup_no_go "Docker startup timed out"
    fi
    RUNTIME_STARTED_CUVSLAM=true
    RUNTIME_CUVSLAM_CONTAINER="$(docker inspect --format '{{.Id}}' "$CN" 2>/dev/null)" \
        || startup_no_go "cannot record the new cuVSLAM container identity"
    snapshot_value "runtime_cuvslam_container" "$RUNTIME_CUVSLAM_CONTAINER"
    echo " Docker 容器已启动，等待 cuVSLAM 初始化..."
    # 等待视觉 SLAM 开始追踪
    for i in $(seq 1 30); do
        sleep 2
        if docker exec $CN bash -c 'source /opt/ros/humble/setup.bash && ros2 topic echo /visual_slam/tracking/odometry --once 2>/dev/null' | grep -q stamp; then
            echo " cuVSLAM 追踪中"
            break
        fi
        echo -n "."
    done
else
    echo "  Docker 已在运行: $CN"
fi
if $ENABLE_CONE_AVOIDANCE; then
    CONTAINER_ROS_DOMAIN_ID=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$CN" 2>/dev/null | sed -n 's/^ROS_DOMAIN_ID=//p' | tail -1)
    if [ -z "$CONTAINER_ROS_DOMAIN_ID" ] || [ "$CONTAINER_ROS_DOMAIN_ID" = "0" ]; then
        startup_no_go "cone avoidance requires the Humble container DDS domain to differ from Host Foxy domain 0"
    fi
    CONE_PIPELINE_READY=false
    for _ in $(seq 1 20); do
        if CONE_UDP_PROBE_JSON="$(python3 scripts/cone_scan_udp_startup_probe.py \
          --host 127.0.0.1 --port 19002 --timeout-sec 2 2>&1)" \
          && docker exec "$CN" pgrep -f '[c]one_scan_udp_exporter.py' >/dev/null; then
            CONE_PIPELINE_READY=true
            snapshot_value "cone_udp_startup_probe" "$CONE_UDP_PROBE_JSON"
            break
        fi
        sleep 1
    done
    if ! $CONE_PIPELINE_READY; then
        startup_no_go "cuVSLAM cone UDP pipeline is not producing a fresh healthy packet: ${CONE_UDP_PROBE_JSON:-no probe result}"
    fi
    echo "  Cone scan: Humble DDS domain $CONTAINER_ROS_DOMAIN_ID -> UDP 127.0.0.1:19002 -> Foxy DDS domain 0"
fi
# 杀掉高CPU的 loop_metrics
docker exec $CN pkill -f loop_metrics_recorder 2>/dev/null && echo "  loop_metrics killed" || true

# ═══════════════════════════════════════════
# [2] 中继 (Camera + Depth)
# ═══════════════════════════════════════════
echo ''
echo '[2/6] 中继...'
docker exec $CN pkill -f camera_relay 2>/dev/null || true
docker exec $CN pkill -f depth_relay  2>/dev/null || true
sleep 1
docker exec "$CN" rm -f /tmp/cam.log /tmp/dep.log 2>/dev/null || true

if $ENABLE_CAMERA_RELAY; then
    docker cp scripts/camera_relay_docker.py $CN:/tmp/ 2>/dev/null || true
    docker exec -d $CN bash -c \
      "source /opt/ros/humble/setup.bash && \
       source /workspaces/isaac_ros-dev/install/setup.bash && \
       mkdir -p /workspaces/isaac_ros-dev/camera_frames && \
       python3 /tmp/camera_relay_docker.py > /tmp/cam.log 2>&1"
    for i in $(seq 1 10); do
        sleep 1
        FRAMES=$(docker exec $CN bash -c 'cat /tmp/cam.log 2>/dev/null' | grep -c 'Saved' || true)
        if [ "$FRAMES" -gt 0 ]; then break; fi
    done
    echo "  Camera: $(docker exec $CN tail -1 /tmp/cam.log 2>/dev/null || echo 'OK')"
else
    echo "  Camera relay: skipped"
fi

if $ENABLE_DEPTH_RELAY; then
    docker cp scripts/depth_relay_docker.py $CN:/tmp/ 2>/dev/null || true
    docker cp src/nodes/navigation/depth_contract.py $CN:/tmp/depth_contract.py 2>/dev/null || true
    DEPTH_RELAY_EXTRA_ARGS=""
    DEPTH_CONTROL_STRATEGY_VALUE="${DEPTH_CONTROL_STRATEGY:-consumer_only}"
    if $ENABLE_CONE_MODE_CONTROL; then
        DEPTH_CONTROL_STRATEGY_VALUE="parameter"
        DEPTH_RELAY_EXTRA_ARGS="--no-write-frames --manage-cone-pipeline-parameters"
        if $VERIFY_DEPTH_DISABLE_LOCALIZATION; then
            DEPTH_RELAY_EXTRA_ARGS="$DEPTH_RELAY_EXTRA_ARGS --verify-localization-after-disable"
        fi
    fi
    docker exec -d $CN bash -c \
      "source /opt/ros/humble/setup.bash && \
       source /workspaces/isaac_ros-dev/install/setup.bash && \
       python3 /tmp/depth_relay_docker.py \
         --control-strategy '$DEPTH_CONTROL_STRATEGY_VALUE' \
         $DEPTH_RELAY_EXTRA_ARGS \
         > /tmp/dep.log 2>&1"
    for i in $(seq 1 10); do
        sleep 1
        READY=$(docker exec $CN bash -c 'cat /tmp/dep.log 2>/dev/null' | grep -c 'depth relay ready' || true)
        if [ "$READY" -gt 0 ]; then break; fi
    done
    echo "  Depth:  $(docker exec $CN tail -1 /tmp/dep.log 2>/dev/null || echo 'OK')"
else
    echo "  Depth relay: skipped"
fi

# ═══════════════════════════════════════════
# [3] UDP 桥接 (odom)
# ═══════════════════════════════════════════
echo ''
echo '[3/6] UDP 桥接...'
# 清理旧桥接
pkill -9 -f final_bridge 2>/dev/null || true
docker exec $CN pkill -f '[c]uvslam_odometry_udp_exporter.py' 2>/dev/null || true
sleep 1

export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0
if [ -f "$PROJECT_ROOT/configs/ros/fastrtps_no_shm.xml" ]; then
    export FASTRTPS_DEFAULT_PROFILES_FILE="$PROJECT_ROOT/configs/ros/fastrtps_no_shm.xml"
fi

nohup python3 scripts/final_bridge.py \
  --camera-world-rebase "$FINAL_BRIDGE_CAMERA_WORLD_REBASE" \
  --planarize-output > /tmp/fb.log 2>&1 &
BRIDGE_PID=$!
# 等待第一个 odom 消息
for i in $(seq 1 30); do
    sleep 1
    if grep -q 'bridged' /tmp/fb.log 2>/dev/null; then
        echo "  Bridge 就绪 (PID=$BRIDGE_PID)"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "  ⚠ Bridge 等待超时 (检查 cuVSLAM)"
    fi
done

# ═══════════════════════════════════════════
# [4] Dog init + transfer driver
# ═══════════════════════════════════════════
if $ENABLE_DOG; then
    echo ''
    echo '[4/6] 狗初始化...'
    # 检查网络
    if ! ping -c 1 -W 1 192.168.1.120 > /dev/null 2>&1; then
        echo "  ⚠ 狗网络不通 (192.168.1.120) — 继续但狗不会动"
    else
        if $ENABLE_CMD_VEL_BRIDGE; then
            if $PREPARE_LITE3_MOTION; then
                echo "  准备 Lite3 motion mode：heartbeat + auto/nav + motion；不发送起立/趴下 toggle"
                python3 scripts/prepare_lite3_motion_mode.py > /tmp/prepare_lite3_motion_mode.log 2>&1
                PREPARE_RC=$?
                if [ $PREPARE_RC -ne 0 ]; then
                    tail -40 /tmp/prepare_lite3_motion_mode.log 2>/dev/null || true
                    startup_no_go "Lite3 motion mode preparation failed (rc=$PREPARE_RC), log: /tmp/prepare_lite3_motion_mode.log"
                fi
                tail -8 /tmp/prepare_lite3_motion_mode.log 2>/dev/null || true
            fi
            if $ENABLE_CMD_VEL_BRIDGE_INIT; then
                echo "  使用备用 cmd_vel_bridge，并显式初始化狗 (auto + motion mode)"
            else
                echo "  使用备用 cmd_vel_bridge；不自动初始化狗，避免改变当前站立/趴下状态"
            fi
        elif [ -f Lite3_ROS-ros2-foxy/install/setup.bash ]; then
            # Dedicated driver node: subscribe /cmd_vel, then talk to Lite3.
            # Navigator publishes /cmd_vel only by default and no longer bypasses this node.
            source Lite3_ROS-ros2-foxy/install/setup.bash
            nohup ros2 launch transfer transfer_launch.py > /tmp/transfer.log 2>&1 &
            TRANSFER_PID=$!
            sleep 2
            if ros2 node list 2>/dev/null | grep -q motion_sender; then
                echo "  transfer driver ready: /cmd_vel -> Lite3 (PID=$TRANSFER_PID)"
            else
                echo "  WARN: transfer driver not visible yet, log: /tmp/transfer.log"
            fi
        else
            echo "  WARN: Lite3 transfer workspace is not built; /cmd_vel will not reach the dog unless --cmd-vel-bridge is used"
        fi
    fi
fi

# ═══════════════════════════════════════════
# [5] 比赛系统
# ═══════════════════════════════════════════
echo ''
echo '[5/6] 启动比赛...'

YF=false; WF=false
$ENABLE_YOLO && YF=true
$ENABLE_WHZ  && WF=true
COMPETITION_LAUNCH_ARGS=(
  "enable_task_manager:=$ENABLE_TASK_MANAGER"
  "enable_navigation:=true"
  "enable_cmd_vel_bridge:=$ENABLE_CMD_VEL_BRIDGE"
  "cmd_vel_bridge_init_dog:=$ENABLE_CMD_VEL_BRIDGE_INIT"
  "enable_depth_publisher:=false"
  "enable_depth_pipeline:=$ENABLE_DEPTH_PIPELINE"
  "enable_cone_avoidance:=$ENABLE_CONE_AVOIDANCE"
  "enable_cone_mode_control:=$ENABLE_CONE_MODE_CONTROL"
  "verify_depth_disable_localization:=$VERIFY_DEPTH_DISABLE_LOCALIZATION"
  "cone_params_file:=$CONE_NAV2_PARAMS_FILE"
  "enable_yolo:=$YF"
  "enable_whz:=$WF"
  "max_nav_retries:=$TASK_MAX_NAV_RETRIES"
  "max_inspection_retries:=$TASK_MAX_INSPECTION_RETRIES"
  "finish_after_inspection:=$TASK_FINISH_AFTER_INSPECTION"
  "allow_placeholder_manipulation:=$TASK_ALLOW_PLACEHOLDER_MANIPULATION"
  "pass_obstacle_timeout_sec:=$TASK_PASS_OBSTACLE_TIMEOUT_SEC"
  "pass_obstacle_waypoint_timeout_sec:=$TASK_PASS_OBSTACLE_WAYPOINT_TIMEOUT_SEC"
  "inspection_timeout_sec:=$TASK_INSPECTION_TIMEOUT_SEC"
  "mission_start_armed:=$TASK_MISSION_START_ARMED"
  "waypoint_route:=$TASK_WAYPOINT_ROUTE"
  "auto_advance:=$AUTO_ADVANCE"
)
[ -n "$TASK_WAYPOINT_FILE" ] \
  && COMPETITION_LAUNCH_ARGS+=("waypoint_file:=$TASK_WAYPOINT_FILE")
[ -n "$TASK_EXPECTED_MAP_ID" ] \
  && COMPETITION_LAUNCH_ARGS+=("expected_map_id:=$TASK_EXPECTED_MAP_ID")
ros2 launch quadruped_robot_competition competition.launch.py \
  "${COMPETITION_LAUNCH_ARGS[@]}" > /tmp/competition.log 2>&1 &
COMP_PID=$!
echo "  Launch PID=$COMP_PID YOLO=$YF WHZ=$WF TASK_MANAGER=$ENABLE_TASK_MANAGER AUTO_ADVANCE=$AUTO_ADVANCE"
if $ENABLE_TASK_MANAGER; then
    # 等待 task_manager 节点出现
    for i in $(seq 1 15); do
        sleep 1
        if ros2 node list 2>/dev/null | grep -q task_manager; then
            echo "  task_manager 就绪"
            break
        fi
    done
fi

# ═══════════════════════════════════════════
# [6] 验证
# ═══════════════════════════════════════════
echo ''
echo '[6/6] 验证...'
sleep 3
echo "  === 节点 ==="
ros2 node list 2>/dev/null | grep -v '/camera\|/visual\|/launch\|/transform\|/docker' || echo "  (无)"
echo "  === Odom ==="
python3 -c "
import json
try:
    d = json.load(open('/tmp/odom_latest.json'))
    print(f'  x={d[\"x\"]:.2f} y={d[\"y\"]:.2f}')
except: print('  odom 文件尚未就绪')
" 2>/dev/null

echo "  === 狗状态 ==="
if $ENABLE_DOG; then
    tail -1 /tmp/lite3_init.log 2>/dev/null || echo "  (无)"
    ping -c 1 -W 1 192.168.1.120 > /dev/null 2>&1 && echo "  狗网络: ✅" || echo "  狗网络: ❌"
fi
echo "  === cmd_vel arbitration ==="
ros2 node list 2>/dev/null | grep 'cmd_vel_arbiter' || echo "  ERROR: cmd_vel_arbiter 节点未出现"
ros2 topic info /cmd_vel_nav2 2>/dev/null || echo "  /cmd_vel_nav2 topic info 不可用"
ros2 topic info /cmd_vel_precision 2>/dev/null || echo "  /cmd_vel_precision topic info 不可用"
if $ENABLE_CMD_VEL_BRIDGE; then
    echo "  === cmd_vel bridge ==="
    ros2 node list 2>/dev/null | grep 'cmd_vel_bridge' || echo "  cmd_vel_bridge 节点未出现"
    ros2 topic info /cmd_vel --verbose 2>/dev/null | sed -n '1,35p' || echo "  /cmd_vel topic info 不可用"
    grep -E 'CmdVelBridge 就绪|CmdVelBridge ROS env|\[diag\]' /tmp/competition.log 2>/dev/null | tail -8 || true
fi

echo "  === CPU TOP5 ==="
ps -eo pcpu,pid,comm --sort=-pcpu 2>/dev/null | head -6 | tail -5

# Success is a runtime acceptance result, not a process-start banner.
STARTUP_LIFECYCLE_TIMEOUT_SEC="${STARTUP_LIFECYCLE_TIMEOUT_SEC:-90}"
STARTUP_CLI_TIMEOUT_SEC="${STARTUP_CLI_TIMEOUT_SEC:-8}"
STARTUP_LIFECYCLE_SNAPSHOT_RETRIES="${STARTUP_LIFECYCLE_SNAPSHOT_RETRIES:-3}"
STARTUP_HEALTH_WINDOW_SEC="${STARTUP_HEALTH_WINDOW_SEC:-10}"
STARTUP_MIN_SCAN_RATE_HZ="${STARTUP_MIN_SCAN_RATE_HZ:-8}"
EXPECTED_CMD_VEL_SUBSCRIBERS="${EXPECTED_CMD_VEL_SUBSCRIBERS:-0}"
if $ENABLE_DOG || $ENABLE_CMD_VEL_BRIDGE; then
    EXPECTED_CMD_VEL_SUBSCRIBERS="${EXPECTED_CMD_VEL_SUBSCRIBERS_MOTION:-1}"
fi

case "$STARTUP_LIFECYCLE_TIMEOUT_SEC:$STARTUP_CLI_TIMEOUT_SEC:$STARTUP_LIFECYCLE_SNAPSHOT_RETRIES:$EXPECTED_CMD_VEL_SUBSCRIBERS" in
    *[!0-9:]*|'') startup_no_go "startup timeout and subscriber settings must be non-negative integers" ;;
esac
[ "$STARTUP_LIFECYCLE_SNAPSHOT_RETRIES" -ge 1 ] \
    || startup_no_go "startup lifecycle snapshot retries must be at least 1"

LIFECYCLE_NODES=(map_server planner_server controller_server recoveries_server bt_navigator)
ALL_LIFECYCLE_ACTIVE=false
LIFECYCLE_DEADLINE=$((SECONDS + STARTUP_LIFECYCLE_TIMEOUT_SEC))
while [ "$SECONDS" -le "$LIFECYCLE_DEADLINE" ]; do
    ALL_LIFECYCLE_ACTIVE=true
    for node in "${LIFECYCLE_NODES[@]}"; do
        state="$(timeout "$STARTUP_CLI_TIMEOUT_SEC" ros2 lifecycle get "/$node" 2>/dev/null || true)"
        if ! printf '%s\n' "$state" | grep -Fq 'active [3]'; then
            ALL_LIFECYCLE_ACTIVE=false
            break
        fi
    done
    $ALL_LIFECYCLE_ACTIVE && break
    kill -0 "$COMP_PID" 2>/dev/null \
        || startup_no_go "competition launch exited before lifecycle activation"
    sleep 2
done
$ALL_LIFECYCLE_ACTIVE \
    || startup_no_go "Nav2 lifecycle nodes did not all become active within ${STARTUP_LIFECYCLE_TIMEOUT_SEC}s"

for node in "${LIFECYCLE_NODES[@]}"; do
    state=""
    for attempt in $(seq 1 "$STARTUP_LIFECYCLE_SNAPSHOT_RETRIES"); do
        state="$(timeout "$STARTUP_CLI_TIMEOUT_SEC" ros2 lifecycle get "/$node" 2>&1 || true)"
        printf '%s\n' "$state" | grep -Fq 'active [3]' && break
        kill -0 "$COMP_PID" 2>/dev/null \
            || startup_no_go "competition launch exited while reading lifecycle state for /$node"
        [ "$attempt" -lt "$STARTUP_LIFECYCLE_SNAPSHOT_RETRIES" ] && sleep 1
    done
    printf '%s\n' "$state" | grep -Fq 'active [3]' \
        || startup_no_go "cannot confirm active lifecycle state for /$node after ${STARTUP_LIFECYCLE_SNAPSHOT_RETRIES} attempts"
    printf 'lifecycle.%s=%s\n' "$node" "$state" >> "$STARTUP_SNAPSHOT"
done

CMD_VEL_INFO="$(timeout "$STARTUP_CLI_TIMEOUT_SEC" ros2 topic info /cmd_vel --verbose 2>&1)" \
    || startup_no_go "cannot inspect /cmd_vel endpoints"
CMD_VEL_SUBSCRIBERS="$(printf '%s\n' "$CMD_VEL_INFO" | sed -n 's/^Subscription count: //p' | head -1)"
[ "$CMD_VEL_SUBSCRIBERS" = "$EXPECTED_CMD_VEL_SUBSCRIBERS" ] \
    || startup_no_go "/cmd_vel subscriber count is ${CMD_VEL_SUBSCRIBERS:-unknown}; expected $EXPECTED_CMD_VEL_SUBSCRIBERS"
snapshot_value "cmd_vel_expected_subscribers" "$EXPECTED_CMD_VEL_SUBSCRIBERS"
snapshot_value "cmd_vel_actual_subscribers" "$CMD_VEL_SUBSCRIBERS"

parameter_value() {
    local node="$1"
    local parameter="$2"
    local output
    output="$(timeout "$STARTUP_CLI_TIMEOUT_SEC" ros2 param get "$node" "$parameter" 2>&1)" \
        || return 1
    snapshot_value "live_parameter.$node.$parameter" "$output"
    printf '%s\n' "${output##*: }"
}

require_numeric_parameter() {
    local node="$1"
    local parameter="$2"
    local expected="$3"
    local actual
    actual="$(parameter_value "$node" "$parameter")" \
        || startup_no_go "cannot read live parameter $node:$parameter"
    if ! python3 - "$actual" "$expected" <<'PY'
import math
import sys
try:
    actual = float(sys.argv[1])
    expected = float(sys.argv[2])
except ValueError:
    raise SystemExit(1)
raise SystemExit(0 if math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-9) else 1)
PY
    then
        startup_no_go "live parameter $node:$parameter is $actual; expected $expected"
    fi
}

require_exact_parameter() {
    local node="$1"
    local parameter="$2"
    local expected="$3"
    local actual
    actual="$(parameter_value "$node" "$parameter")" \
        || startup_no_go "cannot read live parameter $node:$parameter"
    case "$expected" in
        true|false)
            [ "${actual,,}" = "$expected" ] \
                || startup_no_go "live parameter $node:$parameter is $actual; expected $expected"
            ;;
        *)
            [ "$actual" = "$expected" ] \
                || startup_no_go "live parameter $node:$parameter is $actual; expected $expected"
            ;;
    esac
}

if $ENABLE_CONE_AVOIDANCE; then
    SCAN_INFO="$(timeout "$STARTUP_CLI_TIMEOUT_SEC" ros2 topic info /cone_obstacle/scan --verbose 2>&1)" \
        || startup_no_go "cannot inspect cone scan endpoints"
    HEALTH_INFO="$(timeout "$STARTUP_CLI_TIMEOUT_SEC" ros2 topic info /cone_obstacle/health --verbose 2>&1)" \
        || startup_no_go "cannot inspect cone health endpoints"
    printf '\n[cone_scan_topic_info]\n%s\n' "$SCAN_INFO" >> "$STARTUP_SNAPSHOT"
    printf '\n[cone_health_topic_info]\n%s\n' "$HEALTH_INFO" >> "$STARTUP_SNAPSHOT"
    SCAN_PUBLISHERS="$(printf '%s\n' "$SCAN_INFO" | sed -n 's/^Publisher count: //p' | head -1)"
    SCAN_SUBSCRIBERS="$(printf '%s\n' "$SCAN_INFO" | sed -n 's/^Subscription count: //p' | head -1)"
    SCAN_BEST_EFFORT_ENDPOINTS="$(printf '%s\n' "$SCAN_INFO" | grep -Ec 'Reliability: (RMW_QOS_POLICY_RELIABILITY_)?BEST_EFFORT' || true)"
    HEALTH_PUBLISHERS="$(printf '%s\n' "$HEALTH_INFO" | sed -n 's/^Publisher count: //p' | head -1)"
    HEALTH_SUBSCRIBERS="$(printf '%s\n' "$HEALTH_INFO" | sed -n 's/^Subscription count: //p' | head -1)"
    HEALTH_RELIABLE_ENDPOINTS="$(printf '%s\n' "$HEALTH_INFO" | grep -Ec 'Reliability: (RMW_QOS_POLICY_RELIABILITY_)?RELIABLE' || true)"
    SCAN_ENDPOINTS=$(( ${SCAN_PUBLISHERS:-0} + ${SCAN_SUBSCRIBERS:-0} ))
    HEALTH_ENDPOINTS=$(( ${HEALTH_PUBLISHERS:-0} + ${HEALTH_SUBSCRIBERS:-0} ))
    [ "${SCAN_PUBLISHERS:-0}" -ge 1 ] && [ "${SCAN_SUBSCRIBERS:-0}" -ge 1 ] \
        && [ "$SCAN_BEST_EFFORT_ENDPOINTS" -eq "$SCAN_ENDPOINTS" ] \
        || startup_no_go "cone scan publisher/subscriber QoS is incomplete or incompatible"
    [ "${HEALTH_PUBLISHERS:-0}" -ge 1 ] && [ "${HEALTH_SUBSCRIBERS:-0}" -ge 1 ] \
        && [ "$HEALTH_RELIABLE_ENDPOINTS" -eq "$HEALTH_ENDPOINTS" ] \
        || startup_no_go "cone health publisher/subscriber QoS is incomplete or incompatible"

    require_numeric_parameter /local_costmap/local_costmap cone_obstacle_layer.cone_scan.observation_persistence 1.5
    require_numeric_parameter /local_costmap/local_costmap cone_obstacle_layer.inflation_radius "$CONE_EXPECTED_INFLATION_RADIUS"
    require_numeric_parameter /local_costmap/local_costmap cone_obstacle_layer.cost_scaling_factor "$CONE_EXPECTED_COST_SCALING_FACTOR"
    require_numeric_parameter /local_costmap/local_costmap inflation_layer.inflation_radius 0.30
    require_numeric_parameter /local_costmap/local_costmap inflation_layer.cost_scaling_factor 3.0
    require_numeric_parameter /global_costmap/global_costmap cone_obstacle_layer.cone_scan.observation_persistence 1.5
    require_numeric_parameter /global_costmap/global_costmap cone_obstacle_layer.inflation_radius "$CONE_EXPECTED_INFLATION_RADIUS"
    require_numeric_parameter /global_costmap/global_costmap cone_obstacle_layer.cost_scaling_factor "$CONE_EXPECTED_COST_SCALING_FACTOR"
    require_numeric_parameter /global_costmap/global_costmap inflation_layer.inflation_radius 0.30
    require_numeric_parameter /global_costmap/global_costmap inflation_layer.cost_scaling_factor 3.0
    CONTROLLER_PLUGINS="$(parameter_value /controller_server controller_plugins)" \
        || startup_no_go "cannot read live controller plugin list"
    case "$CONTROLLER_PLUGINS" in
        *FollowPath*FollowPathCone*) ;;
        *) startup_no_go "controller_plugins does not contain FollowPath and FollowPathCone: $CONTROLLER_PLUGINS" ;;
    esac
    require_numeric_parameter /controller_server FollowPathCone.PathAlign.scale "$CONE_EXPECTED_PATH_ALIGN_SCALE"
    require_numeric_parameter /controller_server FollowPathCone.PathDist.scale "$CONE_EXPECTED_PATH_DIST_SCALE"
    require_numeric_parameter /controller_server FollowPathCone.sim_time "$CONE_EXPECTED_SIM_TIME"
    require_numeric_parameter /controller_server FollowPathCone.ObstacleFootprint.scale 1.0
    require_numeric_parameter /controller_server FollowPathCone.vtheta_samples 21
    require_numeric_parameter /controller_server FollowPathCone.min_vel_x 0.0
    require_numeric_parameter /controller_server FollowPathCone.max_vel_y 0.0
    require_numeric_parameter /controller_server FollowPath.PathAlign.scale 32.0
    require_numeric_parameter /controller_server FollowPath.PathDist.scale 32.0
    require_numeric_parameter /controller_server FollowPath.sim_time 1.5
    require_numeric_parameter /controller_server FollowPath.ObstacleFootprint.scale 0.02
    require_numeric_parameter /controller_server FollowPath.vtheta_samples 20
    require_numeric_parameter /cone_scan_safety_gate required_consecutive_frames 3
    require_numeric_parameter /cone_scan_safety_gate health_timeout_sec 0.20

    CONTROLLER_PID=""
    for proc_cmdline in /proc/[0-9]*/cmdline; do
        [ -r "$proc_cmdline" ] || continue
        proc_command="$(tr '\0' ' ' < "$proc_cmdline" 2>/dev/null || true)"
        case "$proc_command" in
            *'/nav2_controller/controller_server'*)
                CONTROLLER_PID="${proc_cmdline#/proc/}"
                CONTROLLER_PID="${CONTROLLER_PID%/cmdline}"
                break
                ;;
        esac
    done
    [ -n "$CONTROLLER_PID" ] && [ -r "/proc/$CONTROLLER_PID/maps" ] \
        || startup_no_go "cannot identify the live controller_server process"
    PLUGIN_MAP="$(grep -F 'libcone_inflated_voxel_layer_core.so' "/proc/$CONTROLLER_PID/maps" 2>/dev/null | head -1)"
    PLUGIN_MAP_PATH="$(printf '%s\n' "$PLUGIN_MAP" | awk '{print $NF}')"
    PLUGIN_MAP_REAL="$(readlink -f "$PLUGIN_MAP_PATH" 2>/dev/null || true)"
    [ -n "$PLUGIN_MAP_REAL" ] && [ "$PLUGIN_MAP_REAL" = "$PLUGIN_LIBRARY_REAL" ] \
        || startup_no_go "controller_server did not map the pinned ConeInflatedVoxelLayer library"
    snapshot_value "controller_server_pid" "$CONTROLLER_PID"
    snapshot_value "controller_plugin_map" "$PLUGIN_MAP"
    snapshot_value "controller_plugin_map_real" "$PLUGIN_MAP_REAL"

    PLANNER_PID=""
    for proc_cmdline in /proc/[0-9]*/cmdline; do
        [ -r "$proc_cmdline" ] || continue
        proc_command="$(tr '\0' ' ' < "$proc_cmdline" 2>/dev/null || true)"
        case "$proc_command" in
            *'/nav2_planner/planner_server'*)
                PLANNER_PID="${proc_cmdline#/proc/}"
                PLANNER_PID="${PLANNER_PID%/cmdline}"
                break
                ;;
        esac
    done
    [ -n "$PLANNER_PID" ] && [ -r "/proc/$PLANNER_PID/maps" ] \
        || startup_no_go "cannot identify the live planner_server process"
    PLANNER_PLUGIN_MAP="$(grep -F 'libcone_inflated_voxel_layer_core.so' "/proc/$PLANNER_PID/maps" 2>/dev/null | head -1)"
    PLANNER_PLUGIN_MAP_PATH="$(printf '%s\n' "$PLANNER_PLUGIN_MAP" | awk '{print $NF}')"
    PLANNER_PLUGIN_MAP_REAL="$(readlink -f "$PLANNER_PLUGIN_MAP_PATH" 2>/dev/null || true)"
    [ -n "$PLANNER_PLUGIN_MAP_REAL" ] && [ "$PLANNER_PLUGIN_MAP_REAL" = "$PLUGIN_LIBRARY_REAL" ] \
        || startup_no_go "planner_server did not map the pinned ConeInflatedVoxelLayer library"
    snapshot_value "planner_server_pid" "$PLANNER_PID"
    snapshot_value "planner_plugin_map" "$PLANNER_PLUGIN_MAP"
    snapshot_value "planner_plugin_map_real" "$PLANNER_PLUGIN_MAP_REAL"

    HEALTH_PROBE_JSON="$(python3 scripts/cone_startup_health_probe.py \
        --duration-sec "$STARTUP_HEALTH_WINDOW_SEC" \
        --min-scan-rate-hz "$STARTUP_MIN_SCAN_RATE_HZ" 2>&1)" \
        || startup_no_go "cone scan/health acceptance failed: $HEALTH_PROBE_JSON"
    snapshot_value "cone_health_probe" "$HEALTH_PROBE_JSON"
fi

if $CONE_TO_WHZ_L6; then
    require_exact_parameter /task_manager_node max_nav_retries 0
    require_exact_parameter /task_manager_node max_inspection_retries 0
    require_exact_parameter /task_manager_node finish_after_inspection true
    require_exact_parameter /task_manager_node allow_placeholder_manipulation false
    require_exact_parameter /task_manager_node waypoint_file "$TASK_WAYPOINT_FILE"
    require_exact_parameter /task_manager_node waypoint_route "$TASK_WAYPOINT_ROUTE"
    require_exact_parameter /task_manager_node expected_map_id "$TASK_EXPECTED_MAP_ID"
    require_exact_parameter /task_manager_node enable_cone_controller true
    require_exact_parameter /task_manager_node require_cone_layer_startup_ready true
    require_exact_parameter /task_manager_node cone_behavior_tree "$FORMAL_CONE_BEHAVIOR_TREE"
    require_exact_parameter /task_manager_node mission_start_armed false
fi

kill -0 "$COMP_PID" 2>/dev/null \
    || startup_no_go "competition launch exited before the final acceptance result"

if $CONE_TO_WHZ_L6; then
    MISSION_ARM_RESULT="$(timeout "$STARTUP_CLI_TIMEOUT_SEC" \
        ros2 param set /task_manager_node mission_start_armed true 2>&1)" \
        || startup_no_go "cannot arm TaskManager after startup acceptance: $MISSION_ARM_RESULT"
    snapshot_value "mission_start_arm_result" "$MISSION_ARM_RESULT"
    require_exact_parameter /task_manager_node mission_start_armed true
fi

echo ''
echo '==================================='
echo ' GO: 启动完成，运行验收通过!'
echo " 日志: $LOGFILE"
echo " 启动快照: $STARTUP_SNAPSHOT"
echo ' 停止: bash scripts/stop_all.sh'
echo '==================================='
