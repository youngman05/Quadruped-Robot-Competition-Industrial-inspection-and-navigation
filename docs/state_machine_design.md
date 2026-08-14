# 四足机器人抓取放置状态机设计

## 1. 文档目的

本文档汇总 2026 年中国高校智能机器人创意大赛四足大型组中，目标物块抓取和放置链路的设计结论，并与当前工作区中的已有状态机进行对比。

本文重点覆盖：

- 机器狗、D455、YOLO、Nav2、机械臂之间的职责划分；
- 抓取粗对齐点 `I0` 和细对齐状态 `I1` 的定义；
- 从 `I0` 到 `I1` 的低速闭环控制；
- 机械臂抓取、运输保持和固定放置的调用方式；
- 两个异常区域、两个红色物块的完整循环；
- 当前状态机已有能力、接口不一致和需要补充的实现。

本文是实现设计，不代表文中示例速度、容差和坐标已经完成现场标定。

## 2. 已确认的前提与约定

### 2.1 比赛任务假设

- 仪表巡检最终应得到两个异常区域和两个正常区域。
- 抓取平台上有两个红色物块和两个绿色物块。
- 两个红色物块功能等价，最终都要分别运送到两个异常区域。
- 先抓哪个红色物块不影响任务结果。
- 异常区域按 `A -> B -> C -> D` 的顺序处理。
- 比赛时间较充裕，可以降低运动和状态切换速度，优先保证稳定。

状态机的任务数量由仪表识别得到的异常区域队列决定，不能由当前看到的红色物块数量决定。正常情况下任务队列长度应为 2；若不是 2，应重新检查仪表结果或进入人工确认状态，不能直接开始抓取。

### 2.2 I0 和 I1 的定义

- `I0`：写死在地图中的抓取粗对齐航点。机器狗使用 Nav2 到达 `I0`，并应在该位置看到抓取平台上的全部物块。
- `I1`：针对本趟选中红色物块的动态细对齐状态。它不是写死在地图中的第二个航点，也不是固定的 `map` 坐标。

当选中物块在机械臂基座坐标系中的位置满足抓取参考条件时，认为机器狗到达 `I1`：

```text
target_arm_base ~= (0.42, 0.00, z_final)
```

因此，不同红色物块对应的机器狗最终位置可能不同，但机械臂看到的目标相对位置应尽量相同。

### 2.3 目标物块选择

两个红色物块等价，第一版采用最简单且确定的选择规则：

```text
优先选择与抓取参考横向位置偏差最小的红块；
若横向偏差接近，再选择前后距离偏差更小的红块。
```

等价实现为：

```python
target = min(red_blocks, key=lambda p: (abs(p.y - y_ref), abs(p.x - x_ref)))
```

不能把 YOLO 数组中的第 1 个元素作为跨帧目标身份。YOLO 每帧的检测顺序可能变化。目标一旦选定，本趟细对齐期间必须使用空间位置进行锁定和匹配。

### 2.4 抓取后验证

机械臂抬起物块后会遮挡 D455，因此当前版本不使用抓取后的视觉验证，也不根据红块数量变化决定是否进入放置。

机械臂服务成功仅表示动作序列执行完成，不代表已经通过传感器证明物块被夹住。当前方案接受这一限制，后续可在舵机负载反馈可靠后增加真实抓取验证。

### 2.5 运输位姿

抓取动作的最后一步是夹紧并抬起。该抬起位姿同时作为运输位姿：

- 机械臂不回 Home；
- 舵机保持上电和位置锁定；
- 机器狗直接进入前往放置区域的导航状态；
- 运输过程中不再调用机械臂动作。

抓取规划参数应设置：

```yaml
grasp_include_home: false
```

`include_home=false` 表示动作规划结束时不追加“返回机械臂默认 Home 位姿”的步骤。

## 3. 系统职责划分

### 3.1 总体结构

```text
Docker
  D455 + YOLO + 深度计算
       |
       | UDP JSON: camera_link, sequence, stamp, detections
       v
Host
  yolo_udp_bridge
       |
       | /yolo/detections: base_link
       v
  task_manager
       |-- Nav2 action ----------> 全局导航到 I0、A/B/C/D
       |-- 细对齐速度 ----------> /cmd_vel -> Lite3 UDP
       |-- 抓取/放置 service ----> arm node -> BusLinker
       v
  状态与诊断输出
```

### 3.2 Docker 职责

Docker 独占 D455，执行：

- 彩色图和深度图读取；
- YOLO 推理；
- 目标中心深度和三维坐标计算；
- 通过 UDP 发送轻量 JSON。

Docker 不运行比赛状态机，不控制 Nav2，不直接控制机械臂。

### 3.3 Host 职责

Host 执行：

