# Docker cuVSLAM 与 YOLO 集成最终修改方案（2026-07-20）

## 1. 文档目的

本文档是正式修改代码前的实施指引，目标是在 Jetson Xavier NX 上实现：

- D455 只被 Docker 内一个 RealSense 驱动打开；
- cuVSLAM 和物块/锥桶 YOLO 作为 Docker 内两个相互独立的业务节点运行；
- Docker 内完成物块、锥桶实例分割和三维位置计算；
- 识别结果通过 UDP 穿透到 Host ROS2 Foxy；
- Host 接收节点统一转换并只发布 `base_link` 坐标；
- 机械臂后续负责 `base_link -> arm_base` 转换、逆运动学和抓取；
- 最大限度保留当前已经能够运行的 cuVSLAM 实现。

本文档只确定工程改造边界和实现方法，不改变现有 YOLO 模型权重。

## 2. 最终职责划分

| 模块 | 运行位置 | 输入 | 输出 |
|---|---|---|---|
| RealSense Driver | Docker / Humble | D455 USB | IR、IMU、RGB、aligned Depth、CameraInfo |
| cuVSLAM | Docker / Humble | IR1、IR2、IMU | odometry、tracking status |
| D455 YOLO 3D | Docker / Humble | RGB、aligned Depth、CameraInfo、Docker TF | `camera_link` 三维检测 UDP |
| Odometry Bridge | Host / Foxy | Docker odometry UDP | `/odom`、TF |
| Detection Bridge | Host / Foxy | Docker detection UDP | 仅 `base_link` 下的检测和目标 |
| Nav2 | Host / Foxy | `/odom`、地图、深度障碍 | `/cmd_vel` |
| TaskManager | Host / Foxy | 感知、导航、机械臂状态 | 比赛阶段控制 |
| 机械臂 | Host | `base_link` 目标位姿 | `arm_base` 转换、抓取和放置 |

## 3. Docker 内节点关系

Docker 内实际包含一个设备节点和两个业务节点：

```text
/camera/camera
  RealSense 唯一驱动，独占 D455
       |
       +-- IR1 + IR2 + IMU --------> /visual_slam_node
       |                               cuVSLAM
       |
       +-- RGB + aligned Depth ------> /d455_object_yolo_3d
                                       物块/锥桶 YOLO + 三维计算
```

多个节点订阅同一个 RealSense ROS topic 不会重复打开 D455。禁止在 Host 再启动 `pyrealsense2`、`realsense2_camera` 或其他直接访问 D455 的节点。

## 4. 不修改的 cuVSLAM 范围

以下内容保持不变：

- `visual_slam_node` 的组件类型；
- IR 双目 topic remapping；
- IMU 输入和融合参数；
- cuVSLAM tracking、mapping 和 odometry 参数；
- 当前 IR 分辨率、频率和 camera profile；
- cuVSLAM 里程计 topic；
- `scripts/final_bridge.py`；
- odometry UDP 端口 `19001`；
- Host `/odom` 和 `odom -> base_link` 输出协议；
- 当前基础 cuVSLAM Docker 镜像。

唯一不可避免的改动是让同一个 RealSense 节点按开关额外发布 RGB 和 Depth。该改动必须默认关闭，保证原 cuVSLAM 启动命令行为不变。

## 5. 当前 YOLO 模型

模型源文件：

```text
src/cv/depth_detector/projects/combined/model/best.pt
```

模型规格：

| Class ID | Class Name | 含义 |
|---:|---|---|
| 0 | `red` | 红色异常物块/长条 |
| 1 | `green` | 绿色正常物块/长条 |
| 2 | `obstacle` | 锥桶/障碍物 |

本轮不进行：

- 重新训练；
- 修改类别；
- 修改类别 ID；
- 修改权重；
- 同时进行 TensorRT 改造。

第一版使用原始 `.pt + Ultralytics` 跑通完整链路。TensorRT 作为后续独立性能优化任务。

## 6. 模型进入 Docker

### 6.1 调试阶段

仓库中的权重作为唯一源文件，以只读方式挂载：

```bash
-v "$PROJECT_DIR/src/cv/depth_detector/projects/combined/model/best.pt:\
/opt/quadruped/perception/models/red_green_obstacle.pt:ro"
```

Docker 内统一模型路径：

```text
/opt/quadruped/perception/models/red_green_obstacle.pt
```

