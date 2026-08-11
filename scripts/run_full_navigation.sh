#!/usr/bin/env bash
# Start the Jetson navigation stack and immediately run the full 14-goal route.

set -Eeuo pipefail

readonly DEPLOY_REPO="${NAV_DEPLOY_REPO:-/home/superwfx666/quadruped-robot-competition-nav2-dwb-deploy}"
readonly NAV2_OVERLAY_SETUP="${NAV2_OVERLAY_SETUP:-$HOME/nav2_foxy_overlay_ws/install/setup.bash}"
readonly ROUTE_FILE="configs/navigation/waypoints_reordered_preview.yaml"
readonly ROUTE_NAME="full_interleaved"

RUN_ID="$(date +%Y%m%d_%H%M%S)_oneclick_full14"
RUN_DIR="$HOME/competition_logs/nav2_waypoint_sequence/$RUN_ID"
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
    log "Stopping navigation stack"
    pkill -INT -f '[n]av2_waypoint_sequence_probe.py' 2>/dev/null || true
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

main() {
    local route_rc

    cd "$DEPLOY_REPO"
    log "Starting complete navigation stack"

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

    STACK_STARTED=true
    bash scripts/start_competition.sh \
        --dog \
        --cmd-vel-bridge \
        --prepare-lite3-motion

    source_ros_environment
    log "Running $ROUTE_NAME"
    set +e
    python3 scripts/nav2_waypoint_sequence_probe.py \
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
