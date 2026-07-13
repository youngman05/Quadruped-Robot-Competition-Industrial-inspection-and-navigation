#!/bin/bash
# ==============================================
#  四足机器人竞赛 — 鲁棒一键启动
#  用法: bash scripts/start_competition.sh [--dog] [--cmd-vel-bridge] [--bridge-init-dog] [--yolo] [--whz] [--task-manager] [--auto-advance]
# ==============================================
# 注意: 不用 set -e，每个步骤自行容错

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1
LOGDIR="$HOME/Desktop/logs"
mkdir -p "$LOGDIR"
LOGFILE="$LOGDIR/competition_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOGFILE") 2>&1
echo "日志: $LOGFILE"
trap 'echo ""; echo "Ctrl+C → 清理..."; bash scripts/stop_all.sh' INT TERM

# ── 参数解析 ──────────────────────────────
ENABLE_YOLO=false; ENABLE_WHZ=false; ENABLE_DOG=false; ENABLE_CMD_VEL_BRIDGE=false; ENABLE_CMD_VEL_BRIDGE_INIT=false
ENABLE_TASK_MANAGER=false; AUTO_ADVANCE=false; DO_STAND=false
for arg in "$@"; do
    case $arg in
        --yolo)  ENABLE_YOLO=true ;;
        --whz)   ENABLE_WHZ=true ;;
        --dog)   ENABLE_DOG=true ;;
        --cmd-vel-bridge) ENABLE_CMD_VEL_BRIDGE=true ;;
        --bridge-init-dog|--init-dog) ENABLE_CMD_VEL_BRIDGE_INIT=true ;;
        --task-manager|--mission) ENABLE_TASK_MANAGER=true ;;
        --auto-advance) ENABLE_TASK_MANAGER=true; AUTO_ADVANCE=true ;;
        --stand) DO_STAND=true ;;   # force stand toggle (dog lying down)
    esac
done

echo ''
echo '==================================='
echo ' 四足机器人竞赛系统 v2 — 鲁棒启动'
echo '==================================='
echo " DOG=$ENABLE_DOG  CMD_VEL_BRIDGE=$ENABLE_CMD_VEL_BRIDGE  BRIDGE_INIT_DOG=$ENABLE_CMD_VEL_BRIDGE_INIT  YOLO=$ENABLE_YOLO  WHZ=$ENABLE_WHZ  TASK_MANAGER=$ENABLE_TASK_MANAGER  AUTO_ADVANCE=$AUTO_ADVANCE"

CUVSLAM_MOUNT_MODE="${CUVSLAM_MOUNT_MODE:-bench}"
CUVSLAM_PROFILE="${CUVSLAM_PROFILE:-planar_60fps}"
FINAL_BRIDGE_CAMERA_WORLD_REBASE="${FINAL_BRIDGE_CAMERA_WORLD_REBASE:-base_start}"

# ═══════════════════════════════════════════
# [0] 清理旧进程
# ═══════════════════════════════════════════
echo ''
echo '[0/6] 清理旧进程...'
bash scripts/stop_all.sh 2>&1 | tail -3
sleep 1

# ═══════════════════════════════════════════
# [1] Docker cuVSLAM
# ═══════════════════════════════════════════
echo ''
echo '[1/6] Docker cuVSLAM...'
CN=$(docker ps --format '{{.Names}}' 2>/dev/null | grep cuvslam || true)
if [ -z "$CN" ]; then
    echo "  启动 Docker (需要 ~90s)..."
    PROJECT_DIR="$PROJECT_ROOT" \
    CUVSLAM_MOUNT_MODE="$CUVSLAM_MOUNT_MODE" CUVSLAM_PROFILE="$CUVSLAM_PROFILE" \
      CUVSLAM_PUBLISH_ODOM_TO_BASE_TF=false CUVSLAM_PUBLISH_MAP_TO_ODOM_TF=false \
      bash scripts/start_cuvslam_rviz_gui.sh --no-rviz > /tmp/cuvslam_start.log 2>&1 &
    # 轮询等待 Docker 容器出现 + cuVSLAM 节点起来
    for i in $(seq 1 60); do
        sleep 3
        CN=$(docker ps --format '{{.Names}}' 2>/dev/null | grep cuvslam || true)
        if [ -n "$CN" ]; then break; fi
        echo -n "."
    done
    if [ -z "$CN" ]; then
        echo " ❌ Docker 启动超时"
        exit 1
    fi
    echo " Docker 容器已启动，等待 cuVSLAM 初始化..."
    # 等待视觉 SLAM 开始追踪
    for i in $(seq 1 30); do
        sleep 2
        if docker exec $CN bash -c 'source /opt/ros/humble/setup.bash && ros2 topic echo /visual_slam/tracking/odometry --once 2>/dev/null' | grep -q stamp; then
            echo " cuVSLAM 追踪中"
            break
        fi
        echo -n "."
    done
