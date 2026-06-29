#!/bin/bash
# 比赛完整启动 (轻量版) — Jetson 终端运行
set -e
cd ~/quadruped-robot-competition

echo "═══════════════════════════════"
echo " 四足机器人竞赛系统 (轻量A*)"
echo "═══════════════════════════════"

# ── 1. Docker cuVSLAM ──────────────────────────
CN=$(docker ps --format '{{.Names}}' 2>/dev/null | grep cuvslam || true)
if [ -z "$CN" ]; then
    echo "[1] 启动 cuVSLAM Docker (100s 预热)..."
    CUVSLAM_MOUNT_MODE=robot CUVSLAM_PROFILE=planar_60fps \
      CUVSLAM_PUBLISH_ODOM_TO_BASE_TF=false \
      CUVSLAM_PUBLISH_MAP_TO_ODOM_TF=false \
      bash scripts/start_cuvslam_rviz_gui.sh --no-rviz > /tmp/cuvslam.log 2>&1 &
    sleep 100
    CN=$(docker ps --format '{{.Names}}' | grep cuvslam)
else
    echo "[1] Docker 在跑: $CN"
fi

# ── 2. 相机+深度中继 ─────────────────────────
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
echo "  Camera: $(docker exec $CN tail -1 /tmp/cam.log 2>/dev/null || echo '...')"

docker exec -d $CN bash -c '
source /opt/ros/humble/setup.bash
source /workspaces/isaac_ros-dev/install/setup.bash
python3 /tmp/depth_relay_docker.py > /tmp/dep.log 2>&1'
sleep 3
echo "  Depth:  $(docker exec $CN tail -1 /tmp/dep.log 2>/dev/null || echo '...')"

# ── 3. 定位桥接 ───────────────────────────────
echo "[3] 定位桥接 (docker exec pipeline → /odom)..."
source /opt/ros/foxy/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0
export PYTHONPATH=/opt/ros/foxy/lib/python3.8/site-packages
pkill -f final_bridge 2>/dev/null || true
sleep 1
nohup python3 /tmp/final_bridge.py > /tmp/fb.log 2>&1 &
sleep 10
echo "  $(tail -1 /tmp/fb.log 2>/dev/null || echo 'bridge started')"

# ── 4. 轻量导航 + 任务管理器 ─────────────────
echo "[4] 启动轻量导航 + 任务管理器..."
source ~/quadruped-robot-competition/install/setup.bash
ros2 launch quadruped_robot_competition competition.launch.py \
    enable_task_manager:=true \
    enable_navigation:=true &
LAUNCH_PID=$!
echo "  PID=$LAUNCH_PID, 等 10 秒..."
sleep 10

# ── 5. 验证 ──────────────────────────────────
echo "[5] 验证..."
source /opt/ros/foxy/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0
echo "  nodes:"
ros2 node list 2>/dev/null | head -15
echo ""
echo "  /odom:"
timeout 4 ros2 topic hz /odom 2>&1 | head -3 || echo "  (等待 odom...)"

echo ""
echo "═══════════════════════════════"
echo " 启动完成"
echo " 测试导航: ros2 topic pub /nav/goal std_msgs/String '{data: pos1_middle}'"
echo " 看 /cmd_vel: ros2 topic echo /cmd_vel"
echo "═══════════════════════════════"