这种方式替换模型后不需要重建镜像，适合当前分块测试阶段。

### 6.2 比赛阶段

模型通过 Dockerfile 固化到派生镜像。仓库中的源权重不删除：

```dockerfile
FROM cuvslam_yolo:humble

RUN mkdir -p /opt/quadruped/perception/models \
    /opt/quadruped/perception/bin

COPY src/cv/depth_detector/projects/combined/model/best.pt \
     /opt/quadruped/perception/models/red_green_obstacle.pt

COPY docker/d455_perception/d455_yolo_3d_node.py \
     /opt/quadruped/perception/bin/d455_yolo_3d_node.py

ENV YOLO_MODEL_PATH=/opt/quadruped/perception/models/red_green_obstacle.pt
```

构建镜像时记录源权重 SHA256，避免比赛镜像和仓库权重版本不一致。

## 7. 文件组织

### 7.1 新增文件

```text
docker/
  d455_perception/
    Dockerfile
    requirements.txt
    d455_yolo_3d_node.py

src/nodes/perception/
  d455_detection_bridge.py

configs/yolo/
  d455_objects.yaml
  detection_v1.schema.json
```

职责：

| 文件 | 运行位置 | 职责 |
|---|---|---|
| `Dockerfile` | 构建阶段 | 基于 cuVSLAM 镜像增加 YOLO 层，不修改基础镜像 |
| `requirements.txt` | 构建阶段 | 固定 YOLO 节点额外依赖 |
| `d455_yolo_3d_node.py` | Docker | RGB-D 同步、推理、三维计算、UDP 输出 |
| `d455_detection_bridge.py` | Host | UDP 接收、TF 转换、ROS topic 发布 |
| `d455_objects.yaml` | Docker/Host | 类别、阈值、模型路径、FPS、端口 |
| `detection_v1.schema.json` | Docker/Host | 固定跨容器 JSON 协议 |

### 7.2 保留的旧文件

以下文件不删除，只保留作单模块或离线调试：

- `src/nodes/perception/yolo_detect_publisher.py`；
- `scripts/cv/yolo_live_test.py`；
- `scripts/yolo_detect_once.py`；
- `scripts/camera_relay_docker.py`。

正式比赛启动不得再启动 Host `yolo_detect_publisher`。

`scripts/yolo_relay_docker.py` 是表盘/字母模型的旧 Docker 推理脚本，不复用于本次物块和锥桶节点。

## 8. RealSense 启动改动

修改 `scripts/start_cuvslam_rviz_gui.sh`，新增：

```bash
ENABLE_COLOR="${ENABLE_COLOR:-0}"
ENABLE_DEPTH="${ENABLE_DEPTH:-0}"
ENABLE_ALIGN_DEPTH="${ENABLE_ALIGN_DEPTH:-0}"
```

生成的 RealSense 参数使用开关：

```python
{
    "enable_infra1": True,
    "enable_infra2": True,
    "enable_color": ENABLE_COLOR,
    "enable_depth": ENABLE_DEPTH,
    "enable_gyro": True,
    "enable_accel": True,
    "enable_sync": True,
    "align_depth.enable": ENABLE_ALIGN_DEPTH,
    "depth_module.emitter_enabled": 0,
}
```

注意：实际参数名称需要在 Jetson 当前 `realsense2_camera` 版本上通过以下命令核对：

```bash
ros2 param list /camera/camera
ros2 param dump /camera/camera
```

### 8.1 原 cuVSLAM 模式

```bash
ENABLE_COLOR=0 ENABLE_DEPTH=0 ENABLE_ALIGN_DEPTH=0
```

行为必须与修改前一致。

### 8.2 比赛感知模式

```bash
IMAGE=<cuvslam-yolo派生镜像> \
ENABLE_COLOR=1 \
ENABLE_DEPTH=1 \
ENABLE_ALIGN_DEPTH=1 \
bash scripts/start_cuvslam_rviz_gui.sh --no-rviz
```

D455 投影仪继续关闭，避免干扰 cuVSLAM。启用 Depth 后必须重新验证被动深度质量和 cuVSLAM tracking。

## 9. Docker YOLO 三维节点

节点名：

```text
/d455_object_yolo_3d
```

### 9.1 输入 topic

```text
/camera/color/image_raw
/camera/aligned_depth_to_color/image_raw
/camera/color/camera_info
```

要求：