else
    echo "  Docker 已在运行: $CN"
fi
# 杀掉高CPU的 loop_metrics
docker exec $CN pkill -f loop_metrics_recorder 2>/dev/null && echo "  loop_metrics killed" || true

# ═══════════════════════════════════════════
# [2] 中继 (Camera + Depth)
# ═══════════════════════════════════════════
echo ''
echo '[2/6] 中继...'
docker cp scripts/camera_relay_docker.py $CN:/tmp/ 2>/dev/null || true
docker cp scripts/depth_relay_docker.py $CN:/tmp/ 2>/dev/null || true
docker exec $CN pkill -f camera_relay 2>/dev/null || true
docker exec $CN pkill -f depth_relay  2>/dev/null || true
sleep 1

# 启动 camera relay
docker exec -d $CN bash -c \
  "source /opt/ros/humble/setup.bash && \
   source /workspaces/isaac_ros-dev/install/setup.bash && \
   mkdir -p /workspaces/isaac_ros-dev/camera_frames && \
   python3 /tmp/camera_relay_docker.py > /tmp/cam.log 2>&1"
# 等待 camera relay 开始写入
for i in $(seq 1 10); do
    sleep 1
    FRAMES=$(docker exec $CN bash -c 'cat /tmp/cam.log 2>/dev/null' | grep -c 'Saved' || true)
    if [ "$FRAMES" -gt 0 ]; then break; fi
done
echo "  Camera: $(docker exec $CN tail -1 /tmp/cam.log 2>/dev/null || echo 'OK')"

# 启动 depth relay
docker exec -d $CN bash -c \
  "source /opt/ros/humble/setup.bash && \
   source /workspaces/isaac_ros-dev/install/setup.bash && \
   python3 /tmp/depth_relay_docker.py > /tmp/dep.log 2>&1"
for i in $(seq 1 10); do
    sleep 1
    FRAMES=$(docker exec $CN bash -c 'cat /tmp/dep.log 2>/dev/null' | grep -c 'Depth' || true)
    if [ "$FRAMES" -gt 0 ]; then break; fi
done
echo "  Depth:  $(docker exec $CN tail -1 /tmp/dep.log 2>/dev/null || echo 'OK')"

# ═══════════════════════════════════════════
# [3] UDP 桥接 (odom)
# ═══════════════════════════════════════════
echo ''
echo '[3/6] UDP 桥接...'
# 清理旧桥接
pkill -9 -f final_bridge 2>/dev/null || true
docker exec $CN pkill -f udp_exporter 2>/dev/null || true
sleep 1

source /opt/ros/foxy/setup.bash 2>/dev/null || true
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0
if [ -f "$PROJECT_ROOT/configs/ros/fastrtps_no_shm.xml" ]; then
    export FASTRTPS_DEFAULT_PROFILES_FILE="$PROJECT_ROOT/configs/ros/fastrtps_no_shm.xml"
fi
export PYTHONPATH=/opt/ros/foxy/lib/python3.8/site-packages

nohup python3 scripts/final_bridge.py \
  --camera-world-rebase "$FINAL_BRIDGE_CAMERA_WORLD_REBASE" \
  --planarize-output > /tmp/fb.log 2>&1 &
BRIDGE_PID=$!
# 等待第一个 odom 消息
for i in $(seq 1 30); do
    sleep 1
    if grep -q 'bridged' /tmp/fb.log 2>/dev/null; then
        echo "  Bridge 就绪 (PID=$BRIDGE_PID)"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "  ⚠ Bridge 等待超时 (检查 cuVSLAM)"
    fi
done

