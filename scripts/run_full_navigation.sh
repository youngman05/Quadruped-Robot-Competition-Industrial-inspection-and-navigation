#!/usr/bin/env bash
# One-command Jetson launcher for the validated 14-goal navigation stack.
# Deploy outside the Git checkout, then run: bash ~/run_full_navigation.sh

set -Eeuo pipefail

readonly DEPLOY_REPO="${NAV_DEPLOY_REPO:-/home/superwfx666/quadruped-robot-competition-nav2-dwb-deploy}"
readonly EXPECTED_BRANCH="Stonefield/nav2-foxy-dwb-integration"
readonly EXPECTED_COMMIT="94137ea0bbc10b0e46b684fad5f9c123aced6bfc"
readonly SPEED_PARAMS_PATH="configs/navigation/nav2_params.yaml"
readonly SPEED_ARBITER_PATH="src/nodes/navigation/cmd_vel_arbiter.py"
readonly SPEED_BRIDGE_PATH="src/nodes/navigation/cmd_vel_bridge.py"
readonly SPEED_PARAMS_SHA256="20b4e157c2d49ad73f7a74709913037676542ee5bcac68cb2c15290fed27df6b"
readonly SPEED_ARBITER_SHA256="fe1cc4887d86ff636d698f4fffb9f37e37c1779d247fc6c8b84b32315291daa0"
readonly SPEED_BRIDGE_SHA256="0a70c468e6d4d5687f2bb5d13e6ab160c4099f6dd3bec08f3eead13427bcfe83"
readonly RETIRED_REPO="/home/superwfx666/quadruped-robot-competition-nav2-dwb/"
readonly NAV2_OVERLAY_SETUP="${NAV2_OVERLAY_SETUP:-$HOME/nav2_foxy_overlay_ws/install/setup.bash}"
readonly ROUTE_FILE="configs/navigation/waypoints_reordered_preview.yaml"
readonly ROUTE_NAME="full_interleaved"
readonly D455_USB_ID="8086:0b5c"
readonly LITE3_IP="192.168.1.120"
readonly START_X="4.65"
readonly START_Y="0.75"
readonly START_YAW="3.141592653589793"
readonly START_XY_TOLERANCE="0.40"
readonly START_YAW_TOLERANCE="0.55"

CHECK_ONLY=false
STACK_OWNED=false
CLEANED=false
START_LOG=""

usage() {
    printf '%s\n' \
        "Usage: bash run_full_navigation.sh [--check-only]" \
        "" \
        "Default: validate, cold-start the stack, run all 14 goals, stop, archive." \
        "--check-only: validate hardware/deploy/install contracts without starting ROS nodes."
}

for arg in "$@"; do
    case "$arg" in
        --check-only) CHECK_ONLY=true ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'ERROR: unknown argument: %s\n' "$arg" >&2; usage >&2; exit 2 ;;
    esac
done

RUN_ID="$(date +%Y%m%d_%H%M%S)_oneclick_full14"
RUN_DIR="$HOME/competition_logs/nav2_waypoint_sequence/$RUN_ID"
mkdir -p "$RUN_DIR"
exec > >(tee -a "$RUN_DIR/launcher.log") 2>&1

log() {
    printf '[%s] %s\n' "$(date '+%F %T')" "$*"
}

