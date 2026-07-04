#!/bin/bash
set -e
cd /home/superwfx666/quadruped-robot-competition
echo "=== Quadruped Startup ==="
echo "Time: $(date)"

# ── 1. Docker cuVSLAM ──────────────────────────
CN=$(docker ps --format '{{.Names}}' 2>/dev/null | grep cuvslam || true)
if [ -z "$CN" ]; then
    echo "[1] Starting Docker cuVSLAM (100s wait)..."
    CUVSLAM_MOUNT_MODE=robot CUVSLAM_PROFILE=planar_60fps \
      CUVSLAM_PUBLISH_ODOM_TO_BASE_TF=false \
      CUVSLAM_PUBLISH_MAP_TO_ODOM_TF=false \
      nohup bash scripts/start_cuvslam_rviz_gui.sh --no-rviz > /tmp/cuvslam.log 2>&1 &
    sleep 100
    CN=$(docker ps --format '{{.Names}}' | grep cuvslam)
else
    echo "[1] Docker already: $CN"
fi

# Wait for cuVSLAM odometry
echo "    Waiting for cuVSLAM odometry..."
for i in $(seq 1 20); do
    if docker exec $CN bash -c "source /opt/ros/humble/setup.bash && ros2 topic list 2>/dev/null | grep -q odom"; then
        echo "    cuVSLAM ready after ${i}s"
        break
    fi
    sleep 1
done

# ── 2. Camera + Depth relays ───────────────────
echo "[2] Camera + Depth relays..."
docker exec -d $CN bash -c '
source /opt/ros/humble/setup.bash
source /workspaces/isaac_ros-dev/install/setup.bash
mkdir -p /workspaces/isaac_ros-dev/camera_frames
python3 /tmp/camera_relay_docker.py > /tmp/cam.log 2>&1'

docker exec -d $CN bash -c '
source /opt/ros/humble/setup.bash
source /workspaces/isaac_ros-dev/install/setup.bash
python3 /tmp/depth_relay_docker.py > /tmp/dep.log 2>&1'
sleep 3
echo "    Camera: $(docker exec $CN tail -1 /tmp/cam.log 2>/dev/null || echo ...)"
echo "    Depth:  $(docker exec $CN tail -1 /tmp/dep.log 2>/dev/null || echo ...)"

# ── 3. Copy scripts ────────────────────────────
echo "[3] Copying bridge scripts..."
cp scripts/final_bridge.py /tmp/
cp scripts/cuvslam_odometry_udp_exporter.py /tmp/

# ── 4. final_bridge ────────────────────────────
echo "[4] Starting final_bridge..."
source /opt/ros/foxy/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0
export PYTHONPATH=/opt/ros/foxy/lib/python3.8/site-packages
pkill -f final_bridge 2>/dev/null || true
sleep 1
nohup python3 /tmp/final_bridge.py > /tmp/fb.log 2>&1 &
FB=$!
echo "    PID=$FB"
sleep 8
echo "    Log: $(tail -1 /tmp/fb.log 2>/dev/null || echo ...)"

# ── 5. task_manager ────────────────────────────
echo "[5] Starting task_manager + navigation..."
source install/setup.bash
source /opt/ros/foxy/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0
pkill -f task_manager 2>/dev/null || true
sleep 1
nohup ros2 launch quadruped_robot_competition competition.launch.py \
    enable_task_manager:=true \
    enable_navigation:=true > /tmp/task_manager.log 2>&1 &
LAUNCH=$!
echo "    Launch PID=$LAUNCH"
sleep 10

# ── 6. Verify ──────────────────────────────────
echo ""
echo "=== Status ==="
echo "Docker: $CN"
echo "final_bridge: $(pgrep -f final_bridge || echo DEAD)"
echo "task_manager: $(pgrep -f task_manager || echo DEAD)"
echo "Odom: $(ls -la /tmp/odom_latest.json 2>&1 | tail -1)"
echo ""
echo "=== Navigator init ==="
grep -i "navigator initialized" /tmp/task_manager.log 2>/dev/null || echo "(checking...)"
echo ""
echo "=== DONE ==="