- RGB 和 Depth 分辨率对应；
- Depth 已对齐到 RGB；
- topic 使用 SensorData/BEST_EFFORT QoS；
- 使用近似时间同步；
- 默认同步容差从 30 ms 开始测试；
- 队列深度不超过 3。

### 9.2 最新帧策略

ROS 回调只保存最新一组同步 RGB-D，不直接执行推理。后台工作线程读取最新帧：

```text
同步回调 -> 覆盖 latest_frame -> 推理线程 -> UDP
```

推理期间到达的新帧覆盖旧帧，不积压队列。比赛感知优先保证低延迟，不保证处理每一帧。

### 9.3 推理初始配置

```yaml
model_path: /opt/quadruped/perception/models/red_green_obstacle.pt
imgsz: 640
confidence: 0.5
iou: 0.5
device: "0"
retina_masks: true
max_fps: 5
```

模型仅输出原有 `red`、`green`、`obstacle` 三类。

## 10. Depth 与三维计算

开启 Depth 流后，D455 已经完成双目视差计算，但软件仍需完成：

```text
实例 mask
  -> mask 内有效 Depth
  -> 目标深度
  -> 相机内参反投影
  -> 三维坐标
```

每个实例按以下方式计算：

1. 将 YOLO mask 恢复到 RGB/Depth 原始尺寸；
2. 腐蚀 mask 2 至 4 像素，减少边缘背景；
3. 读取 mask 内非零 Depth；
4. 保留 `0.2-4.0 m` 范围；
5. 删除最低和最高各 10% 的离群值；
6. 使用中位数作为 `z`；
7. 使用有效像素中位位置作为 `(u, v)`；
8. 从 CameraInfo 读取 `fx/fy/cx/cy`；
9. 反投影到 `camera_color_optical_frame`；
10. 使用 Docker 内 RealSense TF 转换到 `camera_link`。

反投影公式：

```text
x = (u - cx) * z / fx
y = (v - cy) * z / fy
z = median_depth
```

节点内部可以记录光学坐标用于调试，但正式 UDP 协议只输出 `camera_link` 坐标。

必须同时计算：

```text
depth_valid_ratio = 有效深度像素数 / mask像素数
```

当比例低于阈值时：

```json
{
  "position_valid": false
}
```

该目标仍可用于二维语义判断，但不能交给机械臂。

## 11. Docker 到 Host 协议

端口分配：

| 端口 | 方向 | 用途 |
|---:|---|---|
| 19001 | Docker -> Host | 现有 cuVSLAM odometry |
| 19002 | Docker -> Host | YOLO 三维检测 |
| 19003 | Host -> Docker | 后续识别模式/FPS控制 |

YOLO 使用独立 UDP socket 和独立进程，不修改 odometry bridge。

检测 JSON v1：

```json
{
  "schema_version": 1,
  "sequence": 1024,
  "stamp": {
    "sec": 1753000000,
    "nanosec": 100000000
  },
  "frame_id": "camera_link",
  "inference_ms": 41.2,
  "detections": [
    {
      "class_id": 0,
      "class_name": "red",
      "confidence": 0.93,
      "bbox": [100, 120, 260, 340],
      "center_px": [180, 230],
      "mask_area_px": 5200,
      "depth_m": 1.28,
      "depth_valid_ratio": 0.84,
      "position_valid": true,
      "position_m": [1.28, -0.12, 0.03]
    }
  ]
}
```

即使当前没有目标，Docker 节点也应至少每秒发送一次空检测健康包。Host 必须能区分“没有目标”和“节点失联”。

## 12. Host Detection Bridge

节点名：

```text
/d455_detection_bridge
```

职责：

1. 监听 `127.0.0.1:19002`；
2. 校验 `schema_version`；
3. 检查字段、序号和源时间戳；
4. 丢弃重复包；
5. 丢弃超过 200 ms 的过期结果；
6. 将 `camera_link` 三维点转换到 `base_link`；
7. 只发布 `base_link` 坐标；
8. 发布接收延迟、包率和失联状态。

Host 不重新读取 RGB/Depth，不重新运行 YOLO，也不发布相机坐标系目标。

### 12.1 ROS 输出接口

