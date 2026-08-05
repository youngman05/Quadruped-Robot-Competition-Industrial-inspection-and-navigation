# D455 Docker YOLO 三维节点（当前版本，2026-08-02）

## 1. 状态和边界

本文档描述当前已实现的 Docker 内 D455 YOLO 三维节点，不再是实施计划。

已经完成并验证：

- D455 由 Docker 内唯一 `realsense2_camera` 驱动持有；
- 同一 Docker 容器内，RealSense 和 YOLO 两个 ROS 2 节点可以通信；
- YOLO 订阅 RGB、Raw Depth、两路 `CameraInfo` 和 RealSense TF；
- 使用 Raw Depth 到 Color 的低频稀疏投影，而不是驱动内 `aligned_depth`；
- YOLO 使用原有 `best.pt`、Ultralytics 和 `yolo_live_test.py` 的 Torchvision NMS 兼容逻辑；
- 以最新帧策略运行，目标频率为 5 FPS；
- 检测结果以 `camera_link` 坐标通过 UDP `127.0.0.1:19002` 输出；
- Jetson 真机已验证 D455 流、RGB-Depth 配对、推理、空检测健康包和 UDP 频率。

尚未完成：

- 已知距离目标的真实 XYZ 误差标定；
- 由 TaskManager、机械臂等下游显式消费 `camera_link` 检测并按需转换坐标；
- PointCloud2 / Nav2 VoxelLayer（或轻量局部避障）接入；
- TaskManager、机械臂、按阶段调整 YOLO FPS 的控制接口。

在没有实测目标的情况下，不能把当前结果描述为“XYZ 精度已经验收”。

## 2. 当前架构

```text
D455
  -> Docker 内唯一 RealSense ROS 节点
       |- IR1 + IR2 + IMU -> cuVSLAM
       |- RGB 640x360 @ 30 Hz
       `- Raw Depth 640x360 Z16 @ 60 Hz
            -> /d455_object_yolo_3d
                 RGB + Raw Depth + 两路 CameraInfo + TF
                 -> YOLOv8-seg + 稀疏 depth-to-color 投影
                 -> camera_link XYZ
                 -> UDP 127.0.0.1:19002

后续 Host detection bridge
  -> camera_link 检测结果
  -> TaskManager / 机械臂
```

RealSense 和 YOLO 必须运行在同一个 Docker 容器。使用 host network 的两个独立容器在此 Jetson 环境中未能稳定发现 DDS topic；同容器已验证可用。

禁止 Host 或第二个容器通过 `pyrealsense2`、另一个 `realsense2_camera` 或旧的直接相机脚本打开 D455。

## 3. 保持不改的现有实现

以下文件和节点不因本工作修改：

- RealSense/cU VSLAM 的现有启动与驱动代码；
- `scripts/cv/yolo_live_test.py`；
- YOLO 模型权重、类别和类别 ID；
- odometry UDP 端口 `19001` 与现有 odometry bridge。

新增测试脚本 `scripts/cv/yolo_live_test_xyz.py` 只订阅 ROS topic，不会打开 D455。它与生产节点复用同一套 YOLO 调用和三维几何逻辑。

## 4. ROS 接口

节点名：`/d455_object_yolo_3d`

| 方向 | 接口 | 说明 |
|---|---|---|
| 输入 | `/camera/color/image_raw` | `bgr8` RGB，预期 30 Hz |
| 输入 | `/camera/depth/image_rect_raw` | `16UC1` Raw Depth，单位 mm，预期 60 Hz |
| 输入 | `/camera/color/camera_info` | Color 内参 |
| 输入 | `/camera/depth/camera_info` | Depth 内参 |
| 输入 | TF | `camera_depth_optical_frame -> camera_color_optical_frame -> camera_link` |
| 输出 | UDP `127.0.0.1:19002` | JSON schema v1，坐标系固定为 `camera_link` |

订阅使用 `BEST_EFFORT`、`KEEP_LAST=1`。节点保存最新 RGB 和最近 4 帧 Depth；每次定时处理选择时间戳最近的 Depth。RGB-Depth 时间差超过 30 ms 的帧会被丢弃，不会积压等待。

## 5. 三维计算

每一个 YOLO 实例 mask 的计算顺序：

```text
Raw Depth 像素
  -> 使用 Depth CameraInfo 反投影为 depth optical 3D 点
  -> RealSense depth-to-color TF
  -> 投影到 RGB 平面
  -> 仅保留落在 YOLO mask 内的点
  -> 距离过滤、mask 腐蚀、trimmed median
  -> color optical 坐标
  -> RealSense TF
  -> camera_link 坐标