die() {
    log "ERROR: $*"
    exit 2
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

archive_runtime_logs() {
    copy_if_present /tmp/competition.log nav2_stack.log
    copy_if_present /tmp/fb.log final_bridge.log
    copy_if_present /tmp/prepare_lite3_motion_mode.log prepare_lite3_motion_mode.log
    copy_if_present /tmp/full14_cmd_vel_gate.txt full14_cmd_vel_gate.txt
    copy_if_present /tmp/full14_route_description.json full14_route_description.json
    if [[ -n "$START_LOG" ]]; then
        copy_if_present "$START_LOG" startup_full.log
    fi
}

stop_and_archive() {
    local container

    set +e
    log "Stopping route, Nav2, bridges, and cuVSLAM"
    pkill -INT -f '[n]av2_waypoint_sequence_probe.py' 2>/dev/null || true
    if [[ -f "$DEPLOY_REPO/scripts/stop_all.sh" ]]; then
        (cd "$DEPLOY_REPO" && bash scripts/stop_all.sh) > "$RUN_DIR/stop_all.log" 2>&1
    fi

    while IFS= read -r container; do
        [[ -n "$container" ]] || continue
        docker logs "$container" > "$RUN_DIR/cuvslam_${container}.log" 2>&1 || true
        docker stop -t 10 "$container" >> "$RUN_DIR/docker_stop.log" 2>&1 || true
    done < <(running_cuvslam_containers)

    archive_runtime_logs
    pgrep -af 'nav2_waypoint_sequence_probe|cmd_vel_bridge|cmd_vel_arbiter|final_bridge|planner_server|controller_server|bt_navigator' \
        > "$RUN_DIR/remaining_processes.txt" 2>&1 || true
    docker ps --format 'table {{.Names}}\t{{.Status}}' \
        > "$RUN_DIR/docker_ps_after.txt" 2>&1 || true
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
    if [[ "$STACK_OWNED" == true && "$CLEANED" != true ]]; then
        stop_and_archive
    elif [[ "$STACK_OWNED" == true ]]; then
        archive_runtime_logs
    fi
    printf '%s\n' "$rc" > "$RUN_DIR/launcher_exit_code.txt"
    write_evidence_hashes
    log "Evidence directory: $RUN_DIR"
    exit "$rc"
}

trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

source_ros_environment() {
    [[ -f /opt/ros/foxy/setup.bash ]] || die "/opt/ros/foxy/setup.bash is missing"
    [[ -f "$NAV2_OVERLAY_SETUP" ]] || die "Nav2 overlay is missing: $NAV2_OVERLAY_SETUP"
    [[ -f "$DEPLOY_REPO/install/setup.bash" ]] || die "project install/setup.bash is missing"

    # ROS Foxy setup scripts reference optional variables and are not nounset-clean.
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
    python3 - "$DEPLOY_REPO" "$RUN_DIR/static_contract.json" <<'PY'
from pathlib import Path
import json
import re
import sys

repo = Path(sys.argv[1])
output_path = Path(sys.argv[2])
route_path = repo / "configs/navigation/waypoints_reordered_preview.yaml"
params_path = repo / "configs/navigation/nav2_params.yaml"
terminal_bt = repo / "configs/navigation/navigate_terminal_no_replanning.xml"
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
    "grab_area_approach",
    "placement_A_approach",
    "placement_B_approach",
    "placement_C_approach",
    "placement_D_approach",
]

document = json.loads(route_path.read_text(encoding="utf-8"))
route = document["routes"]["full_interleaved"]
params = params_path.read_text(encoding="utf-8")
assert document["calibration"]["status"] == "preview"
assert route == expected, route
assert len(re.findall(r"^\s*xy_goal_tolerance:\s*0\.30\s*$", params, re.M)) == 2
assert re.search(r"^\s*tolerance:\s*0\.20\s*$", params, re.M)
assert re.search(r"^\s*max_vel_x:\s*0\.24\s*$", params, re.M)
assert re.search(r"^\s*max_speed_xy:\s*0\.24\s*$", params, re.M)
assert re.search(r"^\s*max_vel_theta:\s*0\.30\s*$", params, re.M)
assert re.search(r"^\s*max_rotational_vel:\s*0\.30\s*$", params, re.M)
assert terminal_bt.is_file()
assert 'glob("configs/navigation/*.xml")' in (repo / "setup.py").read_text(encoding="utf-8")
assert "lower_corner_clear" in (
    repo / "src/nodes/navigation/waypoint_calibration.py"
).read_text(encoding="utf-8")

result = {
    "ok": True,
    "route": "full_interleaved",
    "goal_count": len(route),
    "point_8": route[7],
    "point_13": route[12],
    "xy_goal_tolerance": 0.30,
    "planner_tolerance": 0.20,
    "main_linear_limit": 0.24,
    "main_angular_limit": 0.30,
}
output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2))
PY
}

