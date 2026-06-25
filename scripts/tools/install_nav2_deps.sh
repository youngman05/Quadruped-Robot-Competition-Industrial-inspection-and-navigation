#!/bin/bash
# Install Nav2 and navigation dependencies for quadruped robot competition.
# Target: Jetson Xavier NX, Ubuntu 20.04, ROS2 Foxy.
#
# Usage:
#   chmod +x install_nav2_deps.sh
#   ./install_nav2_deps.sh
#
# This script:
#   1. Installs Nav2 Foxy packages via apt
#   2. Installs depth_image_proc for D455 pointcloud generation
#   3. (Optional) Clones and builds TEB local planner from source
#
# TEB is commented out by default — uncomment the TEB section if needed.

set -e

echo "========================================="
echo " Installing Nav2 + navigation deps"
echo " Target: ROS2 Foxy on Jetson Xavier NX"
echo "========================================="

# ── 1. Nav2 core packages ──────────────────────────
echo ""
echo "[1/3] Installing Nav2 Foxy packages..."
sudo apt-get update
sudo apt-get install -y \
    ros-foxy-nav2-bringup \
    ros-foxy-nav2-map-server \
    ros-foxy-nav2-planner \
    ros-foxy-nav2-controller \
    ros-foxy-nav2-bt-navigator \
    ros-foxy-nav2-lifecycle-manager \
    ros-foxy-nav2-costmap-2d \
    ros-foxy-nav2-voxel-grid \
    ros-foxy-nav2-util \
    ros-foxy-nav2-common \
    ros-foxy-navigation2 \
    ros-foxy-nav2-navfn-planner \
    ros-foxy-nav2-regulated-pure-pursuit-controller \
    ros-foxy-nav2-smac-planner \
    ros-foxy-nav2-behavior-tree \
    ros-foxy-nav2-behaviors \
    ros-foxy-nav2-waypoint-follower

# ── 2. Depth image pipeline ────────────────────────
echo ""
echo "[2/3] Installing depth_image_proc + image_pipeline..."
sudo apt-get install -y \
    ros-foxy-depth-image-proc \
    ros-foxy-image-pipeline \
    ros-foxy-image-transport \
    ros-foxy-image-transport-plugins

# ── 3. TEB Local Planner (optional, from source) ──
# Uncomment below to build TEB from source for Foxy.
#
# echo ""
# echo "[3/4] Building TEB local planner from source..."
# TEB_WS=~/teb_ws
# mkdir -p $TEB_WS/src
# cd $TEB_WS/src
# if [ ! -d teb_local_planner ]; then
#     git clone -b ros2 https://github.com/rst-tu-dortmund/teb_local_planner.git
# fi
# cd $TEB_WS
# source /opt/ros/foxy/setup.bash
# colcon build --packages-select teb_local_planner --symlink-install
# echo "source $TEB_WS/install/setup.bash" >> ~/.bashrc
# echo "TEB local planner built."

echo ""
echo "========================================="
echo " Installation complete."
echo " Verify: ros2 pkg list | grep nav2"
echo "========================================="