- UDP 数据校验和 `camera_link -> base_link` 坐标转换；
- 仪表巡检结果管理；
- 比赛任务队列和状态机；
- Nav2 导航；
- `I0 -> I1` 低速闭环控制；
- 机械臂服务调用；
- 超时、重试和安全停车。

Host 不重复运行 YOLO，也不再次处理 D455 图像完成物块识别。这样可以降低 Xavier CPU 占用，并避免 Docker 和 Host 同时争用相机。

## 4. YOLO 数据使用规则

当前 Host 侧数据链路为：

```text
Docker UDP camera_link
  -> yolo_udp_bridge
  -> /yolo/detections
     frame_id = base_link
     class_name = red / green / obstacle
     position_m = [x, y, z]
```

状态机应至少读取以下字段：

```text
sequence
stamp
frame_id
detections[].class_name
detections[].confidence
detections[].depth_valid_ratio
detections[].position_valid
detections[].position_m
```

处理约束：

1. 只对新的 `sequence` 执行一次控制计算。
2. `frame_id` 必须是 `base_link`。
3. 只使用 `position_valid=true` 的目标。
4. 深度有效比例应达到配置阈值，初值可使用 `0.60`，现场稳定后可提高。
5. 数据过期或目标丢失时立即发布零速度。
6. 不能使用旧帧持续驱动机器狗移动。

### 4.1 稳定观察

到达 I0 并停稳后，维护一个只包含新序列的滚动窗口，例如最近 8 帧。满足以下条件后再选目标：

- 至少 5 帧包含期望数量的有效物块；
- 红块三维位置的帧间跳动在允许范围内；
- 对每个空间目标的 XYZ 取中位数，而不是只使用最后一帧。

第一趟正常应看到 2 个红块和 2 个绿块。第二趟已经放置过一个红块，正常只剩 1 个红块和 2 个绿块。

### 4.2 目标锁定

目标选择完成后保存：

```text
locked_target.last_position_base
locked_target.last_sequence
locked_target.lost_frames
locked_target.selected_at
```

下一帧从所有有效红块中选择与上一位置最近的目标，并使用距离门限，例如 `0.10 m`。由于机器狗每次只移动很短的脉冲，锁定目标在相邻有效帧间不应发生大幅跳变。

若匹配失败：

```text
立即停车
-> 等待新帧
-> 连续丢失超过阈值后返回 OBSERVE_BLOCKS
```

### 4.3 四个物块整体中心

最终 I1 控制不需要使用四个物块的整体中心。如果需要将它作为 I0 视野检查量，定义为单帧四个有效三维中心点的算术平均：

```text
c_frame = (p1 + p2 + p3 + p4) / 4
```

再对多帧 `c_frame` 取中位数。它只用于判断抓取平台是否大致位于预期视野，不用于代替目标红块的位置误差。

## 5. 完整状态机

### 5.1 顶层流程

现有巡检和越障阶段可以保留，抓放部分修改为：

```text
START
-> PASS_OBSTACLE
-> INSPECT_GAUGES
-> PREPARE_JOBS
-> NAV_I0
-> WAIT_I0_SETTLE
-> OBSERVE_BLOCKS
-> SELECT_AND_LOCK_RED
-> ALIGN_I1_Y
-> ALIGN_I1_X
-> CONFIRM_I1
-> CALL_GRASP
-> WAIT_GRASP
-> HOLD_LIFTED
-> NAV_PLACE
-> SETTLE_PLACE
-> CALL_PLACE
-> WAIT_PLACE
-> COMPLETE_JOB
   |-- 有剩余任务 -> NAV_I0
   `-- 无剩余任务 -> FINISH
