# ROS2 Scheme for arm_new

> 本文档中的 `FrameTransformer` / `frame_transforms.yaml` 方案已被运行时
> TF 查询替代。当前机械臂节点以
> `configs/transforms/static_extrinsics.yaml` 为唯一静态外参来源；具体运行
> 方式以 `ARM_MOTION_NODE_README.md` 为准。
>
> `arm_grasp_node` is retired for competition deployment because it subscribes
> to YOLO and selects its own target. Use `arm_motion_node` only, through
> `/arm/execute_grasp_fixed` and `/arm/execute_place_fixed`.

本文档说明如何将 `arm_new` 封装为 ROS2 节点，并接入四足机器人比赛工作空间。目标是在 Xavier CPU/GPU 资源有限的条件下，完成：

```text
深度相机 + YOLO 识别目标物块
    -> 得到目标在相机坐标系下的三维坐标
    -> 转换到机械臂坐标系
    -> 机械臂抓取红色物块
    -> 到固定放置点后释放
```

## 1. 基本假设

以下问题假设已经解决：

1. `/yolo/detections` 中的红色物块检测结果稳定包含 `distance_m`。
2. color/depth 已经对齐，`distance_m` 与 YOLO 输出的 `center` 像素属于同一彩色图坐标系。
3. `frame_id` 已统一，例如统一使用 `d455_color_optical_frame`。

机械臂与相机之间的真实外参暂时还没有实测，第一版先使用：

```text
arm_new/config/frame_transforms.yaml
```

其中的 `arm_from_camera` 矩阵作为占位外参。后续实测外参后，只需要更新该 YAML 文件。

## 2. 封装原则

Xavier 上 CPU 算力有限，因此机械臂 ROS2 节点不重复做视觉计算。

机械臂节点只做：

```text
轻量桥接 + 坐标转换 + 机械臂执行
```

机械臂节点不做：

```text
不运行 YOLO
不订阅 color/depth 图像
不做高频视觉闭环
不做导航
不调整四足机器人姿态
不判断异常区域
```

四足机器人的位置调整、正对物块、停稳、固定姿态，由任务管理器或后续运动控制模块完成。机械臂节点只在机器人停稳后，根据最新 YOLO 结果执行一次抓取。

## 3. 总体结构

推荐结构：

```text
arm_new
  纯 Python 机械臂 API，不直接绑定 ROS2

arm_new_ros / arm_grasp_node
  ROS2 适配层，订阅 YOLO 结果，提供抓取/释放 service
```

整体链路：

```text
/yolo/detections
    |
    v
arm_grasp_node
    |
    v
arm_new.arm_api.yolo_target
    YOLO JSON -> point_camera
    |
    v
arm_new.arm_api.transforms
    point_camera -> point_arm
    |
    v
arm_new planner/service
    机械臂规划、抓取、释放
```

## 4. 为什么不拆多个 ROS2 节点

不推荐拆成：

```text
target_locator_node
arm_transform_node
arm_planner_node
arm_executor_node
```

原因：

1. YOLO 结果到相机三维点只是 JSON 解析和针孔模型反投影，计算量很小。
2. 相机坐标到机械臂坐标只是一次矩阵变换。
3. 拆成多个节点会增加 ROS2 进程、话题传输、序列化、调度开销。
4. 当前只有机械臂抓取需要该三维坐标，没有必要长期发布一个额外的目标坐标话题。

因此推荐：

```text
计算逻辑单独封装为 API
ROS2 常驻节点只保留 arm_grasp_node 一个
```

也就是：

```text
arm_new/arm_api/yolo_target.py
    负责 YOLO JSON -> 相机坐标

arm_new/arm_api/transforms.py
    负责 相机坐标 -> 机械臂坐标

arm_grasp_node.py
    负责 ROS2 订阅、service、调用 arm_new API、执行抓取
```

## 5. arm_grasp_node 职责

`arm_grasp_node` 负责：

1. 订阅 `/yolo/detections`。
2. 缓存最新 YOLO JSON。
3. 在 service 被调用时检查检测结果是否过期。
4. 选择红色目标：

```text
class_id == 0
或
class_name == "red"
```

5. 调用 `yolo_payload_to_camera_point()` 得到相机坐标：

```text
point_camera = (x, y, z)
```

6. 调用 `FrameTransformer.camera_to_arm()` 得到机械臂坐标：

```text
point_arm = (x, y, z)
```

7. 调用 `arm_new` 中的 planner/service 执行 dry-run、真实抓取或固定释放。
8. 返回成功状态、错误信息和调试数据。

## 6. ROS2 输入输出

### 6.1 订阅话题

```text
/yolo/detections    std_msgs/String
```

期望 JSON 格式示例：