validate_speed_overlay() {
    local line path expected_hash actual_hash
    local -a actual_status expected_status
    expected_status=(
        " M $SPEED_PARAMS_PATH"
        " M $SPEED_ARBITER_PATH"
        " M $SPEED_BRIDGE_PATH"
    )
    mapfile -t actual_status < <(git status --porcelain --untracked-files=all)
    printf '%s\n' "${actual_status[@]}" > "$RUN_DIR/git_status.txt"
    [[ "${#actual_status[@]}" -eq "${#expected_status[@]}" ]] \
        || die "deploy worktree must contain exactly the three approved speed files"
    for line in "${expected_status[@]}"; do
        printf '%s\n' "${actual_status[@]}" | grep -Fxq "$line" \
            || die "missing or differently staged speed overlay entry: $line"
    done

    : > "$RUN_DIR/speed_overlay_hashes.txt"
    while IFS='|' read -r path expected_hash; do
        actual_hash="$(sha256sum "$path" | awk '{print $1}')"
        printf '%s  %s\n' "$actual_hash" "$path" >> "$RUN_DIR/speed_overlay_hashes.txt"
        [[ "$actual_hash" == "$expected_hash" ]] \
            || die "unexpected speed overlay hash: $path"
    done <<EOF_SPEED_HASHES
$SPEED_PARAMS_PATH|$SPEED_PARAMS_SHA256
$SPEED_ARBITER_PATH|$SPEED_ARBITER_SHA256
$SPEED_BRIDGE_PATH|$SPEED_BRIDGE_SHA256
EOF_SPEED_HASHES
}

preflight() {
    local command_name actual_repo actual_branch actual_commit package_prefix expected_prefix
    local installed_arbiter installed_bridge

    log "Preflight: deploy identity, hardware, route, and installed package"
    for command_name in git python3 docker lsusb ping awk grep sed timeout sha256sum; do
        require_command "$command_name"
    done
    [[ -d "$DEPLOY_REPO" ]] || die "deploy repository is missing: $DEPLOY_REPO"
    cd "$DEPLOY_REPO"

    actual_repo="$(git rev-parse --show-toplevel)"
    actual_branch="$(git branch --show-current)"
    actual_commit="$(git rev-parse HEAD)"
    [[ "$actual_repo" == "$DEPLOY_REPO" ]] || die "wrong repository: $actual_repo"
    [[ "$actual_branch" == "$EXPECTED_BRANCH" ]] || die "wrong branch: $actual_branch"
    [[ "$actual_commit" == "$EXPECTED_COMMIT" ]] || die "wrong commit: $actual_commit"
    validate_speed_overlay

    {
        printf 'D455:\n'
        lsusb -d "$D455_USB_ID"
        printf '\nLite3 ping:\n'
        ping -c 3 -W 1 "$LITE3_IP"
    } | tee "$RUN_DIR/hardware_preflight.txt"

    validate_static_contract
    source_ros_environment
    require_command ros2

    package_prefix="$(ros2 pkg prefix quadruped_robot_competition)"
    expected_prefix="$DEPLOY_REPO/install/quadruped_robot_competition"
    [[ "$package_prefix" == "$expected_prefix" ]] || die "wrong ROS package prefix: $package_prefix"
    cmp "$ROUTE_FILE" "$package_prefix/share/quadruped_robot_competition/$ROUTE_FILE"
    cmp configs/navigation/nav2_params.yaml \
        "$package_prefix/share/quadruped_robot_competition/configs/navigation/nav2_params.yaml"
    installed_arbiter="$(find "$package_prefix/lib" -path '*/site-packages/nodes/navigation/cmd_vel_arbiter.py' -print | sed -n '1p')"
    installed_bridge="$(find "$package_prefix/lib" -path '*/site-packages/nodes/navigation/cmd_vel_bridge.py' -print | sed -n '1p')"
    [[ -n "$installed_arbiter" && -n "$installed_bridge" ]] \
        || die "installed arbiter/bridge modules are missing"
    cmp "$SPEED_ARBITER_PATH" "$installed_arbiter"
    cmp "$SPEED_BRIDGE_PATH" "$installed_bridge"
    [[ -f "$package_prefix/share/quadruped_robot_competition/configs/navigation/navigate_terminal_no_replanning.xml" ]] \
        || die "installed terminal behavior tree is missing"

    {
        printf 'repo=%s\nbranch=%s\ncommit=%s\npackage_prefix=%s\n' \
            "$actual_repo" "$actual_branch" "$actual_commit" "$package_prefix"
    } | tee "$RUN_DIR/provenance.txt"
    log "Preflight passed"
}

