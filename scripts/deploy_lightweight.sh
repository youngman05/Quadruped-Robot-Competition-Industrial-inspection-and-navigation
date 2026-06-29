#!/bin/bash
# 轻量导航部署 — Jetson 上运行
# 用法: bash deploy_lightweight.sh <项目目录>
# 例:   bash deploy_lightweight.sh ~/quadruped-robot-competition
set -e

PROJ="${1:-$HOME/quadruped-robot-competition}"
echo "部署目录: $PROJ"

# ── 1. 清理旧 Nav2 文件 ───────────────────────
echo "[1] 清理 Nav2 残留..."
rm -rf "$PROJ/configs/navigation"
rm -f  "$PROJ/launch/navigation.launch.py"
rm -f  "$PROJ/src/nodes/navigation/navigation_client.py"
rm -f  "$PROJ/src/nodes/navigation/cuvslam_bridge.py"
rm -f  "$PROJ/navi/navigation_client.py"
rm -f  "$PROJ/navi/cuvslam_bridge.py"
rm -f  "$PROJ/navi/depth_publisher.py"
rm -f  "$PROJ/navi/initial_pose_publisher.py"
rm -f  "$PROJ/navi/map/competition_field.pgm"
rm -f  "$PROJ/navi/map/competition_field.yaml"
rm -f  "$PROJ/navi/map/competition_field_phase1.pgm"
rm -f  "$PROJ/navi/map/competition_field_phase1.yaml"
rm -f  "$PROJ/navi/map/competition_field_phase2.pgm"
rm -f  "$PROJ/navi/map/competition_field_phase2.yaml"
rm -f  "$PROJ/scripts/tools/install_nav2_deps.sh"
echo "  清理完成"

# ── 2. 验证新文件已拷贝 ───────────────────────
echo "[2] 检查新导航模块..."
NEW_FILES=(
    "$PROJ/src/navigation/__init__.py"
    "$PROJ/src/navigation/map_grid.py"
    "$PROJ/src/navigation/astar_planner.py"
    "$PROJ/src/navigation/pure_pursuit.py"
    "$PROJ/src/navigation/local_obstacle.py"
    "$PROJ/src/navigation/navigator.py"
    "$PROJ/src/nodes/navigation/lightweight_navigator_node.py"
    "$PROJ/setup.cfg"
)
MISSING=0
for f in "${NEW_FILES[@]}"; do
    if [ ! -f "$f" ]; then
        echo "  ❌ 缺失: $f"
        MISSING=1
    else
        echo "  ✅ $f"
    fi
done
if [ $MISSING -eq 1 ]; then
    echo ""
    echo "请先将 Windows 上的新文件拷贝到 Jetson:"
    echo "  src/navigation/  →  $PROJ/src/navigation/"
    echo "  src/nodes/navigation/lightweight_navigator_node.py"
    echo "  setup.cfg"
    echo "  以及其他修改过的文件 (task_manager, launch, setup.py 等)"
    exit 1
fi

# ── 3. colcon build ──────────────────────────
echo "[3] colcon build..."
cd "$PROJ"
source /opt/ros/foxy/setup.bash
colcon build --packages-select quadruped_robot_competition --symlink-install 2>&1 | tail -5
echo "  构建完成"

# ── 4. 验证模块可导入 ─────────────────────────
echo "[4] 验证 Python 导入..."
source install/setup.bash
python3 -c "
import sys; sys.path.insert(0, 'src')
from navigation.map_grid import build_grid
from navigation.astar_planner import AStarPlanner
from navigation.pure_pursuit import PurePursuitController
from navigation.local_obstacle import LocalObstacleDetector
from navigation.navigator import Navigator
print('  全部模块导入成功')

grid = build_grid('phase1')
print(f'  Grid: {grid.shape[0]}x{grid.shape[1]}, walls={(grid==0).sum()}')
" || { echo "  ❌ 导入失败"; exit 1; }

echo ""
echo "✅ 部署完成"
echo ""
echo "下一步: bash scripts/start_competition_lightweight.sh"
