#!/usr/bin/env bash
set -Eeuo pipefail

# Start Isaac ROS Visual SLAM/cuVSLAM and RViz from a Jetson GUI terminal.
# This script is read-only with respect to the robot: it never publishes /cmd_vel.

IMAGE="${IMAGE:-isaac_ros_cuvslam_runtime:humble-rs}"
ISAAC_WS="${ISAAC_WS:-$HOME/workspaces/isaac_ros-dev}"
PROJECT_DIR="${PROJECT_DIR:-$HOME/quadruped-robot-competition}"
LOG_ROOT="${LOG_ROOT:-$HOME/cuvslam_lite3_logs}"
INPUT_TEST_SECONDS="${INPUT_TEST_SECONDS:-2.0}"
WAIT_SECONDS="${WAIT_SECONDS:-90}"
DEBUG_DUMP="${DEBUG_DUMP:-0}"
ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
SKIP_INPUT_TEST=0
SKIP_RVIZ=0

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/start_cuvslam_rviz_gui.sh [options]

Options:
  --skip-input-test   Do not run scripts/realsense_cuvslam_input_test.py first.
  --no-rviz           Start cuVSLAM only, without opening RViz.
  --debug-dump        Enable cuVSLAM debug dump under the log directory.
  -h, --help          Show this help.

Environment overrides:
  IMAGE               Docker image. Default: isaac_ros_cuvslam_runtime:humble-rs
  ISAAC_WS            Isaac ROS workspace. Default: ~/workspaces/isaac_ros-dev
  PROJECT_DIR         Repo path for D455 input validator. Default: ~/quadruped-robot-competition
  LOG_ROOT            Log root. Default: ~/cuvslam_lite3_logs
  INPUT_TEST_SECONDS  D455 validator duration. Default: 2.0
  WAIT_SECONDS        Topic wait timeout. Default: 90
  DEBUG_DUMP          Set to 1 to enable cuVSLAM debug dump. Default: 0
  ROS_DOMAIN_ID       ROS 2 DDS domain shared with host Foxy. Default: 0
  RMW_IMPLEMENTATION  ROS 2 middleware implementation. Default: rmw_fastrtps_cpp

Run this from a Jetson desktop terminal, VNC, or NoMachine session.
Plain SSH without X11/VNC will not show RViz.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-input-test)
      SKIP_INPUT_TEST=1
      shift
      ;;
    --no-rviz)
      SKIP_RVIZ=1
      shift
      ;;
    --debug-dump)
      DEBUG_DUMP=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