cold_stop() {
    local container

    STACK_OWNED=true
    log "Cold stop: removing the previous navigation stack and cuVSLAM container"
    pkill -INT -f '[n]av2_waypoint_sequence_probe.py' 2>/dev/null || true
    bash scripts/stop_all.sh > "$RUN_DIR/prestart_stop_all.log" 2>&1 || true
    while IFS= read -r container; do
        [[ -n "$container" ]] || continue
        docker stop -t 10 "$container" >> "$RUN_DIR/prestart_docker_stop.log" 2>&1 || true
    done < <(running_cuvslam_containers)
    sleep 3

    if pgrep -af 'nav2_waypoint_sequence_probe|cmd_vel_bridge|cmd_vel_arbiter|final_bridge|planner_server|controller_server|bt_navigator' \
        > "$RUN_DIR/prestart_remaining_processes.txt" 2>&1; then
        die "old navigation processes remain"
    fi
    if [[ -n "$(running_cuvslam_containers)" ]]; then
        die "old cuVSLAM container remains"
    fi
}

start_stack() {
    local -a startup_logs

    log "Starting cuVSLAM, Nav2, arbiter, Lite3 bridge, and motion-mode preparation"
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

    bash scripts/start_competition.sh \
        --dog \
        --cmd-vel-bridge \
        --prepare-lite3-motion

    shopt -s nullglob
    startup_logs=("$HOME"/Desktop/logs/competition_*.log)
    shopt -u nullglob
    ((${#startup_logs[@]} > 0)) || die "startup log was not created"
    START_LOG="$(ls -1t "${startup_logs[@]}" | sed -n '1p')"
    grep -q '启动完成' "$START_LOG" || die "start_competition.sh did not report completion"
    log "Startup log: $START_LOG"
}

wait_for_lifecycle() {
    local attempt node output all_active
    local -a nodes=(map_server planner_server controller_server recoveries_server bt_navigator)

    for attempt in $(seq 1 30); do
        all_active=true
        : > "$RUN_DIR/lifecycle.txt.tmp"
        for node in "${nodes[@]}"; do
            output="$(ros2 lifecycle get "/$node" 2>&1 || true)"
            printf '%-22s %s\n' "$node" "$output" >> "$RUN_DIR/lifecycle.txt.tmp"
            [[ "$output" == *"active [3]"* ]] || all_active=false
        done
        if [[ "$all_active" == true ]]; then
            mv "$RUN_DIR/lifecycle.txt.tmp" "$RUN_DIR/lifecycle.txt"
            return 0
        fi
        sleep 2
    done
    mv "$RUN_DIR/lifecycle.txt.tmp" "$RUN_DIR/lifecycle.txt"
    die "Nav2 lifecycle nodes did not all become active"
}

check_param() {
    local node="$1" parameter="$2" expected="$3" output
    output="$(ros2 param get "$node" "$parameter" 2>&1)" || die "cannot read $node/$parameter"
    printf '%s %s: %s\n' "$node" "$parameter" "$output" >> "$RUN_DIR/runtime_params.txt"
    [[ "$output" == "Double value is: $expected" ]] \
        || die "unexpected $node/$parameter: $output"
}

validate_start_tf() {
    python3 - "$RUN_DIR/start_tf.json" "$START_X" "$START_Y" "$START_YAW" \
        "$START_XY_TOLERANCE" "$START_YAW_TOLERANCE" <<'PY'
from pathlib import Path
import json
import math
import sys
import time

import rclpy
from rclpy.time import Time
from tf2_ros import Buffer, TransformListener

output_path = Path(sys.argv[1])
expected_x, expected_y, expected_yaw = map(float, sys.argv[2:5])
xy_tolerance, yaw_tolerance = map(float, sys.argv[5:7])

rclpy.init()
node = rclpy.create_node("oneclick_start_tf_gate")
buffer = Buffer()
listener = TransformListener(buffer, node, spin_thread=False)
deadline = time.monotonic() + 12.0
transform = None
try:
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
        if buffer.can_transform("map", "base_link", Time()):
            transform = buffer.lookup_transform("map", "base_link", Time())
            break
finally:
    node.destroy_node()
    rclpy.shutdown()

if transform is None:
    raise SystemExit("map->base_link transform unavailable")
t = transform.transform.translation
q = transform.transform.rotation
yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))
xy_error = math.hypot(t.x - expected_x, t.y - expected_y)
yaw_error = abs(math.atan2(math.sin(yaw - expected_yaw), math.cos(yaw - expected_yaw)))
result = {
    "x": t.x,
    "y": t.y,
    "z": t.z,
    "yaw": yaw,
    "xy_error": xy_error,
    "yaw_error": yaw_error,
    "xy_tolerance": xy_tolerance,
    "yaw_tolerance": yaw_tolerance,
}
output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2))
if xy_error > xy_tolerance or yaw_error > yaw_tolerance:
    raise SystemExit("start pose is outside the allowed tolerance")
