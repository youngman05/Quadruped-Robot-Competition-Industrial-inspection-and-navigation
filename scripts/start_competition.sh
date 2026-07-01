#!/bin/bash
# =========================================
#  四足机器人竞赛 — 一键启动脚本
# =========================================
set -e
cd ~/quadruped-robot-competition

# Log to Desktop/logs with timestamp
LOGDIR="$HOME/Desktop/logs"
mkdir -p "$LOGDIR"
LOGFILE="$LOGDIR/competition_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOGFILE") 2>&1
echo "日志: $LOGFILE"

# Ctrl+C → auto cleanup
trap 'echo ""; echo "Ctrl+C 触发清理..."; bash scripts/stop_all.sh' INT TERM

ENABLE_YOLO=true; ENABLE_WHZ=false; ENABLE_LOG=false
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

# [0] Kill host zombies only (do NOT touch Docker processes)
echo '[0/5] 清理旧进程...'
pkill -9 -f color_image_publisher 2>/dev/null || true
pkill -9 -f inspection_node 2>/dev/null || true
pkill -9 -f task_manager 2>/dev/null || true
pkill -9 -f gauge_status_publisher 2>/dev/null || true
pkill -9 -f depth_publisher 2>/dev/null || true
pkill -9 -f initial_pose_publisher 2>/dev/null || true
sleep 2 && echo '  干净'

# [1] Docker
echo '[1/5] Docker...'
CN=$(docker ps --format '{{.Names}}' 2>/dev/null | grep cuvslam || true)
if [ -z "$CN" ]; then
    CUVSLAM_MOUNT_MODE=robot CUVSLAM_PROFILE=planar_60fps \
      CUVSLAM_PUBLISH_ODOM_TO_BASE_TF=false CUVSLAM_PUBLISH_MAP_TO_ODOM_TF=false \
      bash scripts/start_cuvslam_rviz_gui.sh --no-rviz > /tmp/cuvslam.log 2>&1 &
    echo '  等 100 秒 GPU 预热...'; sleep 100
    CN=$(docker ps --format '{{.Names}}' | grep cuvslam)
fi
echo "  Docker: $CN"

# Kill unnecessary Docker processes (loop_metrics_recorder eats ~53% CPU)
docker exec $CN pkill -f loop_metrics_recorder 2>/dev/null && echo "  ⚡ loop_metrics killed" || true

# [2] Relays (only restart relay scripts, do NOT kill cuVSLAM/realsense)
echo '[2/5] 中继...'
docker cp scripts/camera_relay_docker.py $CN:/tmp/ 2>/dev/null || true
docker cp scripts/depth_relay_docker.py $CN:/tmp/ 2>/dev/null || true
docker exec $CN pkill -f camera_relay 2>/dev/null || true
docker exec $CN pkill -f depth_relay 2>/dev/null || true
sleep 1
docker exec -d $CN bash -c \
  "source /opt/ros/humble/setup.bash && \
   source /workspaces/isaac_ros-dev/install/setup.bash && \
   mkdir -p /workspaces/isaac_ros-dev/camera_frames && \
   python3 /tmp/camera_relay_docker.py > /tmp/cam.log 2>&1"
sleep 3 && echo "  Camera: $(docker exec $CN tail -1 /tmp/cam.log 2>/dev/null || echo OK)"
docker exec -d $CN bash -c \
  "source /opt/ros/humble/setup.bash && \
   source /workspaces/isaac_ros-dev/install/setup.bash && \
   python3 /tmp/depth_relay_docker.py > /tmp/dep.log 2>&1"
sleep 3 && echo "  Depth: $(docker exec $CN tail -1 /tmp/dep.log 2>/dev/null || echo OK)"

# [3] Bridge — use fix_bridge.sh (handles exporter + bridge properly)
echo '[3/5] UDP 桥接...'
bash scripts/fix_bridge.sh

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
ros2 launch quadruped_robot_competition competition.launch.py \
  enable_task_manager:=true enable_navigation:=true \
  enable_yolo:=$YF enable_whz:=$WF &
echo "  PID=$! YOLO=$YF WHZ=$WF"
sleep 10

# [5] Verify
echo '[5/5] 验证...'
source /opt/ros/foxy/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0
echo '  Host nodes:'
ros2 node list 2>/dev/null | grep -v '/camera\|/visual\|/launch\|/transform\|/depth_relay\|/cuvslam\|/camera_relay'
echo '  /odom:'
python3 scripts/probe_odom_best_effort.py --duration 3 --first-timeout 2 --no-color 2>&1 | head -10
echo ''
echo '  CPU TOP5:'
ps -eo pcpu,args --sort=-pcpu | head -6 | tail -5 | sed 's/^/    /'
echo ''
echo '==================================='
echo ' 启动完成! Ctrl+C 自动清场'
echo ' 监控: bash ~/Desktop/monitor_cpu.sh'
echo '==================================='
