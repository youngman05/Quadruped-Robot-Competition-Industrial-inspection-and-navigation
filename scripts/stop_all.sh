#!/bin/bash
# =========================================
#  停止所有比赛进程（不碰 Docker cuVSLAM）
# =========================================
echo "停止比赛进程..."

# Host 进程
pkill -9 -f competition.launch     2>/dev/null && echo "  ✓ competition.launch" || true
pkill -9 -f task_manager           2>/dev/null && echo "  ✓ task_manager" || true
pkill -9 -f final_bridge           2>/dev/null && echo "  ✓ final_bridge" || true
pkill -9 -f gauge_status_publisher 2>/dev/null && echo "  ✓ gauge_status" || true
pkill -9 -f yolo_detect_publisher  2>/dev/null && echo "  ✓ yolo_detect" || true
pkill -9 -f color_image_publisher  2>/dev/null && echo "  ✓ color_publisher" || true
pkill -9 -f depth_publisher        2>/dev/null && echo "  ✓ depth_publisher" || true
pkill -9 -f initial_pose_publisher 2>/dev/null && echo "  ✓ initial_pose" || true
pkill -9 -f inspection_node        2>/dev/null && echo "  ✓ inspection_node" || true
pkill -9 -f whz_standalone         2>/dev/null && echo "  ✓ whz_standalone" || true
pkill -9 -f _ros2_daemon           2>/dev/null && echo "  ✓ ros2_daemon" || true
pkill -9 -f test_logger            2>/dev/null && echo "  ✓ test_logger" || true
pkill -9 -f static_transform_publisher 2>/dev/null && echo "  ✓ static_tf" || true

# Docker 内 relay 脚本（不碰 cuVSLAM 和 realsense）
CN=$(docker ps --format '{{.Names}}' 2>/dev/null | grep cuvslam | head -1)
if [ -n "$CN" ]; then
    docker exec $CN pkill -f loop_metrics_recorder 2>/dev/null && echo "  ✓ loop_metrics (docker)" || true
    docker exec $CN pkill -f camera_relay  2>/dev/null && echo "  ✓ camera_relay (docker)" || true
    docker exec $CN pkill -f depth_relay   2>/dev/null && echo "  ✓ depth_relay (docker)" || true
    docker exec $CN pkill -f udp_exporter  2>/dev/null && echo "  ✓ udp_exporter (docker)" || true
fi

sleep 1
echo ""
echo "===== 剩余进程 ====="
ps aux --sort=-%cpu | head -6 | grep -v grep