die() {
  echo "ERROR: $*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

run_in_container() {
  docker exec "$CONTAINER_NAME" bash -lc \
    "source /opt/ros/humble/setup.bash && source /workspaces/isaac_ros-dev/install/setup.bash && $*"
}

wait_for_topic() {
  local topic="$1"
  local start now
  start="$(date +%s)"
  while true; do
    if run_in_container "ros2 topic list 2>/dev/null | grep -Fx '$topic' >/dev/null"; then
      return 0
    fi
    now="$(date +%s)"
    if (( now - start >= WAIT_SECONDS )); then
      return 1
    fi
    sleep 2
  done
}

write_rviz_config() {
  cat >"$RVIZ_CONFIG" <<'RVIZ'
Panels:
  - Class: rviz_common/Displays
    Help Height: 78
    Name: Displays
    Property Tree Widget:
      Expanded:
        - /Global Options1
        - /TF1
        - /cuVSLAM Odometry1
        - /SLAM Odometry Viz1
        - /VO Path1
        - /SLAM Path1
        - /SLAM Landmarks1
        - /Current Observations1
        - /Loop Closure Cloud1
        - /Pose Graph Nodes1
        - /Pose Graph Edges1
        - /Pose Graph Edges 21
        - /Velocity Marker1
        - /Gravity Marker1
        - /Infra Left1
        - /Infra Right1
      Splitter Ratio: 0.5
  - Class: rviz_common/Views
    Name: Views
Visualization Manager:
  Class: ""
  Displays:
    - Class: rviz_default_plugins/Grid
      Cell Size: 1
      Color: 160; 160; 164
      Enabled: true
      Line Style:
        Line Width: 0.03
        Value: Lines
      Name: Grid
      Normal Cell Count: 0
      Offset:
        X: 0
        Y: 0
        Z: 0
      Plane: XY
      Plane Cell Count: 20
      Reference Frame: <Fixed Frame>
      Value: true
    - Class: rviz_default_plugins/TF
      Enabled: true
      Frame Timeout: 15
      Frames:
        All Enabled: true
      Marker Scale: 0.6
      Name: TF
      Show Arrows: true
      Show Axes: true
      Show Names: true
      Tree: {}
      Update Interval: 0
      Value: true
    - Class: rviz_default_plugins/Odometry
      Angle Tolerance: 0.1
      Color: 255; 25; 0
      Enabled: true
      Keep: 200
      Name: cuVSLAM Odometry
      Position Tolerance: 0.1
      Shape: Arrow
      Topic:
        Depth: 10
        Durability Policy: Volatile
        History Policy: Keep Last
        Reliability Policy: Reliable
        Value: /visual_slam/tracking/odometry
      Value: true
    - Class: rviz_default_plugins/Odometry
      Angle Tolerance: 0.1
      Color: 0; 255; 120
      Enabled: true
      Keep: 200
      Name: SLAM Odometry Viz
      Position Tolerance: 0.1
      Shape: Arrow
      Topic:
        Depth: 10
        Durability Policy: Volatile
        History Policy: Keep Last
        Reliability Policy: Reliable
        Value: /visual_slam/vis/slam_odometry
      Value: true
    - Class: rviz_default_plugins/Path
      Alpha: 1
      Buffer Length: 1
      Color: 25; 180; 255
      Enabled: true
      Line Style: Lines
      Line Width: 0.03
      Name: VO Path
      Offset:
        X: 0
        Y: 0
        Z: 0
      Pose Color: 255; 85; 255
      Pose Style: None
      Radius: 0.03
      Topic:
        Depth: 10
        Durability Policy: Volatile
        History Policy: Keep Last
        Reliability Policy: Reliable
        Value: /visual_slam/tracking/vo_path
      Value: true
    - Class: rviz_default_plugins/Path
      Alpha: 1
      Buffer Length: 1
      Color: 0; 255; 120
      Enabled: true
      Line Style: Lines
      Line Width: 0.03
      Name: SLAM Path
      Offset:
        X: 0
        Y: 0
        Z: 0
      Pose Color: 255; 255; 0
      Pose Style: None
      Radius: 0.03
      Topic:
        Depth: 10
        Durability Policy: Volatile
        History Policy: Keep Last
        Reliability Policy: Reliable
        Value: /visual_slam/tracking/slam_path
      Value: true
    - Class: rviz_default_plugins/PointCloud2
      Alpha: 1
      Autocompute Intensity Bounds: true
      Autocompute Value Bounds:
        Max Value: 10
        Min Value: -10
        Value: true
      Channel Name: intensity
      Color: 255; 255; 255
      Color Transformer: FlatColor
      Decay Time: 0
      Enabled: true
      Invert Rainbow: false
      Max Color: 255; 255; 255
      Max Intensity: 4096
      Min Color: 0; 0; 0
      Min Intensity: 0
      Name: SLAM Landmarks
      Position Transformer: XYZ
      Selectable: true
      Size (Pixels): 3
      Size (m): 0.03
      Style: Points
      Topic:
        Depth: 5
        Durability Policy: Volatile
        History Policy: Keep Last
        Reliability Policy: Reliable
        Value: /visual_slam/vis/landmarks_cloud
      Use Fixed Frame: true
      Use rainbow: true
      Value: true
    - Class: rviz_default_plugins/PointCloud2
      Alpha: 1
      Autocompute Intensity Bounds: true
      Autocompute Value Bounds:
        Max Value: 10
        Min Value: -10
        Value: true
      Channel Name: intensity
      Color: 255; 220; 60
      Color Transformer: FlatColor
      Decay Time: 0
      Enabled: true
      Invert Rainbow: false
      Max Color: 255; 255; 255
      Max Intensity: 4096
      Min Color: 0; 0; 0
      Min Intensity: 0
      Name: Current Observations
      Position Transformer: XYZ
      Selectable: true
      Size (Pixels): 4
      Size (m): 0.04
      Style: Points
      Topic:
        Depth: 5
        Durability Policy: Volatile
        History Policy: Keep Last
        Reliability Policy: Reliable
        Value: /visual_slam/vis/observations_cloud
      Use Fixed Frame: true
      Use rainbow: true
      Value: true
    - Class: rviz_default_plugins/PointCloud2
      Alpha: 1
      Autocompute Intensity Bounds: true
      Autocompute Value Bounds:
        Max Value: 10
        Min Value: -10
        Value: true
      Channel Name: intensity
      Color: 255; 50; 50
      Color Transformer: FlatColor
      Decay Time: 0
      Enabled: true
      Invert Rainbow: false
      Max Color: 255; 255; 255
      Max Intensity: 4096
      Min Color: 0; 0; 0
      Min Intensity: 0
      Name: Loop Closure Cloud
      Position Transformer: XYZ
      Selectable: true
      Size (Pixels): 6
      Size (m): 0.06
      Style: Points
      Topic:
        Depth: 5
        Durability Policy: Volatile
        History Policy: Keep Last
        Reliability Policy: Reliable
        Value: /visual_slam/vis/loop_closure_cloud
      Use Fixed Frame: true
      Use rainbow: true
      Value: true
    - Class: rviz_default_plugins/PoseArray
      Arrow Length: 0.35
      Axes Length: 0.3
      Axes Radius: 0.01
      Color: 255; 255; 0
      Enabled: true
      Head Length: 0.08
      Head Radius: 0.04
      Name: Pose Graph Nodes
      Shaft Length: 0.22
      Shaft Radius: 0.02
      Shape: Axes
      Topic:
        Depth: 5
        Durability Policy: Volatile
        History Policy: Keep Last
        Reliability Policy: Reliable
        Value: /visual_slam/vis/pose_graph_nodes
      Value: true
    - Class: rviz_default_plugins/Marker
      Enabled: true
      Name: Pose Graph Edges
      Topic:
        Depth: 5
        Durability Policy: Volatile
        History Policy: Keep Last
        Reliability Policy: Reliable
        Value: /visual_slam/vis/pose_graph_edges
      Value: true
    - Class: rviz_default_plugins/Marker
      Enabled: true
      Name: Pose Graph Edges 2
      Topic:
        Depth: 5
        Durability Policy: Volatile
        History Policy: Keep Last
        Reliability Policy: Reliable
        Value: /visual_slam/vis/pose_graph_edges2
      Value: true
    - Class: rviz_default_plugins/Marker
      Enabled: true
      Name: Velocity Marker
      Topic:
        Depth: 5
        Durability Policy: Volatile
        History Policy: Keep Last
        Reliability Policy: Reliable
        Value: /visual_slam/vis/velocity
      Value: true
    - Class: rviz_default_plugins/Marker
      Enabled: true
      Name: Gravity Marker
      Topic:
        Depth: 5
        Durability Policy: Volatile
        History Policy: Keep Last
        Reliability Policy: Reliable
        Value: /visual_slam/vis/gravity
      Value: true
    - Class: rviz_default_plugins/Image
      Enabled: true
      Max Value: 255
      Median window: 5
      Min Value: 0
      Name: Infra Left
      Normalize Range: true
      Topic:
        Depth: 5
        Durability Policy: Volatile
        History Policy: Keep Last
        Reliability Policy: Best Effort
        Value: /camera/infra1/image_rect_raw
      Value: true
    - Class: rviz_default_plugins/Image
      Enabled: true
      Max Value: 255
      Median window: 5
      Min Value: 0
      Name: Infra Right
      Normalize Range: true
      Topic:
        Depth: 5
        Durability Policy: Volatile
        History Policy: Keep Last
        Reliability Policy: Best Effort
        Value: /camera/infra2/image_rect_raw
      Value: true
  Enabled: true
  Global Options:
    Background Color: 36; 36; 38
    Fixed Frame: map
    Frame Rate: 30
  Name: root
  Tools:
    - Class: rviz_default_plugins/Interact
      Hide Inactive Objects: true
    - Class: rviz_default_plugins/MoveCamera
    - Class: rviz_default_plugins/Select
    - Class: rviz_default_plugins/FocusCamera
    - Class: rviz_default_plugins/Measure
      Line color: 128; 128; 0
  Transformation:
    Current:
      Class: rviz_default_plugins/TF
  Value: true
  Views:
    Current:
      Class: rviz_default_plugins/Orbit
      Distance: 6
      Focal Point:
        X: 0
        Y: 0
        Z: 0
      Name: Current View
      Pitch: 0.55
      Target Frame: map
      Yaw: 0.8
Window Geometry:
  Height: 900
  Width: 1440
  X: 40
  Y: 40
RVIZ
}

need_cmd docker
need_cmd date

[[ -n "${DISPLAY:-}" ]] || die "DISPLAY is empty. Run this from the Jetson desktop, VNC, or NoMachine terminal."
[[ -d "$ISAAC_WS" ]] || die "Isaac ROS workspace not found: $ISAAC_WS"
[[ -f "$ISAAC_WS/install/setup.bash" ]] || die "Missing install/setup.bash in $ISAAC_WS"
docker image inspect "$IMAGE" >/dev/null 2>&1 || die "Docker image not found: $IMAGE"

if [[ "$SKIP_INPUT_TEST" -eq 0 ]]; then
  if [[ -f "$PROJECT_DIR/scripts/realsense_cuvslam_input_test.py" ]]; then
    echo "Running D455 input validator..."
    (cd "$PROJECT_DIR" && python3 scripts/realsense_cuvslam_input_test.py --seconds "$INPUT_TEST_SECONDS")
  else
    echo "WARNING: D455 validator not found under $PROJECT_DIR; continuing without it." >&2
  fi
fi

if ! lsusb | grep -Eiq '8086:0b5c|realsense'; then
  die "No Intel RealSense device found in lsusb."
fi

if command -v xhost >/dev/null 2>&1; then
  xhost +local:root >/dev/null 2>&1 || true
  xhost +local:docker >/dev/null 2>&1 || true
else
  echo "WARNING: xhost not found; RViz may fail to open." >&2
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
CONTAINER_NAME="${CONTAINER_NAME:-cuvslam_gui_$STAMP}"
LOG_DIR="$LOG_ROOT/$STAMP"
RVIZ_CONFIG="$LOG_DIR/cuvslam.rviz"
mkdir -p "$LOG_DIR"
write_rviz_config

CUVSLAM_LAUNCH_ARGS="enable_slam_visualization:=true enable_landmarks_view:=true enable_observations_view:=true enable_localization_n_mapping:=true"
if [[ "$DEBUG_DUMP" == "1" ]]; then
  mkdir -p "$LOG_DIR/debug_dump"
  CUVSLAM_LAUNCH_ARGS="$CUVSLAM_LAUNCH_ARGS enable_debug_mode:=true debug_dump_path:=/logs/debug_dump"
fi

cleanup() {
  local code=$?
  echo
  echo "Stopping container: $CONTAINER_NAME"
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  if command -v xhost >/dev/null 2>&1; then
    xhost -local:root >/dev/null 2>&1 || true
    xhost -local:docker >/dev/null 2>&1 || true
  fi
  echo "Logs kept at: $LOG_DIR"
  exit "$code"
}
trap cleanup EXIT INT TERM

echo "Starting cuVSLAM container: $CONTAINER_NAME"
echo "Logs: $LOG_DIR"
echo "ROS_DOMAIN_ID=$ROS_DOMAIN_ID"
echo "RMW_IMPLEMENTATION=$RMW_IMPLEMENTATION"
cd "$ISAAC_WS"
docker run -d --name "$CONTAINER_NAME" \
  --runtime nvidia \
  --network host \
  --privileged \
  -e DISPLAY="$DISPLAY" \
  -e QT_X11_NO_MITSHM=1 \
  -e NVIDIA_VISIBLE_DEVICES=all \
  -e NVIDIA_DRIVER_CAPABILITIES=all \
  -e ROS_DOMAIN_ID="$ROS_DOMAIN_ID" \
  -e RMW_IMPLEMENTATION="$RMW_IMPLEMENTATION" \
  -e CUVSLAM_LAUNCH_ARGS="$CUVSLAM_LAUNCH_ARGS" \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v /dev:/dev \
  -v /tmp:/tmp \
  -v /usr/local/cuda-11.4:/usr/local/cuda-11.4:ro \
  -v /usr/lib/aarch64-linux-gnu/tegra:/usr/lib/aarch64-linux-gnu/tegra:ro \
  -v "$ISAAC_WS":/workspaces/isaac_ros-dev \
  -v "$LOG_DIR":/logs \
  -w /workspaces/isaac_ros-dev \
  "$IMAGE" \
  bash -lc 'source /opt/ros/humble/setup.bash && source install/setup.bash && stdbuf -oL -eL ros2 launch isaac_ros_visual_slam isaac_ros_visual_slam_realsense.launch.py ${CUVSLAM_LAUNCH_ARGS} 2>&1 | tee /logs/launch.log' >/dev/null

echo "Waiting for cuVSLAM topics..."
wait_for_topic "/visual_slam/status" || die "Timed out waiting for /visual_slam/status. See $LOG_DIR/launch.log"
wait_for_topic "/visual_slam/tracking/odometry" || die "Timed out waiting for /visual_slam/tracking/odometry. See $LOG_DIR/launch.log"

echo "cuVSLAM is publishing. One status sample:"
run_in_container "timeout 8 ros2 topic echo /visual_slam/status --once" | tee "$LOG_DIR/status_once.txt" || true

echo "Recording topic list and rates..."
run_in_container "ros2 topic list | sort" | tee "$LOG_DIR/topics.txt" >/dev/null || true
for topic in \
  /visual_slam/status \
  /visual_slam/tracking/odometry \
  /visual_slam/tracking/vo_path \
  /visual_slam/tracking/slam_path \
  /visual_slam/vis/slam_odometry \
  /visual_slam/vis/landmarks_cloud \
  /visual_slam/vis/observations_cloud \
  /visual_slam/vis/loop_closure_cloud \
  /visual_slam/vis/pose_graph_nodes \
  /visual_slam/vis/pose_graph_edges \
  /visual_slam/vis/pose_graph_edges2 \
  /visual_slam/vis/velocity \
  /visual_slam/vis/gravity; do
  if run_in_container "ros2 topic list | grep -Fx '$topic' >/dev/null"; then
    echo "OK topic: $topic" | tee -a "$LOG_DIR/topic_check.txt"
  else
    echo "MISSING topic: $topic" | tee -a "$LOG_DIR/topic_check.txt"
  fi
done

for topic in \
  /visual_slam/status \
  /visual_slam/tracking/odometry \
  /visual_slam/tracking/slam_path \
  /visual_slam/vis/landmarks_cloud \
  /visual_slam/vis/observations_cloud \
  /visual_slam/vis/loop_closure_cloud \
  /visual_slam/vis/pose_graph_nodes; do
  if run_in_container "ros2 topic list | grep -Fx '$topic' >/dev/null"; then
    safe_name="${topic#/}"
    safe_name="${safe_name//\//_}"
    run_in_container "timeout 12 ros2 topic hz '$topic'" >"$LOG_DIR/hz_${safe_name}.txt" 2>&1 || true
  fi
done

if [[ "$SKIP_RVIZ" -eq 0 ]]; then
  if run_in_container "command -v rviz2 >/dev/null"; then
    echo "Opening RViz..."
    docker exec -d "$CONTAINER_NAME" bash -lc \
      "source /opt/ros/humble/setup.bash && source /workspaces/isaac_ros-dev/install/setup.bash && rviz2 -d /logs/cuvslam.rviz > /logs/rviz.log 2>&1"
    echo "RViz should appear on the Jetson desktop."
  else
    echo "WARNING: rviz2 is not installed in $IMAGE. cuVSLAM is still running." >&2
  fi
fi

cat <<EOF

Manual GUI test is running.

Watch:
  - RViz window on the Jetson desktop
  - Terminal launch log below
  - $LOG_DIR/launch.log
  - $LOG_DIR/rviz.log

Expected RViz content:
  - Fixed Frame: map
  - TF tree
  - /visual_slam/tracking/odometry
  - /visual_slam/tracking/vo_path
  - /visual_slam/tracking/slam_path
  - /visual_slam/vis/slam_odometry
  - /visual_slam/vis/landmarks_cloud
  - /visual_slam/vis/observations_cloud
  - /visual_slam/vis/loop_closure_cloud
  - /visual_slam/vis/pose_graph_nodes
  - /visual_slam/vis/pose_graph_edges
  - /visual_slam/vis/pose_graph_edges2
  - /visual_slam/vis/velocity
  - /visual_slam/vis/gravity
  - /camera/infra1/image_rect_raw
  - /camera/infra2/image_rect_raw

Suggested teacher demo:
  1. Show /visual_slam/status and confirm vo_state stays 1.
  2. Move the robot/camera in a large loop and watch odometry, VO path, and SLAM path.
  3. Return close to the starting area and watch loop_closure_cloud plus pose_graph nodes/edges.
  4. Keep terminal logs visible for image delta warnings and tracking-lost messages.

Safety:
  - This script does not publish /cmd_vel.
  - Press Ctrl+C in this terminal to stop cuVSLAM and close the container.

EOF

docker logs -f "$CONTAINER_NAME"
