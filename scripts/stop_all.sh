#!/bin/bash
# 停止所有比赛进程（不碰 Docker cuVSLAM）
echo "停止比赛进程..."

# Host 进程
pkill -9 -f competition.launch     2>/dev/null && echo "  killed: competition.launch" || true
pkill -9 -f task_manager           2>/dev/null && echo "  killed: task_manager" || true
pkill -9 -f final_bridge           2>/dev/null && echo "  killed: final_bridge" || true
pkill -9 -f gauge_status_publisher 2>/dev/null && echo "  killed: gauge_status" || true
pkill -9 -f yolo_detect_publisher  2>/dev/null && echo "  killed: yolo_detect" || true
pkill -9 -f color_image_publisher  2>/dev/null && echo "  killed: color_publisher" || true
pkill -9 -f depth_publisher        2>/dev/null && echo "  killed: depth_publisher" || true
pkill -9 -f initial_pose_publisher 2>/dev/null && echo "  killed: initial_pose" || true
pkill -9 -f inspection_node        2>/dev/null && echo "  killed: inspection_node" || true
pkill -9 -f whz_standalone         2>/dev/null && echo "  killed: whz_standalone" || true
pkill -9 -f _ros2_daemon           2>/dev/null && echo "  killed: ros2_daemon" || true
pkill -9 -f test_logger            2>/dev/null && echo "  killed: test_logger" || true
pkill -9 -f static_transform_publisher 2>/dev/null && echo "  killed: static_tf" || true

# Lite3 Transfer (dog SDK)
pkill -9 -f jetson2motion          2>/dev/null && echo "  killed: jetson2motion" || true
pkill -9 -f jetson2app             2>/dev/null && echo "  killed: jetson2app" || true
pkill -9 -f sensor_checker         2>/dev/null && echo "  killed: sensor_checker" || true
pkill -9 -f transfer_launch        2>/dev/null && echo "  killed: transfer_launch" || true

# Docker 内 relay（不碰 cuVSLAM 和 realsense）
CN=$(docker ps --format '{{.Names}}' 2>/dev/null | grep cuvslam | head -1)
if [ -n "$CN" ]; then
    docker exec $CN pkill -f camera_relay  2>/dev/null && echo "  killed: camera_relay (docker)" || true
    docker exec $CN pkill -f depth_relay   2>/dev/null && echo "  killed: depth_relay (docker)" || true
    docker exec $CN pkill -f udp_exporter  2>/dev/null && echo "  killed: udp_exporter (docker)" || true
    docker exec $CN pkill -f loop_metrics_recorder 2>/dev/null && echo "  killed: loop_metrics (docker)" || true
fi

sleep 1
echo ""
echo "剩余进程:"
ps aux --sort=-%cpu | head -6 | grep -v grep
