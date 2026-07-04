#!/bin/bash
source /opt/ros/foxy/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0

echo "=== ROS2 Nodes ==="
timeout 5 ros2 node list 2>/dev/null || echo "(timeout)"

echo ""
echo "=== /odom topic ==="
timeout 3 ros2 topic echo --once /odom 2>/dev/null | head -5 || echo "(no odom)"

echo ""
echo "=== Odom file ==="
cat /tmp/odom_latest.json 2>/dev/null || echo "(no file)"
echo "Age: $(( $(date +%s) - $(stat -c %Y /tmp/odom_latest.json 2>/dev/null || echo 0) ))s"

echo ""
echo "=== Send nav goal ==="
timeout 5 ros2 topic pub --once /nav/goal std_msgs/msg/String "data: pos1_middle" 2>&1 || echo "(timeout)"

echo ""
echo "=== Check cmd_vel ==="
timeout 3 ros2 topic echo --once /cmd_vel 2>/dev/null || echo "(no cmd_vel)"

echo ""
echo "=== Check /nav/result ==="
timeout 3 ros2 topic echo --once /nav/result 2>/dev/null || echo "(no result)"

echo ""
echo "DONE"
