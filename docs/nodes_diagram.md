# 项目节点关系图

> 更新时间: 2026-06-26

---

## 总览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           D455 深度相机                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐               │
│  │ RGB彩色   │  │ 深度图像  │  │ IR 双目   │  │ IMU      │               │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘               │
└───────┼──────────────┼──────────────┼──────────────┼───────────────────┘
        │              │              │              │
        ▼              ▼              └──────┬───────┘
┌──────────────┐ ┌──────────────┐           │
│ gauge_status │ │ yolo_detect  │      ┌────▼─────────┐
│ _publisher   │ │ _publisher   │      │  cuVSLAM      │
│              │ │              │      │ (Docker)      │
│ 发布:        │ │ 发布:        │      │               │
│ /gauge/status│ │ /yolo/detect │      │ 发布:         │
│ /gauge/detect│ │ /yolo/image  │      │ /visual_slam/ │
│              │ │ /yolo/count  │      │   tracking/   │
└──────┬───────┘ └──────┬───────┘      │   odometry    │
       │                │              │ /visual_slam/ │
       │                │              │   status      │
       │                │              └──────┬────────┘
       │                │                     │
       ▼                ▼                     ▼
┌──────────────────────────────────────────────────────────────┐
│                      task_manager                             │
│  订阅: /gauge/status, /yolo/detections, /visual_slam/status  │
│  发布: /task/phase, /task/status, /speech/text               │
│  调用: NavigationClient → Nav2                               │
└──────┬──────────────────────────────────┬────────────────────┘
       │                                  │
       ▼                                  ▼
┌──────────────┐                  ┌──────────────┐
│ speech       │ ⏳                │ arm_control  │ ⏳
│ _publisher   │ 未实现            │              │ 未实现
│              │                   │              │
│ 应订阅:      │                   │ 应接收:      │
│ /speech/text │                   │ 抓取/放置指令 │
└──────────────┘                   └──────────────┘
```

---

## 详细节点

### ✅ 已实现

#### `gauge_status_publisher` — 仪表检测
```
src/nodes/perception/gauge_status.py

订阅: (无)
发布:
  /gauge/status          String(JSON)  仪表完整结果
    {
      stable_detected:   bool,         // 连续3帧一致
      stable_color:      "yellow|green|red",
      stable_level:      "偏低|正常|偏高",
      stable_status:     "异常|正常",
      stable_angle:      float,        // 指针角度
      color_coverage:    {...},        // 颜色覆盖统计
      direction_scores:  {...}         // 各颜色方向得分
    }
  /gauge/detected        Bool          当前帧是否有效
```

#### `yolo_detect_publisher` — YOLO 实例分割
```
src/nodes/perception/yolo_detect_publisher.py

订阅: (无)
发布:
  /yolo/detections       String(JSON)  检测结果列表
    {
      detections: [
        {
          class_id:   0|1|2,           // 0=red,1=green,2=obstacle
          class_name: "red|green|obstacle",
          confidence: float,
          bbox:       [x1,y1,x2,y2],
          center:     {x, y},
          mask_area_px: int,
          distance_m: float,           // 有深度数据时才返回
        }, ...
      ]
    }
  /yolo/image            Image(rgb8)   标注后的画面
  /yolo/instance_count   Int32         检测到的实例总数
```

#### `task_manager` — 比赛状态机
```
src/nodes/decision/task_manager.py

订阅:
  /gauge/status          → _on_gauge_status()    填充 A/B/C/D 仪表槽位
  /yolo/detections       → _on_yolo_detections() 收集红条/绿条
  /visual_slam/status    → _on_slam_status()     追踪定位是否正常

发布:
  /task/phase            String        当前阶段名 "pass_obstacle" 等
  /task/status           String(JSON)  完整状态
    {
      phase:              str,           // 当前阶段
      phase_label:        str,           // 中文名
      phase_elapsed_s:    float,         // 已用时
      timeout_s:          float,         // 超时上限
      slam_ok:            bool,          // 定位是否正常
      abnormal_zones:     ["A","C"],     // 异常仪表列表
      abnormal_handled:   1,             // 已处理几个
      navigation:         {...},         // 导航状态
      gauges: {A:{...}, B:{...}, ...},   // 四个仪表结果
      yolo:      {num_red_bars, ...}     // YOLO 汇总
    }
  /speech/text           String        播报文本 "A区仪表显示偏低，状态异常"