```json
{
  "header": {
    "stamp_sec": 0,
    "stamp_nanosec": 0,
    "frame_id": "d455_color_optical_frame"
  },
  "num_detections": 1,
  "detections": [
    {
      "class_id": 0,
      "class_name": "red",
      "confidence": 0.91,
      "bbox": [380, 230, 460, 290],
      "center": {"x": 420, "y": 260},
      "distance_m": 0.62
    }
  ]
}
```

### 6.2 推荐 service

为方便分块测试和最终任务执行，推荐在同一个 `arm_grasp_node` 中提供以下 service：

```text
/arm/debug_get_camera_target
/arm/debug_get_arm_target
/arm/dry_run_grab_red
/arm/grab_red
/arm/release_fixed
```

含义：

```text
/arm/debug_get_camera_target
    只测试 YOLO -> 相机坐标
    不动机械臂

/arm/debug_get_arm_target
    测试 YOLO -> 相机坐标 -> 机械臂坐标
    不动机械臂

/arm/dry_run_grab_red
    测试坐标转换 + 抓取规划
    不驱动舵机

/arm/grab_red
    完整真实抓取红色物块

/arm/release_fixed
    到达固定放置点后执行固定释放
```

## 7. 分块测试流程

### 7.1 测试 YOLO 输出

只运行相机和 YOLO，确认 `/yolo/detections` 中有红色目标。

```bash
ros2 topic echo /yolo/detections
```

需要确认字段：

```text
class_name: red
class_id: 0
center: {x, y}
distance_m: 正数
frame_id: d455_color_optical_frame
```

### 7.2 测试相机坐标

调用：

```bash
ros2 service call /arm/debug_get_camera_target ...
```

期望返回：

```json
{
  "ok": true,
  "message": "ok",
  "target_camera": {
    "x": 0.10,
    "y": 0.02,
    "z": 0.62
  },
  "frame_id": "d455_color_optical_frame"
}
```

该步骤只验证：

```text
YOLO center + distance_m -> point_camera
```

不控制机械臂。

### 7.3 测试机械臂坐标

调用：

```bash
ros2 service call /arm/debug_get_arm_target ...
```

期望返回：

```json
{
  "ok": true,
  "message": "ok",
  "target_camera": {
    "x": 0.10,
    "y": 0.02,
    "z": 0.62
  },
  "target_arm": {
    "x": 0.10,
    "y": 0.02,
    "z": 0.62
  }
}
```

当前外参是占位矩阵时，`target_camera` 和 `target_arm` 可能相同，这是正常现象。

### 7.4 测试抓取规划 dry-run

调用：

```bash
ros2 service call /arm/dry_run_grab_red ...
```

该步骤检查：

```text
目标点是否可达
IK 是否能解
抓取路径是否生成
舵机目标角度是否合理
```

不真实驱动舵机。

### 7.5 测试真实抓取

四足机器人需要先完成：

```text
调整位置
正对物块
停稳
固定姿态
```

然后调用：

```bash
ros2 service call /arm/grab_red ...
```

该步骤执行完整抓取。

### 7.6 测试固定释放

导航到固定放置区域后调用：

```bash
ros2 service call /arm/release_fixed ...
```

释放动作第一版可以写死，不需要视觉参与。

## 8. 与 task_manager 对接

比赛任务状态机中，机械臂节点建议接入以下阶段：

```text
FIND_RED_BAR
    等待 /yolo/detections 中出现 red

GRASP_BAR
    四足机器人调整到正对物块
    四足机器人停稳
    调用 /arm/grab_red

PLACE_TO_ABNORMAL_ZONE
    导航到 placement_A / placement_B / placement_C / placement_D
    四足机器人停稳
    调用 /arm/release_fixed
```

任务管理器负责：

```text
异常区域记录
导航阶段切换
四足机器人运动控制
调用机械臂 service
```

机械臂节点负责：

```text
坐标转换
抓取规划
抓取执行
固定释放
```

## 9. 推荐参数

`arm_grasp_node` 推荐参数：

```yaml
arm_grasp_node:
  ros__parameters:
    yolo_topic: "/yolo/detections"
    target_class_name: "red"
    target_class_id: 0
    min_confidence: 0.5
    expected_frame_id: "d455_color_optical_frame"
    transform_config: "arm_new/config/frame_transforms.yaml"
    max_detection_age_sec: 1.0
    dry_run_default: true
```

参数说明：

```text
yolo_topic
    YOLO 检测结果话题。

target_class_name / target_class_id
    默认抓取红色物块。当前协议建议 0=red, 1=green, 2=obstacle。

min_confidence
    过滤低置信度检测结果。

expected_frame_id
    用于检查 YOLO 坐标系是否符合预期。

transform_config
    坐标转换 YAML 路径。

max_detection_age_sec
    检测结果最大允许年龄，避免使用四足机器人移动前的旧结果。

dry_run_default
    调试阶段默认不真实驱动机械臂。
```

