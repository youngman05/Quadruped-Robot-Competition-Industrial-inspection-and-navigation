# 2026-08-09VersionDifference

## 1. 文档目的

本文记录 `feature/vision-change` 在 2026-08-09 的主要能力、相对共同基线的
接口变化、尚未完成的接线，以及与 navigation/SLAM 工作合并时的责任边界。
它不是现场标定值来源；所有生产点位以
`configs/calibration/competition_sites.yaml` 为准。

当前协作分工：

- navigation/SLAM 负责人：地图、定位、Nav2 参数、固定狗位姿到达与底盘速度接口；
- 本分支负责人：视觉/深度目标、TF 外参、状态机、机械臂规划与 ROS 服务；
- 共享边界：`competition.launch.py`、`task_manager.py`、静态 TF、点位标定集合、
  ROS topic/service/action 契约。

## 2. 本版本已有改动

### 2.1 D455 与目标坐标

- 增加 Docker 内 D455 YOLO 3D 推理和 Host UDP 接收链路；
- 定义检测 JSON schema、sequence/timestamp/frame 等协议字段；
- Host 将目标从 `camera_link` 转到 `base_link`；
- 增加采样、拟合和记录相机外参的脚本；
- `configs/transforms/static_extrinsics.yaml` 成为项目静态外参唯一真值来源。

### 2.2 机械臂

- 新增独立 `arm_new` Python 规划与 BusLinker 执行层；
- 新增 `arm_new_interfaces` 和生产 `arm_motion_node`；
- 提供 `/arm/preflight`、`/arm/execute_grasp_fixed`、
  `/arm/execute_place_fixed` 三个服务；
- 抓取复用水平端面接近、闭合和抬升序列，放置复用固定 TCP 释放序列；
- 真机动作受 `enable_motion`、TF 标定和点位 configured 标志门控；
- 增加纯规划单元测试和 Xavier 构建/部署说明。

### 2.3 状态机设计

- 明确 I0 是固定 `map` 粗定位航点，I1 是动态视觉细对齐状态；
- 明确状态机锁定目标、分轴脉冲控制、最终 z 多帧确认和服务幂等要求；
- 明确只有机械臂服务返回成功后才能推进抓取/放置任务；
- 当前 `task_manager.py` 的抓取和放置阶段仍含占位推进逻辑，完整 I1 控制和机械臂
  service client 尚未落地，不能将设计文档误认为实现已经完成。

### 2.4 参数整理

- 新增 `configs/calibration/competition_sites.yaml`，统一描述 I0、I1、A/B/C/D、
  公共释放点和 smoke-test z；
- 新增 `configs/ros/task_manager_params.yaml`，状态机参数不再混在所有节点共用的
  `competition_params.yaml` 中；
- `competition.launch.py` 已让 task manager 使用独立参数文件；
- 空间配置目前是整合契约，navigation 和 arm 节点尚未加载它；接线完成前仍不能
  删除节点现有参数或硬编码值。

## 3. 与 navigation/SLAM 当前实现的已知差异

### 3.1 航点存在双源

`src/navi/navigation_client.py` 仍在 `_RAW_WAYPOINTS` 中硬编码航点，新的
`competition_sites.yaml` 尚未被读取。最终版本必须只保留后者作为生产真值，
`NavigationClient` 只接收加载后的 waypoint registry 或明确的 pose。

### 3.2 I0 数值冲突

当前 `navigation_client.py` 中 `grab_area=(4250,3450)` 经现有转换约为 ROS
`(4.25,2.55)`，而 `src/navi/README.md` 给出的候选值为 `(3.60,2.00)`，且 yaw
定义也不同。因此统一配置把 `grasp_i0` 标为 `conflict`，合并时不能任选一个，
必须在最终 SLAM map 上读取 `map -> base_link` 重新标定。

### 3.3 yaw 语义不一致

当前 I0 和 A/B/C/D 的 `yaw_deg=None` 最后仍会向 Nav2 发送单位四元数，实际相当于
yaw=0，而不是“不限制朝向”。抓取与固定放置必须使用明确 yaw；同事侧应移除
`None` 约定或实现真正支持未指定朝向的行为。

