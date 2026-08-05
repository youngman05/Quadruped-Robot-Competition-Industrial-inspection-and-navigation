# ROS2 节点

每个节点可单独启动，也可通过 launch 文件一起启动。

---

## 前置操作（首次部署必做）

```bash
# [Linux]
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
python3 -m pip install -e .
```

---

## 节点列表

| 节点 | 可执行名 | 状态 | 说明 |
|------|----------|------|------|
| GaugeStatusNode | `gauge_status` | ✅ 完成 | D455 仪表检测 |
| YoloDetectNode | `yolo_detect` | ✅ 完成 | YOLOv8 实例分割 |
| TaskManagerNode | `task_manager` | ✅ 完成 | 比赛状态机 |
| SpeechNode | `speech` | ⏳ 待实现 | 语音播报 |

---

## 1. 仪表检测节点 (gauge_status)

> **平台: Linux (Jetson, 需 D455 相机)**

依赖 D455 相机，发布 `/gauge/status`（JSON）和 `/gauge/detected`（Bool）。

```bash
# [Linux] 方式一：直接运行脚本
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
python3 scripts/gauge_status_node.py

# [Linux] 方式二：ros2 run（需先 pip install -e .）
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
ros2 run quadruped_robot_competition gauge_status
```

自定义参数：

```bash
# [Linux]
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
ros2 run quadruped_robot_competition gauge_status \
  --ros-args -p publish_invalid:=false -p stable_frame_count:=5
```

验证输出（另开终端）：

```bash
# [Linux] 另开一个终端
source /opt/ros/foxy/setup.bash
ros2 topic list | grep gauge
ros2 topic echo /gauge/status
```

`/gauge/status` JSON 关键字段：

| 字段 | 说明 |
|------|------|
| `detected` | 单帧是否通过校验 |
| `color` / `level` / `status` | 单帧检测值 |
| `stable_detected` | 连续多帧稳定检测标志 |
| `stable_color` / `stable_level` / `stable_status` | **下游决策必须用这些** |

---

## 2. YOLO 检测节点 (yolo_detect)

> **平台: Linux (Jetson, 需 ultralytics + torch, GPU 推荐)**
>
> 此节点是旧 Host/离线调试入口，不是当前 D455 正式链路。正式链路使用 Docker 内 `/d455_object_yolo_3d`：订阅 RealSense RGB、Raw Depth、CameraInfo 和 TF，输出 `camera_link` 三维结果至 UDP `127.0.0.1:19002`。Host `yolo_udp_bridge` 校验后原样发布 `camera_link` ROS 检测数据；运行 Docker RealSense 时不得用本节点直接打开 D455。详见 `docs/Docker_Yolo_Combine_0720.md`。

发布 YOLO 实例分割结果到 `/yolo/detections`、`/yolo/image`、`/yolo/instance_count`。

### 安装依赖

```bash
# [Linux]
cd ~/quadruped-robot-competition
python3 -m pip install ultralytics torch torchvision
python3 scripts/verify_yolo.py               # 验证安装
```

### 启动

```bash
# [Linux]
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
ros2 run quadruped_robot_competition yolo_detect
```

或指定参数（CPU 模式）：

```bash
# [Linux] CPU 模式
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
ros2 run quadruped_robot_competition yolo_detect \
  --ros-args -p device:=cpu -p interval_sec:=0.2 -p conf:=0.6
```

### 验证输出

```bash
# [Linux] 另开终端
source /opt/ros/foxy/setup.bash
ros2 topic echo /yolo/detections      # JSON 检测结果
ros2 topic echo /yolo/instance_count  # 实例数量
```

类别映射（`configs/yolo/classes.yaml`）：

| class_id | 名称 |
|----------|------|
| 0 | gauge |
| 1 | A |
| 2 | B |
| 3 | C |
| 4 | D |
| 5 | red_bar |
| 6 | green_bar |

---

## 3. 任务管理节点 (task_manager)

> **平台: Linux (Jetson)**

比赛状态机，订阅感知节点，发布 `/task/phase` 和 `/task/status`。

```bash
# [Linux] 正常启动
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
ros2 run quadruped_robot_competition task_manager
```

调试模式（跳过条件自动推进）：

```bash
# [Linux] 调试模式
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
ros2 run quadruped_robot_competition task_manager \
  --ros-args -p auto_advance:=true -p timeout_per_phase:=30.0
```

验证输出：

```bash
# [Linux] 另开终端
source /opt/ros/foxy/setup.bash
ros2 topic echo /task/phase           # 当前阶段 (字符串)
ros2 topic echo /task/status          # 完整状态 (JSON)
```

阶段顺序：START → PASS_OBSTACLE → INSPECT_GAUGES → REPORT_STATUS → FIND_RED_BAR → GRASP_BAR → PLACE_TO_ABNORMAL_ZONE → FINISH

---

## 4. 语音播报节点 (speech)

> **平台: Linux (Jetson)**

⏳ 待实现。启动方式预留：

```bash
# [Linux] (待实现)
ros2 run quadruped_robot_competition speech
```
