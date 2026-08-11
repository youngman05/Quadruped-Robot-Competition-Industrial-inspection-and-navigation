#!/usr/bin/env bash
# Start the validated navigation stack and run the dedicated WHZ inspection route.

set -Eeuo pipefail

readonly DEPLOY_REPO="${NAV_DEPLOY_REPO:-/home/superwfx666/quadruped-robot-competition-nav2-dwb-deploy}"
readonly NAV2_OVERLAY_SETUP="${NAV2_OVERLAY_SETUP:-$HOME/nav2_foxy_overlay_ws/install/setup.bash}"
readonly PYTHON_BIN="${PYTHON_BIN:-python3}"
readonly ROUTE_FILE="configs/navigation/waypoints_reordered_preview.yaml"
readonly ROUTE_NAME="inspection_interleaved"

MODE=""
CHECK_ONLY=false
MOTION_CONFIRMED=false
for arg in "$@"; do
    case "$arg" in
        --single-d) MODE="single_d" ;;
        --full) MODE="full" ;;
        --check-only) CHECK_ONLY=true ;;
        --confirm-motion) MOTION_CONFIRMED=true ;;
        *) printf 'Unknown argument: %s\n' "$arg" >&2; exit 64 ;;
    esac
done

if [[ "$CHECK_ONLY" != true && -z "$MODE" ]]; then
    echo "Select --single-d or --full." >&2
    exit 64
fi
if [[ "$CHECK_ONLY" != true && "$MOTION_CONFIRMED" != true ]]; then
    echo "Motion is locked. Confirm route clearance, emergency stop, and on-site supervision, then pass --confirm-motion." >&2
    exit 64
fi
if [[ -z "$MODE" ]]; then
    MODE="check_only"
fi

RUN_ID="$(date +%Y%m%d_%H%M%S)_inspection_${MODE}"
RUN_DIR="$HOME/competition_logs/nav2_whz_inspection/$RUN_ID"
mkdir -p "$RUN_DIR"
exec > >(tee -a "$RUN_DIR/launcher.log") 2>&1

STACK_STARTED=false
CLEANED=false

log() {
    printf '[%s] %s\n' "$(date '+%F %T')" "$*"
}

copy_if_present() {
    local source_path="$1"
    local target_name="${2:-$(basename "$source_path")}"
    if [[ -f "$source_path" ]]; then
        cp -a "$source_path" "$RUN_DIR/$target_name" 2>/dev/null || true
    fi
}

running_cuvslam_containers() {
    docker ps --format '{{.Names}}' 2>/dev/null | awk '/cuvslam/ {print $1}'
}

stop_and_archive() {
    local container

    set +e
    log "Stopping inspection and navigation stack"
    pkill -INT -f '[n]av2_whz_inspection_probe.py' 2>/dev/null || true
    if [[ -f "$DEPLOY_REPO/scripts/stop_all.sh" ]]; then
        (cd "$DEPLOY_REPO" && bash scripts/stop_all.sh) > "$RUN_DIR/stop_all.log" 2>&1
    fi
    while IFS= read -r container; do
        [[ -n "$container" ]] || continue
        docker logs "$container" > "$RUN_DIR/cuvslam_${container}.log" 2>&1 || true
        docker stop -t 10 "$container" >> "$RUN_DIR/docker_stop.log" 2>&1 || true
    done < <(running_cuvslam_containers)

    copy_if_present /tmp/competition.log nav2_stack.log
    copy_if_present /tmp/fb.log final_bridge.log
    copy_if_present /tmp/prepare_lite3_motion_mode.log prepare_lite3_motion_mode.log
    CLEANED=true
    set -e
}

write_evidence_hashes() {
    (
        cd "$RUN_DIR" || exit 0
        find . -maxdepth 1 -type f \
            ! -name evidence_sha256.txt \
            ! -name launcher.log \
            -print0 \
            | sort -z \
            | xargs -0 -r sha256sum \
            > evidence_sha256.txt
    ) 2>/dev/null || true
}

on_exit() {
    local rc=$?
    trap - EXIT INT TERM
    if [[ "$STACK_STARTED" == true && "$CLEANED" != true ]]; then
        stop_and_archive
    fi
    printf '%s\n' "$rc" > "$RUN_DIR/launcher_exit_code.txt"
    log "Evidence directory: $RUN_DIR"
    write_evidence_hashes
    exit "$rc"
}

trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

source_ros_environment() {
    set +u
    source /opt/ros/foxy/setup.bash
    source "$NAV2_OVERLAY_SETUP"
    source "$DEPLOY_REPO/install/setup.bash"
    set -u

    export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
    export ROS_DOMAIN_ID=0
    export PYTHONPATH="$DEPLOY_REPO/src:${PYTHONPATH:-}"
    export FASTRTPS_DEFAULT_PROFILES_FILE="$DEPLOY_REPO/configs/ros/fastrtps_no_shm.xml"
}