### 3.4 地图和坐标约定

场地模型内部使用毫米、左上原点、y 向下；ROS Nav2 使用米、`map` 原点和 REP-103。
最终现场站位必须直接保存 ROS `map` 位姿，禁止在多个模块重复坐标转换。
`competition_sites.calibration_set.map_id` 必须与实际加载地图一致。

### 3.5 速度控制所有权

Nav2 与 I0->I1 细对齐都会控制底盘。合并前必须确定唯一 `/cmd_vel` 仲裁方案：

1. Nav2 goal 完成并确认取消；
2. Nav2 输出被停用或通过 velocity mux 失去优先权；
3. 状态机才允许发布细对齐短脉冲；
4. 目标丢失、检测过期、超时或状态退出时立即发布零速度。

不能让 Nav2 和状态机同时向同一个底盘入口发送速度。

## 4. 合并时必须保持的接口契约

| 边界 | 最终约定 |
| --- | --- |
| 全局定位 | 持续可用的 `map -> base_link` |
| 固定狗位姿 | `map` 中 `[x_m, y_m, yaw_rad]` |
| Nav2 调用 | `NavigateToPose`，必须区分 accepted/running/succeeded/failed/canceled |
| 检测输入 | 带 sequence、时间戳和明确 frame 的 3D 目标 |
| I1 条件 | 目标在 `arm_base_link` 接近 `[0.42,0.00,z_final]` |
| 抓取服务 | `/arm/execute_grasp_fixed`，动作完成后才返回成功 |
| 放置服务 | `/arm/execute_place_fixed`，动作完成后才返回成功 |
| 静态 TF | 只允许一个 launch 发布项目静态外参 |
| 底盘停车 | 任一错误/超时/目标丢失都必须有显式零速度语义 |

Docker 中 cuVSLAM 使用 ROS 2 Humble，Host 生产节点使用 ROS 2 Foxy；现有设计通过
UDP 数据协议跨越该边界。不要直接假定两个 ROS domain 中的自定义消息、QoS 或
action 可以互通。

## 5. 推荐合并顺序

1. 从双方认可的最新 navigation/SLAM 分支创建新的 integration 分支；
2. 先保留同事侧 `src/navi/`、`configs/navigation/`、navigation launch 和 SLAM
   启停脚本，不用本分支旧副本整体覆盖；
3. 引入视觉 UDP、schema、静态 TF、`arm_new` 和机械臂接口等独立目录；
4. 对 `setup.py`、`package.xml`、`competition.launch.py`、`task_manager.py` 等共享
   文件逐段人工合并；
5. 由 navigation/SLAM 负责人把固定狗位姿接到 `competition_sites.yaml`，并删除
   `_RAW_WAYPOINTS` 生产硬编码；
6. 由状态机/机械臂负责人让 I1 对齐和 arm node 使用同一标定集合；
7. 双方共同完成 cmd_vel 仲裁、Nav2 取消确认和整机状态门控；
8. 分层测试通过后再标记 `calibration_set.id`，最后进行两趟完整流程。

不建议直接把 `feature/vision-change` 整分支 merge 到同事最新分支。该分支历史中
包含导航目录迁移、旧导航文件删除和 launch 修改，直接合并容易把同事的新实现
覆盖成较旧版本。独立目录可 merge/cherry-pick，共享文件应人工审查。

## 6. 联合验收清单

- 同一地图重启 SLAM 后，各固定站位重复到位 3 至 5 次；
- I0 到位后 Nav2 已停止，状态机才取得速度控制权；
- I1 对齐使用的 x/y 与机械臂规划使用的 x/y 来自同一标定集合；
- 检测过期、目标丢失、Nav2 失败、服务失败均不会推进任务索引；
- `/arm/preflight` 能看到 TF、串口和 1 至 6 号舵机；
- `enable_motion=false` 下完成完整 dry-run；
- 单区完成抓取、持物导航、固定放置，再分别验证 A/B/C/D；
- 公共释放点改变后重新验收全部 A/B/C/D；
- 日志记录 Git commit、地图 ID 和 `calibration_set.id`；
- 第一趟成功后回 I0，第二趟成功后进入 FINISH。
