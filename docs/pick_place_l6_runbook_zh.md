# L6 抓放运行手册

本手册只覆盖抓放路线的正式部署、无动作 preflight、无运动 ROS 启动检查和现场最小验证。当前策略以比赛得分为优先：`competition_v1` 固定抓放预设是主路径，AprilTag I2 抓取精对齐和 J1 视觉放置只是可选增强。仓库默认配置保持 fail-closed；未经现场明确授权不得运行 `scripts/start_l6_pick_place.sh`，不得下发导航或机械臂运动命令。

## 当前结论

| 项目 | 状态 | 说明 |
|---|---|---|
| 统一镜像无相机 verifier | PASS | 镜像 `sha256:f7384634ab69256558415a074d4ad53774f2399390ddcdc7135f2c33415fb5a0` 已在 `--runtime nvidia --network none` 下通过 `pip/nms/warmup/synthetic_udp` |
| 固定抓放预设 | 待现场验证 | TaskManager 和机械臂 YAML 必须同时选择 `competition_v1`，并提供已验证的固定抓取、固定放置、夹爪脉冲和动作时序 |
| I2 AprilTag 抓取精对齐 | 可选 | 关闭或检测/对齐失败时，回退抓取区固定偏移和固定抓取预设 |
| J1 视觉放置 | 可选 | 关闭或检测/对齐失败时，回退 J0 固定位置和固定放置预设 |
| 机械臂真实抓持反馈 | 不具备 | 服务 success 只表示动作序列无异常完成，不证明已经抓住、仍持有或成功放下物体 |
| 完整 L6 | 待现场监督 | 当前交付只完成到无运动启动与图/参数/服务检查，不发送导航或机械臂动作 |

## 比赛运行策略

- 感知、I2/J1 对齐或抓放结果失败时，记录对应 outcome 为 `uncertain`，按固定预设或下一任务继续比赛。
- 第四次仪表识别/播报后立即冻结两个不同任务：2 个异常直接使用；1 个按 `abnormal_zone_fallback_order` 补 1 个；0 个取配置前两个；3-4 个按异常投票置信度取前两个。
- 抓放模式固定加载 `waypoints_real.yaml/full_interleaved`，TaskManager 动态发送 `grab -> zone_1 -> grab -> zone_2`，不会顺序执行路线文件中的全部放置区。
- 未收到真实抓持反馈时，不把 ROS 服务 success 记为物理抓取成功；它只表示 `motion sequence completed`。
- 抓取区或放置区单点 Nav2 最多执行配置的有限重试；最终失败时跳过该轮机械臂动作并继续下一冻结任务。定位/里程计失效、启动所有权不唯一、速度发布冲突、关键启动失败或急停条件仍是硬故障，必须进入 `ABORT`。
- 一旦抓取或放置请求已经发出，即使 ROS future 报错、超时或被取消，也不能认为舵机动作已经停止。底盘必须持续保持零速度，直到 `max_arm_sequence_sec` 保护时长结束。

## Formal Deploy 门禁

正式部署必须满足：

- checkout 为目标 exact commit，`git status --porcelain --untracked-files=no` 无输出；
- Foxy install 在同一 formal deploy 中包含 `quadruped_robot_competition`、`whz`、`arm_new_interfaces`、`arm_new_ros`；
- `competition.launch.py`、选中的抓放配置和机械臂配置来自该 checkout；
- Host producer/consumer 使用七类协议 `competition-ad-yellow-red-green-v1`；
- 镜像标签解析到已验证的不可变 image ID，而不只是同名 tag；
- preflight 前没有相关容器、ROS、Nav2、D455、机械臂或 Lite3 控制进程残留。

建议把每次 formal build 放到全新的 `build/install/log` 目录，避免旧 install 残留文件被误用。构建后先检查四个包的 `ros2 pkg prefix`，不要仅凭 `colcon build` 成功判断部署可用。

## 固定预设与运动授权

选中的两份 YAML 必须形成同一套固定预设：

```yaml
# TaskManager
manipulation_preset: competition_v1
abnormal_zone_fallback_order: [A, B, C, D]
pick_red_tag_ids: [<pickup_tag_1>, <pickup_tag_2>]
enable_pick_i2_alignment: false
enable_place_vision_alignment: false
arm_service_timeout_sec: 30.0

# Arm motion
arm_preset: competition_v1
max_arm_sequence_sec: 20.0
grasp_reference_configured: true
place_target_configured: true
enable_motion: false
```

还必须验证固定抓取目标、固定放置参考、夹爪开合脉冲、下探/抬升距离和每段动作持续时间。`arm_service_timeout_sec` 不得小于 `max_arm_sequence_sec`。

配置 YAML 中的 `enable_motion` 必须始终保持 `false`，避免配置文件本身成为运动授权。运动授权由启动入口单独处理：

- 无动作 preflight 强制使用 `ARM_MOTION_AUTHORIZED=false`。
- 完整启动在运动授权方面只接受操作者显式设置的 `ARM_MOTION_AUTHORIZED=true`。
- 不再要求审批人与操作者不同、正式审批 manifest、完整标定证据包或所有配置文件哈希。
- 固定预设不使用实时坐标变换时，完整相机内外参和精确 `base_link -> arm_base_link` TF 匹配不是硬门禁。

两个实际抓取 Tag ID 始终必须填写且必须不同。第一轮优先选择尚未使用且当前可见的 Tag，第二轮排除第一轮已经锁定的 Tag。关闭 I2 时不需要填写 I2 目标表；启用对应增强功能时，再补齐其参数：