| Topic | 类型 | Frame | 用途 |
|---|---|---|---|
| `/perception/objects_3d` | `std_msgs/String` JSON | `base_link` | 全部物块和锥桶 |
| `/block/target_pose` | `geometry_msgs/PoseStamped` | `base_link` | 当前稳定红色抓取目标 |
| `/cone/detections` | `std_msgs/String` JSON | `base_link` | 锥桶语义结果 |
| `/perception/status` | `std_msgs/String` JSON | 无 | FPS、延迟、最后收包时间 |

机械臂接收 `/block/target_pose` 后自行完成：

```text
base_link -> arm_base -> 逆运动学 -> 抓取
```

## 13. `base_link -> camera_link` 外参

Host bridge 依赖唯一且正确的：

```text
base_link -> camera_link
```

当前不同 launch 中存在两套静态外参，必须统一：

- 只保留一个 `base_to_camera_tf` 发布者；
- 安装平移和俯仰角统一放入 `configs/camera/d455.yaml`；
- 删除或禁用另一个重复静态 TF；
- 使用实测安装尺寸替换当前估计值。

外参未完成标定前，只允许验证识别、深度和 UDP 链路，不允许驱动机械臂抓取。

## 14. Host YOLO 退出正式链路

当前 `src/nodes/perception/yolo_detect_publisher.py` 保留为调试工具，正式模式不启动。

`launch/competition.launch.py` 调整：

- 正式 `enable_yolo` 启动 Host `d455_detection_bridge`；
- 不再启动 Host `yolo_detect_publisher`；
- 如需保留旧节点，新增明确的 `enable_host_yolo_debug` 开关；
- `enable_host_yolo_debug` 默认 `false`；
- 正式启动脚本禁止 `use_d455=true`。

## 15. 类别协议统一

`configs/yolo/classes.yaml` 改为模型实际类别：

```yaml
names:
  0: red
  1: green
  2: obstacle
```

删除正式运行中的旧七分类假设：

```text
gauge / A / B / C / D / red_bar / green_bar
```

表盘和字母由 Go2 摄像头巡检链路处理，不再混入 D455 物块/锥桶模型协议。

## 16. TaskManager 修改

`src/nodes/decision/task_manager.py` 负责比赛流程调度，不负责视觉推理和坐标转换。

YOLO解析改成：

```text
red      -> 红色异常物块
green    -> 绿色正常物块
obstacle -> 锥桶/障碍物
```

`FIND_RED_BAR` 推进条件改为：

- `class_name == red`；
- `position_valid == true`；
- 输入 frame 为 `base_link`；
- 检测年龄小于 200 ms；
- 连续至少 3 帧位置稳定；
- 目标位于机械臂允许的候选范围。

TaskManager 后续只负责发出抓取请求并等待机械臂反馈。机械臂逆运动学和动作实现不属于本轮修改。

## 17. 目标稳定和选择

Host bridge 从多个红色候选中选择 `/block/target_pose`：

1. 类别为 `red`；
2. 置信度大于阈值；
3. `depth_valid_ratio` 大于阈值；
4. 三维坐标有效；
5. 检测时间未过期；
6. 目标位于允许范围；
7. 连续帧位置一致。

初始稳定阈值：

```text
连续帧数：3
最大三维中心偏差：0.05 m
最大时间跨度：0.5 s
```

阈值后续通过实测调整。

## 18. 阶段资源调度

第一版可以固定 5 FPS 跑通。稳定后通过 UDP `19003` 增加模式控制：

| TaskManager 阶段 | YOLO模式 | 建议FPS |
|---|---|---:|
| `START` | `idle` | 0-1 |
| `PASS_OBSTACLE` | `cone` | 5 |
| `INSPECT_GAUGES` | `idle` | 0 |
| `FIND_RED_BAR` | `block` | 5-8 |
| `GRASP_BAR` | `block` | 10 |
| `PLACE_TO_ABNORMAL_ZONE` | `idle` | 0-2 |
| `FINISH/ABORT` | `idle` | 0 |

GPU或温度过载时优先降低YOLO FPS，不能降低cuVSLAM优先级。

## 19. Nav2 深度链路

YOLO锥桶识别不是唯一避障输入。Nav2继续采用：

```text
Docker D455 Depth
  -> 独立 Depth Relay
  -> Host Depth Bridge
  -> /camera/depth/image_raw + CameraInfo
  -> PointCloud2
  -> Nav2 VoxelLayer
```

正式模式下，Host `depth_publisher.py` 不能直接打开D455，需要改成读取Docker输出。