内部调用:
  NavigationClient → Nav2 action 服务器
```

#### `depth_publisher` — D455 深度发布
```
src/nodes/navigation/depth_publisher.py

订阅: (无)
发布:
  /camera/depth/image_raw    Image(16UC1)   深度图 (mm)
  /camera/depth/camera_info  CameraInfo     深度相机内参
```

#### `cuvslam_bridge` — cuVSLAM 状态翻译 (已简化)
```
src/nodes/navigation/cuvslam_bridge.py

订阅:
  /visual_slam/status  → 翻译为 ok/lost

发布:
  /slam/status         String      "ok" | "lost"

注: /odom 和 TF 不再由本节点发布 — 改由 EKF 融合后统一输出。
```

#### `initial_pose_publisher` — 初始位姿
```
src/nodes/navigation/initial_pose_publisher.py

订阅: (无)
发布:
  /initialpose     PoseWithCovarianceStamped  机器人起始位姿
  TF: map → odom   (静态, latched)
```

---

### ⏳ 待实现

#### `speech_publisher` — 语音播报
```
src/nodes/decision/speech.py   ← 目前只有占位骨架

应订阅:
  /speech/text          String        task_manager 发出的播报文本
应发布:
  (音频输出, 具体方案待定: TTS / 预录音频拼接)
```

#### `arm_control` — 机械臂控制
```
src/arm_control/README.md   ← 只有设计文档

应接收:
  GRASP_BAR / PLACE_TO_ABNORMAL_ZONE 阶段的触发指令
应返回:
  抓取/放置成功或失败
```

#### `ir_imu_bridge` — D455 IR/IMU 桥接
```
(尚未创建, launch 文件中留有注释)

应发布:
  将 D455 红外双目 + IMU 数据发布为 ROS 话题
  供 cuVSLAM Docker 容器消费
```

---

### 🔵 EKF 定位融合 (robot_localization)
```
configs/navigation/ekf.yaml

  ┌─ /leg_odom2          (腿里程计, 稳定但漂移)
  ├─ /imu/data           (IMU, 高频, 方向准)
  └─ /visual_slam/tracking/odometry (cuVSLAM, 无漂但可能丢)
              │
              ▼
         ekf_node (EKF 50Hz)
              │
              ▼
       /odom (融合输出, 给 Nav2)
       TF: odom → base_link
```

### 🔵 ROS2 内置节点 (由 navigation.launch.py 启动)

```
map_server
  发布: /map              OccupancyGrid   PGM 静态地图

planner_server (A* / NavFn)
  订阅: /map, /tf
  发布: /plan             Path            全局路径

controller_server (RegulatedPurePursuit / TEB)
  订阅: /plan, /odom, /tf, /local_costmap
  发布: /cmd_vel          Twist           机器人速度指令

point_cloud_xyz_node (depth_image_proc)
  订阅: /camera/depth/image_raw, /camera/depth/camera_info
  发布: /camera/depth/points   PointCloud2  供 costmap 障碍层使用
```

### 🔷 Docker 外部容器

```
cuVSLAM (Isaac ROS Humble)
  输入: D455 IR 双目 + IMU (通过 ir_imu_bridge)
  发布:
    /visual_slam/tracking/odometry → EKF (融合用)
    /visual_slam/status            → cuvslam_bridge (状态翻译)
    TF: odom → camera_pose
