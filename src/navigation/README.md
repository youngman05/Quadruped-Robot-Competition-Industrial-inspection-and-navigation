# Navigation

导航模块 — 路径规划与运动控制。

## 方案

- **框架**：ROS2 Nav2
- **全局地图**：预生成 PGM 栅格地图（从 `navi/map/navi_map_data.py` 生成）
- **定位**：cuVSLAM 视觉里程计（Docker 容器内运行）
- **局部避障**：D455 深度点云 → local_costmap 障碍物层
- **约束**：比赛禁止激光雷达，使用纯视觉方案

## 坐标帧链

```text
map → odom → base_link → camera_link → ...
 ↑       ↑
 |       └── cuVSLAM 发布 (连续)
 └── 初始位姿设置 (固定变换)
```

## 待实现

- [ ] `generate_nav2_map.py` — PGM 地图生成脚本
- [ ] `initial_pose_publisher.py` — 初始位姿设置节点
- [ ] `launch/navigation.launch.py` — 导航启动文件
- [ ] cuVSLAM odometry bridge — 格式转换节点
- [ ] Nav2 参数调优

详见父级 [navi/map/README.md](../../navi/map/README.md) 和 [configs/navigation/README.md](../../configs/navigation/README.md)。
