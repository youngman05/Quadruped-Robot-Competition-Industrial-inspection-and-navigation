#!/bin/bash
# ==============================================
#  停止所有比赛进程 — 可靠的强制清理
# ==============================================
echo "=== 停止比赛进程 ==="

# Ask both the precision lease and the final output to stop before any SIGKILL.
if command -v ros2 >/dev/null 2>&1 && command -v timeout >/dev/null 2>&1; then
    timeout 0.5s ros2 topic pub --rate 20 /cmd_vel_precision geometry_msgs/msg/Twist '{}' \
        >/dev/null 2>&1 || true
    timeout 0.3s ros2 topic pub --rate 20 /cmd_vel geometry_msgs/msg/Twist '{}' \
        >/dev/null 2>&1 || true
fi

# 1. 先杀 ros2 launch（防止它复活子进程）—— 最关键！
echo "[1] 停止 launch..."
pkill -9 -f "ros2 launch"          2>/dev/null
pkill -9 -f "competition.launch"   2>/dev/null
pkill -9 -f "transfer_launch"      2>/dev/null
sleep 2

# 2. 杀掉所有比赛节点
echo "[2] 停止比赛节点..."
for name in task_manager initial_pose_publisher depth_publisher \
            gauge_status_publisher inspection_node whz_standalone \
            color_image_publisher yolo_detect_publisher \
            static_transform_publisher test_logger cmd_vel_arbiter cmd_vel_bridge \
            depth_relay_publisher depth_safety_gate \
            cone_scan_udp_bridge cone_scan_safety_gate \
            apriltag_udp_bridge yolo_udp_bridge arm_motion_node \
            map_server planner_server controller_server bt_navigator \
            recoveries_server lifecycle_manager; do
    pkill -9 -f "$name" 2>/dev/null
done
sleep 1

# 3. 杀掉 transfer SDK 和狗初始化
echo "[3] 停止 SDK / 狗..."
for name in jetson2motion jetson2app sensor_checker lite3_init dog_init; do
    pkill -9 -f "$name" 2>/dev/null
done
sleep 1

# 4. 杀掉桥接进程
echo "[4] 停止桥接..."
pkill -9 -f "final_bridge"         2>/dev/null
pkill -9 -f "cuvslam_odometry_udp_exporter" 2>/dev/null
pkill -9 -f "_ros2_daemon"         2>/dev/null
sleep 1

# 5. 清理 Docker 内中继（不碰 cuVSLAM/realsense）
echo "[5] 停止 Docker 中继..."
CN=$(docker ps --format '{{.Names}}' 2>/dev/null | grep cuvslam | head -1)
if [ -n "$CN" ]; then
    docker exec "$CN" pkill -f camera_relay       2>/dev/null || true
    docker exec "$CN" pkill -f depth_relay        2>/dev/null || true
    docker exec "$CN" pkill -f '[d]455_apriltag_pose_node.py' 2>/dev/null || true
    docker exec "$CN" pkill -f '[d]455_yolo_3d_node.py' 2>/dev/null || true
    docker exec "$CN" pkill -f '[c]uvslam_odometry_udp_exporter.py' 2>/dev/null || true
    docker exec "$CN" pkill -f loop_metrics_recorder 2>/dev/null || true
    docker exec "$CN" rm -f /tmp/apriltag_pose.log /tmp/yolo_3d.log 2>/dev/null || true
fi

rm -f -- /tmp/apriltag_bridge_probe.txt /tmp/yolo_bridge_probe.txt 2>/dev/null || true

echo ""
echo "=== 剩余进程 (TOP5 CPU) ==="
ps -eo pcpu,pid,comm --sort=-pcpu 2>/dev/null | head -6 | tail -5 || true
echo "=== 完成 ==="