PY
}

capture_topic_info() {
    local topic="$1" target="$2"
    ros2 topic info "$topic" --verbose > "$target" 2>&1 \
        || die "cannot inspect topic: $topic"
}

require_topic_count() {
    local file="$1" label="$2" expected="$3"
    grep -Eq "^${label} count: ${expected}[[:space:]]*$" "$file" \
        || die "unexpected ${label} count in $(basename "$file")"
}

validate_nav2_input_topic() {
    local topic_file="$1"
    python3 - "$topic_file" <<'PY_NAV2_TOPIC'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
declared = {}
publishers = []
subscribers = []
node_name = None

for line in lines:
    match = re.fullmatch(r"(Publisher|Subscription) count:\s*(\d+)", line.strip())
    if match:
        declared[match.group(1)] = int(match.group(2))
        continue
    if line.startswith("Node name:"):
        node_name = line.split(":", 1)[1].strip().lstrip("/")
        continue
    if line.startswith("Endpoint type:"):
        if not node_name:
            raise SystemExit("endpoint is missing its node name")
        endpoint_type = line.split(":", 1)[1].strip()
        if endpoint_type == "PUBLISHER":
            publishers.append(node_name)
        elif endpoint_type == "SUBSCRIPTION":
            subscribers.append(node_name)
        node_name = None

if declared.get("Publisher") != len(publishers):
    raise SystemExit(f"publisher count mismatch: {declared.get('Publisher')} != {publishers}")
if declared.get("Subscription") != len(subscribers):
    raise SystemExit(f"subscription count mismatch: {declared.get('Subscription')} != {subscribers}")
if not publishers or "controller_server" not in publishers:
    raise SystemExit(f"controller_server publisher missing: {publishers}")
unexpected_publishers = sorted(set(publishers) - {"controller_server", "recoveries_server"})
if unexpected_publishers:
    raise SystemExit(f"unexpected /cmd_vel_nav2 publishers: {unexpected_publishers}")
if subscribers != ["cmd_vel_arbiter"]:
    raise SystemExit(f"unexpected /cmd_vel_nav2 subscribers: {subscribers}")

print(
    "PASS: /cmd_vel_nav2 topology "
    f"publishers={publishers} subscribers={subscribers}"
)
PY_NAV2_TOPIC
}

