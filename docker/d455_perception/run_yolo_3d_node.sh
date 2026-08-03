#!/usr/bin/env bash
set -Ee -o pipefail

source /opt/ros/humble/setup.bash
if [[ -f /workspaces/isaac_ros-dev/install/setup.bash ]]; then
  source /workspaces/isaac_ros-dev/install/setup.bash
fi

exec python3 /opt/quadruped/perception/bin/d455_yolo_3d_node.py "$@"
