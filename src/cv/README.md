# CV

视觉模块 — 仪表检测、YOLO 实例分割、D455 相机驱动。

## 子模块

| 目录 | 说明 |
|------|------|
| `gauge_detector/` | OpenCV 仪表盘状态识别（指针角度、颜色区域） |
| `depth_detector/` | YOLOv8 实例分割（训练 + TensorRT 推理） |
| `realsense_camera/` | D455 相机 Python API（RGB/深度/红外/IMU） |

## 相关 ROS2 节点

| 节点 | 启动方式 |
|------|----------|
| 仪表检测 | `ros2 run quadruped_robot_competition gauge_status` |
| YOLO 检测 | `ros2 run quadruped_robot_competition yolo_detect` |

详见 [src/nodes/README.md](../nodes/README.md)。

## D455 相机快速测试

```bash
cd ~/quadruped-robot-competition
python3 scripts/realsense_smoke_test.py              # 冒烟测试
python3 scripts/realsense_cuvslam_input_test.py      # cuVSLAM 链路检查
```

