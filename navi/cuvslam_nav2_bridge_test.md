# cuVSLAM 60Hz、Bridge、Nvblox 与 Nav2 测试说明

本文档用于在 Jetson 上验证：

- ROS2 Humble Docker 中的 cuVSLAM 是否能被 Foxy 主环境看到；
- `cuvslam_bridge.py` 是否能把 cuVSLAM odometry 转成 Nav2 常用的 `/odom`；
- Nav2 是否能收到 `/odom` 和 TF；
- 后续如何接 nvblox 到 Nav2 costmap。

当前推荐的 cuVSLAM profile 是 `planar_60fps`。不要再优先使用 `official_like` 或 `start_official_cuvslam_realsense.sh` 做主线测试。

## 0. 当前结论

先测 `cuvslam_bridge.py`，再测 Nav2，最后再接 nvblox。

原因：

- cuVSLAM Docker 当前已经能在 60Hz 下输出较好的 `/visual_slam/vis/slam_odometry` 闭环结果。
- `cuvslam_bridge.py` 的作用是把 Docker/Humble 里的 `/visual_slam/tracking/odometry` 转成 Foxy/Nav2 侧的 `/odom` 和 `odom -> base_link` TF。
- nvblox 不是由 `cuvslam_bridge.py` 桥接的。nvblox 到 Nav2 需要 `nvblox_nav2` costmap plugin，或者另写 `nvblox_msgs -> nav_msgs/OccupancyGrid` / `PointCloud2` 转换节点。
- 现在相机支架还没定型，所以 `base_link -> camera_link` 可以先用临时外参，后面再改。

临时外参建议先用：

```text
base_link -> camera_link
x = 0.20 m
y = 0.00 m
z = 0.45 m
roll  = 0.0 rad
pitch = -0.523599 rad
yaw   = 0.0 rad
```

这只是占位值，不代表最终机器人定位精度。

## 1. 推荐启动脚本和参数

使用这个脚本：

```bash
bash scripts/start_cuvslam_rviz_gui.sh
```

使用这个 profile：

```bash
CUVSLAM_PROFILE=planar_60fps
```

不要用这些作为主线：

```bash
scripts/start_official_cuvslam_realsense.sh
CUVSLAM_PROFILE=official_like
CUVSLAM_PROFILE=planar_90fps
```

`official_like` 已经测出明显更差；`planar_90fps` 只作为对照，不作为当前默认。

## 2. 终端 1：启动 Docker cuVSLAM 60Hz

在 Jetson host 上：

```bash
cd ~/quadruped-robot-competition

CUVSLAM_MOUNT_MODE=robot \
CUVSLAM_PROFILE=planar_60fps \
CUVSLAM_BASE_TO_CAMERA_X=0.20 \
CUVSLAM_BASE_TO_CAMERA_Y=0.00 \
CUVSLAM_BASE_TO_CAMERA_Z=0.45 \
CUVSLAM_BASE_TO_CAMERA_ROLL=0.0 \
CUVSLAM_BASE_TO_CAMERA_PITCH=-0.523599 \
CUVSLAM_BASE_TO_CAMERA_YAW=0.0 \
CUVSLAM_PUBLISH_ODOM_TO_BASE_TF=false \
CUVSLAM_PUBLISH_MAP_TO_ODOM_TF=false \
bash scripts/start_cuvslam_rviz_gui.sh --no-rviz
```

这里故意设置：

```bash
CUVSLAM_PUBLISH_ODOM_TO_BASE_TF=false
CUVSLAM_PUBLISH_MAP_TO_ODOM_TF=false
```

目的是先让 Foxy 侧的 `cuvslam_bridge.py` 单独负责发布 `odom -> base_link`，避免 Docker cuVSLAM 和 bridge 同时发布同一条 TF。

如果只是复测 cuVSLAM 闭环，不测 bridge，可以不加这两个参数。

启动成功后，脚本应等待到：

```text
/visual_slam/status
/visual_slam/tracking/odometry
```

并在日志目录下生成：

```text
~/cuvslam_lite3_logs/<timestamp>/loop_metrics_latest.txt
```

## 3. 终端 2：确认 Foxy 能看到 Docker/Humble topic

另开 Jetson host 终端：

```bash
source /opt/ros/foxy/setup.bash
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

ros2 daemon stop
ros2 topic list | grep visual_slam
ros2 topic info /visual_slam/tracking/odometry
ros2 topic echo --once /visual_slam/tracking/odometry
```

成功标准：

```text
/visual_slam/tracking/odometry
```

