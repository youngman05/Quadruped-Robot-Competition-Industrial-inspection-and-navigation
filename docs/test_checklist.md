# Test Checklist

## Gauge ROS2 Node Read-Only Check

- [ ] ROS2 Foxy environment is sourced.
- [ ] D455 is connected and visible.
- [ ] `scripts/gauge_status_node.py` starts without crashing.
- [ ] `/gauge/status` publishes JSON status messages.
- [ ] `/gauge/detected` publishes `std_msgs/msg/Bool`.
- [ ] No gauge in view does not produce a valid detection.
- [ ] A valid gauge in view produces stable `detected=true` output.

Useful commands:

```bash
cd ~/quadruped-robot-competition
source /opt/ros/foxy/setup.bash
python3 scripts/gauge_status_node.py
```

In another terminal:

```bash
source /opt/ros/foxy/setup.bash
ros2 topic list | grep gauge
timeout 5s ros2 topic echo /gauge/status
timeout 5s ros2 topic echo /gauge/detected
```

## 上电前

- [ ] 电池电量充足。
- [ ] 急停或遥控接管可用。
- [ ] Jetson 可 SSH 登录。
- [ ] D455 固定牢靠。
- [ ] 机械臂/夹爪固定牢靠。
- [ ] 场地无人员危险接近。

## 环境检查

```bash
bash scripts/check_jetson_env.sh
```

确认：

- [ ] `cv2` 可导入。
- [ ] `pyrealsense2` 可导入。
- [ ] `tensorrt` 可导入。
- [ ] D455 出现在 USB 和 RealSense device list 中。

## CV 单模块

- [ ] D455 RGB 图像正常。
- [ ] D455 depth 图像正常。
- [ ] 仪表盘能检测。
- [ ] 状态能输出：偏低/正常/偏高。
- [ ] A/B/C/D 能识别。
- [ ] 红/绿长条能识别。

## 系统联调

- [ ] 机器人能移动到检测区。
- [ ] 到点后能触发视觉识别。
- [ ] 终端中文输出正确。
- [ ] 语音播报正确。
- [ ] 异常区域被记录。
- [ ] 能找到红色长条。
- [ ] 能输出抓取目标坐标。
- [ ] 机械臂抓取流程可执行。
- [ ] 放置到对应区域。

## 测试后记录

- [ ] 保存失败截图或视频。
- [ ] 保存日志。
- [ ] 记录失败原因分类：识别/定位/导航/抓取/环境。
- [ ] 形成下一次修改任务。