```

实现时可以保留现有顶层 `Phase`，在抓取和放置阶段内部新增 `ManipulationState` 子状态枚举。这样既保留已有外部 `/task/phase` 接口，又避免把多个异步步骤塞进一个 Tick 函数。

### 5.2 状态定义

| 状态 | 主要动作 | 成功退出条件 | 超时或失败处理 |
|---|---|---|---|
| `PREPARE_JOBS` | 汇总异常区域并按 A/B/C/D 排序 | 恰好得到 2 个异常区域 | 重新巡检或暂停等待人工确认 |
| `NAV_I0` | Nav2 导航到写死的 I0 | Nav2 action 返回成功 | 导航重试；超过次数进入安全中止 |
| `WAIT_I0_SETTLE` | 停车，等待机身和深度图稳定 | 稳定时间达到约 0.8 s | 定位丢失则返回导航/等待 |
| `OBSERVE_BLOCKS` | 收集新 YOLO 序列并进行多帧过滤 | 获得足够稳定的红、绿物块 | 数据过期则保持停车并等待 |
| `SELECT_AND_LOCK_RED` | 按横向偏差最小选择红块并建立空间锁 | 生成有效目标锁 | 无候选时返回观察 |
| `ALIGN_I1_Y` | 横向短脉冲微调 | 横向误差进入容差 | 丢目标停车；超时返回 I0 |
| `ALIGN_I1_X` | 前后短脉冲微调 | 前后误差进入容差 | 丢目标停车；超时返回 I0 |
| `CONFIRM_I1` | 不运动，重新检查 x/y/yaw/z | 连续 5 个新序列均满足条件 | 超差则返回对应对齐状态 |
| `CALL_GRASP` | 只发送一次异步抓取请求 | service future 已创建 | 服务不可用时等待或中止 |
| `WAIT_GRASP` | 等待机械臂执行结束 | 返回 `success=true` | 明确未开始可重试；动作中断需人工处理 |
| `HOLD_LIFTED` | 保持抬起运输位姿 | 保持时间达到配置值 | 不释放舵机，不依赖 D455 验证 |
| `NAV_PLACE` | 导航到当前异常区域的固定狗位姿 | Nav2 action 返回成功 | 导航失败则重试，物块继续保持 |
| `SETTLE_PLACE` | 根据地图定位做小范围最终调整 | 到达放置容差 | 超时保持物块并暂停 |
| `CALL_PLACE` | 只发送一次固定放置请求 | service future 已创建 | 服务不可用时保持当前状态 |
| `WAIT_PLACE` | 等待固定动作序列完成 | 返回 `success=true` | 失败时不增加已处理计数 |
| `COMPLETE_JOB` | 标记当前异常区域完成并清理本趟上下文 | 队列索引更新完成 | 有任务回 I0，否则结束 |

### 5.3 任务队列

建议显式保存：

```python
jobs = ["B", "D"]       # 示例，按 A/B/C/D 排序
job_index = 0
current_zone = jobs[job_index]
```

只有 `/arm/place_fixed` 成功后才能执行：

```python
job_index += 1
```

导航到放置点、等待时间达到阈值或机械臂请求已发送，都不能算作任务完成。

## 6. I0 到 I1 的闭环控制

### 6.1 为什么第一版不使用完整 PID

当前系统具有以下特点：

- YOLO 帧率不高；
- D455 深度存在跳动；
- 机器狗底盘存在动作起步阈值和步态离散性；
- `/cmd_vel` 到 Lite3 的桥接一次只执行一个运动轴；
- 比赛时间充裕，不需要连续高速跟踪。

因此第一版采用增量 P 控制，不使用积分项和微分项：

- 积分项可能在等待新帧时继续累积，造成积分饱和；
- 微分项会放大深度测量和检测中心跳动；
- 停车观察后再移动，可以显著降低坐标变换时延和机身振动的影响。

### 6.2 控制顺序

```text
确认 I0 标定 yaw
-> 调整 y
-> 调整 x
-> 复查 yaw 和 y
-> 停车进行最终多帧确认
```

单个目标点不能独立确定机器狗 yaw。yaw 应由 `map -> base_link` 定位和 I0 标定朝向确定，不能根据一个红块的中心位置反推。

### 6.3 误差定义

机械臂参考抓取点为：

```text
p_ref_arm = (0.42, 0.00, z_final)
```

利用固定外参得到该点在 `base_link` 中的参考坐标：

```text
p_ref_base = T_base_arm * p_ref_arm
```

YOLO 输出选中物块的 `p_target_base`，则平面误差为：

```text
e_x = p_target_base.x - p_ref_base.x
e_y = p_target_base.y - p_ref_base.y
```

当目标比参考点远时，`e_x > 0`，机器狗应向前移动；当目标位于参考点左侧时，按照 ROS `base_link` 约定发布对应正横向速度。具体符号必须通过一次低速现场测试确认 Lite3 桥接方向。

### 6.4 控制输出

```text
vx = clamp(Kx * e_x, -vx_max, vx_max)
vy = clamp(Ky * e_y, -vy_max, vy_max)
```

初始建议参数：

| 参数 | 建议初值 |
|---|---:|
| `Kx`、`Ky` | `0.5 ~ 0.8 s^-1` |
| `vx_max`、`vy_max` | `0.06 m/s` |
| 最低有效速度 | `0.025 m/s` |
| 单次运动脉冲 | `0.15 ~ 0.40 s` |
| 每次运动后停稳 | `0.6 ~ 0.8 s` |
| x/y 容差 | `0.015 ~ 0.020 m` |
| yaw 容差 | `2 ~ 3 deg` |
| 最终稳定帧数 | `5` |
| YOLO 新鲜度上限 | 初值 `0.5 s`，按实测帧率调整 |
| 单次细对齐总超时 | `20 ~ 30 s` |

当误差仍在容差外，但 `K * error` 低于底盘最低有效速度时，可以使用最低速度和更短脉冲，避免因命令过小导致机器狗不动。

### 6.5 控制节拍

每一个轴的微调循环如下：

```text
读取新 sequence
-> 更新锁定目标
-> 计算误差
-> 发布一个轴的 Twist
-> 持续 0.15~0.40 s
-> 发布零速度
-> 等待机身和深度稳定
-> 等待下一个新 sequence
```

不能在等待 YOLO 新帧时保持旧的非零速度。

### 6.6 `/cmd_vel` 所有权

当前 Nav2 和细对齐控制都可能向 `/cmd_vel` 发布消息。进入 `ALIGN_I1_*` 前必须满足：

- Nav2 I0 目标已经成功结束；
- 已等待底盘停止；
- 不再有活动的 Nav2 控制目标；
- 必要时等待导航取消确认，而不是只清空本地句柄。

更稳妥的实现是增加轻量速度仲裁：

```text
Nav2             -> /cmd_vel_nav
fine alignment   -> /cmd_vel_align
velocity mux     -> /cmd_vel
```

如果第一版不引入 mux，也必须用状态机保证两个发布者不会同时输出非零速度。

## 7. 抓取动作接口

### 7.1 职责原则

状态机负责：

- 选择目标；
- 跨帧锁定；
- 驱动机器狗到 I1；
- 确定最终抓取 z；
- 发起机械臂请求。

机械臂节点负责：

- 校验目标是否在可达范围；
- 生成抓取动作序列；
- 控制 BusLinker 和舵机；
- 返回动作执行结果。

机械臂节点不能在服务回调中再次从 YOLO 数组选择另一个红块，否则可能抓取与状态机锁定目标不同的物块。

### 7.2 推荐服务

由于 x/y 经过 I1 对齐后固定，而 z 使用最终多帧测量值，推荐服务请求携带机械臂坐标：

```text
/arm/execute_grasp

