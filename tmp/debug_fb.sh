#!/bin/bash
echo "=== final_bridge log ==="
cat /tmp/fb.log 2>&1 || echo "(empty)"

echo ""
echo "=== Docker exporter log ==="
docker exec cuvslam_gui_20260704-124632 cat /tmp/odom_exporter.log 2>&1 | tail -5 || echo "(empty)"

echo ""
echo "=== final_bridge process ==="
ps aux | grep final_bridge | grep -v grep || echo "DEAD"

echo ""
echo "=== Direct run (8s timeout) ==="
source /opt/ros/foxy/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0
timeout 8 python3 /tmp/final_bridge.py 2>&1
echo "EXIT: $?"