## 10. 推荐包结构

推荐新增独立 ROS2 包：

```text
arm_new_ros/
  arm_new_ros/
    arm_grasp_node.py
  srv/
    GetCameraTarget.srv
    GetArmTarget.srv
    GrabRed.srv
    ReleaseFixed.srv
  package.xml
  setup.py
```

`arm_new` 保持纯 Python API：

```text
arm_new/
  arm_api/
    yolo_target.py
    transforms.py
    planner_new.py
    service.py
  config/
    frame_transforms.yaml
  scripts/
    yolo_target_to_camera.py
    face_approach_grab.py
```

如果为了快速集成，也可以先把 `arm_grasp_node.py` 放入 quadruped 工作空间已有 ROS2 Python 包中，例如：

```text
src/nodes/arm/arm_grasp_node.py
```

但长期更推荐独立 `arm_new_ros` 包，边界更清晰。

## 11. 第一版实现建议

第一版可以按以下顺序实现：

1. 新建 `arm_grasp_node`，只订阅 `/yolo/detections` 并缓存最新 JSON。
2. 实现 `/arm/debug_get_camera_target`。
3. 实现 `/arm/debug_get_arm_target`。
4. 实现 `/arm/dry_run_grab_red`。
5. 实现 `/arm/grab_red`，真实控制机械臂。
6. 实现 `/arm/release_fixed`，固定释放。
7. 最后将 `task_manager` 的 `GRASP_BAR` 和 `PLACE_TO_ABNORMAL_ZONE` 接到对应 service。

## 12. 最终结论

最终推荐方案：

```text
arm_new 作为算法和机械臂执行库
arm_grasp_node 作为唯一常驻机械臂 ROS2 适配节点
调试能力通过多个 service 分层暴露
生产任务只调用 /arm/grab_red 和 /arm/release_fixed
```

该方案既方便单独测试：

```text
深度相机识别 -> 相机坐标 -> 机械臂坐标 -> 抓取规划 -> 真实抓取
```

也符合 Xavier 算力有限的约束，避免重复视觉计算和不必要的 ROS2 节点拆分。

## 13. 当前实现状态

已新增第一版 ROS2 适配包：

```text
arm_new/arm_new_ros/
  package.xml
  setup.py
  setup.cfg
  arm_new_ros/
    arm_grasp_node.py
```

当前实现采用 `std_srvs/Trigger`，不额外引入自定义 srv。service 的 `message` 字段返回 JSON，便于快速调试。

已实现 service：

```text
/arm/debug_get_camera_target
/arm/debug_get_arm_target
/arm/dry_run_grab_red
/arm/grab_red
/arm/release_fixed
```

安全策略：

```text
enable_motion 默认是 false
```

因此默认情况下：

```text
/arm/debug_get_camera_target    可用
/arm/debug_get_arm_target       可用
/arm/dry_run_grab_red           可用
/arm/grab_red                   会拒绝真实运动
/arm/release_fixed              会拒绝真实运动
```

需要真实驱动机械臂时，必须启动节点时设置：

```text
enable_motion:=true
```

## 14. 构建和启动示例

如果单独构建 `arm_new_ros`：

```bash
cd /path/to/arm_new
colcon build --packages-select arm_new_ros
source install/setup.bash
```

启动节点：

```bash
ros2 run arm_new_ros arm_grasp_node
```

真实运动模式：

```bash
ros2 run arm_new_ros arm_grasp_node --ros-args \
  -p enable_motion:=true \
  -p port:=/dev/ttyACM0
```

如果节点无法自动找到 `arm_new` 源码路径，可以显式设置：

```bash
export ARM_NEW_ROOT=/path/to/arm_new
ros2 run arm_new_ros arm_grasp_node
```

## 15. 当前测试命令

测试相机坐标：

```bash
ros2 service call /arm/debug_get_camera_target std_srvs/srv/Trigger {}
```

测试机械臂坐标：

```bash
ros2 service call /arm/debug_get_arm_target std_srvs/srv/Trigger {}
```

测试抓取规划 dry-run：

```bash
ros2 service call /arm/dry_run_grab_red std_srvs/srv/Trigger {}
```

真实抓取：

```bash
ros2 service call /arm/grab_red std_srvs/srv/Trigger {}
```

固定释放：

```bash
ros2 service call /arm/release_fixed std_srvs/srv/Trigger {}
```

注意：真实抓取和固定释放要求节点参数 `enable_motion` 为 `true`。