# ═══════════════════════════════════════════
# [4] Dog init + transfer driver
# ═══════════════════════════════════════════
if $ENABLE_DOG; then
    echo ''
    echo '[4/6] 狗初始化...'
    # 检查网络
    if ! ping -c 1 -W 1 192.168.1.120 > /dev/null 2>&1; then
        echo "  ⚠ 狗网络不通 (192.168.1.120) — 继续但狗不会动"
    else
        if $ENABLE_CMD_VEL_BRIDGE; then
            if $ENABLE_CMD_VEL_BRIDGE_INIT; then
                echo "  使用备用 cmd_vel_bridge，并显式初始化狗 (auto + motion mode)"
            else
                echo "  使用备用 cmd_vel_bridge；不自动初始化狗，避免改变当前站立/趴下状态"
            fi
        elif [ -f Lite3_ROS-ros2-foxy/install/setup.bash ]; then
            # Dedicated driver node: subscribe /cmd_vel, then talk to Lite3.
            # Navigator publishes /cmd_vel only by default and no longer bypasses this node.
            source Lite3_ROS-ros2-foxy/install/setup.bash
            nohup ros2 launch transfer transfer_launch.py > /tmp/transfer.log 2>&1 &
            TRANSFER_PID=$!
            sleep 2
            if ros2 node list 2>/dev/null | grep -q motion_sender; then
                echo "  transfer driver ready: /cmd_vel -> Lite3 (PID=$TRANSFER_PID)"
            else
                echo "  WARN: transfer driver not visible yet, log: /tmp/transfer.log"
            fi
        else
            echo "  WARN: Lite3 transfer workspace is not built; /cmd_vel will not reach the dog unless --cmd-vel-bridge is used"
        fi
    fi
fi

# ═══════════════════════════════════════════
# [5] 比赛系统
# ═══════════════════════════════════════════
echo ''
echo '[5/6] 启动比赛...'
source install/setup.bash 2>/dev/null || { echo "  ⚠ 需要先 colcon build"; exit 1; }

YF=false; WF=false
$ENABLE_YOLO && YF=true
$ENABLE_WHZ  && WF=true
ros2 launch quadruped_robot_competition competition.launch.py \
  enable_task_manager:=$ENABLE_TASK_MANAGER enable_navigation:=true \
  enable_cmd_vel_bridge:=$ENABLE_CMD_VEL_BRIDGE \
  cmd_vel_bridge_init_dog:=$ENABLE_CMD_VEL_BRIDGE_INIT \
  enable_depth_publisher:=false \
  enable_yolo:=$YF enable_whz:=$WF \
  auto_advance:=$AUTO_ADVANCE > /tmp/competition.log 2>&1 &
COMP_PID=$!
echo "  Launch PID=$COMP_PID YOLO=$YF WHZ=$WF TASK_MANAGER=$ENABLE_TASK_MANAGER AUTO_ADVANCE=$AUTO_ADVANCE"
if $ENABLE_TASK_MANAGER; then
    # 等待 task_manager 节点出现
    for i in $(seq 1 15); do
        sleep 1
        if ros2 node list 2>/dev/null | grep -q task_manager; then
            echo "  task_manager 就绪"
            break
        fi
    done
fi

# ═══════════════════════════════════════════
# [6] 验证
# ═══════════════════════════════════════════
echo ''
echo '[6/6] 验证...'
sleep 3
echo "  === 节点 ==="
ros2 node list 2>/dev/null | grep -v '/camera\|/visual\|/launch\|/transform\|/docker' || echo "  (无)"
echo "  === Odom ==="
python3 -c "
import json
try:
    d = json.load(open('/tmp/odom_latest.json'))
    print(f'  x={d[\"x\"]:.2f} y={d[\"y\"]:.2f}')
except: print('  odom 文件尚未就绪')
" 2>/dev/null

echo "  === 狗状态 ==="
if $ENABLE_DOG; then
    tail -1 /tmp/lite3_init.log 2>/dev/null || echo "  (无)"
    ping -c 1 -W 1 192.168.1.120 > /dev/null 2>&1 && echo "  狗网络: ✅" || echo "  狗网络: ❌"
fi

echo "  === CPU TOP5 ==="
ps -eo pcpu,pid,comm --sort=-pcpu 2>/dev/null | head -6 | tail -5

echo ''
echo '==================================='
echo ' ✅ 启动完成!'
echo " 日志: $LOGFILE"
echo ' 停止: bash scripts/stop_all.sh'
echo '==================================='
