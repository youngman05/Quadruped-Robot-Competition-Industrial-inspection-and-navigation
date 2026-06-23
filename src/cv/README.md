# CV

## ROS2 Gauge Status Node

`scripts/gauge_status_node.py` wraps the current D455 OpenCV gauge detector as a ROS2 node.

It reads D455 RGB frames directly and publishes:

```text
/gauge/status    std_msgs/msg/String   JSON payload
/gauge/detected  std_msgs/msg/Bool
```

Run on Jetson:

```bash
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
python3 scripts/gauge_status_node.py
```

Check output:

```bash
ros2 topic list | grep gauge
timeout 5s ros2 topic echo /gauge/status
timeout 5s ros2 topic echo /gauge/detected
```

视觉模块目录。

当前包含：

- `gauge_detector`: OpenCV 仪表盘状态识别原型。
- `realsense_camera`: D455 RGB-D / 红外双目 / BMI055 IMU 采集封装，支持仪表识别和 cuVSLAM 预设。
- `yolo_detector`: YOLO/TensorRT 检测封装，待实现。
