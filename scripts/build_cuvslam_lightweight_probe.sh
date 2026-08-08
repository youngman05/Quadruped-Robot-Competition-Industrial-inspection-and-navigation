#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE="${IMAGE:-isaac_ros_cuvslam_runtime:humble-rs}"
ISAAC_WS="${ISAAC_WS:-$HOME/workspaces/isaac_ros-dev}"
PACKAGE_DIR="$PROJECT_DIR/tools/cuvslam_lightweight_probe"

[[ -d "$PACKAGE_DIR" ]] || { echo "ERROR: missing package: $PACKAGE_DIR" >&2; exit 1; }
[[ -d "$ISAAC_WS" ]] || { echo "ERROR: missing Isaac workspace: $ISAAC_WS" >&2; exit 1; }
[[ -f "$ISAAC_WS/install/setup.bash" ]] || {
  echo "ERROR: missing Isaac overlay: $ISAAC_WS/install/setup.bash" >&2
  exit 1
}
command -v docker >/dev/null || { echo "ERROR: docker is unavailable" >&2; exit 1; }
docker image inspect "$IMAGE" >/dev/null 2>&1 || {
  echo "ERROR: Docker image not found: $IMAGE" >&2
  exit 1
}

docker run --rm \
  --network host \
  -v "$ISAAC_WS":/workspaces/isaac_ros-dev \
  -v "$PACKAGE_DIR":/observer_probe_src:ro \
  -w /workspaces/isaac_ros-dev \
  "$IMAGE" \
  bash -lc '
    set -Eeuo pipefail
    set +u
    source /opt/ros/humble/setup.bash
    source /workspaces/isaac_ros-dev/install/setup.bash
    set -u
    colcon --log-base /workspaces/isaac_ros-dev/log_observer_probe build \
      --base-paths /observer_probe_src \
      --build-base /workspaces/isaac_ros-dev/build_observer_probe \
      --install-base /workspaces/isaac_ros-dev/install_observer_probe \
      --packages-select cuvslam_lightweight_probe
  '

test -f "$ISAAC_WS/install_observer_probe/setup.bash" || {
  echo "ERROR: isolated observer overlay was not created" >&2
  exit 1
}
echo "Observer overlay: $ISAAC_WS/install_observer_probe/setup.bash"
