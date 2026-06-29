#!/bin/bash
# 比赛完整启动 — Jetson 终端运行，按回车继续每一步
cd ~/quadruped-robot-competition

echo "═══════════════════════════════"
echo " 四足机器人竞赛系统"
echo "═══════════════════════════════"

# ── 1. Docker ─────────────────────────────────
CN=$(docker ps --format '{{.Names}}' 2>/dev/null | grep cuvslam || true)
if [ -z "$CN" ]; then
    echo "[1] 启动 cuVSLAM Docker..."
    CUVSLAM_MOUNT_MODE=robot CUVSLAM_PROFILE=planar_60fps \
      CUVSLAM_PUBLISH_ODOM_TO_BASE_TF=false \
      CUVSLAM_PUBLISH_MAP_TO_ODOM_TF=false \
      bash scripts/start_cuvslam_rviz_gui.sh --no-rviz > /tmp/cuvslam.log 2>&1 &
    echo "  等 100 秒 GPU 预热..."
    sleep 100
    CN=$(docker ps --format '{{.Names}}' | grep cuvslam)
else
    echo "[1] Docker 在跑: $CN"
fi

# ── 2. Relays ────────────────────────────────
echo "[2] 相机+深度中继..."
docker exec $CN pkill -f camera_relay 2>/dev/null || true
docker exec $CN pkill -f depth_relay 2>/dev/null || true
sleep 1

docker exec -d $CN bash -c '
source /opt/ros/humble/setup.bash
source /workspaces/isaac_ros-dev/install/setup.bash
mkdir -p /workspaces/isaac_ros-dev/camera_frames
python3 /tmp/camera_relay_docker.py > /tmp/cam.log 2>&1'
sleep 3
echo "  Camera: $(docker exec $CN tail -1 /tmp/cam.log 2>/dev/null || echo 'retrying...')"

docker exec -d $CN bash -c '
source /opt/ros/humble/setup.bash
source /workspaces/isaac_ros-dev/install/setup.bash
python3 /tmp/depth_relay_docker.py > /tmp/dep.log 2>&1'
sleep 3
echo "  Depth:  $(docker exec $CN tail -1 /tmp/dep.log 2>/dev/null || echo 'retrying...')"

# ── 3. Bridge ─────────────────────────────────
echo "[3] 定位桥接..."
source /opt/ros/foxy/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0
export PYTHONPATH=/opt/ros/foxy/lib/python3.8/site-packages
pkill -f final_bridge 2>/dev/null || true
sleep 1
nohup python3 /tmp/final_bridge.py > /tmp/fb.log 2>&1 &
sleep 10
echo "  $(tail -1 /tmp/fb.log)"

# ── 4. Nav2 ──────────────────────────────────
echo "[4] Nav2 导航栈..."
source ~/quadruped-robot-competition/install/setup.bash
ros2 launch quadruped_robot_competition navigation.launch.py &
NAV_PID=$!
echo "  PID=$NAV_PID, 等 15 秒激活..."
sleep 15

# ── 5. Verify ────────────────────────────────
echo "[5] 验证..."
source /opt/ros/foxy/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0
echo "  /odom:"
timeout 4 ros2 topic hz /odom 2>&1 | head -3
echo "  nodes: $(ros2 node list 2>/dev/null | wc -l)"
ros2 node list 2>/dev/null | head -10

echo ""
echo "═══════════════════════════════"
echo " 完成。验证 /cmd_vel:"
echo "  ros2 topic echo /cmd_vel"
echo " 接狗: ros2 launch transfer transfer.launch"
echo "═══════════════════════════════"
