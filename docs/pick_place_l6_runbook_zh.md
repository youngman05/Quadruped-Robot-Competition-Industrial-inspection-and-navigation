# L6 抓放运行手册

本手册只覆盖抓放路线的正式部署、无动作 preflight 和现场分段验收。仓库默认配置保持 fail-closed；没有真实现场标定、机械臂停机手段和人工监督时，禁止运行完整 L6 路线。

## 当前结论

| 项目 | 状态 | 证据 |
|---|---|---|
| 统一镜像无相机 verifier | PASS | 镜像 `sha256:f7384634ab69256558415a074d4ad53774f2399390ddcdc7135f2c33415fb5a0` 已在 `--runtime nvidia --network none` 下通过 `pip/nms/warmup/synthetic_udp` |
| Jetson formal deploy | NO-GO | 审计时部署仍缺 `arm_new_ros`、`arm_new_interfaces` 和抓放入口 |
| Jetson ROS overlay | NO-GO | 旧 overlay 使用六类协议，已接受镜像使用 `competition-ad-yellow-red-green-v1` 七类协议 |
| AprilTag、I2、grasp、place、放置距离 | NO-GO | 没有完整、独立、已接受的现场标定记录 |
| 机械臂急停/取消 | NO-GO | `scripts/stop_all.sh` 不是机械臂硬件急停，当前没有已证明的 cancel/hold 协议 |

## 证据等级

| 等级 | 含义 | 本阶段是否允许 |
|---|---|---|
| L0 | 静态代码、配置和门禁审计 | 允许 |
| L1 | 本地合同测试、语法和配置解析 | 允许 |
| L2 | Jetson exact commit 的干净构建、安装和来源校验 | 允许 |
| L3 | 无相机 GPU verifier，禁止网络 | 允许 |
| L4 | 上电但无动作的设备、进程、ROS 数据流观测 | 需现场负责人批准，且必须证明不会触发运动 |
| L5 | 受监督的分段运动、停机链和单步抓放验收 | 必须现场双人监督 |
| L6 | 完整自主路线 | 仅在全部 L0-L5 证据通过后允许 |

L0-L4 通过不能表述为 L5/L6 ready。

## Formal Deploy 门禁

正式部署必须满足：

- checkout 为批准的 exact commit，`git status --porcelain --untracked-files=no` 无输出；
- Foxy install 在同一 formal deploy 中包含 `quadruped_robot_competition`、`whz`、`arm_new_interfaces`、`arm_new_ros`；
- `competition.launch.py`、默认抓放配置和默认机械臂配置与该 checkout 字节一致；
- Host producer/consumer 使用七类协议 `competition-ad-yellow-red-green-v1`；
- 镜像标签解析到上表的不可变 image ID，而不只是同名 tag；
- preflight 前没有相关容器、ROS、Nav2、D455、机械臂或 Lite3 控制进程残留。

建议把每次 formal build 放到全新的 `build/install/log` 目录，避免旧 install 残留文件被误用。构建后先检查四个包的 `ros2 pkg prefix`，不要仅凭 `colcon build` 成功判断部署可用。

## 标定授权变量

以下变量必须指向现场负责人已经审核的真实值：

```bash
export PICK_PLACE_SOURCE_COMMIT='<批准的 formal deploy commit>'
export TASK_MANIPULATION_PARAMS_FILE='<已接受的 TaskManager 标定 YAML 绝对路径>'
export ARM_MOTION_PARAMS_FILE='<已接受的机械臂标定 YAML 绝对路径>'
export APRILTAG_TAG_IDS='[0,1,2,3,4]'
export APRILTAG_TAG_SIZE_M='<实测黑色方块边长，单位 m>'
export TASK_MANIPULATION_CALIBRATED=true
export PICK_PLACE_CALIBRATION_APPROVED=true
```

不得把仓库默认 YAML、历史候选值或重复 I2 值标记为已接受标定。每份 YAML 都应另存操作者、时间、场地、测量方法和审批记录；启动快照会记录实际文件路径和 SHA-256。

## 无动作 Preflight

确认机器人周围无人、机械臂未使能、相机未被其他进程占用后，运行：

```bash
bash scripts/preflight_l6_pick_place.sh
```

该入口会：

- 校验 exact source commit、tracked-clean 状态和 formal install 来源；
- 校验两份标定 YAML、AprilTag 参数、模型 hash 和不可变 image ID；
- 使用唯一容器名执行有超时的 `--runtime nvidia --network none` verifier；
- 清理 verifier 容器并在正式 runtime cleanup、相机、cuVSLAM、Nav2、机械臂服务和 Lite3 motion-mode 准备之前退出。

看到 `GO: pick/place preflight passed` 只表示 L0-L3 preflight 通过，不表示允许启动完整路线。

## Preflight 后残留检查

```bash
docker ps --format '{{.ID}} {{.Names}} {{.Image}}'
pgrep -af 'ros2|realsense|visual_slam|nav2|apriltag|yolo|task_manager|arm_motion|lite3|cmd_vel'
ss -lunp | grep -E ':(19002|19003|19004)\b' || true
```

预期结果是没有相关运行容器、控制进程或 UDP listener。发现残留时保持 NO-GO，记录 PID、命令行、容器 ID 和日志后再处理。

## L5 分段验收

完整 L6 前必须逐项保留证据：

1. 实测 AprilTag 黑色方块边长，确认 pickup ID 0 和 place ID 1-4 的实体对应关系。
2. 分别测量四个独立 I2 目标；完全重复、占位、非有限或未记录来源的值一律拒绝。
3. 验证 `base_link -> arm_base_link`、抓取参考、Z 包络、夹爪开合脉冲和碰撞间隙。
4. 单独验证 place 目标、下降距离和 `place_target_distance_m`，不得保留 0/null 占位。
5. 在最低速度、清空工作区、双人监督下执行单动作；每段先证明停止链，再进入下一段。
6. 保存每段命令、配置 SHA-256、ROS 参数、服务响应、视频和人工签字。

## 停机边界

- `scripts/stop_all.sh` 可停止本仓库基础栈并发送底盘零速度，但不能证明已取消机械臂内已提交的舵机动作。
- L5 前必须提供可触达的物理断能手段，或由机械臂厂商协议证明并实测 cancel/hold/e-stop。
- 一名操作者只负责执行步骤，另一名监督者只负责观察危险区和触发停机。
- 没有停机证据时，不得运行 `scripts/start_l6_pick_place.sh`。

## L6 启动条件

只有当 formal deploy、七类协议、全部现场标定、L4 无动作观测和 L5 分段/停机证据都已接受后，才允许使用：

```bash
bash scripts/start_l6_pick_place.sh
```

该入口会准备 Lite3 motion mode、启动相机/导航/机械臂/TaskManager，并在最终验收后设置 `mission_start_armed=true`。它不是诊断或无动作入口。
