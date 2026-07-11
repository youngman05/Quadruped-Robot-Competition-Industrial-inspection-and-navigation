# 四足机器人竞赛系统 — 开发上下文传递

## SSH 连接

```
IP: 100.126.48.49 (Tailscale)
用户: superwfx666
密码: superwfx
Tailscale SSH 已关, 普通 SSH 端口 22
```

## 架构总览

```
D455 → Docker(Humble): realsense + cuVSLAM → UDP 127.0.0.1:19001
                                                    ↓
Host(Foxy): final_bridge.py → /odom + TF → Navigator(A*+PurePursuit) → /cmd_vel
                         camera_relay → JPEG → whz(内嵌task_manager) → MP3播报
                         depth_relay  → RAW  → depth_publisher
```

## 启动命令

```bash
# 1. Docker
cd ~/quadruped-robot-competition
CUVSLAM_MOUNT_MODE=robot CUVSLAM_PROFILE=planar_60fps CUVSLAM_PUBLISH_ODOM_TO_BASE_TF=false CUVSLAM_PUBLISH_MAP_TO_ODOM_TF=false bash scripts/start_cuvslam_rviz_gui.sh --no-rviz > /tmp/cuvslam.log 2>&1 &
# 等 100 秒, docker ps | grep cuvslam 确认

# 2. 比赛系统
bash scripts/start_competition.sh

# 3. 停止
Ctrl+C 自动清场, 或 bash scripts/stop_all.sh
```

## 关键脚本

| 脚本 | 用途 |
|------|------|
| `scripts/start_competition.sh` | 一键启动所有(日志→~/Desktop/logs/) |
| `scripts/stop_all.sh` | 杀所有比赛进程, 不碰 Docker |
| `scripts/fix_bridge.sh` | 重装 UDP bridge |
| `scripts/final_bridge.py` | Host UDP→/odom (BEST_EFFORT QoS, KEEP_LAST depth=1) |
| `scripts/cuvslam_odometry_udp_exporter.py` | Docker内 odom→UDP |
| `scripts/probe_odom_best_effort.py` | /odom 探测(不能用ros2 topic echo) |

## 构建命令

```bash
cd ~/quadruped-robot-competition
colcon build --base-paths . src/whz --symlink-install
```

注意: 主包在 `.` (根目录), whz在 `src/whz/`。

## 已解决的问题

### 1. DDS 跨版本不通 (Humble↔Foxy)
**现象**: ros2 topic list 能看到topic, 但echo无数据
**方案**: 用UDP bridge替代DDS
- Docker内 `cuvslam_odometry_udp_exporter.py` 订阅odom→JSON→UDP 127.0.0.1:19001
- Host `final_bridge.py` 监听UDP→发布/odom (BEST_EFFORT)
- BEST_EFFORT QoS匹配, KEEP_LAST depth=1 避免积压
**注意**: FASTDDS inside Docker 关闭SHM (configs/ros/fastrtps_no_shm.xml)

### 2. CPU 满载
**现象**: gauge_status(83%) + loop_metrics(53%) + color_publisher(45%) + realsense+cuVSLAM(115%) = 400%+
**方案**:
- gauge_status 默认关闭 (whz内嵌替代)
- loop_metrics_recorder 在start脚本中自动kill
- color_image_publisher 删除 (whz直接读relay文件)
- whz检测只在观察位调一次, 不在后台跑

### 3. 相机中继 rclpy 崩溃
**现象**: `RCLError: failed to initialize wait set` 
**方案**: 重启Docker后可解决 (rclpy context是新docker里的干净状态)

### 4. launch文件找不到
**现象**: `file 'competition.launch.py' was not found in the share directory`
**原因**: setup.py缺少data_files
**修复**: 添加 data_files=["launch/competition.launch.py"]
**构建**: `colcon build --base-paths . src/whz --symlink-install` (主包在根目录)

### 5. Tailscale SSH blocked
**方案**: `sudo tailscale up --ssh=false` 关闭Tailscale SSH, 用普通SSH

### 6. Camera relay OpenCV error
**现象**: `could not find a writer for the specified extension`
**原因**: 临时文件后缀 `.jpg.tmp` OpenCV不识
**修复**: 改为 `latest_color_tmp.jpg`

## 导航系统

### 参数
- 障碍膨胀: 5cm (0.05m)
- 目标容差: 5cm (0.05m)
- 前视距离: 0.5m
- 最大线速度: 0.25 m/s
- 最大角速度: 0.5 rad/s
- 卡住检测: 10秒位移<5cm

### 航点
```
obstacle_exit: (600, 5250)mm = ROS(0.60, 0.75)m
grab_area: (4250, 3450)mm = ROS(4.25, 2.55)m
placement_A/B/C/D: y=600mm
```

### 相机TF
```
base_link → camera_link:
  x=0.080, y=0, z=0.493, roll=0, pitch=+30°, yaw=0
```

## whz 检测
- 字母识别: OpenCV模板匹配 A/B/C/D.png
- 仪表检测: 霍夫圆+霍夫线+HSV颜色采样
- 语音: mpg123播放MP3 (assets/audio/)
- 已内嵌到task_manager, 到观察位后拍1帧→识别→播报→关
- 不依赖ROS service, 不持续占CPU

## YOLO
- 默认开启 (enable_yolo:=true)
- 模型: src/cv/yolo_detector/projects/combined/model/best.pt
- 类别: 0=red, 1=green, 2=obstacle

## 已知待办
- 上狗实测导航 (需要切自动模式)
- YOLO锥桶检测→动态障碍注入A* (代码已写, 待验证)
- whz检测端到端验证 (需要对着柜面)
- CPU进一步优化 (camera_relay 100%, depth_relay 84%仍高)
- /odom在CPU高负载时掉到15Hz (空闲时60Hz), 需要上狗后看实际表现

## 常用排查
```bash
docker ps | grep cuvslam              # Docker在不在
tail -f /tmp/fb.log                    # bridge日志
tail -f /tmp/cuvslam.log               # Docker启动日志
python3 scripts/probe_odom_best_effort.py --duration 3  # odom探测
ps aux --sort=-%cpu | head -6          # CPU占用
ls ~/Desktop/logs/                     # 日志文件
```

## Jetson桌面
```
~/Desktop/
  monitor_cpu.sh          ← 实时监控
  logs/                   ← 比赛日志
  启动命令.txt             ← 启动命令
  temp/                   ← 旧脚本
```

## GPU监控
Jetson无nvidia-smi, 用 `sudo tegrastats` 或 `sudo timeout 2 tegrastats | head -1 | grep -oP 'GR3D_FREQ \K\d+'`