request:
  geometry_msgs/Point target_arm_base

response:
  bool success
  string message
```

实际请求目标使用：

```text
x = 0.42
y = 0.00
z = 最终稳定帧的中位数，并经过可达范围检查
```

如果现场确认平台高度和狗身姿态足够固定，也可以把 z 一并标定为固定值，随后使用 `std_srvs/Trigger` 简化接口。但在验证完成前，保留动态 z 更符合当前需求。

### 7.3 抓取动作终点

```text
预抓取位
-> 分步接近
-> 夹紧
-> 抬升
-> 停留在抬升后的运输位姿
```

要求：

- `include_home=false`；
- 服务响应应在整个动作序列执行结束后返回；
- 服务调用采用异步 future，状态机 Tick 不能阻塞；
- 抓取请求每趟只能发送一次；
- 抬起后保持时间作为参数，建议使用 `3.2 s` 留出余量；
- 当前版本不执行抓取后视觉验证。

## 8. 放置区域和放置动作

### 8.1 A/B/C/D 固定狗位姿

第一版将 A/B/C/D 对应的机器狗放置位姿提前标定并写入配置。这里写死的是：

> 当固定机械臂放置动作执行时，`base_link` 在 `map` 坐标系中应处于的 `x/y/yaw`。

它不是纸箱中心坐标，也不是纸箱边缘坐标。标定流程为：

1. 手动把机器狗放在纸箱外侧安全位置；
2. 调整狗的位置和朝向，使固定放置动作的释放点落在纸箱有效区域；
3. 记录此时 `map -> base_link` 的 x、y、yaw；
4. 分别记录 A、B、C、D；
5. 至少重复到位和放置测试，验证定位重复性。

配置中四个放置点必须包含 yaw，不能使用 `yaw=None`。

### 8.2 Nav2 到位精度

当前 Nav2 通用目标容差为：

```text
xy_goal_tolerance  = 0.15 m
yaw_goal_tolerance = 0.25 rad
```

这对于机械臂可达区域有限的固定放置动作通常过大。建议采用以下两种方法之一：

1. 为最终放置目标使用更严格的 Nav2 goal checker；
2. Nav2 完成粗到位后，进入 `SETTLE_PLACE`，根据 `map -> base_link` 误差进行低速分轴修正。

第一版更容易落地的是第二种方案。建议现场从 `3~5 cm` 和 `3~5 deg` 的放置容差开始验证。

### 8.3 放置动作

放置细节使用已有 `arm_new/scripts/direct_place.py` 对应的动作规划逻辑。生产节点应直接复用：

```text
ArmGrabPlannerNew.plan_place()
BusLinkerExecutor.execute_steps()
```

不要在状态机中启动 `direct_place.py --execute` 子进程，因为脚本包含终端 Enter 确认，不适合作为无人值守比赛接口。

推荐服务：

```text
/arm/place_fixed
type: std_srvs/Trigger
```

只有放置服务返回成功，才能执行 `COMPLETE_JOB` 并增加已处理任务数。

## 9. 超时与恢复策略

不要继续使用一个统一的 `timeout_per_phase` 覆盖所有动作。不同状态应使用独立超时和重试计数。

| 故障 | 立即动作 | 恢复策略 |
|---|---|---|
| YOLO 数据过期 | 发布零速度 | 等待新序列；超时返回观察状态 |
| 锁定目标丢失 | 发布零速度 | 短暂等待；持续丢失则重新观察和选块 |
| I1 对齐超时 | 发布零速度 | 返回 I0 重新开始本趟，不更新任务队列 |
| Nav2 导航失败 | 保持机械臂当前状态 | 重置导航并限次重试 |
| 抓取服务不可用 | 不开始放置导航 | 等待服务或安全中止 |
| 抓取执行中断 | 停止狗运动 | 不盲目重复抓取，转人工保护流程 |
| 放置服务失败 | 不增加完成计数 | 保持当前任务，按机械臂错误类型处理 |
| SLAM/定位丢失 | 停止导航和细对齐 | 等待定位恢复或安全中止 |

进入 `ABORT` 时至少应：

- 取消活动导航目标；
- 向底盘发布零速度；
- 清除未发送的动作请求；
- 如果机械臂正在持物，不发送松夹或掉电命令。

## 10. 当前状态机概况

当前主状态机位于：

```text
src/nodes/decision/task_manager.py
```

已有顶层阶段：

```text
START
-> PASS_OBSTACLE
-> INSPECT_GAUGES
-> FIND_RED_BAR
-> GRASP_BAR
-> PLACE_TO_ABNORMAL_ZONE
-> FINISH
```

现有代码已经具备：

- 越障和巡检状态外壳；
- `NavigationClient` 封装；
- `_abnormal_zones` 异常区域列表；
- `_abnormal_handled` 已处理数量；
- 放置后仍有任务时回到抓取区的两趟循环框架；
- `/task/phase` 和 `/task/status` 状态输出。

## 11. 新老状态机对比

| 功能 | 当前状态机 | 新设计 | 结论 |
|---|---|---|---|
| 异常任务来源 | 从仪表结果生成 `_abnormal_zones` | 校验恰好两个异常并按 A/B/C/D 排序 | 保留并加强校验 |
| 两趟循环 | 放置后根据剩余数量返回抓取区 | 放置服务成功后才完成当前任务并回 I0 | 保留循环框架，修正完成条件 |
| 抓取粗定位 | 导航到 `grab_area` | 明确定义为 I0，写死 x/y/yaw | 重命名并补齐朝向 |
| 等待导航完成 | 导航和检测判断可能同时向下执行 | 必须先收到 Nav2 成功结果，再停稳和观察 | 需要修复状态门控 |
| YOLO 类别 | 按旧 `gauge/red_bar/green_bar` 解析 | 按 `red/green/obstacle` 解析 | 当前接口不兼容 |
| 坐标契约 | 未检查 Host 新 schema | 使用 `frame_id=base_link` 和 `position_m` | 需要重写解析 |
| 检测新鲜度 | 只保存本机收到消息的时间 | 检查 sequence、stamp 和 stale timeout | 需要补充 |
| 多帧过滤 | 无 | 新序列滚动窗口和中位数 | 需要新增 |
| 红块选择 | `red_bars[0]` | 最小横向偏差，选定后空间锁定 | 需要替换 |
| I1 | 无 | 目标在机械臂坐标达到固定抓取参考点 | 需要新增 |
| I0 到 I1 控制 | 无 `/cmd_vel` 发布 | 分轴、停车观察式增量 P 控制 | 需要新增 |
| 抓取执行 | 进入状态 1 秒后自动完成 | 异步调用真实机械臂服务 | 当前仅占位 |
| 运输位姿 | 未定义 | 抓取抬起终点直接作为运输位姿 | 需要接入机械臂参数 |
| 抓取验证 | 未实现 | 当前明确不做视觉验证 | 记录为现阶段限制 |
| 放置导航 | 已有 `placement_A/B/C/D` 位置 | 标定每个区域的 x/y/yaw 和最终到位条件 | 当前航点不完整 |
| 放置执行 | 1 秒后自动增加完成数量 | 真实服务成功后才能增加计数 | 当前有提前完成风险 |
| 机械臂启动 | 总 launch 不包含机械臂节点 | 增加 arm launch 参数和节点 | 需要集成 |
| 单元测试 | 没有 task manager 专项测试 | 覆盖门控、乱序、丢帧、两趟循环 | 需要新增 |

## 12. 当前代码中的具体问题

### 12.1 抓取区导航尚未结束就可能进入抓取

`task_manager.py::_tick_find_red_bar()` 发送导航目标后，没有在“导航仍在执行”时返回。只要 `_latest_yolo` 中存在缓存红块，就可能取消导航并进入抓取阶段。

需要改成严格顺序：

```text
发送 I0 导航
-> 等待 Nav2 done
-> 检查 succeeded
-> 停稳
-> 清空旧检测
-> 才允许观察红块
```

### 12.2 YOLO 类别和字段不兼容

当前状态机仍识别：

```text
gauge / red_bar / green_bar
class_id 0 / 5 / 6
```

当前 UDP bridge 实际输出：

```text
red / green / obstacle
class_id 0 / 1 / 2
frame_id = base_link
position_m = [x, y, z]
```

因此当前状态机无法正确得到 `red_bars`。

### 12.3 没有目标锁定

当前直接使用：

```python
bar = self._latest_yolo.red_bars[0]
```

当检测数组顺序变化时，该索引可能代表另一个红块。新状态机必须把“选择目标”和“持续跟踪选定目标”分开。

### 12.4 抓取仍是占位逻辑

当前 `GRASP_BAR` 在进入状态 1 秒后自动推进，没有机械臂 client、请求 future 或执行结果。

### 12.5 放置可能提前计数

当前 `PLACE_TO_ABNORMAL_ZONE` 使用整个阶段的 `elapsed > 1.0` 作为放置完成条件。该计时从进入放置阶段就开始，可能在 Nav2 仍然行驶时增加 `_abnormal_handled`。

### 12.6 巡检也存在导航门控问题

`INSPECT_GAUGES` 发送导航目标后，如果导航还未完成，代码仍可能继续执行拍图和识别。虽然不属于抓放新增功能，但在整体状态机落地时应一并修复。

### 12.7 导航航点朝向问题

当前 `grab_area` 和 `placement_A/B/C/D` 的 `yaw_deg` 均为 `None`。代码注释认为这表示“不限制朝向”，但发送给 Nav2 的仍是单位四元数，且 `yaw_set` 没有真正影响 action goal。

I0 和所有固定放置位必须写入经过标定的 yaw。

### 12.8 Nav2 取消未等待确认

当前 `NavigationClient.cancel()` 调用 `cancel_goal_async()` 后立即清空本地状态，没有等待取消确认。细对齐开始前应确保 Nav2 已经真正停止输出速度。

### 12.9 机械臂节点现状

工作区中有两套相关适配：

1. `arm_grasp_node.py`
   - 已定义 `/arm/grab_red` 和 `/arm/release_fixed` 等 `Trigger` 服务；
   - 会自行读取 YOLO 并按置信度重新选择目标；
   - 使用的是旧 YOLO 字段和旧相机 frame 约定；
   - 不适合直接接在新状态机锁定目标之后。

2. `arm_motion_node.py`
   - 接收 `PointStamped`，能够规划抓取和放置动作；
   - 发布动作状态，但当前没有请求与结果明确对应的抓取/放置 service；
   - 默认 `enable_motion=false`、`transform_calibrated=false`；
   - 尚未集成到比赛总 launch。

建议最终只保留一个生产机械臂节点：由状态机传入已经确认的机械臂目标坐标，节点不再订阅 YOLO 进行目标决策。

## 13. 建议的代码落地范围

### 13.1 `src/nodes/decision/task_manager.py`

- 修正新 YOLO schema 解析；
- 保存 `sequence`、数据时间和有效三维坐标；
- 增加多帧窗口和目标锁；
- 增加抓放子状态；
- 增加细对齐 `/cmd_vel` 发布；
- 增加机械臂异步 service client；
- 将异常区域改为有明确完成语义的任务队列；
- 所有状态采用独立超时和进入时间；
- 修复巡检、抓取、放置的导航完成门控。

复杂的过滤和控制计算应放到无 ROS 依赖的纯 Python 类中，状态机只负责调用，以便单元测试。

### 13.2 `src/navi/navigation_client.py`

- 将 `grab_area` 重命名或别名为 `grasp_i0`；
- 为 I0 和 A/B/C/D 配置明确 yaw；
- 修正 `yaw=None` 的语义或移除该约定；
- 增加可靠的取消完成状态；
- 提供清晰的 goal accepted、running、succeeded、failed、canceled 状态。

### 13.3 `arm_new/arm_new_ros`

- 合并目标选择重复职责；
- 增加携带 `target_arm_base` 的抓取服务；
- 增加固定放置服务；
- 抓取设置 `include_home=false`；
- 保证抓取终点为抬起运输位姿；
- 服务执行结束后返回明确成功或失败；
- 保留 `enable_motion` 和变换标定安全开关。

### 13.4 `launch/competition.launch.py`

- 增加 `enable_arm` 参数；
- 启动唯一的生产机械臂节点；
- 确保静态 TF 只由一个 launch 发布；
- 如果使用速度 mux，在此处完成 Nav2 和细对齐话题重映射。

### 13.5 配置文件

建议把现场参数从代码移到 YAML：

```yaml
task_manager_node:
  ros__parameters:
    grasp_i0: [I0_X, I0_Y, I0_YAW]

    grasp_reference_arm: [0.42, 0.00]
    grasp_z_min: Z_MIN
    grasp_z_max: Z_MAX

    observe_window_size: 8
    required_stable_frames: 5
    yolo_stale_timeout_s: 0.5
    target_match_gate_m: 0.10

    align_kx: 0.6
    align_ky: 0.6
    align_max_speed_mps: 0.06
    align_min_speed_mps: 0.025
    align_xy_tolerance_m: 0.02
    align_yaw_tolerance_rad: 0.052
    align_pulse_min_s: 0.15
    align_pulse_max_s: 0.40
    align_settle_s: 0.70
    align_timeout_s: 30.0

    lifted_hold_s: 3.2

    placement_A: [A_X, A_Y, A_YAW]
    placement_B: [B_X, B_Y, B_YAW]
    placement_C: [C_X, C_Y, C_YAW]
    placement_D: [D_X, D_Y, D_YAW]