Depth Relay、YOLO节点和cuVSLAM分别使用独立文件及进程。YOLO故障时Depth几何避障仍应工作。

## 20. 启动脚本修改

`scripts/start_competition.sh` 调整后的顺序：

```text
1. 清理旧进程
2. 启动带YOLO层的cuVSLAM派生镜像
3. 等待cuVSLAM tracking
4. 验证RGB、aligned Depth和CameraInfo
5. 启动Docker d455_object_yolo_3d
6. 启动Docker Depth Relay
7. 启动Host odometry final_bridge
8. 启动Host d455_detection_bridge
9. 启动Host Depth Bridge/Nav2
10. 启动TaskManager和机械臂接口
11. 执行健康检查
```

日志完全分开：

```text
/tmp/cuvslam.log
/tmp/d455_yolo_3d.log
/tmp/depth_relay.log
/tmp/odom_bridge.log
/tmp/detection_bridge.log
/tmp/competition.log
```

停止脚本分别终止各进程，不能通过修改或重启cuVSLAM节点来控制YOLO。

## 21. 分阶段实施

### P0：基线和设备边界

1. 记录当前cuVSLAM单独运行的tracking、FPS和资源占用；
2. 确认Host没有其他进程打开D455；
3. 记录当前模型SHA256和类别；
4. 修正仓库中错误的`yolo_detector`模型路径。

### P1：派生镜像和相机流

1. 构建派生镜像，不修改基础镜像；
2. 新镜像关闭RGB/Depth/YOLO运行cuVSLAM；
3. 对比基线，确认cuVSLAM行为不变；
4. 单独开启RGB测试；
5. 再开启Depth和alignment测试；
6. 检查IR帧率和tracking变化。

### P2：Docker三维识别

1. 实现同步RGB-D输入；
2. 加载原模型；
3. 验证三类实例分割；
4. 实现mask深度统计；
5. 实现反投影和`camera_link`转换；
6. 使用固定距离物块验证三维误差；
7. 此阶段先写本地JSON，不接Host。

### P3：跨容器接口

1. 固定JSON schema v1；
2. 实现UDP 19002发送；
3. 实现Host bridge；
4. 实现序号、过期和失联处理；
5. 转换并只发布`base_link`坐标；
6. 验证静止和移动状态下的端到端延迟。

### P4：TaskManager和机械臂接口

1. 统一三分类协议；
2. 增加目标稳定判断；
3. 发布`/block/target_pose`；
4. TaskManager使用新鲜有效的红色目标；
5. 机械臂先只打印和验证base_link输入，不立即执行动作。

### P5：Nav2和整机压力测试

1. Host Depth节点改为Docker relay输入；
2. 补齐PointCloud2生成；
3. 验证YOLO关闭时仍能避障；
4. 同时运行cuVSLAM、YOLO、Nav2和Bridge；
5. 记录CPU、GPU、内存、温度、延迟和tracking；
6. 稳定后再接实际机械臂动作。

## 22. 验收标准

### 22.1 cuVSLAM保护

- 关闭RGB/Depth/YOLO时，新镜像cuVSLAM行为与基线一致；
- 开启RGB-D后tracking没有不可接受的下降；
- YOLO崩溃不导致cuVSLAM退出；
- YOLO重启不重启RealSense和cuVSLAM。

### 22.2 感知

- 模型类别保持`red/green/obstacle`；
- Docker稳定输出三维检测；
- `position_valid`与深度质量一致；
- 无检测时仍有健康包；
- 不出现帧队列持续积压。

### 22.3 跨容器和坐标

- Host可检测重复、乱序和过期数据；
- Host ROS topic只发布`base_link`坐标；
- `base_link -> camera_link`只有一个静态TF来源；
- 固定目标多点测试的坐标误差满足机械臂需求；
- 机械臂负责`base_link -> arm_base`。

### 22.4 性能初始目标

| 指标 | 目标 |
|---|---:|
| YOLO稳定帧率 | 5 FPS |
| 抓取阶段目标帧率 | 8-10 FPS |
| Docker到Host检测延迟 | 小于200 ms |
| Depth避障更新 | 5-10 Hz |
| 过期结果 | Host自动丢弃 |
| 热降频 | 完整流程中不持续发生 |

## 23. 回退策略

每个阶段保持可单独回退：

