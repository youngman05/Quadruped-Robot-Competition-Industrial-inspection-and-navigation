# Navigation Configs

Nav2 导航参数配置。

## 文件

| 文件 | 用途 |
|------|------|
| `nav2_params.yaml` | Nav2 全局/局部代价地图、规划器、控制器参数 |

## 关键参数

- `global_costmap`：静态层加载 PGM 地图，分辨率 0.025m
- `local_costmap`：D455 深度点云障碍物层，滚动窗口 2m × 2m
- `planner`：NavFn 全局路径规划
- `controller`：RegulatedPurePursuit 路径跟踪（适合四足）
- **不使用 AMCL**：定位由 cuVSLAM 提供

## 使用

```bash
# map_server 加载 PGM 地图
ros2 run nav2_map_server map_server \
  --ros-args -p yaml_filename:=navi/map/competition_field.yaml

# Nav2 导航栈
ros2 launch nav2_bringup navigation_launch.py \
  params_file:=configs/navigation/nav2_params.yaml
```
