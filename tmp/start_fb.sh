#!/bin/bash
cd /home/superwfx666/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0
export PYTHONPATH=/opt/ros/foxy/lib/python3.8/site-packages
exec python3 scripts/final_bridge.py >> /tmp/final_bridge.log 2>&1