```

---

## 话题流程图

```
                          D455 相机
                   _________|_________
                  |    |      |       |
          [RGB]   |  [深度] [IR双目] [IMU]
            |     |     |      |       |
            ▼     ▼     |      |       |
    ┌─────────┐ ┌───────┴──┐   |       |
    │ gauge   │ │ yolo     │   |       |
    │_status  │ │_detect   │   |       |
    │         │ │          │   |       |
    │/gauge/  │ │/yolo/    │   |       |
    │ status  │ │detections│   |       |
    │/gauge/  │ │/yolo/    │   |       |
    │ detected│ │image     │   |       |
    └────┬────┘ └────┬─────┘   |       |
         │           │         |       |
         └─────┬─────┘         |       |
               ▼               |       |
         ┌──────────┐          |       |
         │  task    │◄─────────┘       |
         │ _manager │                  |
         │          │                  |
         │/task/    │    ┌─────────────┘
         │ phase    │    │
         │/task/    │    ▼
         │ status   │  ┌─────────────┐
         │/speech/  │  │ cuVSLAM     │
         │ text     │  │ (Docker)    │
         └────┬─────┘  │             │
              │        │/visual_slam/│
    ══════════╪════════│ tracking/   │
    ⏳ 未实现  │        │ odometry    │
    ══════════╪════════│/visual_slam/│
         ┌────▼────┐   │ status      │
         │ speech  │   └──────┬──────┘
         │_publish │          │
         └─────────┘          ▼
              ⏳         ┌──────────────┐
                         │ cuvslam      │
                         │ _bridge      │
                         │              │
                         │ /odom        │
                         │ /slam/status │
                         └──────┬───────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
              ▼                 ▼                 ▼
        ┌──────────┐    ┌──────────────┐   ┌──────────────┐
        │ map_     │    │ depth_       │   │ initial_pose │
        │ server   │    │ publisher    │   │ _publisher   │
        │          │    │              │   │              │
        │ /map     │    │/camera/depth/│   │ /initialpose │
        └────┬─────┘    │ image_raw    │   │ TF:map→odom  │
             │          │/camera/depth/│   └──────────────┘
             │          │ camera_info  │
             │          └──────┬───────┘
             │                 │
             │          ┌──────▼───────┐
             │          │ point_cloud  │
             │          │ _xyz (proc)  │
             │          │              │
             │          │/camera/depth/│
             │          │ points       │
             │          └──────┬───────┘
             │                 │
             └────────┬────────┘
                      ▼
              ┌───────────────┐
              │  Nav2 导航栈   │
              │               │
              │ planner(A*)   │
              │ controller(RPP)│
              │ costmap       │
              │               │
              │ /plan         │
              │ /cmd_vel      │
              └───────┬───────┘
                      │
                      ▼
              ┌───────────────┐
              │   机器人底盘   │
              │  (Jueying Lite)│
              └───────────────┘
```

---

## 数据流总结

| 发布者 | 话题 | 类型 | 订阅者 |
|--------|------|------|--------|
| gauge_status_pub | `/gauge/status` | String JSON | task_manager |
| gauge_status_pub | `/gauge/detected` | Bool | (RViz 调试) |
| yolo_detect_pub | `/yolo/detections` | String JSON | task_manager |
| yolo_detect_pub | `/yolo/image` | Image rgb8 | (RViz 调试) |
| yolo_detect_pub | `/yolo/instance_count` | Int32 | (监控) |
| task_manager | `/task/phase` | String | (外部监控) |
| task_manager | `/task/status` | String JSON | (外部监控) |
| task_manager | `/speech/text` | String | speech_pub ⏳ |
| depth_publisher | `/camera/depth/image_raw` | Image 16UC1 | point_cloud_xyz |
| depth_publisher | `/camera/depth/camera_info` | CameraInfo | point_cloud_xyz |
| point_cloud_xyz | `/camera/depth/points` | PointCloud2 | Nav2 costmap |
| cuVSLAM Docker | `/visual_slam/tracking/odometry` | Odometry | cuvslam_bridge |
| cuVSLAM Docker | `/visual_slam/status` | String | cuvslam_bridge, task_manager |
| cuvslam_bridge | `/odom` | Odometry | Nav2 controller |
| cuvslam_bridge | `/slam/status` | String | (监控) |
| map_server | `/map` | OccupancyGrid | Nav2 planner, costmap |
| planner_server | `/plan` | Path | Nav2 controller |
| controller_server | `/cmd_vel` | Twist | 机器人底盘 |
