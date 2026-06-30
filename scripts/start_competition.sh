#!/bin/bash
# =========================================
#  四足机器人竞赛 — 一键启动脚本
# =========================================
set -e
cd ~/quadruped-robot-competition

ENABLE_YOLO=false; ENABLE_WHZ=false; ENABLE_LOG=false
for arg in "$@"; do
    case $arg in
        --yolo) ENABLE_YOLO=true ;;
        --whz)  ENABLE_WHZ=true ;;
        --log)  ENABLE_LOG=true ;;
    esac
done

echo ''
echo '==================================='
echo ' 四足机器人竞赛系统 - 轻量A*'
echo '==================================='

# [0] Kill zombies
echo '[0/5] 清理旧进程...'
pkill -9 -f color_image_publisher 2>/dev/null || true
pkill -9 -f inspection_node 2>/dev/null || true
pkill -9 -f final_bridge 2>/dev/null || true
pkill -9 -f task_manager 2>/dev/null || true
pkill -9 -f gauge_status_publisher 2>/dev/null || true
pkill -9 -f depth_publisher 2>/dev/null || true
pkill -9 -f initial_pose_publisher 2>/dev/null || true
sleep 2 && echo '  干净'

# [1] Docker
echo '[1/5] Docker...'
CN=$(docker ps --format '{{.Names}}' 2>/dev/null | grep cuvslam || true)
if [ -z "$CN" ]; then
    CUVSLAM_MOUNT_MODE=robot CUVSLAM_PROFILE=planar_60fps       CUVSLAM_PUBLISH_ODOM_TO_BASE_TF=false CUVSLAM_PUBLISH_MAP_TO_ODOM_TF=false       bash scripts/start_cuvslam_rviz_gui.sh --no-rviz > /tmp/cuvslam.log 2>&1 &
    echo '  等 100 秒 GPU 预热...'; sleep 100
    CN=$(docker ps --format '{{.Names}}' | grep cuvslam)
fi
echo "  Docker: $CN"

# [2] Relays
echo '[2/5] 中继...'
docker cp scripts/camera_relay_docker.py $CN:/tmp/ 2>/dev/null || true
docker cp scripts/depth_relay_docker.py $CN:/tmp/ 2>/dev/null || true
docker exec $CN pkill -f camera_relay 2>/dev/null || true
docker exec $CN pkill -f depth_relay 2>/dev/null || true
sleep 1
docker exec -d $CN bash -c "source /opt/ros/humble/setup.bash; source /workspaces/isaac_ros-dev/install/setup.bash; mkdir -p /workspaces/isaac_ros-dev/camera_frames; python3 /tmp/camera_relay_docker.py > /tmp/cam.log 2>&1"
sleep 3 && echo "  Camera: $(docker exec $CN tail -1 /tmp/cam.log 2>/dev/null || echo OK)"
docker exec -d $CN bash -c "source /opt/ros/humble/setup.bash; source /workspaces/isaac_ros-dev/install/setup.bash; python3 /tmp/depth_relay_docker.py > /tmp/dep.log 2>&1"
sleep 3 && echo "  Depth: $(docker exec $CN tail -1 /tmp/dep.log 2>/dev/null || echo OK)"

# [3] Bridge (no-SHM for cross-DDS)
echo '[3/5] 桥接...'
source /opt/ros/foxy/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0 PYTHONPATH=/opt/ros/foxy/lib/python3.8/site-packages FASTRTPS_DEFAULT_PROFILES_FILE=~/quadruped-robot-competition/configs/ros/fastrtps_no_shm.xml
nohup python3 scripts/final_bridge.py > /tmp/fb.log 2>&1 &
sleep 10 && echo "  $(tail -1 /tmp/fb.log)"

# [4] Competition system
echo '[4/5] 导航...'
if $ENABLE_LOG; then
    nohup python3 scripts/test_logger.py > /tmp/logger.log 2>&1 &
    sleep 2 && echo "  Logger: ~/competition_logs/$(ls ~/competition_logs/ | tail -1)"
fi
source install/setup.bash
YF=false; WF=false
$ENABLE_YOLO && YF=true
$ENABLE_WHZ && WF=true
ros2 launch quadruped_robot_competition competition.launch.py   enable_task_manager:=true enable_navigation:=true   enable_yolo:=$YF enable_whz:=$WF &
echo "  PID=$! YOLO=$YF WHZ=$WF"
sleep 10

# [5] Verify
echo '[5/5] 验证...'
source /opt/ros/foxy/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0
echo '  Host nodes:'
ros2 node list 2>/dev/null | grep -v '/camera\|/visual\|/launch\|/transform\|/depth_relay\|/cuvslam'
echo '  /odom:'
timeout 4 ros2 topic hz /odom 2>&1 | head -3 || echo '  (waiting...)'
echo ''
echo '==================================='
echo ' 启动完成!'
echo ' 监控: bash ~/Desktop/monitor_cpu.sh'
echo '===================================