- 设置`ENABLE_COLOR=0 ENABLE_DEPTH=0`恢复原cuVSLAM模式；
- 停止`d455_object_yolo_3d`不影响cuVSLAM；
- 停止Host detection bridge不影响odom；
- 保留旧Host YOLO脚本用于离线调试；
- 派生镜像失败时回到原cuVSLAM基础镜像。

不通过修改cuVSLAM参数来掩盖RGB-D或YOLO引入的问题。

## 24. 本轮修改边界

本轮计划修改：

- 新增Docker物块/锥桶YOLO三维节点；
- 新增Host检测接收桥；
- 模型挂载和镜像固化；
- RealSense增加可选RGB、Depth和alignment开关；
- 统一三分类协议；
- 统一相机安装外参；
- 修改正式启动、停止和健康检查；
- TaskManager接入稳定、有效、未过期的红色物块；
- 阻止Host正式节点直接访问D455；
- 补齐Docker Depth到Host Nav2的必要链路。

本轮不修改：

- YOLO模型权重和训练数据；
- cuVSLAM算法、输入remapping和融合参数；
- odometry bridge协议；
- TensorRT导出；
- 机械臂逆运动学和真实抓取动作；
- 使用YOLO替代Nav2深度几何避障。

最终运行边界固定为：**Docker负责D455、cuVSLAM、YOLO和相机坐标三维计算；Host负责接收、转换并只发布`base_link`结果；机械臂负责从`base_link`转换到`arm_base`并执行动作。**

## 25. 实施记录

### 25.1 第一阶段：协议、三维核心和相机流开关

状态：代码完成，本机测试通过，等待 Jetson D455/cuVSLAM 实机验证。

已新增：

- `configs/yolo/d455_objects.yaml`
  - 固定模型源路径和 Docker 路径；
  - 固定 `red/green/obstacle` 三分类；
  - 记录推理、Depth过滤和UDP端口初始参数。
- `configs/yolo/detection_v1.schema.json`
  - 固定 Docker 到 Host 的检测数据结构；
  - 正式输出 frame 固定为 `camera_link`；
  - 明确深度有效率、三维有效标志和三维位置字段。
- `docker/d455_perception/d455_yolo_3d_core.py`
  - 新增不依赖 ROS 的 mask Depth 统计核心；
  - 支持 mask 腐蚀、距离过滤、离群值裁剪和中位深度；
  - 新增基于 CameraInfo 内参的光学坐标反投影。
- `tests/test_d455_yolo_3d_core.py`
  - 覆盖有效Depth、无效值、离群值、像素反投影和输入尺寸校验。
- `tests/test_d455_model_contract.py`
  - 校验当前权重仍为实例分割模型；
  - 校验类别严格为 `{0: red, 1: green, 2: obstacle}`。

已修改：

- `scripts/start_cuvslam_rviz_gui.sh`
  - 新增默认关闭的 `ENABLE_DEPTH`；
  - 新增默认关闭的 `ENABLE_ALIGN_DEPTH`；
  - 继续沿用已有 `ENABLE_COLOR`；
  - 只有显式开启Depth时才向RealSense增加同步和对齐参数；
  - 未修改 `visual_slam_node`、IR remapping、IMU和cuVSLAM参数。

本阶段未修改：

- `scripts/final_bridge.py`；
- odometry UDP和Host `/odom`；
- `visual_slam_node`参数；
- 正式启动脚本；
- Host detection bridge；
- Docker YOLO ROS节点；
- TaskManager；
- Nav2 Depth链路。

模型确认结果：

```text
path: src/cv/depth_detector/projects/combined/model/best.pt
sha256: 4445d7593d7a515da84d325d6c70a8e4cbbe667bc877d51591e72c0d539df270
task: segment
classes: 0=red, 1=green, 2=obstacle
```

本机验证环境：

```text
WSL2
conda env: gauge_env
Python: 3.10.20
Ultralytics: 8.4.89
OpenCV: 4.12.0
NumPy: 2.2.6
```

已执行：

```bash
bash -n scripts/start_cuvslam_rviz_gui.sh
conda run -n gauge_env \
  python -m unittest discover -s tests -p 'test_d455_*.py' -v
git diff --check
```

结果：7项测试全部通过，shell语法和Git空白检查通过。

下一步验证门：在Jetson上依次验证原cuVSLAM模式、仅RGB模式、RGB+Depth+alignment模式。实机验证通过前，不继续接入Docker YOLO ROS节点和正式启动脚本。