```

默认有效深度范围为 `0.2-4.0 m`，两端各裁剪 10% 深度离群值，mask 腐蚀 2 次，至少需要 20 个有效点且有效比例不低于 0.6。否则仍保留二维检测，但输出：

```json
{
  "position_valid": false,
  "position_m": null
}
```

这种稀疏投影只在 YOLO 的 5 FPS 工作周期内执行，避免 RealSense 驱动以 60 FPS 对整幅图运行 continuous alignment。

## 6. UDP 协议

协议定义在 `configs/yolo/detection_v1.schema.json`。每次推理和每秒至少一次健康包都会发送：

```json
{
  "schema_version": 1,
  "sequence": 520,
  "stamp": {"sec": 1785495460, "nanosec": 395744385},
  "frame_id": "camera_link",
  "inference_ms": 106.071,
  "detections": []
}
```

非空 `detections` 的 `position_m` 始终是米单位的 `[x, y, z]`，表达在 `camera_link`。发送端不发布 ROS detection topic，也不会在 Docker 内转换到 `base_link`。

Host bridge 验证 `schema_version`、序号、源时间戳和过期时间后，保持 `camera_link` 坐标原样发布 Host ROS topic。唯一的 `base_link -> camera_link` 静态外参保留给显式需要其他坐标系的下游节点使用。

## 7. 文件与职责

| 文件 | 职责 |
|---|---|
| `docker/d455_perception/d455_yolo_3d_core.py` | 无 ROS 依赖的 Raw Depth 几何和稳健统计 |
| `docker/d455_perception/d455_yolo_3d_pipeline.py` | YOLO 分割、NMS 兼容和检测封包 |
| `docker/d455_perception/d455_yolo_3d_node.py` | ROS 订阅、最新帧、TF、UDP |
| `docker/d455_perception/run_yolo_3d_node.sh` | ROS 环境初始化和节点入口 |
| `docker/d455_perception/Dockerfile` | 基于现有 Jetson 镜像的派生镜像 |
| `scripts/cv/yolo_live_test_xyz.py` | GUI/日志验证脚本，不直接访问 D455 |
| `tests/test_d455_yolo_3d_core.py` | Raw Depth 投影和异常输入单元测试 |

## 8. Docker 依赖与运行方式

派生镜像基于 `cuvslam_yolo:humble`。该镜像包含 ROS、RealSense 和可视化依赖，但其内置 Torch 缺少 `libcurand.so.10`，不能单独用于此节点。

已验证的 Jetson 运行时使用 Host 的 Python 3.8 Torch/Ultralytics 与 CUDA 库，只读挂载：

```text
/home/superwfx666/.local/lib/python3.8/site-packages -> /opt/host-python:ro
/usr/local/cuda-11.4 -> /usr/local/cuda-11.4:ro
/usr/lib/aarch64-linux-gnu/tegra -> /usr/lib/aarch64-linux-gnu/tegra:ro
```

容器需要：

```text
--runtime nvidia
PYTHONPATH=/opt/host-python:/opt/quadruped/perception/bin
LD_LIBRARY_PATH=/usr/local/cuda-11.4/targets/aarch64-linux/lib
```

模型在验证阶段以只读方式挂载到：

```text
/opt/quadruped/perception/models/red_green_obstacle.pt
```

构建示例：

```bash
docker build \
  -f docker/d455_perception/Dockerfile \
  -t d455-yolo-3d:validation \
  .
```

先用现有方式在同一个容器启动 RealSense/cU VSLAM，然后在该容器中启动 YOLO：

```bash
docker exec -d <container_name> bash -lc '
  export PYTHONPATH=/opt/host-python:/opt/quadruped/perception/bin
  export LD_LIBRARY_PATH=/usr/local/cuda-11.4/targets/aarch64-linux/lib
  exec /opt/quadruped/perception/bin/run_yolo_3d_node.sh \
    --ros-args -p max_fps:=5.0 -p udp_host:=127.0.0.1 -p udp_port:=19002
'
```

实际容器创建命令还必须提供上面的只读挂载、模型挂载、USB D455 设备访问和 NVIDIA runtime。不要另开一个读取 D455 的测试进程。

## 9. 验证结果和下一步

本地 WSL2 `gauge_env`：10 个 D455 三维相关单元测试通过，Python 编译、shell 语法和 Git 空白检查通过。

Jetson D455 实测：

| 项目 | 结果 |
|---|---|
| Raw Depth | `640x360 Z16 @ 60 Hz` |
| RGB | `640x360 RGB8 @ 30 Hz` |
| RealSense 参数 | `enable_sync=false`、`align_depth.enable=false`、emitter off |
| 推理耗时 | 约 75-189 ms |
| RGB-Depth 时间差 | 通常 0.4-8 ms；超过 30 ms 会安全丢帧 |
| UDP | 4 秒 20 包，约 5 FPS |
| frame_id | `camera_link` |

下一次真机测试必须将已知距离的红色、绿色目标或锥桶放入 D455 视野，记录 `position_valid=true` 后的 XYZ，并和卷尺距离比较。应同时检查前向距离、横向符号和重复帧的稳定性。

## 10. 与 Jetson 协作迁移

本地工作区是开发和验证源，Jetson 原仓库可能同时被其他同事修改。迁移时只传递本功能的 commit 或 patch，在 Jetson 的独立 worktree 或 `/tmp` 构建上下文先验证；不要复制整个工作区，也不要覆盖同事正在编辑的仓库。

验证通过后，合并负责人再将小范围 commit cherry-pick 到共享分支。