```

大写占位符必须由现场标定值替换，不能直接作为运行配置。

## 14. 测试方案

### 14.1 纯逻辑单元测试

至少覆盖：

- YOLO 新 schema 能正确解析红、绿物块；
- 检测数组顺序每帧变化时目标锁不切换；
- 重复 `sequence` 不重复计算和发命令；
- 数据过期、目标丢失时立即输出零速度；
- y 误差未满足时不会进入 x 对齐；
- 最终稳定帧不足时不会调用抓取；
- 抓取请求只发送一次；
- 导航未完成时不能观察、抓取或放置；
- 放置失败时任务索引不增加；
- 第一趟成功后回 I0，第二趟成功后进入 FINISH；
- 异常区域按 A/B/C/D 排序；
- 异常区域数量不是 2 时不开始抓取。

### 14.2 仿真和 dry-run

1. 使用录制的 UDP/ROS JSON 回放检测数据；
2. 用假的 NavigationClient 控制成功、失败和延迟；
3. 用假的机械臂 service 验证请求次数和状态切换；
4. 将 `enable_motion=false`，验证机械臂规划和目标坐标；
5. 检查任意感知停更时 `/cmd_vel` 是否在看门狗时间内归零。

### 14.3 实机分阶段验证

```text
只观察，不动狗
-> 单轴横移脉冲
-> 单轴前后脉冲
-> 完整 I0 到 I1，不动机械臂
-> 机械臂 dry-run
-> 单次真实抓取并保持
-> 持物短距离导航
-> 单个固定放置区
-> A/B/C/D 分别重复到位
-> 完整两趟状态机
```

每个阶段通过后再开启下一阶段，避免同时调试感知、底盘、导航和机械臂。

## 15. 上场前必须完成的现场标定

- I0 的 `map` 坐标和 yaw；
- `base_link -> arm_base_link` 固定外参；
- 抓取参考 x/y 和允许误差；
- 抓取 z 的有效范围；
- 细对齐速度方向、最低有效速度和单脉冲位移；
- A/B/C/D 四个固定狗位姿及 yaw；
- Nav2 到位后的实际重复误差；
- 抓取抬起位姿是否遮挡、碰撞或影响机器狗行走；
- 舵机在串口执行器退出后是否继续保持扭矩；
- 固定放置动作是否在所有目标区域都有足够余量。

完成上述标定和状态门控后，整体链路可以在不增加 Host 图像计算的前提下实现：

```text
狗到 I0
-> 视觉闭环到动态 I1
-> 机械臂固定相对位置抓取并抬起
-> 狗到固定异常区域位姿
-> 机械臂执行固定放置
-> 循环处理第二个异常区域
```

## 16. 参数维护方案

### 16.1 设计目标

参数按“数据所有权”而不是按“方便写在哪里”分配。每个有效数值只能有一个
运行真值来源，文档、测试命令和代码默认值不能再维护第二份生产坐标。

配置分为三层：

| 配置 | 唯一负责内容 | 不应包含 |
| --- | --- | --- |
| `configs/calibration/competition_sites.yaml` | 系统级空间标定：固定狗位姿、I1 契约、公共机械臂释放点、标定版本 | 控制增益、串口、安全开关 |
| `configs/ros/task_manager_params.yaml` | 状态机阶段、超时、话题以及后续 I1 控制器参数 | map 点位、机械臂 TCP |
| `arm_new/config/arm_motion_params.yaml` | 串口、动作时序、接近/抬升参数、机械臂安全开关 | I0、A/B/C/D 狗位姿 |

`configs/transforms/static_extrinsics.yaml` 继续作为项目静态 TF 的唯一真值来源，
不能把 `base_link -> arm_base_link` 或相机外参复制到上述文件。

### 16.2 空间标定集合

`competition_sites.yaml` 是一次联合标定的原子集合。它同时保存：

- `grasp_i0`：`map` 中固定的粗对齐狗位姿 `[x_m, y_m, yaw_rad]`；
- `grasp_i1`：`arm_base_link` 中动态细对齐终止条件，当前固定 x/y 为
  `[0.42, 0.00]`，z 由每趟最终稳定观测提供；
- `placement_A/B/C/D`：四个 `map` 中的固定放置狗位姿；
- `fixed_release`：ArmPi API 坐标系中的公共释放 TCP；
- `smoke_test.grasp_z_m`：人工服务链路测试使用的 z，当前为 `0.15 m`。

I1 不是一个 `map` 航点，不能新增 `i1` 导航目标。它表示选中物块在
`arm_base_link` 中已经进入机械臂抓取参考位置。

第一版要求 A/B/C/D 共用一个 `fixed_release`。现场应调整四个狗位姿，使同一
机械臂释放动作均落入有效区域。如果必须为四区使用不同 TCP，应先把
`/arm/execute_place_fixed` 从无参数 `Trigger` 改成携带 `zone_id` 的自定义服务，
不能只在 YAML 中增加四个点而让节点隐式选择。

### 16.3 坐标与单位

- 固定狗位姿统一直接记录 ROS `map` 坐标，长度单位为米、yaw 单位为弧度；
- 禁止把场地图左上原点、毫米、y 向下的绘图坐标直接写入运行点位；
- I1 目标使用 `arm_base_link`：`+X` 前、`+Y` 左、`+Z` 上；
- 固定释放点使用明确标记的 `arm_api`：`+X` 右、`+Y` 前、`+Z` 上；
- TF 平移使用米，四元数顺序固定为 `xyzw`。

字段名必须携带 frame 或单位语义，例如 `pose_map_m_rad`、`fixed_xy_m` 和
`target_m`。任何 frame 不明确的三元数组都不能进入已标定状态。

### 16.4 标定状态和启动门控

空间条目的状态采用：

- `uncalibrated`：无有效值，禁止自动任务；
- `conflict`：现有来源互相矛盾，禁止自动任务；
- `provisional`：有候选值，只允许人工分阶段验证；
- `confirmed_reference`：接口参考值已确认，但不代表整条实机链路已验收；
- `calibrated`：完成重复性验收，可进入自动任务。

运行加载器落地后，任何必需点位为 `null`、缺 yaw、含非有限数或状态不是
`calibrated` 时必须 fail closed。两个节点必须输出同一 `calibration_set.id`；
日志无法证明所加载标定集合时，不允许执行真机自动流程。

当前 `competition_sites.yaml` 仅建立统一格式，导航侧尚未接入。文件中的
候选狗位姿仍是 `provisional`，`grasp_i0` 因代码与文档冲突明确标为 `conflict`，
不能因为文件已经存在就视为现场标定完成。

### 16.5 日常维护流程

1. 在 PC 工作分支修改源码配置，不直接编辑 Xavier 的 `install/` 或 `/tmp/`；
2. 修改前先将受影响条目标记为 `uncalibrated`；
3. 一次只调整一个变量，保留前一版本的 Git commit；
4. 同步 Xavier 后重新 `colcon build` 并 `source install/setup.bash`；
5. 依次完成 YAML 校验、`enable_motion=false`、TF/preflight、dry-run、单点导航、
   低速真机动作和完整链路；
6. 每个固定站位至少重复到位 3 至 5 次，再写入标定人、日期并更新
   `calibration_set.id`；
7. 验收通过的集合用 Git tag 固化，问题回退到整套标定，不手工猜测旧数值。

仓库中的 `enable_motion` 必须保持 `false`。真机运动授权属于本次启动行为，
只能在有人监护和可立即断电时显式打开。禁止在动作执行中使用
`ros2 param set` 修改点位、速度或安全开关。

### 16.6 变更失效传播

| 变更 | 必须重新验收 |
| --- | --- |
| 地图原点、尺度或 SLAM 定位定义 | 所有 `map` 狗位姿 |
| `base_link -> arm_base_link` | I1、抓取、公共释放点和 A/B/C/D |
| 相机安装位姿或相机外参 | 目标坐标、I1 闭环和真实抓取 |
| I1 固定 x/y | 状态机闭环与机械臂抓取 |
| 公共释放 TCP | A/B/C/D 四个联合放置测试 |
| 机械臂运输位姿或抬升高度 | 抓取、持物导航和环境碰撞检查 |

配置维护的责任边界、当前分支差异和与 navigation/SLAM 分支的整合流程见
`docs/2026-08-09VersionDifference.md`。
