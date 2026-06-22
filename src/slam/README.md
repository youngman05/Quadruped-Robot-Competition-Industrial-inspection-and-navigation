# SLAM / VIO

比赛规则禁止激光雷达，采用 **NVIDIA cuVSLAM**（GPU 加速视觉惯性 SLAM）。

## 方案选择

| 方案 | 说明 | 推荐 |
|------|------|:---:|
| **cuVSLAM** | NVIDIA 官方，GPU 加速，VIO 内置封装，Jetson 原生 | ✅ 首选 |
| VINS-Fusion | 港科大，CPU 双目+IMU | 备选 |
| ORB-SLAM3 + IMU | 萨拉戈萨，精度顶级，CPU | 备选 |

## 硬件输入

```
D455 红外双目 (infra1 + infra2)  →  cuVSLAM 立体视觉跟踪
D455 BMI055 IMU (Accel + Gyro)   →  cuVSLAM 惯性融合
D455 红外投影仪                   →  关闭 (避免散斑干扰)
```

## 部署 (Jetson Xavier NX)

```bash
# 安装
sudo apt-get install -y ros-humble-isaac-ros-visual-slam

# 启动
ros2 launch isaac_ros_visual_slam isaac_ros_visual_slam_realsense.launch.py
```

## 输出 Topics

| Topic | 类型 | 说明 |
|-------|------|------|
| `/visual_slam/vis/slam_odometry` | Odometry | SLAM 修正后的位姿 |
| `/visual_slam/vis/observations_cloud` | PointCloud2 | 当前帧特征点 |
| `/visual_slam/vis/landmarks_cloud` | PointCloud2 | 全局 3D 路标地图 |
| `tf: map → odom → base_link` | Transform | 坐标变换树 |

## 关键参数

- D455 红外基线：**95 mm**
- 红外分辨率：640×480 @ 30fps
- IMU Accel：200 Hz，Gyro：200 Hz
- 投影仪：**必须关闭** (`emitter_enabled: 0`)

## 参考

- cuVSLAM GitHub: https://github.com/nvidia-isaac/cuVSLAM
- Isaac ROS Visual SLAM: https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam
- 官方文档: https://nvidia-isaac-ros.github.io/concepts/visual_slam/cuvslam/
