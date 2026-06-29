#!/bin/bash
# Complete environment setup - run ONCE on Jetson
set -e

echo "=== Setting up camera relay inside Docker ==="
CN=$(docker ps --format '{{.Names}}' | grep cuvslam)
echo "Container: $CN"

# Deploy camera relay (color jpg)
docker cp /tmp/camera_relay_docker.py $CN:/tmp/ 2>/dev/null || true
docker exec $CN pkill -f camera_relay 2>/dev/null || true
docker exec -d $CN bash -c "source /opt/ros/humble/setup.bash && source /workspaces/isaac_ros-dev/install/setup.bash && mkdir -p /workspaces/isaac_ros-dev/camera_frames && python3 /tmp/camera_relay_docker.py > /tmp/camera_relay.log 2>&1"
sleep 3
docker exec $CN cat /tmp/camera_relay.log | tail -1

# Deploy depth relay (raw uint16)
docker cp /tmp/depth_relay_docker.py $CN:/tmp/ 2>/dev/null || true
docker exec $CN pkill -f depth_relay 2>/dev/null || true
docker exec -d $CN bash -c "source /opt/ros/humble/setup.bash && source /workspaces/isaac_ros-dev/install/setup.bash && python3 /tmp/depth_relay_docker.py > /tmp/depth_relay.log 2>&1"
sleep 3
docker exec $CN cat /tmp/depth_relay.log | tail -1

echo ""
echo "=== Starting odometry bridge ==="
pkill -f final_bridge 2>/dev/null || true
source /opt/ros/foxy/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0 PYTHONPATH=/opt/ros/foxy/lib/python3.8/site-packages
nohup python3 /tmp/final_bridge.py > /tmp/fb.log 2>&1 &
sleep 8
tail -3 /tmp/fb.log

echo ""
echo "=== Verifying ==="
echo "Camera jpg: $(ls -la ~/workspaces/isaac_ros-dev/camera_frames/latest_color.jpg 2>/dev/null | awk '{print $5}') bytes"
echo "Depth raw: $(ls -la ~/workspaces/isaac_ros-dev/camera_frames/latest_depth.raw 2>/dev/null | awk '{print $5}') bytes"
echo "Bridge: $(tail -1 /tmp/fb.log)"

echo ""
echo "=== Done! Environment ready ==="
echo "Run: python3 /tmp/test_odom_sub.py   (verify /odom)"
echo "Run: ros2 launch launch/navigation.launch.py  (Nav2)"