validate_runtime() {
    local action_info process_info latest_diag

    source_ros_environment
    wait_for_lifecycle

    action_info="$(ros2 action info /navigate_to_pose 2>&1)" \
        || die "cannot inspect /navigate_to_pose"
    printf '%s\n' "$action_info" > "$RUN_DIR/navigate_to_pose_action.txt"
    grep -Eq '^Action servers: 1[[:space:]]*$' "$RUN_DIR/navigate_to_pose_action.txt" \
        || die "/navigate_to_pose does not have exactly one server"

    : > "$RUN_DIR/runtime_params.txt"
    check_param /controller_server goal_checker.xy_goal_tolerance 0.3
    check_param /controller_server FollowPath.xy_goal_tolerance 0.3
    check_param /planner_server GridBased.tolerance 0.2
    check_param /controller_server FollowPath.max_vel_x 0.24
    check_param /controller_server FollowPath.max_speed_xy 0.24
    check_param /controller_server FollowPath.max_vel_theta 0.3
    check_param /recoveries_server max_rotational_vel 0.3
    check_param /cmd_vel_arbiter max_vx 0.24
    check_param /cmd_vel_arbiter max_wz 0.3
    check_param /cmd_vel_bridge_node hard_max_vx 0.24
    check_param /cmd_vel_bridge_node hard_max_speed_xy 0.24
    check_param /cmd_vel_bridge_node hard_max_az 0.3
    validate_start_tf

    process_info="$(pgrep -af 'planner_server|controller_server|cmd_vel_arbiter|cmd_vel_bridge|bt_navigator' || true)"
    printf '%s\n' "$process_info" > "$RUN_DIR/process_provenance.txt"
    [[ -n "$process_info" ]] || die "navigation process provenance is empty"
    [[ "$process_info" != *"$RETIRED_REPO"* ]] || die "a process is using the retired worktree"
    for process_name in planner_server controller_server cmd_vel_arbiter cmd_vel_bridge bt_navigator; do
        grep -q "$process_name" "$RUN_DIR/process_provenance.txt" \
            || die "missing process: $process_name"
    done

    capture_topic_info /cmd_vel_nav2 "$RUN_DIR/cmd_vel_nav2_topic.txt"
    capture_topic_info /cmd_vel_precision "$RUN_DIR/cmd_vel_precision_topic.txt"
    capture_topic_info /cmd_vel /tmp/full14_cmd_vel_gate.txt
    cp -a /tmp/full14_cmd_vel_gate.txt "$RUN_DIR/full14_cmd_vel_gate.txt"

    validate_nav2_input_topic "$RUN_DIR/cmd_vel_nav2_topic.txt"

    require_topic_count "$RUN_DIR/cmd_vel_precision_topic.txt" Publisher 0
    require_topic_count "$RUN_DIR/cmd_vel_precision_topic.txt" Subscription 1
    grep -Eq 'Node name: /?cmd_vel_arbiter' "$RUN_DIR/cmd_vel_precision_topic.txt" \
        || die "/cmd_vel_precision subscriber is not cmd_vel_arbiter"

    require_topic_count "$RUN_DIR/full14_cmd_vel_gate.txt" Publisher 1
    require_topic_count "$RUN_DIR/full14_cmd_vel_gate.txt" Subscription 1
    grep -Eq 'Node name: /?cmd_vel_arbiter' "$RUN_DIR/full14_cmd_vel_gate.txt" \
        || die "/cmd_vel publisher is not cmd_vel_arbiter"
    grep -Eq 'Node name: /?cmd_vel_bridge(_node)?' "$RUN_DIR/full14_cmd_vel_gate.txt" \
        || die "/cmd_vel subscriber is not cmd_vel_bridge"

    grep -Eq 'done simple=50 complex=48 errors=0[[:space:]]*$' /tmp/prepare_lite3_motion_mode.log \
        || die "Lite3 motion-mode preparation did not complete cleanly"
    for _ in $(seq 1 10); do
        latest_diag="$(grep '\[diag\]' /tmp/competition.log 2>/dev/null | tail -n 1 || true)"
        if [[ "$latest_diag" == *"udp_errors=0"* && "$latest_diag" == *"last_send=(0.000,0.000,0.000)"* ]]; then
            break
        fi
        sleep 1
    done
    printf '%s\n' "$latest_diag" > "$RUN_DIR/bridge_pre_goal_diag.txt"
    [[ "$latest_diag" == *"udp_errors=0"* ]] || die "bridge reports UDP errors or no diagnostics"
    [[ "$latest_diag" == *"last_send=(0.000,0.000,0.000)"* ]] \
        || die "bridge is not holding zero before route submission"

    python3 scripts/nav2_waypoint_sequence_probe.py \
        --describe-route \
        --waypoint-file "$ROUTE_FILE" \
        --waypoint-route "$ROUTE_NAME" \
        --allow-preview-route \
        > /tmp/full14_route_description.json
    cp -a /tmp/full14_route_description.json "$RUN_DIR/full14_route_description.json"
    python3 - /tmp/full14_route_description.json <<'PY'
from pathlib import Path
import json
import sys

description = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
steps = description.get("steps", [])
labels = [step.get("label") for step in steps]
assert len(steps) == 14, len(steps)
assert labels[7] == "lower_corner_clear", labels
assert labels[12] == "placement_C_approach", labels
assert [step.get("index") for step in steps] == list(range(1, 15))
print("PASS: runtime route description has the expected 14 goals")
PY

    log "All runtime gates passed; submitting the 14-goal route"
}

