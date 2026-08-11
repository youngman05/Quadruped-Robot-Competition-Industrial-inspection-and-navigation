# WHZ Inspection Package

`whz` 是独立的 ROS 2 配电柜巡检 package，不依赖 D455 ROS 图像 topic。

```text
Lite3 前置 RTSP -> 3 个不同新帧 -> YOLO 字母/仪表检测
-> 空间配对 -> 至少 2 帧一致 -> 播放一次 MP3 -> Trigger JSON
```

固定接口：

```bash
ros2 service call /whz/inspect std_srvs/srv/Trigger {}
```

完整部署、参数和验证说明见 [USAGE.md](USAGE.md)。