- `enable_pick_i2_alignment: true`：需要实测 tag size、两个 ID 对应的 I2 目标和 AprilTag 数据链；两个 Tag 可以使用同一个已测试的期望相对位姿。
- `enable_place_vision_alignment: true`：需要 J1 使用的 RGB-D/安装参数和 `place_target_distance_m`。

## 无动作 Preflight

确认机械臂运动未授权且系统无相关残留后，运行：

```bash
bash scripts/preflight_l6_pick_place.sh
```

该入口会：

- 强制设置 `ARM_MOTION_AUTHORIZED=false`；
- 校验 exact source commit、tracked-clean 状态和 formal install 来源；
- 校验两份 YAML 都选择 `competition_v1`、固定抓放参数完整且动作时序一致；
- 仅在启用 I2/J1 时校验对应的可选视觉参数；
- 校验模型 hash、不可变 image ID 和七类 Host 协议；
- 使用唯一容器名执行有超时的 `--runtime nvidia --network none` verifier；
- 在相机、cuVSLAM、Nav2、机械臂服务和 Lite3 motion-mode 准备之前退出，并清理 verifier 容器。

看到 `GO: pick/place preflight passed` 只表示离线和无动作门禁通过，不表示允许启动完整路线或机械臂运动。

## 无运动 ROS 启动检查

离线 preflight 通过后，可以在 Jetson 上启动不具备运动授权的完整 ROS 图：

```bash
bash scripts/start_l6_pick_place_no_motion.sh
```

该入口不会启用 Lite3、不会启动 cmd_vel bridge、不会准备 motion mode，机械臂保持 `ARM_MOTION_AUTHORIZED=false`，TaskManager 保持 `mission_start_armed=false`。此时 `/arm/preflight` 只验证固定抓放规划和时长，不打开串口扫描舵机；正式运动授权启动仍要求舵机在线。它只用于检查节点、服务、实时参数、`full_interleaved` 航点来源和启动入口。检查完成后执行 `bash scripts/stop_all.sh` 并复核无残留。

## Preflight 后残留检查

```bash
docker ps --format '{{.ID}} {{.Names}} {{.Image}}'
pgrep -af 'ros2|realsense|visual_slam|nav2|apriltag|yolo|task_manager|arm_motion|lite3|cmd_vel'
ss -lunp | grep -E ':(19002|19003|19004)\b' || true
```

预期结果是没有相关运行容器、控制进程或 UDP listener。发现残留时保持 NO-GO，记录 PID、命令行、容器 ID 和日志后再处理。

## 现场最小验证

完整 L6 前只需围绕实际比赛预设完成以下验证，不构造产品验收式证据包：

1. 在清空工作区、最低速度和人工监督下，验证固定抓取目标、固定放置参考、夹爪开合脉冲、下探/抬升距离与动作持续时间。
2. 确认最慢一次完整动作不超过 `max_arm_sequence_sec`，并实测请求发出后底盘在保护时长内保持静止。
3. 填写两个实际 pickup Tag ID；只有计划启用 I2 时，才额外验证 AprilTag 尺寸、I2 目标和失败回退。
4. 只有计划启用 J1 时，才验证视觉放置参数、目标距离和 J0 失败回退。
5. 分别记录服务返回、实际观察结果和 `uncertain` outcome；不得用服务 success 代替真实抓持证据。

## 停机边界

- `scripts/stop_all.sh` 可停止本仓库基础栈并发送底盘零速度，但不能证明已取消机械臂内已提交的舵机动作。
- 物理断能或经实测有效的厂商 cancel/hold/e-stop 是现场安全手段，不需要为本次比赛额外构造正式审批包。
- 机械臂请求发出后，软件必须先执行 `max_arm_sequence_sec` 保守等待；现场人员仍应能立即使用物理断能或已验证的停机手段处理危险情况。
- 未经用户明确现场授权和监督，不得运行 `scripts/start_l6_pick_place.sh`。

## 完整启动边界

只有 exact deploy、四包构建、七类协议、固定 `competition_v1` 预设、无残留/所有权冲突和现场最小验证都确认后，才可在后续受监督任务中考虑：

```bash
ARM_MOTION_AUTHORIZED=true bash scripts/start_l6_pick_place.sh
```

该入口会固定加载 `waypoints_real.yaml/full_interleaved`，准备 Lite3 motion mode、启动相机/导航/机械臂/TaskManager，并在最终启动检查后设置 `mission_start_armed=true`。它不是诊断或无动作入口；上面的命令仅说明授权方式，不授权本任务执行。

当前正式部署 `16ad08c` 另提供现场专用的纯启动封装：

```bash
bash scripts/start_l6_pick_place_test_16ad08c.sh
```

该封装只切换到 `/home/superwfx666/worktrees/quadruped-pick-place-formal-16ad08c`，注入已冻结的两份外部 YAML、source commit、镜像及运动授权，然后通过 `exec` 进入已部署版本的正式启动器。它设置已有的 `PURE_L6_START=true` 分支，并传入与正式 L6 入口相同的 `--pick-place-l6 --dog --cmd-vel-bridge --prepare-lite3-motion`：正式栈启动后直接以 armed 状态交给 TaskManager 执行完整两轮任务，不再执行启动器后半段的 ROS 图、QoS、参数和健康轮询。它不启动监控进程，不复制 TaskManager 航点逻辑；正式启动器在启动前仍保留 source/config/image 基线门禁、命令仲裁和故障清理。这个脚本是面向已冻结 `16ad08c` worktree 的单文件辅助入口，复制进去不会改变 tracked-clean 判定或要求重建四包。运行该脚本本身即代表现场监督者已完成运动授权，并确认外部 TaskManager YAML 中的两个 `pick_red_tag_ids` 是本轮实际抓取 Tag。