validate_static_contract() {
    local launch_block

    cd "$DEPLOY_REPO"
    for path in \
        scripts/nav2_waypoint_sequence_probe.py \
        scripts/nav2_whz_inspection_probe.py \
        scripts/start_competition.sh \
        scripts/stop_all.sh \
        "$ROUTE_FILE" \
        configs/navigation/navigate_terminal_no_replanning.xml; do
        [[ -f "$path" ]] || { echo "Missing required file: $path" >&2; return 1; }
    done

    "$PYTHON_BIN" -m py_compile scripts/nav2_whz_inspection_probe.py
    "$PYTHON_BIN" - "$ROUTE_FILE" <<'PY'
import json
import sys

expected = [
    "obstacle_cross_target",
    "pos1_left_clear",
    "pos1_middle",
    "upper_corner_clear",
    "pos2a_upper_right",
    "upper_corner_clear",
    "pos1_middle_turned",
    "lower_corner_clear",
    "pos2b_lower_right",
]
with open(sys.argv[1], "r", encoding="utf-8") as handle:
    document = json.load(handle)
route = document["routes"]["inspection_interleaved"]
if route != expected:
    raise SystemExit("inspection_interleaved route mismatch")
actions = [
    document["waypoints"][name].get("action", "")
    for name in route
]
if sum(action.startswith("observe_") for action in actions) != 4:
    raise SystemExit("inspection route must contain four observation actions")
print("static route contract: PASS")
PY

    launch_block="$(sed -n '/^[[:space:]]*bash scripts\/start_competition.sh \\/,/^[[:space:]]*--whz$/p' scripts/run_inspection_navigation.sh)"
    if printf '%s\n' "$launch_block" | grep -Eq -- '--task-manager|--mission|--auto-advance'; then
        echo "Inspection launcher must not enable TaskManager" >&2
        return 1
    fi
}

ensure_idle_runtime() {
    local matches
    matches="$(pgrep -af '[n]av2_whz_inspection_probe.py|[n]av2_waypoint_sequence_probe.py|[t]ask_manager|[p]lanner_server|[c]ontroller_server|[b]t_navigator|[c]md_vel_arbiter|[c]md_vel_bridge.py|[w]hz_inspection_node' || true)"
    if [[ -n "$matches" ]]; then
        echo "Conflicting runtime is active:" >&2
        echo "$matches" >&2
        return 1
    fi
    if [[ -n "$(running_cuvslam_containers)" ]]; then
        echo "A cuVSLAM container is already active." >&2
        return 1
    fi
}

main() {
    local route_rc

    validate_static_contract
    if [[ "$CHECK_ONLY" == true ]]; then
        log "Static inspection contract passed; no ROS process or motion was started"
        return 0
    fi

    ensure_idle_runtime
    cd "$DEPLOY_REPO"
    export FINAL_BRIDGE_CAMERA_WORLD_REBASE=base_start
    export CUVSLAM_MOUNT_MODE=robot
    export CUVSLAM_PROFILE=custom
    export CUVSLAM_CAMERA_PROFILE=640x360x30
    export CUVSLAM_ENABLE_LOCALIZATION_N_MAPPING=true
    export ENABLE_SLAM_VISUALIZATION=false
    export ENABLE_LANDMARKS_VIEW=false
    export ENABLE_OBSERVATIONS_VIEW=false
    export ENABLE_SLAM_DIAGNOSTICS=false
    export ENABLE_LOOP_METRICS_RECORDER=false
    export STARTUP_TOPIC_CHECKS=false
    export STARTUP_RATE_PROBES=false
    export WHZ_STARTUP_TIMEOUT_SEC=60
    export WHZ_SERVICE_WAIT_SEC=15
    export WHZ_RESPONSE_TIMEOUT_SEC=30
    export WHZ_SETTLE_DURATION_SEC=1
    export WHZ_SETTLE_TIMEOUT_SEC=10

    if [[ "$MODE" == "single_d" ]]; then
        export WHZ_INSPECTION_TARGETS=pos2b_lower_right
        export WHZ_EXPECTED_AREAS=pos2b_lower_right=D
    else
        unset WHZ_INSPECTION_TARGETS
        unset WHZ_EXPECTED_AREAS
    fi

    log "Starting Nav2, velocity chain, cuVSLAM, and WHZ with TaskManager disabled"
    STACK_STARTED=true
    bash scripts/start_competition.sh \
        --dog \
        --cmd-vel-bridge \
        --prepare-lite3-motion \
        --whz

    source_ros_environment
    log "Running $ROUTE_NAME mode=$MODE"
    set +e
    "$PYTHON_BIN" scripts/nav2_whz_inspection_probe.py \
        --waypoint-file "$ROUTE_FILE" \
        --waypoint-route "$ROUTE_NAME" \
        --allow-preview-route \
        --goal-timeout 130 \
        --map-tf-timeout 30 \
        --inter-goal-pause 2 \
        --stop-on-failure \
        --behavior-tree /opt/ros/foxy/share/nav2_bt_navigator/behavior_trees/navigate_w_replanning_time.xml \
        --terminal-behavior-tree configs/navigation/navigate_terminal_no_replanning.xml \
        --terminal-replan-stop-radius 0.35 \
        --output-dir "$RUN_DIR" \
        2>&1 | tee "$RUN_DIR/route_stdout.log"
    route_rc="${PIPESTATUS[0]}"
    set -e
    printf '%s\n' "$route_rc" > "$RUN_DIR/route_exit_code.txt"

    stop_and_archive
    return "$route_rc"
}

main