能在 Foxy host 上被看到，并且 `ros2 topic echo --once` 能打印 `nav_msgs/msg/Odometry`。

如果看不到，优先检查：

- Docker 启动命令是否用了 `--network host`；
- host 和 Docker 的 `ROS_DOMAIN_ID` 是否都是 `0`；
- host 和 Docker 的 `RMW_IMPLEMENTATION` 是否都是 `rmw_fastrtps_cpp`；
- D455/cuVSLAM 是否真的已经在终端 1 里跑起来。

## 4. 终端 3：启动 cuVSLAM bridge

`origin/main` 里的 bridge 路径是：

```text
src/nodes/navigation/cuvslam_bridge.py
```

当前仓库如果还没有通过 ROS2 package 正式安装，最稳的启动方式是直接用 Python：

```bash
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export PYTHONPATH=$PWD/src:$PYTHONPATH

python3 src/nodes/navigation/cuvslam_bridge.py \
  --ros-args \
  -p slam_odom_topic:=/visual_slam/tracking/odometry \
  -p slam_status_topic:=/visual_slam/status \
  -p odom_frame:=odom \
  -p base_frame:=base_link \
  -p camera_frame:=camera_link
```

如果后面已经把包安装成 ROS2 entry point，也可以尝试：

```bash
ros2 run quadruped_robot_competition cuvslam_bridge
```

但当前更推荐直接跑 Python 文件，因为 GitHub 当前版本没有看到标准 `package.xml`，`ros2 run` 不一定能发现这个包。

## 5. 终端 4：验证 bridge 输出

另开 Foxy host 终端：

```bash
source /opt/ros/foxy/setup.bash
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

ros2 topic hz /odom
ros2 topic echo --once /odom
ros2 run tf2_ros tf2_echo odom base_link
```

成功标准：

- `/odom` 有频率；
- `/odom.header.frame_id` 是 `odom`；
- `/odom.child_frame_id` 是 `base_link`；
- `tf2_echo odom base_link` 能持续输出 transform。

`/slam/status` 暂时不是主验收项，因为 Isaac ROS Visual SLAM 的 `/visual_slam/status` 在实际环境里可能不是 `std_msgs/String`。如果类型不匹配，bridge 的 status 订阅会失败，但不影响先验收 odometry。

确认 status 类型：

```bash
ros2 topic info /visual_slam/status
```

如果不是 `std_msgs/msg/String`，后面需要改 `cuvslam_bridge.py` 的 status 订阅类型。

## 6. 给 Nav2 补一个临时 map -> odom

如果终端 1 里已经禁用了 `CUVSLAM_PUBLISH_MAP_TO_ODOM_TF`，而 Nav2 参数里 `global_frame` 还是 `map`，就需要先补一条临时静态 TF：

```bash
source /opt/ros/foxy/setup.bash
ros2 run tf2_ros static_transform_publisher 0 0 0 0 0 0 map odom
```

这只是接口验证用。后面正式导航时，`map -> odom` 应由定位系统统一负责，不能长期用假的 identity TF 混过关。

## 7. 启动 Nav2 做接收验证

先确认 Nav2 依赖已安装：

```bash
source /opt/ros/foxy/setup.bash
ros2 pkg list | grep -E 'nav2|navigation2'
```

如果用 GitHub `origin/main` 的 launch：

```bash
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

ros2 launch ./launch/navigation.launch.py \
  params_file:=configs/navigation/nav2_params.yaml \
  map_yaml:=navi/map/competition_field.yaml
```

注意：当前 `launch/navigation.launch.py` 会启动 `depth_publisher`，而 `depth_publisher` 会直接打开 D455。cuVSLAM Docker 也在使用 D455，所以全栈启动时可能出现相机抢占。

因此分两种情况：

- 只测 Nav2 能否收到 `/odom` 和 TF：优先只启动 bridge 和 Nav2 核心，暂时不要启动 `depth_publisher`。
- 要测深度障碍物：不要让 Foxy host 的 `depth_publisher` 和 Docker RealSense driver 同时打开相机，应让 Docker 里的同一个 RealSense driver 同时发布 cuVSLAM 和 depth，或者后面改 launch 增加一个开关禁用 host `depth_publisher`。

Nav2 接收成功后检查：

```bash
ros2 lifecycle nodes
ros2 topic list | grep -E 'odom|costmap|cmd_vel|plan'
ros2 topic echo --once /local_costmap/costmap
ros2 topic hz /local_costmap/costmap
```

安全原则：现阶段只看 `/cmd_vel`，不要把它接到 Lite3 实际底盘。

