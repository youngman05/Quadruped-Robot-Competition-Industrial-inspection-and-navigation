# WHZ 使用说明

`whz` 通过 Lite3 前置 RTSP 相机完成一次按需巡检。节点常驻时只创建一个 YOLO 模型、执行一次预热，并保持一个低延迟 GStreamer 连接。

## 1. 接口与流程

```text
service: /whz/inspect
type: std_srvs/srv/Trigger
```

```text
读取 3 个不同的新帧
-> YOLO 检测 A/B/C/D 和 green/red/yellow
-> 按水平距离和上下关系配对字母与仪表
-> 拒绝无空间配对或多个近似最优配对
-> 对 (area, state_key) 做至少 2/3 投票
-> 投票成功后播放对应 MP3 一次
-> 返回 JSON
```

直接启动与调用：

```bash
ros2 run whz inspection_node
ros2 service call /whz/inspect std_srvs/srv/Trigger {}
```

随比赛 launch 启动：

```bash
ros2 launch quadruped_robot_competition competition.launch.py \
  enable_whz:=true \
  whz_rtsp_url:=rtsp://192.168.1.120:8554/test \
  whz_device:=0 \
  whz_required_frames:=3 \
  whz_min_agree_frames:=2
```

`enable_whz=true` 只启动 `whz/inspection_node`，不会为 WHZ 启动 D455 `color_image_publisher`。

## 2. 安装资源

```text
whz/assets/models/gauge_best.pt
whz/assets/audio/ALA.mp3 ... whz/assets/audio/DHA.mp3
```

正式模型 SHA-256：

```text
3ed76de727a87be8d64cc3b259bf2b0ec39daaaa3fac1f3f97af249824abc648
```

模型类别必须为：

```text
A B C D green red yellow
```

音频文件命名规则：

```text
第 1 位: A/B/C/D
第 2 位: L/M/H = low/middle/high
第 3 位: A/N = abnormal/normal
```

建议在 Jetson 安装 `mpg123`。运行时还需要已验证版本的 Torch、Torchvision、Ultralytics、NumPy、PyGObject 和 GStreamer H.264 插件。

## 3. 参数

| 参数 | 默认值 | 含义 |
|---|---:|---|
| `rtsp_url` | `rtsp://192.168.1.120:8554/test` | Lite3 前置相机地址 |
| `model_path` | ament 安装目录下的 `gauge_best.pt` | 模型路径 |
| `device` | `0` | Ultralytics 推理设备；CPU 测试可用 `cpu` |
| `required_frames` | `3` | 每次调用读取的新帧数 |
| `min_agree_frames` | `2` | 成功所需一致票数 |
| `connect_timeout_sec` | `8.0` | RTSP 启动超时 |
| `frame_timeout_sec` | `2.0` | 每个新帧的读取超时 |
| `image_size` | `320` | YOLO 推理尺寸 |
| `confidence_threshold` | `0.30` | YOLO 置信度阈值 |
| `iou_threshold` | `0.50` | YOLO NMS IoU 阈值 |
| `prefer_hw_decode` | `false` | 优先尝试 Jetson 硬解码 |
| `play_audio` | `true` | 投票成功后播放一次 MP3 |

`min_agree_frames` 不能大于 `required_frames`。这些资源型参数为启动期只读参数，修改后应重启节点。

## 4. 返回 JSON

成功示例：

```json
{
  "ok": true,
  "area": "A",
  "state_key": "low",
  "is_abnormal": true,
  "state_text": "偏低",
  "status_text": "异常",
  "color": "yellow",
  "audio_file": "/.../ALA.mp3",
  "audio_played": true,
  "letter_confidence": 0.88,
  "gauge_confidence": 0.91,
  "pair_score": 0.84,
  "agree_frames": 2,
  "total_frames": 3,
  "error": null
}
```

业务逻辑只使用 `area`、`state_key` 和 `is_abnormal`。`state_text`、`status_text` 仅用于中文显示，不参与判断。

失败时 `ok=false`，常见 `error` 包括：

```text
letter_not_detected
gauge_not_detected
no_spatial_pair
ambiguous_spatial_pair
ambiguous_vote
not_enough_agreement=1/2
camera_read_failed: ...
camera_frame_count_mismatch=2/3
audio_play_failed: ...
```

## 5. 验证顺序

本机 L1：

```bash
python3 -m unittest discover -s tests -p 'test_whz*.py' -v
```

Jetson L2 模型加载，不打开相机：

```bash
source /opt/ros/foxy/setup.bash
colcon build --packages-select whz
source install/setup.bash
python3 -c "from whz.paths import default_model_path; from whz.yolo_detector import YOLODetector; YOLODetector(default_model_path(), device='0'); print('model_ok')"
```

Jetson L4 相机与服务验证：

```bash
ros2 run whz inspection_node --ros-args -p play_audio:=false
ros2 service call /whz/inspect std_srvs/srv/Trigger {}
```

确认单帧、三帧投票和结果正确后，再启用音频：

```bash
ros2 run whz inspection_node --ros-args -p play_audio:=true
```

先完成静止真机验证，再与 cuVSLAM + Nav2 同时运行但不发送目标。TaskManager 接入必须等上述识别与播报验收通过后进行。
