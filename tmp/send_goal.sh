#!/bin/bash
source /opt/ros/foxy/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0

echo "=== Sending nav goal: pos1_middle ==="
timeout 5 ros2 topic pub --once /nav/goal std_msgs/msg/String "data: pos1_middle" 2>&1
echo "EXIT: $?"

# Wait and check cmd_vel
sleep 3
echo ""
echo "=== cmd_vel (recent) ==="
timeout 3 ros2 topic echo --once /cmd_vel 2>/dev/null || echo "(no cmd_vel yet)"

echo ""
echo "=== Check nav logs ==="
grep -i "Turn to\|Walk\|move_forward\|Nav goal\|SUCCEEDED\|FAILED" /tmp/task_manager.log 2>/dev/null | tail -5
