# WHZ 使用说明

`whz` 是配电柜巡检识别 ROS2 package。收到 `/whz/inspect` service 调用后，它会读取 3 帧图像，识别 A/B/C/D 区域和仪表状态；至少 2 帧结果一致时播放一次对应 MP3，并通过 service 返回 JSON。

## 1. 固定接口

```text
彩色图像: /camera/color/image_raw
对齐深度: /camera/aligned_depth_to_color/image_raw
service: /whz/inspect
service 类型: std_srvs/srv/Trigger
```

运行：

```bash
ros2 run whz inspection_node
```

调用：

```bash
ros2 service call /whz/inspect std_srvs/srv/Trigger {}
```

## 2. 必要文件

字母模板：

```text
whz/assets/templates/A.png
whz/assets/templates/B.png
whz/assets/templates/C.png
whz/assets/templates/D.png
```

音频文件：

```text
whz/assets/audio/ALA.mp3  whz/assets/audio/AMN.mp3  whz/assets/audio/AHA.mp3
whz/assets/audio/BLA.mp3  whz/assets/audio/BMN.mp3  whz/assets/audio/BHA.mp3
whz/assets/audio/CLA.mp3  whz/assets/audio/CMN.mp3  whz/assets/audio/CHA.mp3
whz/assets/audio/DLA.mp3  whz/assets/audio/DMN.mp3  whz/assets/audio/DHA.mp3
```

命名规则：

```text
第 1 位: A/B/C/D 区域
第 2 位: L/M/H = low/middle/high
第 3 位: A/N = abnormal/normal
```

状态映射：

```text
黄色 -> low    -> 偏低 -> 异常 -> LA
绿色 -> middle -> 正常 -> 正常 -> MN
红色 -> high   -> 偏高 -> 异常 -> HA
```

建议安装 MP3 播放器：

```bash
sudo apt install mpg123
```

## 3. 使用前检查

确认上游图像 topic 存在并持续发布：

```bash
ros2 topic info /camera/color/image_raw
ros2 topic hz /camera/color/image_raw
ros2 topic info /camera/aligned_depth_to_color/image_raw
ros2 topic hz /camera/aligned_depth_to_color/image_raw
```

确认 service 存在：

```bash
ros2 service list | grep whz
```

应看到：

```text
/whz/inspect
```

## 4. 识别逻辑

字母识别：

```text
找白色面板 -> 取面板上半部分 -> 找黑色字母区域 -> 和 A/B/C/D 模板匹配
```

仪表识别：

```text
优先用 RealSense 深度找最近平面 -> 在最近平面内找仪表圆 -> 识别指针方向 -> 采样黄/绿/红
```

对应关系：

```text
字母必须在仪表圆心上方
3 帧中至少 2 帧的 (区域, 状态) 一致才成功
成功后只播放一次音频
```

## 5. 返回示例

成功：

```json
{
  "ok": true,
  "area": "A",
  "state_key": "low",
  "level": "偏低",
  "status": "异常",
  "color": "yellow",
  "audio_file": ".../ALA.mp3",
  "letter_score": 0.88,
  "gauge_confidence": 1.0,
  "letter_above_gauge": true,
  "agree_frames": 2,
  "total_frames": 3,
  "error": null
}
```

失败时 `ok=false`，错误原因在 `error` 字段。

## 6. 可调参数位置

字母识别：

```text
whz/whz/letter_detector.py
```

常调内容：

```text
模板匹配阈值 min_score
字母候选区域大小过滤
白色面板上半部分搜索范围
```

仪表识别：

```text
whz/whz/gauge_detector.py
```

常调内容：

```text
深度平面容差 DEPTH_NEAR_MARGIN_M / DEPTH_FAR_MARGIN_M
黄/绿/红 HSV 阈值 COLOR_RANGES
指针方向颜色采样阈值
```

三帧投票：

```text
whz/whz/inspection_node.py
```

常调内容：

```text
REQUIRED_FRAMES = 3
MIN_AGREE_FRAMES = 2
FRAME_TIMEOUT_SEC = 2.0
```
