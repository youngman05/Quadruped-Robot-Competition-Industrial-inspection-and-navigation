#!/bin/bash
set -e
cd /home/superwfx666/quadruped-robot-competition

CN=$(docker ps --format '{{.Names}}' | grep cuvslam)
echo "Container: $CN"

# 1. Copy scripts
echo "[1] Copying scripts..."
cp scripts/final_bridge.py /tmp/final_bridge.py
cp scripts/cuvslam_odometry_udp_exporter.py /tmp/cuvslam_odometry_udp_exporter.py
docker cp /tmp/cuvslam_odometry_udp_exporter.py $CN:/tmp/cuvslam_odometry_udp_exporter.py
docker cp scripts/camera_relay_docker.py $CN:/tmp/camera_relay_docker.py 2>/dev/null || true
docker cp scripts/depth_relay_docker.py $CN:/tmp/depth_relay_docker.py 2>/dev/null || true
echo "Scripts copied OK"

# 2. Start camera + depth relays in Docker
echo "[2] Camera + Depth relays..."
docker exec -d $CN bash -c 'source /opt/ros/humble/setup.bash && source /workspaces/isaac_ros-dev/install/setup.bash && mkdir -p /workspaces/isaac_ros-dev/camera_frames && python3 /tmp/camera_relay_docker.py > /tmp/cam.log 2>&1'
docker exec -d $CN bash -c 'source /opt/ros/humble/setup.bash && source /workspaces/isaac_ros-dev/install/setup.bash && python3 /tmp/depth_relay_docker.py > /tmp/dep.log 2>&1'
sleep 3
echo "Camera: $(docker exec $CN tail -1 /tmp/cam.log 2>/dev/null || echo '...')"
echo "Depth:  $(docker exec $CN tail -1 /tmp/dep.log 2>/dev/null || echo '...')"

# 3. Start odom exporter in Docker
echo "[3] Odom exporter..."
docker exec -d $CN bash -c 'source /opt/ros/humble/setup.bash && source /workspaces/isaac_ros-dev/install/setup.bash && python3 /tmp/cuvslam_odometry_udp_exporter.py --port 19001 > /tmp/odom_exporter.log 2>&1'
sleep 3
echo "Exporter: $(docker exec $CN tail -1 /tmp/odom_exporter.log 2>/dev/null || echo '...')"

# 4. Start final_bridge
echo "[4] final_bridge..."
source /opt/ros/foxy/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0
export PYTHONPATH=/opt/ros/foxy/lib/python3.8/site-packages
pkill -f final_bridge 2>/dev/null || true
nohup python3 /tmp/final_bridge.py > /tmp/fb.log 2>&1 &
FB_PID=$!
echo "final_bridge PID=$FB_PID"
sleep 8
echo "Log: $(tail -3 /tmp/fb.log 2>/dev/null || echo 'empty')"

# 5. Check odom
echo "[5] Odom check..."
ls -la /tmp/odom_latest.json 2>&1 || echo "NO ODOM FILE"
echo "Done!"