```bash
ros2 topic echo /cmd_vel
```

## 8. nvblox 到 Nav2 怎么接

这里要区分清楚：

```text
cuvslam_bridge.py 只负责 odometry/TF
nvblox_nav2 才负责 nvblox -> Nav2 costmap
```

理想链路：

```text
D455 depth image + camera_info
cuVSLAM odom + TF
        |
        v
nvblox
        |
        v
/nvblox_node/static_map_slice
        |
        v
Nav2 nvblox costmap layer
        |
        v
/local_costmap/costmap
```

关键问题：`nvblox_nav2` 是 Nav2 costmap 插件，必须和 Nav2 在同一个 ROS 发行版/ ABI 下编译和运行。

所以有两条路线：

### 路线 A：Nav2 也放到 Humble Docker

这是 nvblox 最顺的路线：

- cuVSLAM、RealSense、nvblox、Nav2 全在 Humble Docker；
- `nvblox_nav2` 插件直接加载；
- Foxy 只保留其他国赛任务节点，必要时再桥接任务指令/状态。

适合先验证 nvblox costmap 是否真的可用。

### 路线 B：Nav2 保持 Foxy host

这是当前比赛主环境路线，但多一步：

- Foxy Nav2 不能直接加载 Humble Docker 里的 `nvblox_nav2` 插件；
- 如果要 Foxy Nav2 使用 nvblox，需要：
  - 在 Foxy host 上编译兼容的 `nvblox_nav2`，或
  - 写一个转换节点，把 `/nvblox_node/static_map_slice` 转成 Foxy Nav2 可用的 `nav_msgs/OccupancyGrid` 或 `PointCloud2`。

当前 `cuvslam_bridge.py` 不做这件事。

## 9. nvblox 最小检查步骤

在 cuVSLAM Docker 容器里检查 nvblox 是否已安装：

```bash
docker ps
docker exec -it <cuvslam_container_name> bash

source /opt/ros/humble/setup.bash
source /workspaces/isaac_ros-dev/install/setup.bash

ros2 pkg list | grep nvblox
ros2 topic list | grep camera
```

当前 `start_cuvslam_rviz_gui.sh` 默认只启用 IR 双目和 IMU：

```text
enable_infra1=true
enable_infra2=true
enable_depth=false
```

所以 nvblox 所需的 depth topic 默认不存在。后面要接 nvblox，需要把同一个 Docker RealSense launch 改成同时发布：

```text
/camera/depth/image_rect_raw
/camera/depth/camera_info
```

检查命令：

```bash
ros2 topic hz /camera/depth/image_rect_raw
ros2 topic echo --once /camera/depth/camera_info
```

再启动 nvblox 后，检查：

```bash
ros2 topic list | grep nvblox
ros2 topic hz /nvblox_node/static_map_slice
ros2 topic echo --once /nvblox_node/static_map_slice
```

只有 `/nvblox_node/static_map_slice` 有输出，才进入 Nav2 costmap plugin 测试。

## 10. 成功验收表

按这个顺序打勾：

```text
[ ] Foxy host 能看到 /visual_slam/tracking/odometry
[ ] cuvslam_bridge.py 能输出 /odom
[ ] tf2_echo odom base_link 正常
[ ] Nav2 lifecycle 节点能进入 active
[ ] Nav2 能看到 /odom，并能发布 /local_costmap/costmap
[ ] Docker 内能发布 /camera/depth/image_rect_raw
[ ] nvblox 能发布 /nvblox_node/static_map_slice
[ ] Nav2 costmap 能接收 nvblox layer 或转换后的 costmap/pointcloud
[ ] /cmd_vel 只在终端观察，不接狗
```

## 11. 目前最可能需要改的地方

1. `cuvslam_bridge.py` 目前只是把 odometry 的 `child_frame_id` 改成 `base_link`，没有真正应用 `camera_link -> base_link` 外参矩阵。接口验证可以用，最终精度前需要修。
2. `/visual_slam/status` 的消息类型可能不是 `std_msgs/String`。如果类型不匹配，先忽略 status，只验 `/odom`。
3. `launch/navigation.launch.py` 当前会启动 `depth_publisher` 抢 D455，不适合和 Docker cuVSLAM 同时直接全栈启动。
4. 当前 cuVSLAM Docker launch 默认没有 depth topic，nvblox 还缺输入。
5. Foxy Nav2 不能直接加载 Humble Docker 里的 nvblox costmap 插件；要么 Nav2 进 Humble Docker，要么写转换节点。