run_route() {
    local route_rc

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
    printf '%s\n' "$route_rc" > "$RUN_DIR/route_exit_code.txt"
    return "$route_rc"
}

evaluate_summary() {
    python3 - "$RUN_DIR/summary.json" <<'PY'
from pathlib import Path
import json
import sys

path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit(f"summary missing: {path}")
data = json.loads(path.read_text(encoding="utf-8"))
segments = data.get("segments", [])
passed = data.get("ok") is True and len(segments) == 14 and all(
    segment.get("succeeded") is True for segment in segments
)
print(f"summary={path}")
print(f"ok={data.get('ok')} sent_segments={len(segments)}/14")
for segment in segments:
    goal = segment.get("goal") or {}
    label = goal.get("label") or goal.get("approach_label") or "<unnamed>"
    print(
        f"{segment.get('index', 0):02d}. {label}: "
        f"{segment.get('action_status_name')} succeeded={segment.get('succeeded')} "
        f"error={segment.get('error')}"
    )
print("PASS: all 14 navigation goals succeeded" if passed else "FAIL/INCOMPLETE")
raise SystemExit(0 if passed else 2)
PY
}

main() {
    local route_rc summary_rc final_rc

    log "Run directory: $RUN_DIR"
    preflight
    if [[ "$CHECK_ONLY" == true ]]; then
        log "Check-only validation passed; no stack or route was started"
        return 0
    fi

    cold_stop
    start_stack
    validate_runtime

    set +e
    run_route
    route_rc=$?
    set -e

    stop_and_archive

    set +e
    evaluate_summary | tee "$RUN_DIR/result.txt"
    summary_rc="${PIPESTATUS[0]}"
    set -e

    final_rc="$route_rc"
    if [[ "$final_rc" -eq 0 ]]; then
        final_rc="$summary_rc"
    fi
    if [[ "$final_rc" -eq 0 ]]; then
        log "Navigation completed: all 14 goals succeeded"
    else
        log "Navigation stopped with rc=$final_rc; inspect the first failed segment"
    fi
    return "$final_rc"
}

main
