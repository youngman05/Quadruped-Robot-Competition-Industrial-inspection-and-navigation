# WHZ Inspection Package

`whz` 是源码树内的配电柜巡检识别 Python package，用于 ROS2 `/whz/inspect` 服务。

固定流程：

```text
订阅 /camera/color/image_raw
订阅 /camera/aligned_depth_to_color/image_raw
调用 /whz/inspect
等待 3 帧新彩色图像，并使用最近一次对齐深度图
OpenCV 识别 A/B/C/D 区域，在最近深度平面内识别仪表状态
至少 2 帧一致才成功
播放对应 MP3 一次
service 返回 JSON
```

完整使用说明见 [USAGE.md](USAGE.md)。
