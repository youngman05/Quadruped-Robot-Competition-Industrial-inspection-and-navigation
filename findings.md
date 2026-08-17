# Findings & Decisions

## 2026-08-17 Phase 149 physical Depth continuity
- The mode controller currently sends `enable_depth=desired.requires_depth`, so entering `DISABLED` physically stops the RealSense Depth stream and restarts the shared Stereo/Depth Module, transiently interrupting IR1/IR2 and cuVSLAM odometry.
- The intended separation already exists for expensive cone processing: `pointcloud.enable` and `decimation_filter.enable` are enabled only in `AVOIDANCE`.
- Keep the existing logical `depth_enabled` status contract and `_on_depth` mode gate so `DISABLED` still means "do not consume/relay Depth" even though the physical D455 Depth stream stays on.
- `scripts/start_competition.sh` already forces `CUVSLAM_ENABLE_DEPTH=true`; the generic cuVSLAM launcher default and unrelated CV utilities that disable Depth are outside the formal competition mode-transition path.

## 2026-08-16 Phase 145 depth-mode timing
- The fourth inspection correctly froze exactly two tasks even though three gauges were classified abnormal; the live stop was not caused by a `>=3 abnormal` termination branch.
- The actual stall began when TaskManager requested `MANIPULATION` at `before:grab_area_approach`. The depth controller acknowledged it, but the cone safety gate waited for a new disabled-layer revision even though local/global cone layers were already disabled, then entered permanent `fault` and held `/cmd_vel` at zero.
- `depth_relay_docker.py` changes only the RealSense `enable_depth` parameter plus avoidance-only pointcloud/decimation parameters. `DISABLED` therefore does not disable D455 RGB, cuVSLAM IR stereo, or IMU.
- Docker AprilTag pickup consumes RGB plus color camera info only; J1 placement consumes synchronized RGB plus Depth. The required sequence is `AVOIDANCE -> DISABLED` after `obstacle_cross_target`, remain `DISABLED` through inspection/pickup, switch to `MANIPULATION` only after placement arrival, then restore `DISABLED` before another pickup transit.
- A real cone-layer enabled-state change still requires post-baseline sequence and revision advancement. Only a parameter-readback-confirmed no-op transition may reuse matching local/global applied state, so the correction does not introduce fail-open navigation.
- J1 Depth timeout/fault fallback is deliberately isolated from I2: it clears only `enable_place_vision_alignment`; pickup RGB AprilTag remains enabled for the next round.

## 2026-08-13 Phase 97 formal deploy ancestry gate
- Jetson formal checkout was clean at `b1ae5af757a9dad7b85313f93991f810b7e22365` on branch `codex/inspection-runner-20260812`.
- Fetch advanced `origin/Stonefield/nav2-foxy-dwb-integration` to the requested `941bed6503f22d76a7bc9017757876e047f9d03c`.
- Backup branch `backup/pre-cone-l3d-b1ae5af-20260813` was created at `b1ae5af`.
- Required ancestry check returned 1. The merge base is `97ca3efdab01e2e826c3af6212cc79fa8d264918`; `b1ae5af...941bed6` has 4 commits only on the formal branch and 10 only on the cone branch.
- Per the user's stop condition, no merge was attempted and phases for image promotion, package builds, D455 ownership transfer, cone startup, ROS acceptance, and restoration were not entered.

## 2026-08-13 Phase 97 startup/teardown audit
- At target `941bed6`, `scripts/start_competition.sh` installs `trap '... bash scripts/stop_all.sh' INT TERM` at line 16, then backgrounds `ros2 launch ...` and returns after its startup summary. Sending Ctrl+C to this shell would therefore invoke the explicitly forbidden generic cleanup script rather than simply interrupting a persistent launcher.
- Safe interpretation: run the exact requested cone-only start command with the specified environment and no additional feature flags; for teardown, send SIGINT only to the exact new ROS launch process created by this run, then stop only the exact newly created cuVSLAM container. Never signal the top-level start script trap and never invoke `stop_all.sh`.
- Runtime confirmed the exact required command did execute its internal line-81 pre-clean. At that instant there were no running containers, no domain-0 ROS nodes, no forbidden process, and Lite3 remained physically unreachable, but the internal cleanup call is still a documented deviation from an ideal no-Twist startup path.
- First formal run rejected: live `/cmd_vel` had one `cmd_vel_arbiter` publisher and zero subscribers; `controller_server` was active; `/goal_pose` had zero publishers; no Lite3/TaskManager/cmd_vel-bridge identity existed. However, Host `/cone_obstacle/scan` and `/cone_obstacle/health` were absent, and process arguments proved package executables and Nav2 configs came from legacy `/home/superwfx666/quadruped-robot-competition-nav2-dwb` despite `ros2 pkg prefix` reporting the formal install.
- Container-side cone generation itself was healthy: `/cone_obstacle/scan_humble` had one BEST_EFFORT publisher and one BEST_EFFORT exporter subscription, with more than 2100 continuously logged healthy frames. The failure boundary is formal Host overlay provenance/launch, not D455 cone extraction.
- Root cause of attempt-1 provenance failure: `start_competition.sh` defaults `NAV2_OVERLAY_SETUP` to `$HOME/nav2_foxy_overlay_ws/install/setup.bash`; that full setup explicitly chains `/home/superwfx666/quadruped-robot-competition-nav2-dwb/install/local_setup.sh` before loading its two Nav2 packages. The overlay's own `local_setup.bash` exposes `nav2_bt_navigator` and `nav2_behavior_tree` without injecting the legacy repository, while retaining the formal deploy as the resolved competition package/Python source.
- Formal package build/install links and ament metadata are now confirmed to resolve to the deploy checkout; no generated-file cleanup is justified. Retry should set the startup script's existing `NAV2_OVERLAY_SETUP` environment variable to the same overlay's `local_setup.bash`, with no extra feature flags.
- Retry 2 passed all formal runtime gates. Evidence is stored on Jetson in `/tmp/phase97_formal_cone_smoke_retry2/acceptance_snapshot.txt` and `/tmp/phase97_formal_cone_smoke_retry2/continuous_health_scan.json`; final D455 rate captures are in the same directory.
- Final restored state has only historical D455 container `cadfa809e7b2...` running; color `29.157 Hz`, depth `59.920 Hz`, OOM=false. Formal Git is clean at exact target; `eth0` remains no-carrier/no-address and Lite3 unreachable.

## 2026-08-12 Phase 96 cone avoidance L3-D preparation
- The formal Jetson deploy at `b1ae5af` lacks the installed cone bridge/gate/probe; stationary L3-D must continue from the clean acceptance worktree `/home/superwfx666/cone-l2-l3-acceptance-6a69b93` at `6a69b93`.
- The runbook's L3-D source example still mentions `$HOME/nav2_foxy_overlay_ws/install/setup.bash`, but Phase 94 proved that overlay can inject a legacy repository install prefix. Runtime startup must first be audited and should use the pinned `nonpersistent_voxel_layer` 2.2.1 overlay plus acceptance worktree setup without legacy prefix contamination.
- Real costmap marking/clearing requires an on-site cone movement sequence. All automated graph, scan, health, timing, resource, and cleanup checks can proceed around that manual physical step, but the agent must not claim costmap acceptance without the actual cone-in/cone-out evidence.
- ByteRover CLI/MCP remains unavailable, so Phase 96 is based on the repository PWF, accepted runbook, source, and Jetson provenance.
- The first Jetson startup gate found D455 present (`8086:0b5c`), both Git worktrees clean, the pinned plugin and acceptance prefixes uncontaminated, no relevant process/container, UDP 19002 free, and no domain-0 `/cmd_vel` topic. However, `192.168.1.120` remained directly reachable through `eth0` from `192.168.1.111` with a `0.748 ms` ping, so the claimed physical Lite3 control-link isolation could not be accepted as true at runtime.
- Baseline A resource evidence is complete except for the required container-side odometry rate: 59 tegrastats lines and 12 Docker samples were captured, with mean RAM about `3149.983 MB`, mean container CPU `66.103%`, and mean container memory `538.450 MiB`; cleanup was clean.
- Historical container `d455_yolo_repro_20260811` (`cadfa809e7b2`) was externally started at `2026-08-12T11:12:32Z` (19:12 local), restart policy `no`, host network, image `d455-yolo:pick-test-20260811`. It owns D455 with one RealSense node and publishes color/depth only; it has no cuVSLAM or cone pipeline. This owner blocks L3-D and is outside the cone acceptance process set.
- After explicit authorization, the historical D455 container was stopped with full inspect/process/topic evidence preserved for mandatory restoration. Baseline A container-side odometry after 90 seconds warmup measured about `30.010 Hz` over 366 samples; the timeout traceback is the expected CLI termination after usable rate output.
- Cone-enabled mode B failed before node construction because the container's Humble prefix set contains Isaac ROS and `/opt/ros/humble` but no `pointcloud_to_laserscan` package. The exact launch exception is preserved in `/home/superwfx666/cuvslam_lite3_logs/20260812-201703/launch.log`; no evidence points to OOM, RealSense ownership, exporter import, or point-cloud parameters because launch stopped at package lookup first.
- The failed B container was launched with automatic removal, so Docker no longer has object `e8d90d4b...` for exit-code or mount inspection. Future diagnostic runs that may fail before acceptance should retain the stopped container until logs and inspect metadata are captured.
- A temporary derived image `isaac_ros_cuvslam_runtime:humble-rs-cone-l3d-20260812` (`sha256:3062ea205303...`) adds only pinned `ros-humble-pointcloud-to-laserscan=2.0.1-3focal.20231003.024830`; package discovery, executable enumeration, and dynamic linking passed without changing the base image or either Git worktree.
- The cone startup has a real DDS-discovery race: `start_competition.sh` checks `/cone_obstacle/scan_humble` exactly once immediately after odometry appears. B2 first exited at that check, while the retained container already had the pointcloud converter/exporter alive and subsequently listed the topic with continuously advancing healthy frames. This needs a bounded retry in the startup script.
- After reusing the same container, the Foxy stack passed exact safety/provenance gates: `/cmd_vel` had zero subscribers, no Lite3/command bridge/TaskManager node or exact process existed, UDP 43893 had no listener, D455 owner count was one, the derived image was exact, and local costmap plugins were `static_layer`, `cone_obstacle_layer`, `inflation_layer`.
- The first real 10-second Foxy data sample received 98 scans. Every sampled scan had 180 beams in `base_link`; every health message was healthy; maximum source age was `68.511 ms`; the gate had completed its required three-frame warmup and reported allowed. Humble raw scan measured about `30.859 Hz`; the UDP/Foxy published path is intentionally around 10 Hz.


## Phase 78 fast supervised full14 L6 run - 2026-08-11

- The first gate attempt sent no goal: all five lifecycle nodes and the action server were active, and `tf2_echo` had already emitted `(4.689,0.746)` plus a quaternion near pi, but the parser incorrectly required the later RPY line. The exit trap stopped the stack and Docker cleanly before retry.
- The actual run started at `(4.650,0.750,3.142)` with Lite3 prepare `simple=50 complex=48 errors=0`, one NavigateToPose server, and a zero command chain with `udp_errors=0`.
- Route result: points 1-9 succeeded, including `lower_corner_clear` and `pos2b_lower_right`; point 10 `grab_area_approach=(3.1,2.0,0)` aborted after about 19.9 seconds; points 11-14 were not sent due to `--stop-on-failure`.
- Segment 10 started at `(2.717,1.873,-2.865)` and ended at `(2.452,2.004,0.762)`, still about `0.646m` from the target. Terminal handover never triggered because the distance stayed above `0.35m`.
- The direct failure was DWB local control: `controller_server` reported `No valid trajectories out of 335` twice, then aborted FollowPath and NavigateToPose. This is not the prior point-13 global Planner failure and not the prior point-1 no-motion fault.
- The last two probe command samples were zero. Bridge diagnostics remained `udp_errors=0` and showed continuous zero output for about 2.0 seconds after abort before cleanup. Nav2/probe/bridge/cuVSLAM/RealSense processes and Docker were empty after cleanup.
- Evidence: `/home/superwfx666/competition_logs/nav2_waypoint_sequence/20260811_134549_phase78_fast_full14_retry/` with 13 hashed files. This is L6 evidence for 9 successful points and a point-10 DWB abort, not a complete-route pass.

## Phase 76 persistent full14 deployment - 2026-08-11

- Jetson deploy is clean at `52d30d66883538d46f571eb392b6e84680a21d72`, with 11 route points, two `xy_goal_tolerance=0.15` values, and no terminal no-replanning BT.
- The approved six runtime files are committed in source commit `94137ea0bbc10b0e46b684fad5f9c123aced6bfc`; commit-level checks show 14 points, `lower_corner_clear` at point 8, two `0.30` tolerances, planner tolerance `0.20`, and all required runtime files present.
- Initial audit considered an isolated six-file deployment branch. A complete range audit then showed `52d30d6..94137ea` is only six consecutive related commits and 13 files: the six runtime files plus the matching start-script default, real calibration template, navigation notes, and regression tests. The coherent persistent deployment is therefore a fast-forward of the existing branch to `94137ea`, after creating a local backup branch at `52d30d6`.
- The old commit remains an explicit rollback target. Normal shutdown must preserve the new deploy commit; rollback is never automatic.
- Jetson `Stonefield/nav2-foxy-dwb-integration` was fast-forwarded cleanly to `94137ea0bbc10b0e46b684fad5f9c123aced6bfc`; local backup branch `backup/jetson-11pt-xy015-20260811` points to `52d30d66883538d46f571eb392b6e84680a21d72`.
- L2 deployment evidence passed: one-package colcon build, deploy-only `ros2 pkg prefix`, source/install `cmp` for params, preview/real routes and terminal BT, installed 14-point parse, point 8 `lower_corner_clear`, two `0.30` goal tolerances, planner `0.20`, and action-free `--describe-route` with 14 steps.
- Final Jetson state had no Nav2/probe/bridge/cuVSLAM/RealSense process and no Docker container. No lifecycle node was activated and no motion command was sent. Evidence is in `/home/superwfx666/competition_logs/deployment/20260811_133108_full14_94137ea/`.
- Local verification passed: focused 17 tests plus 24 subtests, expanded 106 tests plus 24 subtests excluding only the pre-existing Lite3 fixture, JSON/Python/Markdown contracts, `git diff --check`, and ROS skill validator with zero issues.
- This establishes a persistent L2 deployment, not a 14/14 L6 result. Existing field evidence remains 12 successful points, point 13 planner abort, and point 14 not sent.

## Phase 55 local costmap 与安全过渡路线实现 — 2026-08-10

- `configs/navigation/nav2_params.yaml` 的 local costmap 已由单独 `inflation_layer` 改为 `static_layer + inflation_layer`；静态层复用 Foxy 当前 global costmap 已验证的 `nav2_costmap_2d::StaticLayer` 与 transient-local 地图订阅配置。
- `upper_corner_clear=(2.60,3.25,pi)` 已加入 preview waypoint、inspection/full route、真实标定模板和默认校准/路线常量；`pos2a_upper_right -> upper_corner_clear -> pos1_middle_turned` 将原斜切墙角改为先沿墙右侧下降、再穿过中间走廊的 L 形路线。
- 保持两处 `xy_goal_tolerance=0.20m`、`inflation_radius=0.30m`、`cost_scaling_factor=3.0` 和全部速度/backend 参数不变，避免把第二轮 inflation 调整混入当前修复。
- 新增 `tests/test_navigation_static_clearance.py`：锁定 local static layer 契约；确认 Phase 53 历史碰撞姿态会失败；对新 L 形中心线 102 个位置、24 个 yaw 做 padded footprint 扫掠，全部不与 Phase 1 PGM 占用栅格重叠。
- 聚焦导航测试 11/11 通过；排除既有 `test_lite3_udp_smoke.py` 夹具错误后，设置正确 `PYTHONPATH=src` 的扩展标准库回归 101/101 通过。全量原始 discover 的唯一剩余业务外错误是既有 mock `SimpleNamespace` 缺 `test_closed_yaw`，本次未修改该不相关测试。
- 当前验证级别为 L0/L1；尚未在 Jetson 实际加载 local static layer，也未在真机运行新 12 航点路线。机器狗必须先回官方起点，下一轮只跑前六点并检查 local costmap 静态墙与足迹净空。

## Phase 53 第 5 段 NavFn 失败根因 — 2026-08-10

- 第 5 段目标 `pos1_middle_turned=(1.50,3.25,-pi/2)` 的中心静态净空为 `0.750m`，目标足迹不碰撞；因此不是目标点本身被占用，也不是 `0.20m` goal tolerance 造成。
- 第 5 段从约 `(2.792,4.385,2.872)` 正常运动 `11.586s` 到约 `(2.165,3.893,-2.119)`；终止位姿中心距最近占用栅格仅 `0.196436m`，带 `0.02m` padding 的实际足迹与 Phase 1 PGM 上巡检区墙角明确重叠。
- 轨迹复算显示：第 `7.922s` 足迹首次切入占用栅格，当时中心净空仍为 `0.441901m`；第 `9.750s` 中心净空首次低于 `inflation_radius=0.30m`；第 `10.164s` 低于 padded footprint 的 `0.27m` 最小半径。随后周期 NavFn 无法从当前膨胀区内生成到目标的有效路径并 abort。
- 直接配置原因：global costmap 有 `static_layer + inflation_layer`，但 DWB 使用的 rolling local costmap 只有 `inflation_layer`，没有 `static_layer`、voxel/obstacle layer 或其他障碍源；因此 `BaseObstacle` 在局部控制阶段看不到静态巡检区墙，无法阻止转弯足迹扫入墙角。
- 放大因素：padded footprint 的半尺寸约 `0.37x0.27m`，外接半径约 `0.458m`，而全局 inflation radius 仅 `0.30m`。这不足以用中心点代价对任意旋转姿态提供保守净空；本应由局部完整足迹碰撞检查补足，但当前 local costmap 缺少静态墙。
- 修复边界：先让 local costmap 加载静态墙以恢复 DWB 足迹安全约束，再通过更大转角净空或安全过渡航点保证第 4→5 段可行；只继续增大 `xy_goal_tolerance` 不会解决该故障。

## Requirements
- 用户要求：首先根据 L1 系统在 `C:\Users\111\Desktop\比赛\quadruped-robot-competition` 创建 PWF 三件套。
- 三件套位置：仓库根目录。
- 三件套文件：
  - `task_plan.md`
  - `progress.md`
  - `findings.md`

## Research Findings
- 仓库是四足机器人比赛项目，目标平台是 NVIDIA Jetson Xavier NX，主要传感器是 Intel RealSense D455。
- 当前完成度最高的链路是 D455 + OpenCV 仪表识别 + ROS2 状态发布。
- 主要 ROS2 节点是 `scripts/gauge_status_node.py`。
- 仪表识别算法位于 `src/cv/gauge_detector/gauge_detector.py`。
- 连续帧稳定判定和结果有效性校验位于 `src/cv/gauge_detector/live_validation.py`。
- `/gauge/status` 发布 JSON 字符串，`/gauge/detected` 发布 `std_msgs/msg/Bool`。
- 文档明确当前阶段不发布非零 `/cmd_vel`，以只读感知和状态订阅为主。
- Git 状态观察：本地 `main` 相对 `origin/main` ahead 1，未观察到未提交改动。
- 用户给出的 GitHub URL 与本地 `origin` 一致：`https://github.com/youngman05/quadruped-robot-competition.git`。
- GitHub Web 页面访问返回 404；Git remote 查询可访问，说明更可能是私有仓库或 Web 工具无权限。
- 远端 `origin/main` 当前指向 `158a9b6 Update gauge status documentation`。
- 本地 `main` 当前指向 `62d8370 Update work log for documentation sync`，相对远端 ahead 1。
- 本地领先远端的 1 个提交只修改 `docs/work_log.md`。
- 远端分支包括 `origin/main` 和 `origin/stable/jetson-gauge-ok`。
- 本地 PWF 三件套 `task_plan.md`、`progress.md`、`findings.md` 是新增未提交文件。
- `stable/jetson-gauge-ok` 不是 `main` 的简单旧版本；它包含 `493431f Capture Jetson stable gauge script` 和 `45aa5cc Document Lite3 ROS2 bring-up` 两个 `main` 没有的提交。
- `main` 包含 stable 没有的后续提交，包括 gauge ROS2 status node、稳定帧判定和文档更新。
- `stable/jetson-gauge-ok` 中已有 tracked 的 `task_plan.md`、`progress.md`、`findings.md`；当前 `main` 上新建的未跟踪 PWF 三件套会影响直接 checkout。

## Navigation 技术栈调研补充 — 2026-07-09
- 本地 `Stonefield/nav2-foxy-dwb-integration` 分支实际工作区位于 `C:\Users\111\Desktop\比赛\quadruped-robot-competition-nav2-dwb`；分支指针当前与 `origin/main` 同为 `72e3833`，但该 worktree 中存在大量未提交 Nav2 集成改动，真正需要保护和推进的是这些未提交文件。
- 该 worktree 的 `navi/README.md` 明确定位为 Nav2 Foxy host 方案：cuVSLAM Docker/Humble -> host `/odom` + TF -> Nav2 map_server/NavFnPlanner(use_astar=true)/DWB -> `/cmd_vel` -> Lite3。
- 该 worktree 的 `configs/navigation/nav2_params.yaml` 当前使用 NavFn A* 全局规划 + DWBLocalPlanner，动态 D455 障碍物输入在第一版 DWB profile 中刻意禁用，等待 Jetson `/camera/depth/points` 验证。
- 官方 Nav2 文档确认：NavFn 支持 Dijkstra 或 A*，`use_astar=true` 时使用 A*；DWB 是基于 Dynamic Window Approach 的默认控制器；RPP 面向服务/工业机器人路径跟踪，适用于 differential、Ackermann、legged 等平台；Nav2 调优指南说明 RPP 更偏精确路径跟踪，DWB/MPPI 可在动态障碍物场景中偏离路径避障。
- NVIDIA Isaac ROS 官方资料确认：Isaac ROS Visual SLAM 支持带 IMU 的 RealSense 相机教程；RealSense setup 文档列出 D455 为支持型号；Nvblox RealSense 示例把 nvblox 与 Visual SLAM 结合使用，但若 Nav2 保持 Foxy host 而 cuVSLAM/nvblox 在 Humble Docker，则不能直接加载 Humble 侧 `nvblox_nav2` 插件，需要同发行版运行或做消息转换。
- ROS2 Foxy 已 EOL，Jetson 当前仍因 Ubuntu 20.04/L4T 约束使用 Foxy host；这使“少改发行版、少引入新插件、优先跑通比赛链路”比追求最新 Nav2 功能更重要。

## A* + Savitzky-Golay + RPP 路线评估 — 2026-07-09
- 官方 Nav2 NavFn 文档说明 NavFn planner 可使用 Dijkstra 或 A* 扩展；这支持将 A* 作为静态栅格地图上的全局路径规划层。
- 官方 Nav2 RPP 文档说明 Regulated Pure Pursuit 是 Pure Pursuit 变体，会按路径曲率等因素调节线速度，目标是降低拐角超调并更安全地跟踪路径；文档和 README 均说明其适用于 service/industrial robot，且可用于 legged robot。
- 官方 Nav2 Simple Smoother / Smoother Server 文档说明 Nav2 的 smoother 设计目标就是把 planner 输出路径变平滑，以减少 jagged path / oscillation；因此“全局路径规划 -> path smoothing -> controller tracking”这个三段式架构本身合理。
- SciPy `savgol_filter` 文档说明 Savitzky-Golay 是一维滤波器，可沿给定 axis 对数组做平滑；原始 Savitzky & Golay 1964 论文提出用简化最小二乘过程做平滑/微分。将其用于路径时，应分别对按弧长重采样后的 x(s)、y(s) 序列平滑，并保留起终点/碰撞检查。
- 对本比赛而言，A* + SG + RPP 适合作为“已知小场地 + 固定航点 + 四足可低速原地转向”的主叙述路线；但代码落地要注意 SG 平滑可能把路径拉进障碍物或墙体，必须在膨胀地图上二次碰撞检查，或只对离障碍物足够远的路径段平滑。

## 比赛最稳导航路线全网调研结论 — 2026-07-09
- 官方 Nav2 调优文档明确：RPP 适合精确路径跟踪，不负责动态障碍物偏离；DWB/MPPI 更偏局部动态避障和轨迹采样。对本比赛的小场地固定航点流程，RPP 适合承担路径跟踪，但需要外部安全门处理随机锥桶。
- Nav2 MPPI 是预测控制器，功能强但参数/算力/版本复杂度高；对当前 Jetson Xavier NX + ROS2 Foxy host + Humble Docker cuVSLAM 混合环境，不适合作为赛前主线。
- Nav2 Smac 2D/Hybrid/State Lattice 能产生更高质量 A* 路径，但当前 Host Foxy 已 EOL 且 Stonefield 已有 NavFn/DWB dry-run 证据，赛前不宜为追求“更高级 planner”引入新依赖。
- NVIDIA Isaac ROS Nvblox 官方说明可由 depth+pose 生成 3D reconstruction 和 Nav2 2D costmap；它是技术上更完整的视觉避障方案，但当前 D455 已被 cuVSLAM Docker 占用，且 Foxy host 不能直接复用 Humble Docker 的 Nav2 costmap 插件，赛前应降级为 Docker depth relay 或 YOLO/depth safety gate。
- 对本比赛最稳路线应是“确定性全局规划 + 轻量平滑跟踪 + 独立安全门 + 状态机重试”：A*/Theta* 负责已知地图与动态锥桶重规划，SG/shortcut 只做碰撞检查后的路径平滑，RPP/Pure Pursuit 低速跟踪，D455 depth/YOLO safety gate 负责 STOP/SLOW，任务管理器按阶段切地图和航点。

## Stonefield 实测闭环实现发现 — 2026-07-09
- Stonefield worktree 中 `cmd_vel_bridge.py` 是更合适的底层保活改动点，因为它位于 Nav2 `/cmd_vel` 与 Lite3 UDP 之间，不会推翻现有 Nav2 dry-run 成果。
- Lite3 官方 transfer driver `Jetson2Motion.cpp` 对每个 `/cmd_vel` 回调按顺序发送 `linear.x`、`linear.y`、`angular.z` 三个 MotionComplexCMD；Stonefield Python bridge 之前默认只发一个主轴。为安全起见，当前默认保留单轴优先，新增 `send_combined_axes` 作为实测开关。
- `depth_relay_docker.py` 写出的是 raw uint16 depth image + meta，不包含相机内参；新增 depth safety gate probe 因此只能做中心 ROI 深度门控和滞回验证，不等价于完整 base_link 3D 点云安全门。
- Stonefield worktree 没有 PWF 三件套，当前 session 的实质进度继续记录在启动仓库的 `progress.md/findings.md` 中。

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| 初始化三件套时只记录仓库现状，不新增业务任务 | 当前用户请求是建立 L1-2 记忆基础设施，不是修改功能 |
| 将仓库观察结论写入 `findings.md` | 这些是恢复上下文所需的事实性发现 |
| 将本次创建动作写入 `progress.md` | `progress.md` 作为项目级 append-only 日志，需要记录实际动作 |
| 远端测试 stable 分支时优先使用独立 worktree/独立目录，不直接切换现有 main 工作区 | `main` 与 `stable/jetson-gauge-ok` 已分叉，且 PWF 三件套跟踪状态不同；直接 checkout 容易冲突或污染当前国赛主线 |

## GitLab/GitHub 协同管理资料来源 — 2026-06-26
- GitLab Protected branches 官方文档说明：protected branches 用于控制谁能 merge/push、阻止关键分支误删、执行 code review / approval、管理 Code Owner approval 和 force push 权限。
- GitLab Code Owners 官方文档说明：CODEOWNERS 用于定义特定路径的专家/负责人，并可结合 protected branches 要求 owner 批准 MR。
- GitHub Protected branches 官方文档说明：branch protection rules 可限制删除/force push，并要求 PR、审批 review、状态检查或线性历史等。
- GitHub CODEOWNERS 官方文档说明：CODEOWNERS 文件可放在 `.github/`、仓库根目录或 `docs/`，用于自动请求对应 owner review。
- GitHub Pull request reviews 官方文档说明：仓库管理员可要求合并前获得 approvals，以保证代码质量并避免误合并。
- 本次学习文档据此采用“main 受保护 + 功能分支 + MR/PR + CODEOWNERS + Jetson 集成测试 + release/tag”的轻量企业协作模型。

## User Workflow Clarification
- 本机是主要开发环境。
- GitHub 私有仓库是同步中心。
- 远端 Ubuntu 系统中有一份基本一致的仓库，用于 `git pull` 后测试。
- 除 PWF 三件套尚未提交外，用户预期本机、GitHub、远端 Ubuntu 三处代码基本一致。
- `main` 分支当前面向国赛方向，包含 ROS2 节点封装和 topic 通信。
- `stable/jetson-gauge-ok` 分支更接近预赛第一天仪表盘识别稳定版本。
- 用户计划先把 stable 版本在远端 Ubuntu 上测试，通过后再放到本机对应“第一部分/第一任务一”的位置。

## Current Remote Access Finding
- 目标远端：`superwfx666@100.126.48.49`
- SSH / TCP 22 已恢复可达。
- 远端主仓库路径：`~/quadruped-robot-competition`
- 远端 stable 测试 worktree：`~/quadruped-robot-competition-stable`
- 远端 stable worktree 当前 detached at `45aa5cc Document Lite3 ROS2 bring-up`。
- 远端 `git fetch origin --prune` 因 HTTPS remote 在非交互 SSH 中缺少 GitHub 凭据而失败；但已有 `origin/stable/jetson-gauge-ok` 引用可用。

## Remote Stable Test Results
- Python syntax check passed for stable branch scripts.
- `python3 scripts/run_gauge_sample.py` passed:

```text
sample_gauge -> yellow / 偏低 / 异常
```

- Stable branch D455 live script starts successfully and reads from Intel RealSense D455.
- Current live test did not detect a valid gauge because the camera view did not contain a complete valid gauge; observed invalid reasons:
  - `low_color_ratio=0.0000`
  - `weak_color_zones=[...]`
  - `no_hough_circle`
- This is not a code crash; it is an input-scene validity result.

## 第一部分：任务一（表计识别）正式要求

### Core Objective
- 编写视觉算法程序，语言可用 C++ 或 Python。
- 程序读取官方给定的表计/指针仪表图片素材。
- 通过计算机视觉自动识别表计读数或状态，并输出最终结果。

### Hard Requirements
- 禁止硬编码答案。
- 代码必须包含真实图像处理流程，例如：
  - 图像预处理
  - 边缘检测
  - 轮廓提取
  - 指针角度解算
  - 颜色/刻度区域判定
- 严禁直接用 `print()` 或 `std::cout` 输出预先看好的答案。
- 程序从执行到结果输出必须全自动。
- 不允许运行时用鼠标框选表盘或人工指定指针位置。
- 基础图片素材应从官方 `赛题.pdf` 截图或提取，不要求额外训练深度学习数据集。
- 传统 OpenCV 算法可以满足任务要求。

### Deliverable 1: Source Code
- 目标目录：`文档与源码/源码包/视觉相关/`
- 可放置独立脚本或功能包，例如 `gauge_recognition`。
- 代码需要必要注释，说明识别逻辑：
  - 如何提取指针
  - 如何计算角度
  - 如何将角度或颜色区域转换为读数/状态

### Deliverable 2: Validation Video
- 文件名：`第一部分-任务1.mp4`
- 目标目录：`第一部分/`
- 视频必须完整录制：
  - 终端敲入运行指令
  - 程序开始处理
  - 屏幕终端或图像窗口显示最终识别读数
- 单段录屏绝对不能超过 5 分钟。
- 必须原始正常速度，严禁软件加速。
- 视频左下角必须全程显示文字水印：

```text
学校名称+队伍名称+组别
```

### Submission Checklist
- 源码包含真实 OpenCV/视觉处理逻辑。
- 源码中不存在投机取巧的直接打印答案。
- 运行脚本后无需鼠标键盘干预即可输出结果。
- 演示视频不超过 5 分钟。
- 录屏左下角水印清晰可见且全程存在。

## Mapping to Current Repository
- 当前 stable 分支已有传统 OpenCV 表计识别逻辑，核心文件为：
  - `src/cv/gauge_detector/gauge_detector.py`
  - `scripts/run_gauge_sample.py`
  - `scripts/realsense_gauge_live.py`
- 对第一部分任务一而言，更应提交“读取官方图片素材并输出识别结果”的离线脚本，而不是 ROS2 topic 节点。
- `main` 分支中的 ROS2 topic 封装更适合后续国赛/系统集成，不是任务一提交的必要内容。
- 任务一交付包应突出：
  - 输入官方图片
  - 自动识别
  - 终端输出结果
  - 无人工交互
  - 无硬编码答案

## Pulled Back Tested Script
- 用户确认在 Jetson/Ubuntu 上测试通过的脚本是：
  - `scripts/realsense_gauge_live.py`
- 已从远端 stable worktree 拉回本机同一路径。
- 本机拉回后的 SHA256：

```text
b4252401d11d86f0061da9224d37cefeb6059fe359151e5f59d39cf527dfe8c3
```

- 本机语法检查通过：

```text
python -m py_compile scripts\realsense_gauge_live.py
```

## Submission Package Placement
- Task 1 source package target:

```text
C:\Users\111\Desktop\比赛\西交利物浦大学+团队名称+四足机器人大型组\文档与源码\源码包\视觉相关\gauge_recognition
```

- Added tested D455 live script:

```text
realsense_gauge_live.py
```

- The script was adapted for the submission package by changing its detector import path from the original repository layout to the current `gauge_recognition` folder.
- Updated package README with commands:

```bash
python3 realsense_gauge_live.py --verbose --debug-dir /tmp/gauge_debug
python3 realsense_gauge_live.py --frames 20 --verbose --debug-dir /tmp/gauge_debug
```

- Task 1 video target remains:

```text
C:\Users\111\Desktop\比赛\西交利物浦大学+团队名称+四足机器人大型组\第一部分\任务一
```

## Live Preview Window Update
- `realsense_gauge_live.py` now opens an OpenCV window by default.
- The window displays the current D455 RGB image.
- The frame overlay shows:
  - timestamp
  - valid / invalid status
  - gauge level
  - normal / abnormal status
  - detected color
  - needle angle
  - invalid reason when detection is rejected
- Terminal output remains available for recording and grading.
- To quit from the preview window, press `q`.
- For SSH/headless testing, use:

```bash
python3 realsense_gauge_live.py --no-window --verbose
```

- For live preview recording on the Jetson desktop, use:

```bash
python3 realsense_gauge_live.py --verbose --debug-dir /tmp/gauge_debug
```

## Live Preview Troubleshooting
- If the program starts but no live image appears, first make sure it is being run from the Jetson graphical desktop terminal, not a plain SSH session.
- SSH session check showed `DISPLAY` was empty; GUI windows are not expected to appear from that context.
- OpenCV on Jetson has GTK support, so GUI display should work from desktop.
- The script now calls `cv2.namedWindow` and updates the display every received camera frame.
- If D455 startup fails with:

```text
Device or resource busy
```

then another process is already using the camera. On 2026-05-07, the occupying process was:

```text
python3 realsense_gauge_live.py
```

Stop the existing terminal process with Ctrl+C before rerunning.

## Expected Current Runtime Behavior
- Run from Jetson graphical desktop terminal:

```bash
cd ~/quadruped-robot-competition-stable/scripts
python3 realsense_gauge_live.py
```

- Expected:
  - The same terminal continuously prints current recognition status.
  - A separate OpenCV window named `D455 Gauge Recognition` opens.
  - The window shows the current D455 camera image with status overlay.
- Optional flags:
  - `--quiet-invalid`: suppress terminal messages for invalid/no-gauge frames.
  - `--no-window`: run without GUI window for SSH/headless testing.

## Terminal Output Bug Fix
- Symptom: live preview window appeared, but terminal did not print live recognition status.
- Cause: duplicate interval gate in the main loop. The first gate updated `last_run`; the second gate then prevented the recognition block from running.
- Fix:
  - Removed the first gate.
  - Kept continuous frame display.
  - Kept recognition/printing at `--interval`.
  - Added `flush=True` to status prints.

## Gauge Validation Compatibility Fix
- Symptom: camera showed a real gauge, but terminal still printed invalid/no-gauge status.
- Inspection of Jetson debug frames showed the original detector was actually finding:
  - circle
  - angle
  - color
  - level/status
- Cause: `realsense_gauge_live.py` validation expected newer ROS2 detector fields:
  - `circle_detected`
  - `color_coverage`
  - `direction_scores`
- The submission-package `gauge_detector.py` is the older Task 1 detector and only returns fields such as:
  - `circle`
  - `angle`
  - `color`
  - `level`
  - `status`
- Fix: accept legacy detector output when it has a circle, valid color, angle, level, and status.
- Verified real captured frames now validate as:

```text
偏低 / 异常 / yellow -> ok_legacy_detector
偏高 / 异常 / red -> ok_legacy_detector
```

## Split Terminal Live Viewer Design
- Requirement: after running the stable D455 gauge script, the original terminal should keep printing the current gauge state, while a newly opened terminal/window displays the live D455 image.
- Constraint: two independent Python processes should not both open the D455 camera, because RealSense access is exclusive and can cause `Device or resource busy`.
- Implemented approach in remote main repository `~/quadruped-robot-competition/scripts/realsense_gauge_live.py`:
  - Main process is the only process that starts the RealSense pipeline.
  - Main process prints gauge state in the original terminal.
  - Main process publishes the latest RGB frame to `/tmp/d455_gauge_live_view.jpg`.
  - Viewer process runs with `--viewer-only`, reads `/tmp/d455_gauge_live_view.jpg`, and displays it with OpenCV.
  - If `DISPLAY` is present and a terminal such as `gnome-terminal` exists, main process auto-opens the viewer terminal.
- OpenCV 4.2 detail: `cv2.imwrite()` needs a recognized file extension. Atomic frame writing must use a temp name like `d455_gauge_live_view.tmp.jpg`, not `d455_gauge_live_view.jpg.tmp`.

## Current Remote Main Runtime Command
- From Jetson graphical desktop terminal:

```bash
cd ~/quadruped-robot-competition
python3 scripts/realsense_gauge_live.py
```

- Expected behavior:
  - Original terminal continuously prints current gauge recognition status.
  - A second terminal opens automatically.
  - The second terminal displays the current D455 image in an OpenCV window.
- For SSH/headless smoke testing:

```bash
python3 scripts/realsense_gauge_live.py --frames 1 --no-viewer-terminal
```

## Camera/IMU/cuVSLAM Branch Import
- GitHub branch `feature/camera-imu-cuvslam` points to commit `8b713c2474ef5b67f9df85f1f2be3534f922bd75`.
- The commit is a root commit with no parents; GitHub compare reports no common ancestor with `main`.
- Decision: do not merge this branch directly and do not use `--allow-unrelated-histories` for normal integration.
- Safer integration path used:
  - Create a normal local branch from current `main`: `codex/import-camera-imu-cuvslam`.
  - Download the remote branch snapshot.
  - Selectively import only the new camera/IMU/cuVSLAM files and documentation.
- Imported capabilities:
  - `RealsenseCamera` D455 wrapper with context manager lifecycle.
  - Factory presets: `for_gauge()` and `for_cuvslam()`.
  - Color/depth/infrared stereo stream support.
  - BMI055 IMU sample helpers.
  - Projector control for cuVSLAM mode.
  - Depth post-processing filter presets.
  - `scripts/realsense_viewer.py` for D455 color/depth overlay viewing.
  - Package metadata (`pyproject.toml`, `setup.py`) so `src/` modules can be imported as package modules after editable install.
- Implementation note:
  - Imported branch docs used shorthand constructor keyword examples such as `color=True`, but actual constructor args are `enable_color`, `enable_depth`, `enable_infrared`, and `enable_imu`.
  - Docs/comments were corrected during import to avoid runtime keyword errors.
  - Imported wrapper used Python 3.10-style annotations (`str | Path`, `list[IMUSample]`); these were changed to Python 3.8-compatible `Union[...]` and `List[...]` because Jetson deployment currently targets Python 3.8.
- Local verification status:
  - Syntax checks passed.
  - Python 3.8 parse checks passed for the new wrapper/viewer files.
  - Whitespace check passed.
  - Full runtime/hardware checks require Jetson because local Windows Python lacks `cv2` and `pyrealsense2`.

## cuVSLAM Navigation Research — 2026-06-22
- User goal: use NVIDIA cuVSLAM / Isaac ROS Visual SLAM for navigation with only a depth camera and IMU.
- Primary sources checked:
  - NVIDIA Isaac ROS Visual SLAM documentation.
  - NVIDIA Isaac ROS Visual SLAM RealSense tutorial.
  - NVIDIA Isaac ROS Nvblox documentation.
  - NVIDIA Isaac ROS Visual SLAM GitHub repository page.
- Key findings:
  - Isaac ROS Visual SLAM / cuVSLAM estimates odometry from one or more stereo cameras and optionally IMU; it is an odometry/localization source for navigation, not a full navigation stack by itself.
  - Current latest Isaac ROS Visual SLAM docs target ROS 2 Jazzy and newer Jetson platforms; older release docs show ROS 2 Humble support, while ROS versions earlier than Humble are explicitly unsupported.
  - Current repository docs and Jetson deployment are ROS 2 Foxy / Ubuntu 20.04 oriented, so cuVSLAM should be introduced in an isolated Isaac ROS Humble/Jazzy environment first, not directly dropped into the current Foxy runtime.
  - cuVSLAM camera requirements are strict: at least 30 Hz images, low jitter, and tightly synchronized stereo image timestamps.
  - For RealSense with IMU, NVIDIA tutorial expects IR stereo image topics, camera info, `/camera/imu`, and cuVSLAM outputs such as `/visual_slam/tracking/odometry`, `/visual_slam/tracking/vo_pose`, `/visual_slam/status`, and TF.
  - NVIDIA docs warn that the RealSense emitter/projector can hurt pose estimation; for cuVSLAM stereo IR mode, projector should be disabled.
  - Isaac ROS Visual SLAM does not provide standalone global localization without pose hint/external localization; it can save/load maps and localize with a hint, but robust global localization should be treated as a separate capability.
  - Isaac ROS Nvblox consumes depth + pose, reconstructs a 3D scene, and provides a 2D costmap to Nav2 for vision-based obstacle avoidance.
- Architectural implication:
  - Recommended stack is `D455 IR stereo + IMU -> cuVSLAM odometry/TF -> nvblox depth costmap -> Nav2 planner/controller -> robot cmd_vel/vendor bridge`, with current Lite3 control kept read-only until onsite safety validation.

## Jetson Environment Probe — 2026-06-23
- SSH target used successfully: `superwfx666@100.126.48.49`.
- User-provided `superwfx666-desktop@100.126.48.49` is not a valid SSH user on the host; Tailscale reported local user `superwfx666-desktop` not found.
- Hostname: `superwfx666-desktop`.
- Jetson model: `NVIDIA Jetson Xavier NX Developer Kit`.
- OS: Ubuntu 20.04.6 LTS (Focal Fossa).
- L4T: R35 release, revision 6.4.
- Kernel: `5.10.216-tegra`.
- Installed L4T package: `nvidia-l4t-core 35.6.4-20260126234748`.
- JetPack meta package `nvidia-jetpack` is not installed, but apt candidate is `5.1.6-b5`; effective platform corresponds to JetPack 5.1.6 / L4T 35.6.4.
- CUDA compiler exists at `/usr/local/cuda/bin/nvcc` and `/usr/local/cuda-11.4/bin/nvcc`; version is CUDA 11.4.315, but `nvcc` is not on default PATH.
- Docker is not installed or not on PATH.
- NVIDIA container runtime packages were not detected.
- ROS installation:
  - `/opt/ros/foxy`
  - ROS distro after sourcing setup: `foxy`
  - `ros2 pkg list` count: 168
  - installed core package: `ros-foxy-ros-base 0.9.2`
  - detected `ros-foxy-tf2-ros`
  - no installed Nav2 / navigation2 / RealSense ROS packages detected by package query.
- Python:
  - Python 3.8.10
  - `cv2` available, version 4.2.0
  - `pyrealsense2` import works
  - `numpy` version 1.17.4
- cuVSLAM implication:
  - Current host is firmly JetPack 5 / Ubuntu 20.04 / ROS 2 Foxy, while current Isaac ROS Visual SLAM docs target newer ROS 2 stacks.
  - A container-based Isaac ROS test path will first require Docker + NVIDIA container runtime installation, or a separate JetPack/ROS upgrade path.

### Reusable SSH Probe Procedure
- Use SSH target:

```bash
ssh superwfx666@100.126.48.49
```

- Do not use `superwfx666-desktop@100.126.48.49`; `superwfx666-desktop` is the hostname, not a valid login user.
- If Tailscale SSH prints an approval URL, the user must approve it in browser before non-interactive commands will complete.
- On Windows PowerShell, avoid putting complex remote shell scripts directly in a quoted one-liner when they contain pipes or regex alternation. Prefer:

```powershell
$remoteScript = @'
echo "===HOST==="
hostname
whoami
cat /etc/nv_tegra_release 2>/dev/null || true
ls -1 /opt/ros 2>/dev/null || true
'@
$remoteScript | ssh -o BatchMode=yes -o ConnectTimeout=10 superwfx666@100.126.48.49 'bash -s'
```

- Commands used for this probe:

```bash
tr -d '\0' < /proc/device-tree/model
cat /etc/os-release
cat /etc/nv_tegra_release
dpkg-query -W -f='${Package} ${Version}\n' nvidia-l4t-core nvidia-jetpack
uname -a
/usr/local/cuda/bin/nvcc --version
ls -1 /opt/ros
source /opt/ros/foxy/setup.bash && ros2 pkg list | wc -l
dpkg-query -W -f='${Package} ${Version}\n' 'ros-foxy-*'
python3 -c 'import cv2, pyrealsense2, numpy'
```

## cuVSLAM Hardware Feasibility Probe — 2026-06-23
- Scope: verify whether current Jetson + existing D455/IMU hardware can run cuVSLAM inputs.
- SSH target: `superwfx666@100.126.48.49`.
- Safety boundary: read-only and short diagnostics only; no package installs, no Docker install, no ROS installs, no nonzero `/cmd_vel`.
- Probe method:
  - Initial PowerShell here-string attempts caused UTF-8 BOM and here-doc parsing issues on the remote bash side.
  - Stable method was to write a local UTF-8-without-BOM, LF-only shell script and pipe it with `cmd.exe /c type ... | ssh ... bash -s`.
- Hardware enumeration result:
  - `lsusb` did not show Intel RealSense D455.
  - USB tree showed Realtek USB hubs, Intel wireless/Bluetooth, and Logitech receiver, but no RealSense device.
  - `/dev/video*` was absent.
  - `v4l2-ctl --list-devices` only showed NVIDIA Tegra media device `/dev/media0`.
  - `pyrealsense2` imported, but `rs.context().query_devices()` returned `device_count=0`.
  - `rs-enumerate-devices` was not installed.
- Software/runtime result:
  - ROS2 Foxy is installed, but no Isaac ROS Visual SLAM/cuVSLAM, RealSense ROS, Nav2/navigation2, or nvblox packages were found.
  - Docker and NVIDIA container runtime were not detected.
- Current conclusion:
  - cuVSLAM cannot be run on the current hardware state because the required D455 input device is not enumerated by Jetson.
  - It is not yet meaningful to test infrared stereo or IMU streams; those require RealSense enumeration first.
  - Even after hardware enumeration is fixed, the current Foxy-only host is not a direct Isaac ROS Visual SLAM runtime. It needs an isolated compatible Isaac ROS environment, most likely Docker + NVIDIA container runtime, or a separate Humble/Jazzy setup.
- Immediate next validation gate:
  - D455 must appear in `lsusb` as an Intel RealSense device.
  - `/dev/video*` nodes must appear.
  - `pyrealsense2` must report `device_count >= 1`.
  - Then run short stream tests for infrared 1/2 and accel/gyro.

### Reusable D455 Enumeration Probe

```powershell
$script = @'
printf '===USB===\n'
lsusb
printf '\n===VIDEO===\n'
ls -l /dev/video* 2>/dev/null || true
printf '\n===V4L2===\n'
if command -v v4l2-ctl >/dev/null 2>&1; then v4l2-ctl --list-devices 2>&1 || true; else echo 'v4l2-ctl not found'; fi
printf '\n===PY_RS_COUNT===\n'
python3 -c "import pyrealsense2 as rs; ctx=rs.context(); ds=list(ctx.query_devices()); print('device_count=', len(ds)); [print(d.get_info(rs.camera_info.name), d.get_info(rs.camera_info.serial_number)) for d in ds]"
'@
$script = $script -replace "`r`n", "`n"
$tmp = Join-Path $env:TEMP 'cuvslam_probe_usb_lf.sh'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($tmp, $script, $utf8NoBom)
$cmd = 'type "' + $tmp + '" | ssh.exe -o BatchMode=yes -o ConnectTimeout=10 superwfx666@100.126.48.49 bash -s'
cmd.exe /c $cmd
```

## D455 Connected Re-test — 2026-06-23 16:19
- User connected the D455 to the Jetson and the enumeration status changed from not detected to detected.
- Device enumeration:
  - USB: `Bus 002 Device 003: ID 8086:0b5c Intel Corp. USB3.2 Hub`.
  - USB tree shows the RealSense device under the USB3 bus at `5000M` with `uvcvideo` video interfaces and `usbhid` motion interface.
  - `/dev/video0` through `/dev/video5` now exist.
  - `v4l2-ctl --list-devices` shows `Intel(R) RealSense(TM) Depth Ca`.
  - `pyrealsense2` reports `device_count=1`.
  - Device info: Intel RealSense D455, serial `235422300321`, firmware `5.17.0.10`, USB descriptor `3.2`, product ID `0B5C`.
  - Sensors: `Stereo Module`, `RGB Camera`, `Motion Module`.
- Visual stream tests:
  - `infrared 1 + infrared 2` at `640x480 y8 30fps` started successfully.
  - 3-second SSH short test observed `ir1_count=79`, `ir2_count=79`, approx `26.1 Hz`.
  - `infrared 1 + infrared 2 + depth` at `640x480 30fps` also started successfully.
  - 3-second SSH short test observed `ir1_count=81`, `ir2_count=81`, `depth_count=81`, approx `26.8 Hz`.
- Motion/IMU finding:
  - Supported motion profiles include accel `100/200 Hz` and gyro `200/400 Hz`.
  - Starting accel/gyro through `pyrealsense2` failed with:

```text
Failed to set frequency ... in_accel_sampling_frequency Last Error: Permission denied
```

  - IIO sampling frequency files are `root:root` and mode `600`:
    - `/sys/bus/iio/devices/iio:device0/in_anglvel_sampling_frequency`
    - `/sys/bus/iio/devices/iio:device1/in_accel_sampling_frequency`
  - No RealSense udev rules were found under `/etc/udev/rules.d` or `/lib/udev/rules.d`.
  - `sudo -n true` failed, so no non-interactive root-level fix/test was attempted.
- Updated conclusion:
  - D455 visual hardware input is now sufficient for the camera side of cuVSLAM validation.
  - D455 IMU is physically detected but blocked by host permissions.
  - Full cuVSLAM hardware readiness is therefore **partially passed**: camera/IR/depth pass, IMU pending udev/root-permission fix.
  - Software stack gap remains unchanged: current host is ROS2 Foxy without Isaac ROS Visual SLAM, RealSense ROS, Nav2, nvblox, Docker, or NVIDIA container runtime.

## cuVSLAM Reliability Assessment — 2026-06-23
- Decision: cuVSLAM is technically credible as an odometry/VIO component, but not reliable enough to be the sole competition navigation baseline on the current Xavier NX + Ubuntu 20.04 + ROS2 Foxy host.
- Evidence:
  - Current NVIDIA Isaac ROS Visual SLAM documentation targets ROS2 Jazzy on Jetson Thor / JetPack 7.1 or x86_64 with newer NVIDIA GPU stack.
  - Historical Isaac ROS 2.1 documentation supported ROS2 Humble on Jetson Xavier / JetPack 5.1.2, but NVIDIA notes that the Ubuntu 20.04 Focal buildfarm for Isaac ROS 2.1 ended on 2025-06-30 and old Humble Debian packages for Ubuntu 20.04 are no longer available from the Isaac Apt Repository.
  - The current Jetson host is ROS2 Foxy only; ROS2 versions earlier than Humble are explicitly not supported by Isaac ROS Visual SLAM 2.1.
  - D455 camera-side input now works, but measured SSH short test saw IR/depth around 26-27 Hz; NVIDIA camera requirements list 30 Hz target, tight framerate jitter, and tight stereo timestamp offset. A ROS topic-level timing test is still required.
  - IMU is detected but blocked by IIO permissions until RealSense udev/root-permission handling is fixed.
  - cuVSLAM outputs odometry/localization, not a complete navigation solution; usable autonomy still needs depth mapping/costmap, Nav2, robot control bridge, and safety gating.
- Practical recommendation:
  - Use cuVSLAM as a research/backup odometry track, validated in an isolated container or separate environment.
  - Do not make it the only competition path until a minimal chain proves stable for at least: D455 IR/depth/IMU topics, cuVSLAM odometry, TF, tracking status, and recovery behavior under real robot vibration/motion.

## Issues Encountered
| Issue | Resolution |
|-------|------------|

## Resources
- `README.md`
- `docs/system_design.md`
- `docs/work_log.md`
- `docs/test_checklist.md`
- `scripts/gauge_status_node.py`
- `src/cv/gauge_detector/gauge_detector.py`
- `src/cv/gauge_detector/live_validation.py`
- Git remote: `https://github.com/youngman05/quadruped-robot-competition.git`

## Visual/Browser Findings
- 本次未查看图片、PDF 或浏览器页面。

## GitHub Feature Branch Import Finding — 2026-06-23 16:58 +08:00
- eature/camera-imu-cuvslam has no common ancestor with main, so it should be treated as a source snapshot rather than directly merged with --allow-unrelated-histories.
- Useful content imported into local main:
  - InstanceSegmentation/ YOLOv8-seg workspace.
  - configs/yolo/classes.yaml already exists and remains part of the repo.
  - Documentation updates were manually merged instead of overwritten.
- Binary model weights from the feature branch were intentionally not kept in Git:
  - InstanceSegmentation/yolov8n.pt
  - InstanceSegmentation/yolov8n-seg.pt
  - InstanceSegmentation/models/yolov8n.pt
- .gitignore now excludes model artifacts under InstanceSegmentation/.
- Documentation correction: D455 visual streams are verified, but D455 IMU is not fully verified because accel/gyro access is blocked by IIO permissions until RealSense udev/root fix is applied.

## Latest GitHub Main Jetson D455 Validation — 2026-06-23 17:44 +08:00
- GitHub latest `main` is `11b783e` (`Merge pull request #1 from youngman05/codex/import-camera-imu-cuvslam-segmentation`) and includes the D455 Python wrapper under `src/cv/realsense_camera/`.
- Jetson original repo at `~/quadruped-robot-competition` could not directly `git pull` latest private GitHub code because:
  - remote URL is HTTPS and non-interactive fetch cannot read GitHub credentials;
  - `gh` CLI is not installed;
  - SSH auth to `git@github.com` fails with `Permission denied (publickey)`;
  - the repo has a local modified `scripts/realsense_gauge_live.py`.
- To test the exact GitHub latest code without overwriting Jetson local changes, latest `origin/main` was transferred as a git bundle and checked out into `/home/superwfx666/quadruped-robot-competition-main-latest-test` at `11b783e`.
- `python3 -m pip install --user -e .` succeeded from that latest worktree; plain `python3` imports `cv.realsense_camera` from the latest worktree.
- RealSense udev fix:
  - Installed official librealsense `99-realsense-libusb.rules` to `/etc/udev/rules.d/99-realsense-libusb.rules` using `root@100.126.48.49`.
  - Reloaded and triggered udev rules.
  - D455 IIO sampling frequency nodes changed from non-user-writable `root:root 600` to writable permissions, unblocking accel/gyro.
- Post-fix D455 tests as ordinary user:
  - RGB/depth smoke test passed at `640x480`, center depth around `2.372 m`.
  - IR left/right + depth short test passed with roughly `80` frames over `3.0 s`.
  - IMU short test passed with `accel=755`, `gyro=755` frames over about `2.0 s`.
  - Wrapper `RealsenseCamera.for_cuvslam(accel_rate=200, gyro_rate=200)` passed, returning IR left/right `(480, 640)` and IMU samples.
  - Wrapper full mode with RGB + depth + IR + IMU passed.
- Current conclusion:
  - For the user’s “修 RealSense IMU udev 权限；跑通 D455 IR/depth/IMU；确认 D455 Python 封装已导入” checklist, the hardware/input/wrapper side is now validated on Jetson with latest GitHub main.
  - This does not yet mean full Isaac ROS Visual SLAM/cuVSLAM runtime is available; earlier environment finding remains: Jetson is Ubuntu 20.04 / ROS2 Foxy without Docker/NVIDIA container runtime/Isaac ROS Visual SLAM/Nav2/nvblox.

## Reusable D455 Input Validator — 2026-06-23 17:55 +08:00
- Added PR branch `codex/add-realsense-cuvslam-input-test` with `scripts/realsense_cuvslam_input_test.py`.
- PR #2: `https://github.com/youngman05/quadruped-robot-competition/pull/2`.
- Intended Jetson command after editable install:

```bash
cd ~/quadruped-robot-competition
python3 scripts/realsense_cuvslam_input_test.py --seconds 2.0
```

- The script validates:
  - D455 enumeration and sensor list.
  - RGB + depth through `RealsenseCamera`.
  - IR1 + IR2 + depth through direct `pyrealsense2` multi-stream pipeline.
  - IMU accel + gyro through direct `pyrealsense2` motion streams.
  - cuVSLAM wrapper preset through `RealsenseCamera.for_cuvslam()`.
- Jetson original repo update status:
  - Local old modification to `scripts/realsense_gauge_live.py` was protected before update:
    - backup branch `backup/jetson-local-gauge-live-20260623-175008`;
    - patch `/home/superwfx666/jetson_repo_backups/realsense_gauge_live_local_20260623-175008.patch`;
    - stash `stash@{0}`.
  - Original repo fast-forwarded to `11b783e` via git bundle.
  - Original repo then switched to local branch `codex/add-realsense-cuvslam-input-test` at `bc46b40` for validator testing.
- Final Jetson result from `scripts/realsense_cuvslam_input_test.py --seconds 2.0`:
  - D455 enumeration passed: serial `235422300321`, firmware `5.17.0.10`, USB `3.2`.
  - RGB/depth passed: color `(480, 640, 3)`, depth `(480, 640)`, center depth around `2.372 m`.
  - IR stereo + depth passed: `ir1=52`, `ir2=52`, `depth=52`, baseline `0.095029 m`.
  - IMU passed: `accel=738`, `gyro=738`.
  - `RealsenseCamera.for_cuvslam()` passed with left/right IR `(480, 640)` and IMU sample.
  - Script ended with `All D455 input checks passed.`
- Implementation lesson:
  - Direct IR+depth validation is more reliable with raw `pyrealsense2` framesets.
  - The existing `RealsenseCamera.get_depth_image()` path internally uses `get_frames()`, which expects a color frame; avoid using it in color-disabled IR/depth-only wrapper configurations unless the wrapper is later refactored.

## Jetson GitHub SSH Credential Setup — 2026-06-23 18:14 +08:00
- Jetson now has account-level GitHub SSH access through a dedicated key:
  - private key: `/home/superwfx666/.ssh/id_ed25519_quadruped_robot_competition`
  - SSH config alias: `github.com-quadruped`
  - repo origin: `git@github.com-quadruped:youngman05/quadruped-robot-competition.git`
- GitHub SSH probe succeeded:

```text
Hi youngman05! You've successfully authenticated, but GitHub does not provide shell access.
```

- Jetson can now run normal Git commands against GitHub:

```bash
cd ~/quadruped-robot-competition
git fetch origin --prune
git pull --ff-only
```

- After PR #2 merge, Jetson `main` was fast-forwarded to `82512c6`.
- Current Jetson repo state:
  - branch `main`
  - clean relative to `origin/main`
  - HEAD `82512c6`
- Previous Jetson local `scripts/realsense_gauge_live.py` change remains recoverable:
  - branch `backup/jetson-local-gauge-live-20260623-175008`
  - patch `/home/superwfx666/jetson_repo_backups/realsense_gauge_live_local_20260623-175008.patch`
  - stash `stash@{0}`
- Current D455 physical state after credential setup:
  - D455 is not enumerated (`lsusb` has no `8086:0b5c`).
  - `/dev/video*` is absent.
  - `pyrealsense2` reports `device_count=0`.
  - Therefore `scripts/realsense_cuvslam_input_test.py` fails correctly with `No RealSense device found`.
- Action when the camera is reconnected:

```bash
cd ~/quadruped-robot-competition
python3 scripts/realsense_cuvslam_input_test.py --seconds 2.0
```

## Isaac ROS Visual SLAM Runtime Bringup — 2026-06-23
- Hardware regression after reconnect passed on Jetson latest `main`:
  - `scripts/realsense_cuvslam_input_test.py --seconds 2.0` reports one D455 (`serial=235422300321`, firmware `5.17.0.10`, USB `3.2`).
  - RGB/depth PASS, IR1/IR2/depth PASS, accel/gyro PASS, and `RealsenseCamera.for_cuvslam()` PASS.
- Runtime route remains container isolated:
  - Host stays ROS2 Foxy.
  - Isaac ROS workspace is `~/workspaces/isaac_ros-dev`.
  - Source repos are on `release-2.1`: `isaac_ros_common`, `isaac_ros_visual_slam`, `isaac_ros_nitros`.
  - Base image available: `nvcr.io/nvidia/isaac/ros:aarch64-ros2_humble_42f50fd45227c63eb74af1d69ddc2970`.
- Build blocker diagnosis:
  - Previous `colcon build --packages-up-to isaac_ros_visual_slam` failed in `isaac_ros_nitros`.
  - Error: `fatal error: nvToolsExt.h: No such file or directory` and `/usr/bin/ld: cannot find -lnvToolsExt`.
  - `isaac_ros_nitros` enables `USE_NVTX` by default and links `nvToolsExt`.
  - Jetson host had partial CUDA 11.4 packages but not `cuda-nvtx-11-4`, so the `run_dev.sh` aarch64 bind mount assumption was not satisfied.
- Fix applied:
  - Installed Jetson package `cuda-nvtx-11-4` as root.
  - This created:
    - `/usr/local/cuda-11.4/targets/aarch64-linux/include/nvToolsExt.h`
    - `/usr/local/cuda-11.4/targets/aarch64-linux/lib/libnvToolsExt.so`
    - `/usr/local/cuda-11.4/targets/aarch64-linux/lib/libnvToolsExt.so.1`
    - `/usr/local/cuda-11.4/targets/aarch64-linux/lib/libnvToolsExt.so.1.0.0`
- L1-3 note:
  - Attempted `brv query "Isaac ROS Visual SLAM cuVSLAM Jetson D455 runtime"` from the Windows repo host.
  - `brv` is not in PATH and no ByteRover MCP tool is currently exposed, so no long-term-memory result was available for this runtime step.

## Isaac ROS Visual SLAM Runtime Short-Test Result — 2026-06-23
- Build/runtime dependency resolution:
  - `isaac_ros_nitros` passed after installing and mounting `cuda-nvtx-11-4`.
  - `isaac_ros_visual_slam` final link then failed on `libcusolver.so.11`.
  - Installed Jetson host packages `cuda-libraries-11-4` and `cuda-cupti-11-4`, providing:
    - `libcusolver.so.11`
    - `libcusparse.so.11`
    - `libcurand.so.10`
    - `libcufft.so.10`
    - `libcupti.so.11.4`
  - Re-running the container build completed successfully: `7 packages finished`, including `isaac_ros_visual_slam`.
  - `ldd install/isaac_ros_visual_slam/lib/isaac_ros_visual_slam/isaac_ros_visual_slam` reported no missing shared libraries in the mounted runtime environment.
- Runtime image:
  - Built local image `isaac_ros_cuvslam_runtime:humble-rs` from the Isaac ROS Humble base image.
  - Added `ros-humble-realsense2-camera`, `ros-humble-realsense2-camera-msgs`, `ros-humble-realsense2-description`, and dependencies.
  - `apt-get update` fails in this old base image because the Isaac ROS focal apt Release endpoint is gone and some keys are stale; direct `apt-get install` using the existing package list succeeded.
- RealSense ROS driver probe:
  - Container detected D455 serial `235422300321`, firmware `5.17.0.10`, USB `3.2`.
  - RealSense ROS v4.54.1 / librealsense v2.54.1 started.
  - Published expected topics:
    - `/camera/infra1/image_rect_raw`
    - `/camera/infra2/image_rect_raw`
    - `/camera/imu`
    - camera info, IMU info, extrinsics, and TF static topics.
  - Observed approximate rates:
    - `/camera/infra1/image_rect_raw`: about 89.9 Hz at `640x360`.
    - `/camera/imu`: about 200 Hz.
- Official cuVSLAM RealSense launch result:
  - Command inside container:

```bash
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch isaac_ros_visual_slam isaac_ros_visual_slam_realsense.launch.py
```

  - Logs confirmed:
    - `Load Library: .../libvisual_slam_node.so`
    - `cuVSLAM version: 11.4`
    - `Time taken by CUVSLAM_WarmUpGPU()`
    - `Baseline is : 0.095029`
    - `left_camera_pose_imu reading from TF Tree`
    - `Use use_gpu: true`
    - `Enable IMU Fusion: true`
    - `Time taken by CUVSLAM_CreateTracker()`
  - ROS graph confirmed `/visual_slam_node` subscribes to:
    - `/camera/infra1/image_rect_raw`
    - `/camera/infra1/camera_info`
    - `/camera/infra2/image_rect_raw`
    - `/camera/infra2/camera_info`
    - `/camera/imu`
  - ROS graph confirmed `/visual_slam_node` publishes:
    - `/visual_slam/status`
    - `/visual_slam/tracking/odometry`
    - `/visual_slam/tracking/slam_path`
    - `/visual_slam/tracking/vo_pose`
    - `/tf`
    - `/tf_static`
    - visualization topics.
  - 20-second message count probe after GPU warmup:
    - `infra1`: 1732
    - `infra2`: 1730
    - `imu`: 3724
    - `status`: 1739
    - `odom`: 1735
  - Last sampled status:
    - `vo_state: 1` (success)
    - `track_execution_time`: about `0.00162 s`
    - `node_callback_execution_time`: about `0.00204 s`
  - Last sampled odometry:
    - `frame_id: odom`
    - `child_frame_id: camera_link`
    - Static camera produced zero pose, as expected for a stationary short test.
- Remaining runtime risk:
  - Logs contain repeated `Delta between current and previous frame ... above threshold [22.000000]`.
  - Short-test is sufficient to say runtime enters and publishes successful VO output.
  - It is not yet sufficient to claim field stability; next test should move the camera/robot for 3-5 minutes and record odom continuity, dropped frames, tracking state, and delta warnings.

## cuVSLAM Motion Probe Result — 2026-06-24
- Scope: 180-second hand-held or lightly mounted motion probe on Jetson using D455 + Isaac ROS Visual SLAM/cuVSLAM runtime.
- Jetson log directory: `/home/superwfx666/cuvslam_lite3_logs/20260624-162501`.
- Preflight:
  - D455 input validator passed all checks before launch.
  - Runtime container launched successfully and detected D455.
  - cuVSLAM log confirmed version `11.4`, baseline `0.095029`, IMU fusion enabled, and tracker created.
- Probe rates and continuity:
  - `/camera/infra1/image_rect_raw`: `13814` messages over 180 s, about `76.97 Hz`.
  - `/camera/infra2/image_rect_raw`: `13803` messages over 180 s, about `76.91 Hz`.
  - `/camera/imu`: `35171` messages over 180 s, about `195.96 Hz`.
  - `/visual_slam/status`: `12672` messages over 180 s, about `71.22 Hz`.
  - `/visual_slam/tracking/odometry`: `12672` messages over 180 s, about `71.22 Hz`.
  - `vo_state_counts=1:12672`; all sampled status messages reported successful VO state.
  - Odom changed continuously with about `1.85 m` delta norm across the probe.
- Timing/stability risk:
  - The launch log added `656` image delta warnings during the 180-second probe.
  - The full launch log contained `1437` image delta warnings and `10` `Visual tracking is lost` warnings.
  - There were `2` Motion Module failure warnings at startup, but `0` new Motion Module failures during the probe.
  - No launch `ERROR` lines were counted.
- Current conclusion:
  - cuVSLAM is runnable on the Jetson/D455 stack and can keep publishing status/odom through a light motion test.
  - It is not yet stable enough to be the sole navigation baseline because frame timing jitter and lost-tracking warnings remain significant.
  - Next technical target should be timing/load mitigation before Nav2 or autonomous motion integration: compare lower IR FPS/profile, reduce competing load, inspect RealSense ROS timestamps/QoS, and repeat the same 180-300 s probe.

## cuVSLAM RViz / Loop-Closure Demo Requirements — 2026-06-24
- Teacher-facing requirement:
  - Use RViz to visually inspect cuVSLAM loop closure behavior.
  - Demonstrate long-distance or large-loop tracking performance, not only static startup.
  - Show that cuVSLAM publishes the expected ROS topics for downstream navigation.
- Practical interpretation for this repo:
  - Keep `/visual_slam/status` visible or logged; `vo_state=1` is the key success signal during motion.
  - In RViz, show `/visual_slam/tracking/odometry`, `/visual_slam/tracking/vo_path`, and `/visual_slam/tracking/slam_path` to compare instantaneous tracking and optimized SLAM trajectory.
  - Enable SLAM visualization topics and show `/visual_slam/vis/landmarks_cloud`, `/visual_slam/vis/loop_closure_cloud`, `/visual_slam/vis/pose_graph_nodes`, `/visual_slam/vis/pose_graph_edges`, and `/visual_slam/vis/pose_graph_edges2`.
  - Keep D455 IR topics visible: `/camera/infra1/image_rect_raw`, `/camera/infra2/image_rect_raw`, plus `/camera/imu` rate logs.
  - A valid demo should move through a 3-5 minute large loop and return near the start area; the interesting moment is whether loop-closure/pose-graph visualization appears and whether `vo_state` remains healthy.
- Script support:
  - `scripts/start_cuvslam_rviz_gui.sh` starts the Isaac ROS Humble cuVSLAM container from a Jetson GUI/VNC/NoMachine session.
  - The script is read-only with respect to robot motion and never publishes `/cmd_vel`.
  - It writes a RViz config into the run log directory and records `topics.txt`, `topic_check.txt`, `status_once.txt`, and selected `ros2 topic hz` outputs.
  - Default launch args enable SLAM visualization, landmarks view, observations view, and localization-and-mapping.
  - Debug dump is optional via `--debug-dump`; it is not enabled by default to avoid adding load during long motion tests.

## ROS2 Foxy Host vs Humble cuVSLAM Container Communication — 2026-06-24
- Current split:
  - Jetson host competition environment is ROS2 Foxy on Ubuntu 20.04.
  - Isaac ROS Visual SLAM/cuVSLAM runs in an isolated ROS2 Humble container.
- Communication implication:
  - Same-machine ROS2 topic discovery can work through DDS if the container uses host networking, the same `ROS_DOMAIN_ID`, and a compatible RMW implementation.
  - Cross-distribution communication is not the same as API/source compatibility. It may work for standard messages such as `nav_msgs/msg/Odometry`, `geometry_msgs`, `sensor_msgs`, and TF when message definitions match.
  - It is risky to make Foxy host nodes directly depend on Humble-only custom interfaces such as `isaac_ros_visual_slam_interfaces/msg/VisualSlamStatus` unless those interfaces are also built for Foxy.
- Recommended integration path:
  - Keep cuVSLAM inside the Humble container for now; do not install Isaac ROS into the host Foxy environment.
  - Export only stable standard interfaces to the host/robot stack first: `/visual_slam/tracking/odometry` (`nav_msgs/Odometry`) and `/tf`/`/tf_static`.
  - Treat `/visual_slam/status` as a health signal that can be consumed inside the Humble container, then bridge or republish a simple standard type such as `std_msgs/Bool` or `std_msgs/String` if Foxy needs it.
  - Set `ROS_DOMAIN_ID` explicitly on both host and container, and default to `rmw_fastrtps_cpp` because Foxy commonly uses Fast DDS.
  - If direct DDS discovery is unstable, use an explicit bridge/relay process rather than relying on implicit cross-distro topic visibility.
- Script update:
  - `scripts/start_cuvslam_rviz_gui.sh` now passes `ROS_DOMAIN_ID` and `RMW_IMPLEMENTATION` into the cuVSLAM container.
  - Defaults are `ROS_DOMAIN_ID=0` and `RMW_IMPLEMENTATION=rmw_fastrtps_cpp`; override them before running if the host competition stack uses a different domain.

## cuVSLAM RViz Script Sync State — 2026-06-25
- GitHub `main` contains `scripts/start_cuvslam_rviz_gui.sh` at commit `4275300 feat: add cuVSLAM RViz GUI launcher`.
- The script was committed on top of the current GitHub `main=0347fbc`, not the stale Windows local base `2f5e60d`.
- Reason: Windows host could not push over HTTPS because `github.com:443` was unreachable, and Jetson showed GitHub `main` had been force-updated since the Windows local tracking ref.
- Jetson GitHub SSH access through `github.com-quadruped` was used to push the clean commit from a temporary worktree.
- Jetson current working repo also has the script copied directly to:

```text
/home/superwfx666/quadruped-robot-competition/scripts/start_cuvslam_rviz_gui.sh
```

- Remote verification:
  - executable mode: `-rwxr-xr-x`
  - syntax: `bash -n scripts/start_cuvslam_rviz_gui.sh` passed
  - SHA256: `60427f32b2ddf24e3a4eedf0899339657e13aaa04ca8bd3cd098db04d50ea2fa`
- Important caution:
  - Jetson current working repo `HEAD` is still `82512c6` and has many local modifications/deletions.
  - The copied script appears as untracked in that working repo because we did not fast-forward or reset it.
  - Do not run a blind `git pull` in that Jetson working repo until the local changes are reviewed or moved aside.

## cuVSLAM Loop Metrics Recorder — 2026-06-25
- The RViz script alone was not enough to judge loop-closure accuracy because it only wrote topic lists, hz, and launch logs.
- New recorder script:
  - subscribes to `/visual_slam/tracking/slam_path`
  - subscribes to `/visual_slam/tracking/vo_path`
  - subscribes to `/visual_slam/tracking/odometry`
  - writes live summary and final summary files under the run log directory
- The main accuracy number to read after a loop demo is:

```text
loop_metrics_latest.txt -> closure_error_m
```

- Recommended interpretation for the 20 m loop demo:
  - `< 0.2 m` = good
  - `0.2 m - 0.5 m` = usable but drifting
  - `>= 0.5 m` = not good enough to claim accurate closure
- Load/stability mitigation applied:
  - default RealSense IR profile changed from `640x360x90` to `640x360x60`
  - `img_jitter_threshold_ms` changed from `22` to `35`
  - RViz heavy image/cloud displays are opt-in, not default
- This means the next loop run should be judged primarily by numeric path metrics, not only by the presence of RViz topic panels.

## cuVSLAM RViz Launcher Startup Fix — 2026-06-25
- Root cause of 2026-06-25 post-recorder startup failures:
  - Generated `/logs/run_cuvslam_launch.py` used `PythonLaunchDescriptionSource.get_launch_description()` without a `LaunchContext`.
  - In the Jetson ROS2 Humble launch API, this raises `TypeError: get_launch_description() missing 1 required positional argument: 'context'`.
  - Because the launch runner exited before creating the cuVSLAM node, the shell script waited for `/visual_slam/status` and timed out before RViz could open.
- Fix:
  - Generate runner with `from launch import LaunchContext`.
  - Call `source.get_launch_description(LaunchContext())`.
- Secondary finding:
  - The custom default `CUVSLAM_CAMERA_PROFILE=640x360x60` caused RealSense ROS to create topics but repeatedly report `Frames didn't arrived within 5 seconds`; cuVSLAM did not reach `CUVSLAM_CreateTracker()` and recorder saw no odometry/path samples.
  - The default was reverted to the previously proven `640x360x90`.
  - Keep `CUVSLAM_CAMERA_PROFILE` as an environment override for future experiments, but do not use `640x360x60` as the default until it has a clean RealSense frame-flow validation.
- Validation after fix:
  - Remote no-RViz smoke test log: `/home/superwfx666/cuvslam_lite3_logs/20260625-155658`.
  - `TypeError=0`, `Frames Timeout=0`, `RealSense Node Is Up=1`, `CUVSLAM_CreateTracker=1`.
  - Recorder received data: `odometry.samples=375`, `slam_path.poses=1024`, `vo_path.poses=1024` while camera was stationary.

## cuVSLAM Re-run Check — 2026-06-25
- Latest Jetson run log directory:
  - `/home/superwfx666/cuvslam_lite3_logs/20260625-202512`
- Result:
  - The previous launch API failure is gone.
  - cuVSLAM starts, RViz starts, and the expected topics are present.
  - `RealSense Node Is Up=1`, `CUVSLAM_CreateTracker=1`, `TypeError=0`, `Frames Timeout=0`.
- Remaining issues:
  - `Delta between current and previous frame` still appears frequently, about `361` lines in this run.
  - `rviz.log` only shows harmless `XDG_RUNTIME_DIR` fallback and `Stereo is NOT SUPPORTED`.
  - `loop_metrics_latest.txt` reports `insufficient_motion`, but that label is misleading for this run because odometry already accumulated `37.303 m` and shows `closure_error_m=2.7190 m` with ratio `0.0729`.
  - `slam_path` / `vo_path` summaries remained at zero path length in the recorder output, so current loop judgment should rely on odometry plus manual RViz review, not on the recorder's interpretation string alone.
- Practical takeaway:
  - Startup chain is fixed.
  - Stability / frame timing still needs tuning before claiming a clean loop-closure demo.

## cuVSLAM Competition Localization Handoff — 2026-06-26

### What Was Done
- Continued debugging after user clarified the true goal: reduce cuVSLAM trajectory/loop error for competition-grade self-localization, not merely launch RViz.
- Re-read PWF context and ROS2 robotics references; ROS2 risks emphasized: TF frame semantics, QoS/topic correctness, and avoiding silent frame/topic mismatches.
- Queried Jetson latest run artifacts under `/home/superwfx666/cuvslam_lite3_logs/20260625-202512`.
- Queried live ROS graph/TF from active container `cuvslam_gui_20260625-202512`.

### Confirmed Facts
- Startup is no longer the blocking issue:
  - `TypeError=0`
  - RealSense frame timeout `0`
  - `RealSense Node Is Up=1`
  - `CUVSLAM_CreateTracker=1`
  - `Visual tracking is lost=0` in the latest long run
- Accuracy is still not good enough:
  - odometry path length: `37.303 m`
  - odometry closure error: `2.7190 m`
  - closure ratio: `0.0729`
  - This is too large to call competition-stable localization.
- Frame timing remains a risk:
  - Latest `launch.log` had about `380` `Delta between current and previous frame` warnings.
  - Raising `img_jitter_threshold_ms` only changes warning sensitivity; it does not fix true frame timing jitter.
- Current recorder interpretation is misleading:
  - `slam_path` and `vo_path` had `1024` poses but `path_length_m=0`, i.e. repeated/static points.
  - odometry clearly moved `37.303 m`.
  - Therefore recorder must choose the first source with real motion and explicitly report `primary_source`.
- Current TF semantics are wrong for robot self-localization:
  - Live parameter query confirmed `base_frame=camera_link`.
  - `/tf_static` includes RealSense internal transforms such as:
    - `camera_link -> camera_infra1_frame`
    - `camera_link -> camera_infra2_frame`
    - `camera_link -> camera_accel_frame`
    - `camera_link -> camera_gyro_frame`
  - `/tf_static` did not include `base_link -> camera_link`.
  - Thus current output is camera pose, not robot body pose.

### Partial Code Work Already Applied Locally
- File: `scripts/cuvslam_loop_metrics_recorder.py`
- Partial edits applied:
  - `LoopMetricsRecorder.__init__` now takes:
    - `min_path_length_m`
    - `good_closure_m`
    - `usable_closure_m`
  - odometry summary now stores:
    - `frame_id`
    - `child_frame_id`
  - Added `select_primary_source()`:
    - priority: `slam_path` if moving enough, else `vo_path`, else `odometry`
    - adds notes such as `slam_path_static_while_odometry_moved`
  - Replaced interpretation path with `interpret(primary_source)`.
- Still incomplete:
  - `write_summary()` still needs to print `primary_source`.
  - CLI arguments and constructor call still need to pass the new thresholds.
  - Must run `python -m py_compile scripts/cuvslam_loop_metrics_recorder.py` after finishing.

### Next Engineering Steps
1. Finish recorder output and CLI threshold wiring.
2. Modify `scripts/start_cuvslam_rviz_gui.sh`:
   - add configurable `CUVSLAM_BASE_FRAME`
   - add configurable static transform publisher for `base_link -> camera_link`
   - explicitly set `enable_localization_n_mapping`, `publish_map_to_odom_tf`, `publish_odom_to_base_tf`
   - consider `force_planar_mode` for ground robot tests after confirming parameter behavior
3. Ask/measure camera mounting extrinsics:
   - translation from `base_link` to `camera_link`: x/y/z in meters
   - rotation roll/pitch/yaw in radians or degrees
4. Copy scripts directly to Jetson dirty repo; do not run blind `git pull`.
5. Validate syntax and run a short no-RViz smoke test.
6. Run fixed-route A/B tests and compare:
   - closure error
   - closure ratio
   - delta warnings per minute
   - `vo_state` distribution
   - tracking lost count
   - whether `child_frame_id` is `base_link`

## GitHub README National Competition Stack Update — 2026-06-26

### Source Baseline
- 用户明确说明当前本机 workspace 与 GitHub 不同步，GitHub 应作为最新基准。
- 为避免污染当前本机 dirty workspace，README 任务在干净 worktree 中完成：
  - Path: `C:\Users\111\Desktop\比赛\quadruped-robot-competition-github-main-readme`
  - Base: GitHub `main=f517ad704278efe20453f6b120659ed42e5812c6`
  - Branch: `codex/readme-national-stack`
- 新增根目录 `README.md` 并推送到 GitHub `main`：
  - Commit: `b90e761 docs: add national competition stack README`

### Competition Rule Findings
- 国赛线下挑战核心任务分为：
  - 避障任务：自主穿越障碍区域，避开随机放置的 2 个锥形桶。
  - 巡检识别：识别 A/B/C/D 区域与仪表盘状态，并进行语音播报。
  - 长条抓取：抓取红色异常长条并放到异常仪表对应的 A/B/C/D 区域。
- 比赛禁止激光雷达，因此定位/导航路线必须使用视觉、IMU、深度相机或机器人自身里程计等非激光方案。
- 巡检播报得分依赖语音播报；只有终端输出正确但无语音播报会降分。
- 机械臂抓取是比赛任务组成部分，但用户明确当前仓库未实现机械臂控制，因此 README 只保留接口边界。

### Project Technical Stack Findings
- 当前项目国赛主线应表述为：
  - SLAM：D455 IR 双目 + IMU -> Isaac ROS Visual SLAM / cuVSLAM。
  - Navigation：cuVSLAM 提供 odom/TF，Nav2 使用 PGM 地图、NavFn/A*、Regulated Pure Pursuit 和 D455 点云 costmap 导航。
  - YOLO：YOLOv8 实例分割用于锥桶/障碍物、红/绿长条、物块类目标，以及可能的 A/B/C/D/仪表 ROI 辅助识别。
  - Gauge：OpenCV 传统视觉识别仪表盘指针角度和颜色区域，输出偏低/正常/偏高与异常/正常。
  - Task Manager：ROS2 状态机串联导航、巡检、播报、寻找红条、抓取/放置接口。
  - Speech：当前 `/speech/text` 接口存在，TTS 节点仍是占位。
- GitHub 最新仓库已包含：
  - `launch/competition.launch.py`
  - `launch/navigation.launch.py`
  - `configs/navigation/nav2_params.yaml`
  - `navi/map/competition_field.pgm`
  - `src/nodes/perception/gauge_status.py`
  - `src/nodes/perception/yolo_detect_publisher.py`
  - `src/nodes/navigation/cuvslam_bridge.py`
  - `src/nodes/decision/task_manager.py`
  - `scripts/start_cuvslam_rviz_gui.sh`
  - `scripts/cuvslam_loop_metrics_recorder.py`
- README 明确保留当前 cuVSLAM 主线问题：
  - 启动/RViz/topic 链路已基本打通。
  - 比赛级定位精度仍不足。
  - recorder 需要修正 `primary_source` 与 frame 输出。
  - 需要补 `base_link -> camera_link` 实测静态外参。
  - 需要固定路线 A/B 测试并以数字指标选择默认 profile。

### Important Documentation Risk
- GitHub 最新代码中 YOLO 类别描述存在不一致：
  - `InstanceSegmentation/projects/combined/README.md` 描述 combined 模型类别为 `red / green / obstacle`。
  - `configs/yolo/classes.yaml` 写的是 `gauge / A / B / C / D / red_bar / green_bar`。
  - `src/nodes/perception/yolo_detect_publisher.py` 注释也需要与实际模型类别统一。
- README 已将 YOLO 模块标注为“实例分割工作区和 ROS2 publisher 已存在，但比赛最终类别映射仍需统一验证”，避免把类别接口误写成稳定事实。

## cuVSLAM Competition Localization Local Fix — 2026-06-26

### Current SLAM State
- cuVSLAM 已经不是“不能跑”的阶段：D455 + Isaac ROS Visual SLAM runtime、RViz/topic 启动链路此前已跑通。
- 当前主要问题是比赛级定位精度与语义：
  - 最新已记录回环 odometry 路径约 `37.303 m`。
  - 回到起点仍有约 `2.719 m` 偏差，不能作为 5 m x 6 m 国赛场地的稳定导航基线。
  - 此前 recorder 会在 `slam_path` / `vo_path` 静态重复点时输出 `insufficient_motion`，掩盖 odometry 已经移动的事实。
  - 此前 cuVSLAM 输出使用 `base_frame=camera_link`，缺少 `base_link -> camera_link` 静态外参，因此更接近相机位姿，不是机器人本体位姿。

### Local Code Fixes
- `scripts/cuvslam_loop_metrics_recorder.py` 已完成本地修复：
  - 输出 `primary_source`，按 `slam_path -> vo_path -> odometry` 选择真正有运动的轨迹源。
  - 输出 `robot_base_ready`，直接判断 odometry `child_frame_id` 是否为 `base_link`。
  - 输出 odometry `frame_id` / `child_frame_id`。
  - 当 path topic 静止但 odometry 已运动时输出 `slam_path_static_while_odometry_moved` / `vo_path_static_while_odometry_moved`。
  - 支持 `--min-path-length`、`--good-closure`、`--usable-closure` 阈值参数。
- `scripts/start_cuvslam_rviz_gui.sh` 已完成本地修复：
  - 生成自定义 cuVSLAM launch 文件，不再只调用上游默认 RealSense launch。
  - 显式发布 `base_link -> camera_link` 静态 TF，外参通过 `CUVSLAM_BASE_TO_CAMERA_X/Y/Z/ROLL/PITCH/YAW` 配置。
  - 默认 `CUVSLAM_BASE_FRAME=base_link`，目标是让 cuVSLAM odometry 的 child frame 从 `camera_link` 修正到 `base_link`。
  - 显式配置 `enable_localization_n_mapping`、`publish_map_to_odom_tf`、`publish_odom_to_base_tf`。
  - 显式配置 `enable_ground_constraint_in_odometry` 和 `enable_ground_constraint_in_slam`，用于地面机器人约束测试。
  - 对齐官方 Isaac ROS Visual SLAM 参数名和 remap：
    - `imu_frame`
    - `image_jitter_threshold_ms`
    - `visual_slam/image_0`
    - `visual_slam/camera_info_0`
    - `visual_slam/image_1`
    - `visual_slam/camera_info_1`
  - RealSense profile 使用 `depth_module.infra_profile` 和 `depth_module.profile`，默认 `640,360,90`，因为此前 Jetson 实测 90 FPS 是已知可用 profile。

### Verification
- 本地检查已通过：
  - `bash -n scripts/start_cuvslam_rviz_gui.sh`
  - `python -m py_compile scripts/cuvslam_loop_metrics_recorder.py`
  - `git diff --check -- scripts/start_cuvslam_rviz_gui.sh scripts/cuvslam_loop_metrics_recorder.py`

### Remote Blocker
- Jetson `100.126.48.49` 在线，Tailscale 直连正常，`tailscale ping` 成功。
- TCP 22 可达，但 OpenSSH/Tailscale SSH 卡在用户认证阶段：
  - 日志显示已连接到 remote software `Tailscale`。
  - 已完成 key exchange。
  - 卡在 `ssh-userauth` 的 `input_userauth_banner` 后。
- 因此当前未完成的是 Jetson 脚本同步和 no-RViz 烟测；不是本地代码语法或网络连通性问题。
## cuVSLAM Bench vs Robot Semantics — 2026-06-26
- The current repo state now distinguishes two evaluation layers:
  - bench: hand-held Jetson + D455 loop validation, used to inspect camera-frame loop closure and SLAM stability.
  - robot: mounted-on-dog validation, used to verify `base_link` as the navigation reference frame.
- `child_frame_id=camera_link` from previous runtime logs is only valid for bench-camera verification, not final competition navigation readiness.
- Competition-grade readiness requires the robot-mode run to show the expected `base_link`-anchored frame chain and then feed navigation.
- Jetson 2026-06-26 smoke tests now prove both `bench` and `robot` modes can启动并且 recorder 能订到 `/visual_slam/tracking/odometry`。
- 当前两次 smoke test 的 `primary_source` 仍然没有达到可判闭环的运动长度，因此两次结果都只能说明链路通，不足以判断 5m x 6m 场地的闭环精度。
- `visual_slam_node` 发布 `/visual_slam/tracking/odometry` 与 `/visual_slam/tracking/vo_path` 的 QoS 是 `RELIABLE`，而 recorder 订阅用 `BEST_EFFORT` 也能接到样本，说明本轮不再是 QoS 断链问题。
- `visual_slam_node` 日志持续出现 `Delta between current and previous frame ... above threshold [22.000000]`，提示图像时序抖动仍需在后续带运动场景中继续关注。

## cuVSLAM Standalone Accuracy Limit for 10 cm Navigation — 2026-06-27
- User's target for national competition navigation is approximately `<= 0.10 m` localization error.
- Multiple bench/chair rectangle tests show D455 + Isaac ROS Visual SLAM/cuVSLAM alone is currently around `0.50-0.57 m` loop closure error:
  - custom wrapper best repeated runs: `0.5058 m`, `0.5260 m`, `0.5625 m`
  - official NVIDIA RealSense launch wrapper: `0.5744 m`
- The official launch comparison is important because it shows the custom wrapper is not the main source of error; the official baseline did not improve accuracy by an order of magnitude.
- The 5x6-ish wheeled-chair test produced a plausible rectangular trajectory shape in RViz, but metrics still showed:
  - `closure_error_m=0.5625`
  - `z_span_m=1.0236`
  - `slam_path` and `vo_path` effectively static while odometry moved
- Engineering implication:
  - cuVSLAM should be treated as a short-term visual odometry source, not as the sole 10 cm-class competition localization solution.
  - Next solution direction should be planar sensor fusion and correction anchors:
    - robot-localization EKF with `two_d_mode`
    - robot body IMU / proprioceptive odometry if available
    - accurate `base_link -> camera_link` extrinsics
    - external visual correction points such as AprilTag/ArUco/known field landmarks if allowed
- Do not keep spending time repeating the same bench loop as the primary path to 10 cm accuracy; it has established the current single-source cuVSLAM error scale.

## cuVSLAM SLAM Path vs Backend Pose Semantics — 2026-06-27
- Isaac ROS Visual SLAM source on the Jetson confirms `/visual_slam/tracking/slam_path` and `/visual_slam/tracking/vo_path` are bounded visualization/tracking Path topics:
  - `path_max_size` default is `1024`.
  - Internally they use `limited_vector`, which rotates old entries out when full.
  - They only add samples when the corresponding Path publisher has subscribers.
- Therefore a static or tiny `slam_path` is not sufficient by itself to conclude that the SLAM backend/global optimizer is not working.
- For backend/global trajectory diagnosis, use the new recorder fields in `loop_metrics_latest.txt`:
  - `all_poses_service`: official `visual_slam/get_all_poses` output from `CUVSLAM_GetAllPoses`.
  - `slam_odometry`: live `/visual_slam/vis/slam_odometry` stream, i.e. backend SLAM pose in `map`.
  - `vo_pose`: live `/visual_slam/tracking/vo_pose` stream.
  - `odometry`: `/visual_slam/tracking/odometry`, the smooth/front-end VO odometry used as a real-time navigation candidate.
- Interpretation rule for the next moving test:
  - If `all_poses_service.path_length_m` or `slam_odometry.path_length_m` moves while `slam_path.path_length_m` remains tiny, the old RViz/Path observation was a rolling-path/display artifact.
  - If `all_poses_service` and `slam_odometry` also remain tiny while `odometry` moves, the SLAM backend/global pose is not updating meaningfully and the next debugging target is cuVSLAM backend/localization-and-mapping behavior.
- Startup script self-exit root cause:
  - Default `ros2 topic list` can use the ROS daemon and return stale/incomplete graph data; on Jetson it returned only `/parameter_events` and `/rosout` while cuVSLAM had already reached `CUVSLAM_CreateTracker()`.
  - `ros2 topic list --no-daemon --spin-time 2` sees the full graph including `/visual_slam/status`, `/visual_slam/tracking/odometry`, `/visual_slam/vis/slam_odometry`, and pose graph topics.
  - Both cuVSLAM wrapper scripts now use this no-daemon topic-list command for wait/check logic, preventing false timeout exits.

## cuVSLAM Backend-Aware Rectangle Retest — 2026-06-27
- Log: `/home/superwfx666/cuvslam_lite3_logs/20260627-204848`.
- User deliberately gave cuVSLAM a clear visual landmark at both the start and return point.
- Backend stream `/visual_slam/vis/slam_odometry` moved normally and was selected as `primary_source`.
- Key comparison:
  - front-end `odometry` / `vo_pose` closure error: about `0.697 m`
  - backend `slam_odometry` closure error: about `0.224 m`
- This indicates the SLAM backend/global pose stream is providing meaningful correction in this run, even though rolling `slam_path` and `vo_path` Path topics remain nearly static.
- The visual-landmark return procedure likely helped loop/pose-graph consistency, but the result remains above the competition target of roughly `<=0.10 m`.
- Residual risks:
  - `launch.log` still contains about `952` image delta warnings, so camera timing/load remains unstable.
  - The run is still bench/camera-link mode, not final robot `base_link` navigation validation.
  - `all_poses_service` currently reports only a tiny path despite `slam_odometry` moving, so it should not be treated as the primary accuracy source until its service semantics/export limit are better understood.

## cuVSLAM 20cm -> 10cm tuning plan — 2026-06-27
- User clarified that the latest `~0.224 m` result should not be explained as "the camera saw the box at the finish":
  - previous hand-held/chair tests also started and ended at the same physical point;
  - the test procedure already looked at the box at both start and finish;
  - therefore the more plausible improvement is measuring the backend `/visual_slam/vis/slam_odometry` stream and allowing SLAM backend optimization to show up in the metric.
- Current bottleneck signals:
  - backend `slam_odometry` improved closure to about `0.224 m`;
  - front-end `odometry` / `vo_pose` still remained around `0.697 m`;
  - launch log still had about `952` image delta warnings;
  - test is still bench/camera-link mode, not robot/base-link navigation.
- Official/current-runtime reference findings:
  - Jetson's installed Isaac ROS Visual SLAM launch/source uses `denoise_input_images`, `img_jitter_threshold_ms`, `force_planar_mode`, `input_base_frame`, and `path_max_size`; this runtime, not a newer online branch, is the source of truth for scripts on the current Jetson.
  - The installed source declares `img_jitter_threshold_ms`, supporting treatment of repeated image delta warnings as timing/load diagnostics rather than just cosmetic logs.
  - The installed source declares `force_planar_mode`; this is the correct planar-motion knob for the current release.
  - Nav2 setup guidance uses `robot_localization` EKF to provide odometry for Nav2; robot_localization documentation recommends `two_d_mode` for planar robots to force 3D variables to zero.
- Implemented tuning hooks:
  - `CUVSLAM_PROFILE=planar_60fps`: `640x360x60`, `force_planar_mode=true`; first candidate because current warning count suggests 90fps may be overloading timing.
  - `CUVSLAM_PROFILE=planar_90fps`: `640x360x90`, `force_planar_mode=true`; isolates the effect of frame rate.
  - `CUVSLAM_PROFILE=official_like`: `640x360x90`, `force_planar_mode=false`; keeps a near-official baseline.
  - recorder now reports `xy_closure_error_m` and `z_span_m`; planar navigation should optimize primarily for XY closure, while Z span diagnoses vertical drift.
- Next Jetson test matrix:
  1. Same 5x6-ish route, same start/end mark, `CUVSLAM_PROFILE=planar_60fps`, no RViz if possible.
  2. Same route, `CUVSLAM_PROFILE=planar_90fps`, no RViz if possible.
  3. Optional: same route, `CUVSLAM_PROFILE=official_like`, no RViz.
  4. Compare `primary_source`, `xy_closure_error_m`, `closure_error_m`, `z_span_m`, `delta warnings/min`, and `/camera/*` hz logs.
- Success criterion for this tuning pass:
  - if `planar_60fps` reduces delta warnings and brings `slam_odometry.xy_closure_error_m <= 0.10 m`, keep it as default;
  - if both 60fps and 90fps remain above `0.10 m`, proceed to robot-mode EKF plus external correction anchors rather than repeating bench-only cuVSLAM loops.

## cuVSLAM internal TF requirement — 2026-06-27
- The `20260627-230911` `planar_60fps` run is invalid for accuracy evaluation because cuVSLAM crashed before recorder received samples.
- Root cause: disabling RealSense `publish_tf` removed D455 internal TFs required by cuVSLAM IMU fusion.
- Required TF chain for the current installed Isaac ROS Visual SLAM release includes `camera_link -> camera_gyro_optical_frame`.
- Do not disable RealSense internal TFs for cuVSLAM. For robot mode, publish the external `base_link -> camera_link` static transform in addition to RealSense's internal camera/IMU TFs.

## cuVSLAM 60 Hz valid bench result — 2026-06-27
- After restoring RealSense internal TFs, the `planar_60fps` bench/chair motion run at `20260627-232850` became valid.
- Reliable metric:
  - live `/visual_slam/vis/slam_odometry` closed at about `0.017 m` over `22.14 m` path length, with `z_span_m=0.0`.
- Unreliable / secondary metrics for this run:
  - `all_poses_service` returned a `4.15 m` closure and should not be used as the primary judge here.
  - front-end `/visual_slam/tracking/odometry` and `vo_pose` stayed around `0.36 m` XY closure and are worse than backend SLAM.
- Operational conclusion:
  - For bench/chair testing on this Jetson + D455 setup, `640x360x60` with `force_planar_mode=true` is currently the best-known profile among the tested options.
  - The remaining delta warnings are still useful as a load/timing diagnostic, but they did not prevent a good backend closure in this run.

## cuVSLAM official_like regression — 2026-06-27
- User reran the same motion route with `CUVSLAM_PROFILE=official_like bash scripts/start_cuvslam_rviz_gui.sh --no-rviz`.
- Latest log: `/home/superwfx666/cuvslam_lite3_logs/20260627-235712`.
- Key backend metrics:
  - `slam_odometry.samples=902`
  - `slam_odometry.path_length_m=21.1168`
  - `slam_odometry.xy_closure_error_m=0.9250`
  - `slam_odometry.z_span_m=0.3519`
- Stability counters:
  - `delta warnings=1243`
  - `Visual tracking is lost=1`
- Interpretation:
  - `official_like` is worse than both `planar_60fps` and `planar_90fps` on the same bench route.
  - Compared with the 60 Hz result, the XY closure regressed from `0.017 m` to `0.925 m`.
  - The extra `visual tracking is lost` event suggests the official-like parameter set is not a good default for this Jetson/D455 bench route.
  - Treat `official_like` only as a reference baseline, not as the current recommended profile.

## Lite3 / D455 45cm Camera Bracket CAD Research — 2026-06-27
- User target: use the roughly triangular three screw holes on the back/top of a DEEP Robotics Lite3 Explore/Venture robot to mount an Intel RealSense D455 depth camera at about 45 cm height, pitched about 30 degrees downward from horizontal.
- Best CAD workflow for this task:
  - Use Codex/Agent to write parametric CAD code rather than pure text-to-mesh. For screw-hole alignment, camera pitch, wall thickness, ribs, and later correction, a text/code parametric model is more reliable and reviewable than a one-shot generative mesh.
  - Recommended stack: Python + CadQuery or build123d, exporting STEP for editable CAD review and STL/3MF for slicing.
  - OpenSCAD is also viable for simple brackets, but CadQuery/build123d are better for fillets, assemblies, STEP export, and mechanical iteration.
  - FreeCAD Python is useful as a GUI inspection/refinement fallback, but less convenient than CadQuery/build123d for agent-driven iteration.
  - Zoo/Zookeeper and other Text-to-CAD products are useful for concept generation, but not the primary source of truth for this bracket because the critical part is exact bolt-hole geometry and stiffness.
- D455 official mechanical facts found:
  - D455/D455f/D456 nominal body dimensions: 124 mm width, 29 mm height, 26 mm depth; nominal weight 116 g.
  - D455 rear mounting holes: 2 x M4 mounting points, maximum insertion depth 4 mm, recommended torque 0.4 Nm.
  - The official D455 mechanical drawing shows the two rear M4 mounting points spaced 95 mm center-to-center.
  - The drawing also shows a 1/4-20 mounting point with maximum insertion depth 9 mm and 2 x M2 USB cable mounting features.
  - D455 depth baseline is 95 mm and the depth/color FOVs are wide; avoid any bracket lip or guard entering the camera/projector FOV.
- Lite3 official hole-pattern facts found:
  - DEEP Robotics public Lite3 product page separates Basic, Venture/Explore, Pro, and LiDAR variants. The Explore/Venture class has lower payload than Basic and includes external interfaces.
  - Jueying Lite3-AI User Manual V1.0.3-0 payload drawing shows `2 x M4` and `6 x M3` back thread holes, with labeled dimensions including 205 mm, 145 mm, 170 mm, 134 mm, 105 mm, 88 mm, 65 mm, 46 mm, and 28.5 mm references.
  - Jueying Lite3 LiDAR/User Manual V1.0.6-0 payload drawing shows a different simpler `4 x M3` rectangular pattern, with 74 mm horizontal spacing and 94 mm vertical spacing.
  - Important conflict: the user's physical observation is "three holes in a triangular pattern"; the two public official manuals found do not directly publish a clean three-hole triangular pattern. Treat the public diagrams as reference only and measure the actual robot before generating final holes.
- Practical design direction:
  - Do not make a single 45 cm solid printed tower. Use a low printed adapter plate on the robot, an aluminum/carbon tube or two struts for height, and a printed/top machined camera tilt head. This reduces print time, mass, flex, and vibration.
  - If fully printed, split into base adapter, two triangular side plates/columns, diagonal braces, and D455 tilt plate; print in PETG/ABS/nylon-CF rather than brittle PLA if the robot will move aggressively.
  - Put the camera mount near the robot centerline and as low as the sensing requirement allows; 45 cm above the back raises center of gravity and increases vibration moment.
  - Use slotted holes on the robot-side plate for the first prototype: M4 slots around 4.5-5.0 mm clearance, M3 slots around 3.3-3.6 mm clearance, and enough washer area. After confirming fit, lock dimensions in the second revision.
  - For D455 pitch, model the rear plate normal 30 degrees below horizontal; include a small angular adjustment range such as 25-35 degrees if possible.
- Measurements still required from real hardware:
  - Choose one origin hole and define robot axes: +X forward, +Y left/right, +Z up.
  - Measure each of the three actual top-hole center coordinates `(x, y)` in mm, thread type, usable screw depth, and any surface curvature/height offsets.
  - Measure available top-deck flat area, handle/camera/radar/cable clearance, and desired camera optical center position relative to robot `base_link`.

## Lite3 / D455 Mount CAD Output — 2026-06-28
- User corrected the Lite3 measured three-hole geometry:
  - upper two holes are 105 mm apart;
  - lower hole lies on the perpendicular bisector;
  - lower-to-left-upper and lower-to-right-upper distances are both 70 mm;
  - therefore the actual vertical drop from upper-hole line to lower hole is `sqrt(70^2 - 52.5^2) = 46.301 mm`, not 70 mm.
- User material constraints:
  - rigid load-bearing structure will be printed in PLA Tough;
  - vibration pads can be printed in TPU;
  - print difficulty and mass are secondary to stiffness and low camera vibration.
- Structural decision:
  - generated a PLA Tough triangular truss tower rather than a single-post mount;
  - the three Lite3 holes become three tower legs;
  - the tower has 18 mm vertical columns, 14 mm horizontal triangular rings, 12 mm crossed diagonal braces, a broad top deck, and a gusseted D455 rear plate;
  - this is intentionally overbuilt to reduce left-right and fore-aft sway at about 45 cm height.
- TPU isolation decision:
  - bottom TPU pad is only 2 mm thick;
  - D455 rear TPU pad is only 2 mm thick;
  - TPU is kept out of the main load path because a thick soft bottom layer can reduce high-frequency vibration but increase low-frequency pendulum sway.
- Generated files:
  - `cad/lite3_d455_mount/generate_lite3_d455_mount.js`
  - `cad/lite3_d455_mount/out/lite3_d455_mount_pla.stl`
  - `cad/lite3_d455_mount/out/lite3_bottom_tpu_pad.stl`
  - `cad/lite3_d455_mount/out/d455_rear_tpu_pad.stl`
  - `cad/lite3_d455_mount/out/metadata.json`
  - `cad/lite3_d455_mount/out/lite3_d455_mount_preview.png`
  - `cad/lite3_d455_mount/DESIGN_NOTES.md`
- Verified generated mesh sizes:
  - PLA main mount: 1,339,984 bytes, 26,798 triangles, bounding box about `150 x 111.6 x 450.2 mm`.
  - bottom TPU pad: 50,684 bytes, 1,012 triangles, bounding box about `143 x 84.3 x 2 mm`.
  - D455 rear TPU pad: 47,084 bytes, 940 triangles, bounding box about `131 x 2 x 47 mm`.
- Modeling errors fixed:
  - JSCAD thin rounded cuboid round radius exceeded allowable dimension radius; reduced thin-part round radius.
  - JSCAD STL binary serializer returns multiple ArrayBuffers; generator now concatenates all chunks before writing.

## Lite3 / D455 Mount Top Rib Revision — 2026-06-28
- User identified that the first top camera-head revision had vertical rectangular blocks protruding into the D455 mounting volume.
- Revised the model by deleting the old rectangular side gussets and center web.
- Added three vertical triangular ribs:
  - left, center, and right;
  - each rib is a thin triangular plate;
  - one side supports the horizontal top deck;
  - another side supports the 30-degree tilted D455 plate;
  - intended included-angle concept is 120 degrees, matching the user's requested triangular support idea.
- Regenerated STL outputs and preview image.
- Verification after revision:
  - `npm run generate` passed.
  - main PLA STL changed to 1,292,684 bytes and 25,852 triangles.
  - bounding box is about `150 x 102.9 x 450.2 mm`.

## Lite3 / D455 Mount Split Joint and Screw Access Revision — 2026-06-28
- User requested two additional mechanical fixes:
  - split the tall frame into two printable PLA Tough halves at the end of the second truss bay;
  - add a practical way to insert screws through the lower mount into the Lite3 deck holes.
- Implemented split:
  - split height is `206.8 mm` from the robot deck, matching `height * 0.55` and the end of the second truss bay;
  - lower half bounding box is about `133.0 x 74.3 x 213.8 mm`;
  - upper half bounding box is about `150.0 x 102.9 x 265.4 mm`;
  - assembled reference remains about `150 x 102.9 x 450.2 mm`.
- Implemented joint:
  - upper half has three downward PLA pins;
  - lower half has three matching blind sockets;
  - pin diameter `10 mm`, socket clearance `10.7 mm`, pin length `22 mm`, socket depth `24 mm`;
  - connector points are inset from the outer legs at `(-25.2, -8.025)`, `(25.2, -8.025)`, `(0, -30.25)` mm to avoid colliding with screw channels.
- Implemented robot screw access:
  - each of the three main columns now has a vertical `10.5 mm` access channel aligned with the Lite3 screw hole;
  - the base keeps a `5.2 mm` screw clearance and a shallow `10.5 mm` screw-head pocket;
  - this allows screws and a driver to approach from above through the column axis.
- New/generated PLA files:
  - `lite3_d455_mount_lower_pla.stl`: 664,584 bytes, 13,290 triangles;
  - `lite3_d455_mount_upper_pla.stl`: 802,384 bytes, 16,046 triangles;
  - `lite3_d455_mount_pla_assembled_reference.stl`: 1,414,584 bytes, 28,290 triangles.

## AI-Assisted CAD Workflow Research — 2026-06-28
- Current JSCAD workflow is useful for simple CSG-style geometry stacking, but it is not the best long-term workflow for complex mechanical design:
  - it has no normal CAD feature tree;
  - it does not preserve sketch constraints/design intent in a GUI-editable native model;
  - STL is mesh output and is poor as a source of truth for later CAD edits.
- Better principle:
  - keep an editable CAD-native or B-Rep source of truth;
  - use Codex/LLM to generate scripts, macros, feature definitions, parameter tables, and validation checks;
  - let the human intervene in a real CAD GUI.
- Strong candidate workflows found:
  - Fusion 360 + Python API: good for a user who wants manual editing plus script/add-in automation.
  - FreeCAD + Python macro/FCStd: best fully local/open-source option; native parametric GUI can be edited manually.
  - Onshape + FeatureScript/REST API: strong for browser collaboration, custom features, and versioned CAD documents.
  - CadQuery/build123d: good for reproducible parametric B-Rep code and STEP export, but less ideal when the user wants direct GUI feature-tree edits.
  - Zoo Design Studio/Zookeeper/Text-to-CAD: promising AI-native workflow; good for concept generation and editable B-Rep/STEP output, but should not be the sole source of truth for competition-critical mechanical parts yet.
- Recommended next workflow for this project:
  - switch from JSCAD STL-first generation to FreeCAD or Fusion script generation;
  - generate a native editable model plus STEP/STL outputs;
  - user edits sketches/features in GUI;
  - user returns updated CAD file/screenshots/parameter changes;
  - Codex updates scripts/docs/exports accordingly.

## Lite3 / D455 Mount STEP-First CAD Redraw — 2026-06-28
- The bracket has been redrawn with the local CAD skill as a STEP-first build123d/cadpy model, so SolidWorks should import the `.step` files as editable B-Rep geometry rather than mesh-only STL.
- New CAD source directory:
  - `cad/lite3_d455_mount_step/`
- Primary source files:
  - `CAD_BRIEF.md` stores the design intent and validation targets.
  - `model.py` stores all parameters and geometry builders.
  - `lite3_d455_mount_lower_pla.py`, `lite3_d455_mount_upper_pla.py`, `lite3_bottom_tpu_pad.py`, `d455_rear_tpu_pad.py`, and `lite3_d455_mount_assembly.py` are explicit generator entrypoints.
- Primary STEP outputs:
  - `out/lite3_d455_mount_lower_pla.step`
  - `out/lite3_d455_mount_upper_pla.step`
  - `out/lite3_bottom_tpu_pad.step`
  - `out/d455_rear_tpu_pad.step`
  - `out/lite3_d455_mount_assembly.step`
- Secondary STL outputs with the same basenames were generated for slicing.
- Key parameters preserved:
  - Lite3 upper hole span: `105.0 mm`.
  - Lite3 side distances from lower hole to each upper hole: `70.0 mm`.
  - Lite3 lower-hole vertical drop from the upper-hole line: `46.300648 mm`.
  - D455 rear M4 mount span: `95.0 mm`.
  - Split height: `206.8 mm`.
  - Assembly bbox from CAD inspect: `151.051354 x 103.964102 x 453.310889 mm`.
- CAD inspect validation:
  - `inspect refs --facts --planes --positioning` returned `ok: true` for assembly, lower PLA, upper PLA, bottom TPU pad, and D455 rear TPU pad.
  - Lower PLA bbox: `133.782096 x 70.275482 x 213.8 mm`.
  - Upper PLA bbox: `150.0 x 103.964102 x 266.510889 mm`.
  - Bottom TPU pad bbox: `151.051354 x 77.069561 x 2.0 mm`.
  - D455 rear TPU pad bbox: `131.0 x 2.0 x 47.0 mm`.
- CAD snapshot validation:
  - Snapshot PNGs were generated in `cad/lite3_d455_mount_step/out/snapshots/`.
  - Reviewed assembly ISO, upper ISO, and lower top images.
  - Visual check confirmed the truss tower, split joint, top triangular ribs, D455 plate holes, bottom pad, and upper/lower split features are present.
- Dependency note:
  - CAD CLI needs `PYTHONPATH` including `C:\Users\111\.codex\skills\cad\scripts\packages\cadpy\src` and the repo-local `.cad-deps`.
  - Snapshot needed Python `playwright` and Playwright Chromium runtime.
- SolidWorks handoff:
  - Open/import the STEP files from `cad/lite3_d455_mount_step/out/`.
  - Use the assembly STEP for visual context, but print/revise the four physical pieces from the separate part STEP/STL files.
  - Before printing, manually check screw type/length, washer clearance, D455 cable clearance, and whether the 2 mm TPU pads create too much low-frequency sway on the robot.

## Lite3 / D455 Mount Rev3 Base and Top Revision — 2026-06-28
- User requested a stronger/easier-to-screw base and a top head with the D455 plate moved to the top deck edge.
- Final design interpretation:
  - the measured Lite3 triangle remains the screw triangle;
  - a congruent copy of that triangle is rotated 180 degrees around the triangle centroid, not the global origin;
  - this creates three separate screw corners and three separate structural-column corners on a rounded six-corner base.
- Implementation details:
  - `robot_hole_points()` stores the measured Lite3 screw triangle.
  - `support_points()` stores the 180-degree centroid-rotated support triangle for the three main columns.
  - `base_outline_points()` combines the expanded screw triangle and support triangle, sorts points by polar angle, and creates a rounded six-corner base.
  - main columns are solid; the old through-column screw/driver channels were removed.
  - lower split sockets and upper split pins are centered on the three main columns.
  - D455 tilted plate is moved to the top deck edge and supported by three triangular ribs.
- Important modeling lesson:
  - Rotating the triangle around the global origin was wrong because two support points overlapped two screw points.
  - Snapshot review caught this: the rev2 lower top image showed only one clearly separate screw hole.
  - Correct operation is rotation around the measured triangle centroid.
- Final CAD inspect facts:
  - assembly: `164.483 x 140.764619 x 450.621778 mm`;
  - lower PLA: `145.294936 x 102.041929 x 213.8 mm`;
  - upper PLA: `150.0 x 104.306035 x 263.821778 mm`;
  - bottom TPU pad: `164.483 x 121.711142 x 2.0 mm`;
  - D455 rear TPU pad: `131.0 x 2.0 x 47.0 mm`.
- Final snapshot prefix:
  - `cad/lite3_d455_mount_step/out/snapshots/rev3_*_20260628T081955Z.png`
- The earlier `rev2_*` snapshots should be treated as intermediate debug output, not final design evidence.

## Lite3 / D455 Mount Rev4 Split-Cap Enlargement — 2026-06-28
- User requested changing only the middle split plates.
- Final rev4 change:
  - lower and upper split caps are now large rounded six-corner plates generated from the same style of outline as the base;
  - the split caps no longer use the smaller support-triangle-only outline;
  - the three blind sockets and three downward pins remain centered on the three main columns.
- Intent:
  - avoid the split plate being too small where the vertical columns pass through it;
  - make the split interface closer to the bottom base footprint for better local stiffness and support.
- Validation:
  - `inspect refs --facts --planes --positioning` passed for affected lower PLA, upper PLA, and assembly STEP files.
  - assembly bbox remains `164.483 x 140.764619 x 450.621778 mm`.
  - lower PLA bbox remains `145.294936 x 102.041929 x 213.8 mm`.
  - upper PLA bbox becomes `150.0 x 130.918616 x 263.821778 mm` because the lower split cap is larger.
  - lower split face at `z=206.8` and upper matching split face both cover about `145.294936 x 102.041929 mm`.
- Final snapshot prefix:
  - `cad/lite3_d455_mount_step/out/snapshots/rev4_*_20260628T084338Z.png`

## cuVSLAM Bridge / Nav2 / Nvblox Test Plan — 2026-06-28
- Added operator-facing test guide:
  - `docs/cuvslam_nav2_bridge_test.md`
- Current recommended cuVSLAM test entry remains:
  - `CUVSLAM_PROFILE=planar_60fps bash scripts/start_cuvslam_rviz_gui.sh --no-rviz`
- For bridge testing, run cuVSLAM in robot mode but disable Docker-side TF ownership of `odom -> base_link` and `map -> odom`:
  - `CUVSLAM_PUBLISH_ODOM_TO_BASE_TF=false`
  - `CUVSLAM_PUBLISH_MAP_TO_ODOM_TF=false`
- Temporary camera extrinsics for interface testing only:
  - `base_link -> camera_link`: `x=0.20`, `y=0.00`, `z=0.45`, `roll=0.0`, `pitch=-0.523599`, `yaw=0.0`
- `origin/main` bridge file inspected:
  - `src/nodes/navigation/cuvslam_bridge.py`
  - duplicate path: `navi/cuvslam_bridge.py`
- Bridge behavior:
  - subscribes `/visual_slam/tracking/odometry`;
  - republishes `/odom`;
  - broadcasts `odom -> base_link`;
  - changes `child_frame_id` to `base_link`.
- Bridge limitation:
  - it does not yet mathematically apply the camera-to-base extrinsic transform, so it is acceptable for interface testing but not final robot-frame precision validation.
- Status topic risk:
  - bridge subscribes `/visual_slam/status` as `std_msgs/String`;
  - Isaac ROS Visual SLAM status may be another interface type, so odometry/TF should be validated first and status fixed separately if needed.
- Nav2 launch risk:
  - `launch/navigation.launch.py` starts `depth_publisher`, which opens D455 from Foxy host;
  - Docker cuVSLAM also opens D455 via RealSense ROS, so full launch may cause camera ownership conflict.
- Nvblox integration boundary:
  - `cuvslam_bridge.py` does not bridge nvblox maps/costmaps;
  - nvblox-to-Nav2 requires `nvblox_nav2` in the same ROS distro/ABI as Nav2, or a custom conversion node to Foxy-compatible `OccupancyGrid` / `PointCloud2`.
- Current Docker cuVSLAM launch default enables IR stereo + IMU and disables depth, so nvblox still needs depth topics enabled before map-slice testing.

## Lite3 / D455 Mount Rev5 Centered Top Head and Downward Camera Pitch — 2026-06-28
- User corrected the intended top geometry:
  - the rounded rectangular top deck should sit in the middle of the three-column triangular support cross-section;
  - the D455 plate should also be centered on that deck, not moved to one edge;
  - the camera should look downward 30 degrees relative to horizontal.
- Current CAD interpretation:
  - `top_deck_center_y()` uses `centroid(support_points())`, so the top deck is centered on the three structural columns.
  - `camera_plate_contact_point()` uses that same centered top-deck line.
  - `camera_plate_angle_deg()` returns `-30.0`.
  - `camera_plate_normal()` returns approximately `(0.0, 0.866, -0.5)`, which is the camera optical direction if the D455 back is mounted to the plate. This is 30 degrees downward from horizontal.
- Important visual interpretation:
  - The side snapshot can make the physical plate edge look like it rises upward.
  - That does not mean the camera is looking upward; the optical direction is the plate normal, not the visual edge of the plate.
- Latest validated artifacts for this interpretation:
  - `cad/lite3_d455_mount_step/out/lite3_d455_mount_assembly.step`
  - `cad/lite3_d455_mount_step/out/lite3_d455_mount_upper_pla.step`
  - `cad/lite3_d455_mount_step/out/d455_rear_tpu_pad.step`
  - latest snapshot prefix: `rev5_*_20260628T091009Z.png`
- Validation run on 2026-06-28 17:18 +08:00:
  - assembly inspect: `ok: true`, bbox `164.483 x 121.733936 x 450.621778 mm`;
  - upper PLA inspect: `ok: true`, bbox `150.0 x 102.041929 x 263.821778 mm`;
  - D455 TPU pad inspect: `ok: true`, bbox `131.0 x 2.0 x 47.0 mm`.

## Lite3 / D455 Mount Rev6 Front-Edge Camera Head — 2026-06-28
- Latest user correction:
  - keep the rounded top deck exactly where it is;
  - move only the slanted D455 mounting plate to the front edge of that top deck;
  - move the three triangular ribs along with that D455 plate;
  - do not move any lower structure, split joint, top deck, columns, braces, or base.
- Implemented by changing only the camera contact reference:
  - `top_deck_front_y() = top_deck_center_y() + top_deck_depth / 2`;
  - `camera_plate_contact_point()` now uses `top_deck_front_y()`.
- This is a useful modeling rule for future edits:
  - top deck placement belongs to `tower_frame_range(... include_top_deck=True)`;
  - camera head placement belongs to `camera_plate_contact_point()`;
  - changing the latter moves the D455 plate, triangular ribs, and placed D455 TPU pad without moving the top deck or tower.
- Rev6 validation:
  - `lite3_d455_mount_assembly.step`: `ok: true`, bbox `164.483 x 145.331069 x 450.621778 mm`;
  - `lite3_d455_mount_upper_pla.step`: `ok: true`, bbox `150.0 x 135.485066 x 263.821778 mm`;
  - `d455_rear_tpu_pad.step`: `ok: true`, bbox `131.0 x 2.0 x 47.0 mm`.
- Latest snapshot prefix:
  - `rev6_*_20260628T115358Z.png` and `rev6_upper_right_20260628T115359Z.png`.
- Treat rev6 as the current CAD state; rev5 is now superseded for top camera-head placement.

## cuVSLAM planar_60fps Remote Result — 2026-06-29
- Complete run inspected:
  - remote path: `/home/superwfx666/cuvslam_lite3_logs/20260629-150311`;
  - command profile: `CUVSLAM_PROFILE=planar_60fps`;
  - generated launch config used `640x360x60`, planar mode enabled, IMU fusion enabled, bench mode with `camera_link` as base frame.
- Result:
  - primary metric source was `slam_odometry`;
  - `slam_odometry` traveled `48.7037 m` and ended with `1.5428 m` XY closure error;
  - recorder interpretation was `poor_slam_backend_return_to_start`;
  - `vo_pose` was worse: `41.8004 m` XY path, `2.6635 m` XY closure error, and `6.4623 m` Z span.
- Important diagnostic signal:
  - `launch.log` contained `6157` frame-delta warnings above the `22 ms` threshold and `9` `Visual tracking is lost` events, with no `[ERROR]` lines.
  - This means the 60 Hz run did not only fail because of final drift; the input timing/processing cadence was unstable throughout the run.
- Interpretation:
  - This 60 Hz result is not competition-grade and is worse than the previous roughly `0.50-0.57 m` single-source cuVSLAM closure range.
  - The `slam_path`, `vo_path`, and `all_poses_service` files show very small path lengths compared with odometry and include notes like path static while odometry moved, so they should not be used as the primary closure metric for this run.
- Adjacent short run:
  - `/home/superwfx666/cuvslam_lite3_logs/20260629-163751` exists but only captured about `0.021 m` of `slam_odometry` motion, so it is a startup/static sanity run rather than a loop test.

## cuVSLAM Startup Speed Optimization — 2026-06-30
- Problem:
  - `scripts/start_cuvslam_rviz_gui.sh` spent significant time after cuVSLAM started because it ran multiple ROS 2 startup diagnostics:
    - `ros2 topic info -v` for several topics;
    - `ros2 topic echo /visual_slam/status --once`;
    - full OK/MISSING topic checks;
    - `timeout 12 ros2 topic hz` across many topics.
  - These checks were useful during bring-up, but now they slow the normal run path and add load just before the actual demo/test.
- Implemented rule:
  - default startup path is now minimal:
    - wait for `/visual_slam/tracking/odometry`;
    - start `cuvslam_loop_metrics_recorder.py`;
    - enter the manual run immediately.
  - slow diagnostics are opt-in via:
    - `STARTUP_DIAGNOSTICS=1 bash scripts/start_cuvslam_rviz_gui.sh ...`
    - or `bash scripts/start_cuvslam_rviz_gui.sh --startup-diagnostics ...`
- Practical command:
  - fast normal run: `CUVSLAM_PROFILE=planar_60fps bash scripts/start_cuvslam_rviz_gui.sh --no-rviz`
  - diagnostic run: `CUVSLAM_PROFILE=planar_60fps STARTUP_DIAGNOSTICS=1 bash scripts/start_cuvslam_rviz_gui.sh --no-rviz`
- Validation:
  - local Git Bash and remote Jetson `bash -n` syntax checks passed.

## cuVSLAM Trajectory CSV Exports — 2026-06-30
- Every normal run of `scripts/start_cuvslam_rviz_gui.sh` starts `scripts/cuvslam_loop_metrics_recorder.py`, so trajectory CSV export is automatic once `/visual_slam/tracking/odometry` appears.
- Existing per-source CSVs remain:
  - `odometry_samples.csv`: `/visual_slam/tracking/odometry`;
  - `slam_odometry_samples.csv`: `/visual_slam/vis/slam_odometry`;
  - `vo_pose_samples.csv`: `/visual_slam/tracking/vo_pose`;
  - `slam_path_latest.csv`: latest `/visual_slam/tracking/slam_path` snapshot;
  - `vo_path_latest.csv`: latest `/visual_slam/tracking/vo_path` snapshot;
  - `slam_all_poses_latest.csv`: latest `GetAllPoses` service response when enabled.
- Added plot-friendly unified output:
  - `trajectory_for_plot.csv`;
  - columns: `source, elapsed_s, stamp_sec, frame_id, child_frame_id, x, y, z, yaw_rad, yaw_deg, path_length_m, xy_path_length_m`;
  - rows include `source=odometry`, `source=slam_odometry`, and `source=vo_pose`.
- For third-party plotting:
  - use `trajectory_for_plot.csv`;
  - filter `source=slam_odometry` for the planar SLAM backend trajectory when available;
  - plot `x` vs `y`;
  - use `yaw_deg` for heading visualization if needed.

## Jetson SSH Authentication Notes — 2026-06-30
- Remote Jetson target:
  - Tailscale IP: `100.126.48.49`;
  - hostname: `superwfx666-desktop`;
  - login user: `superwfx666`;
  - project repo: `/home/superwfx666/quadruped-robot-competition`.
- Important diagnosis from this session:
  - Tailscale/network reachability was OK; `tailscale status` showed `100.126.48.49 superwfx666-desktop` as active.
  - Plain non-interactive SSH failed with `Permission denied (publickey,password)` because the remote did not accept the local Windows public key `C:\Users\111\.ssh\id_ed25519.pub`.
  - `ssh -o BatchMode=yes ...` only tests non-interactive auth and will not prompt for the updated login password; do not interpret this failure as the Jetson being offline.
  - Plain password SSH without `BatchMode` can hang in Codex shell because the password prompt is interactive.
  - `tailscale ssh` hit a separate host-key strict-checking issue for `superwfx666-desktop.tailc828f4.ts.net`; this is not the same as password/public-key rejection.
  - Password auth succeeded through Python `paramiko` after using the handoff password from `README_交接.txt`.
- One-week-later checklist before remote work:
  1. First run `tailscale status` and confirm `superwfx666-desktop` is active.
  2. If `ssh -o BatchMode=yes superwfx666@100.126.48.49 "pwd"` fails with `Permission denied`, treat it as an authentication/key issue, not a network issue.
  3. If interactive password login is needed from Codex, use `paramiko` or install/configure a proper non-interactive SSH key; Codex shell cannot reliably answer the password prompt.
  4. Best durable fix: add the local public key `C:\Users\111\.ssh\id_ed25519.pub` to Jetson `~/.ssh/authorized_keys`, then ordinary SSH commands should work again without password.
  5. After login, verify the expected repo with `cd ~/quadruped-robot-competition && git status --short --branch`.

## Jetson Competition Integration Stage Check — 2026-06-30
- Remote target inspected through password-based `paramiko` SSH:
  - host: `100.126.48.49` / `superwfx666-desktop`;
  - repo: `/home/superwfx666/quadruped-robot-competition`;
  - remote time during check: `2026-06-30 16:40-16:42 +0800`.
- Desktop handoff files found:
  - `README_交接.txt`;
  - `比赛启动.txt`;
  - `启动Docker.txt`;
  - `start_docker.sh`;
  - `restart.sh`;
  - `fix_bridge.sh`;
  - `test_whz.sh`;
  - `test_whz_direct.sh`;
  - `monitor_cpu.sh`;
  - `终端输出.txt`.
- Handoff state:
  - project has moved beyond standalone cuVSLAM bring-up into integrated competition system assembly;
  - current architecture is Docker Humble `realsense2_camera + cuVSLAM` plus Host Foxy `final_bridge.py`, lightweight A* navigator, `task_manager`, and whz inspection via relay files;
  - lightweight A* + pure pursuit, cuVSLAM Docker, odometry bridge, camera/depth relay, task manager, whz package, test logger, and start script are documented as done;
  - pending items are DDS data-plane workaround/fix, whz end-to-end cabinet-facing validation, `/whz/inspect` integration in `task_manager`, Lite3 robot connection test, and YOLO enablement.
- Git state on Jetson:
  - branch: `main`;
  - HEAD: `82512c6 Merge pull request #2 from youngman05/codex/add-realsense-cuvslam-input-test`;
  - tracking status: `main...origin/main [ahead 20, behind 5]`;
  - `origin/main`: `f517ad7 feat: navigation system + nodes reorganization`;
  - many competition-integration files are untracked or locally modified, so the Jetson working state is not a clean reproducible Git commit.
- Important repository files present on Jetson:
  - `scripts/start_competition.sh`;
  - `scripts/start_cuvslam_rviz_gui.sh`;
  - `scripts/final_bridge.py`;
  - `scripts/camera_relay_docker.py`;
  - `scripts/depth_relay_docker.py`;
  - `scripts/test_whz_detect.py`;
  - `src/navigation/{map_grid.py,astar_planner.py,pure_pursuit.py,local_obstacle.py,navigator.py}`;
  - `src/nodes/decision/task_manager.py`;
  - `src/nodes/perception/{gauge_status.py,whz_standalone_inspect.py}`;
  - `src/whz/whz/{letter_detector.py,gauge_detector.py,audio_player.py}`;
  - `configs/ros/{fastrtps_no_shm.xml,competition_params.yaml}`;
  - `navi/map/navi_map_data.py`.
- Runtime state during check:
  - no cuVSLAM Docker container was running;
  - no `final_bridge`, `camera_relay`, `depth_relay`, competition launch, navigator, task manager, or whz process was running;
  - `/tmp/cuvslam.log` contained `bash: scripts/start_cuvslam_rviz_gui.sh: No such file or directory`, indicating the latest startup attempt was launched from a context where the relative `scripts/...` path was not valid or the script was absent at that moment.
- Most accurate stage label:
  - "competition-system integration and bring-up, not yet end-to-end validated on Lite3";
  - code/scripts for Docker cuVSLAM, relay, bridge, lightweight navigation, task manager, and whz inspection are deployed;
  - the next useful work is to cleanly launch from the repo root, verify cuVSLAM Docker and `/odom`, then validate whz on a cabinet face, then connect and test Lite3 `/cmd_vel`.

## cuVSLAM Fast Startup vs Docker-Host Data Relay — 2026-06-30
- User suspected the fast `CUVSLAM_PROFILE=planar_60fps bash scripts/start_cuvslam_rviz_gui.sh --no-rviz` path may have broken Docker-to-host data transfer after skipping startup diagnostics.
- Diagnosis:
  - `STARTUP_DIAGNOSTICS=0` only skips slow `ros2 topic info`, `ros2 topic echo /visual_slam/status --once`, topic OK/MISSING checks, and `ros2 topic hz` sampling.
  - It does not remove Docker mounts or directly affect shared-file relay.
  - Docker mount remains `-v "$ISAAC_WS":/workspaces/isaac_ros-dev`, so files written in the container under `/workspaces/isaac_ros-dev/camera_frames` appear on the host at `~/workspaces/isaac_ros-dev/camera_frames`.
- Actual issue found:
  - some generated launch files from `20260630-121730`, `20260630-131136`, and `20260630-143147` had:
    - `enable_color: False`;
    - `enable_depth: False`.
  - In that version, cuVSLAM IR/IMU could still run, but `camera_relay_docker.py` and `depth_relay_docker.py` had no `/camera/color/image_raw` or `/camera/depth/image_rect_raw` stream to relay.
  - This looks like "Docker and host cannot transfer data", but the deeper cause is that RGB/depth topics were never published.
- Current Jetson state:
  - remote `scripts/start_cuvslam_rviz_gui.sh` now has `enable_color: True` and `enable_depth: True`;
  - latest generated launch `~/cuvslam_lite3_logs/20260630-145134/cuvslam_realsense_tuned.launch.py` also has both enabled;
  - shared files exist on host:
    - `~/workspaces/isaac_ros-dev/camera_frames/latest_color.jpg`;
    - `~/workspaces/isaac_ros-dev/camera_frames/latest_depth.raw`;
    - `~/workspaces/isaac_ros-dev/camera_frames/latest_depth_meta.txt`.
- Local repo fix:
  - local `scripts/start_cuvslam_rviz_gui.sh` still had `enable_color: False` / `enable_depth: False`;
  - changed both to `True` so future copies from Windows to Jetson do not regress whz relay.
- Separate startup-path issue:
  - latest `/tmp/cuvslam.log` showed `bash: scripts/start_cuvslam_rviz_gui.sh: No such file or directory`;
  - this is likely from launching the command outside `~/quadruped-robot-competition` or with a stale/missing script path, not from the fast diagnostics change itself.
- Practical next command:
  - `cd ~/quadruped-robot-competition && CUVSLAM_PROFILE=planar_60fps bash scripts/start_cuvslam_rviz_gui.sh --no-rviz`
  - if using robot frame for competition integration, include existing desktop-script overrides:
    `CUVSLAM_MOUNT_MODE=robot CUVSLAM_PUBLISH_ODOM_TO_BASE_TF=false CUVSLAM_PUBLISH_MAP_TO_ODOM_TF=false`.

## final_bridge Source Timestamp Passthrough — 2026-07-01
- User asked whether Docker cuVSLAM `/visual_slam/vis/slam_odometry` includes its own source timestamp and, if so, to propagate it through Host `/odom` and TF.
- Verified by temporarily starting a no-RViz cuVSLAM probe container with:
  - `RUN_JETSON_CLOCKS=0`;
  - `CUVSLAM_MOUNT_MODE=robot`;
  - `CUVSLAM_PROFILE=planar_60fps`;
  - `CUVSLAM_PUBLISH_ODOM_TO_BASE_TF=false`;
  - `CUVSLAM_PUBLISH_MAP_TO_ODOM_TF=false`.
- Direct Docker-side sample confirmed source timestamp exists:
  - topic: `/visual_slam/vis/slam_odometry`;
  - command: `ros2 topic echo /visual_slam/vis/slam_odometry --once`;
  - sample header included `stamp.sec: 1782889412`, `stamp.nanosec: 837760986`, `frame_id: map`, `child_frame_id: base_link`.
- Prior `scripts/final_bridge.py` behavior:
  - parsed only pose values from `ros2 topic echo` text;
  - set `msg.header.stamp = node.get_clock().now().to_msg()`;
  - therefore Host `/odom` and `odom -> base_link` TF used Host receipt/republication time, not cuVSLAM source time.
- Updated remote `scripts/final_bridge.py`:
  - parses each complete YAML-like `ros2 topic echo` message between `---` separators;
  - extracts `header.stamp.sec` and `header.stamp.nanosec`;
  - assigns them to Host `msg.header.stamp`;
  - assigns the same timestamp to the emitted `TransformStamped`;
  - falls back to Host `now()` only if source stamp is missing;
  - parses pose position/orientation by path to avoid confusing `twist` `x/y/z` with pose position.
- Validation:
  - remote `python3 -m py_compile scripts/final_bridge.py` passed;
  - short bridge run logged `stamp=... (source)`, e.g. `bridged 1 msgs | stamp=1782889760.490827637 (source)`;
  - copied updated `scripts/final_bridge.py` back to local Windows repo and local `python -m py_compile scripts/final_bridge.py` passed.
- Cleanup:
  - temporary cuVSLAM probe container `cuvslam_gui_20260701-150113` was stopped with `docker rm -f`;
  - no cuVSLAM container remained running after the probe.

## UDP cuVSLAM Odometry Bridge — 2026-07-01
- User chose the medium-term architecture upgrade: replace `ros2 topic echo` text parsing with Docker-to-Host UDP over localhost.
- Rationale:
  - `ros2 topic echo` text is not a stable API and is fragile at high message rates;
  - UDP over localhost avoids ROS 2 DDS data-plane issues between Docker Humble and Host Foxy;
  - Docker is run with `--network host`, so packets sent from the container to `127.0.0.1:19001` are visible to the Host.
- Added Docker-side exporter:
  - file: `scripts/cuvslam_odometry_udp_exporter.py`;
  - runs inside the cuVSLAM container;
  - subscribes `/visual_slam/vis/slam_odometry` with BEST_EFFORT QoS;
  - serializes each Odometry message to compact JSON;
  - sends UDP to `127.0.0.1:19001`;
  - payload includes source `stamp.sec/nanosec`, `frame_id`, `child_frame_id`, pose position/orientation, pose covariance, twist, twist covariance, and a local sequence counter.
- Reworked Host bridge:
  - file: `scripts/final_bridge.py`;
  - copies exporter into the running cuVSLAM container with `docker cp`;
  - starts exporter through `docker exec`;
  - listens on UDP `127.0.0.1:19001`;
  - publishes Host `/odom` and `odom -> base_link` TF;
  - preserves the cuVSLAM source timestamp;
  - preserves pose/twist covariances when present;
  - kills the container-side exporter during shutdown.
- Validation on Jetson:
  - remote `python3 -m py_compile scripts/final_bridge.py scripts/cuvslam_odometry_udp_exporter.py` passed;
  - temporary no-RViz cuVSLAM probe container `cuvslam_gui_20260701-155847` was started;
  - `/visual_slam/vis/slam_odometry` was present in the container;
  - `final_bridge.py --log-every 100` logged continuous UDP bridging, e.g. `bridged 1 UDP msgs | stamp=1782892972.460244629 (source)`;
  - Host BEST_EFFORT Python subscriber received `/odom`: `596` messages in about 5 seconds;
  - sample subscriber timestamps came from cuVSLAM source stamps, e.g. first `1782893235.494421`, last `1782893240.2726903`.
- ROS CLI caveat:
  - Host `ros2 topic list` showed `/odom`;
  - `ros2 topic echo /odom --once` is not supported by the Jetson Foxy CLI;
  - plain `ros2 topic echo /odom` did not print during the short check, while a Python BEST_EFFORT subscriber did receive messages, so prefer BEST_EFFORT probe scripts for `/odom` validation on this setup.
- Cleanup:
  - temporary cuVSLAM probe container was stopped with `docker rm -f`;
  - no cuVSLAM Docker container, `final_bridge.py`, or UDP exporter process remained running after validation.

## UDP Bridge Golden Probe and Idempotent Startup — 2026-07-01
- `scripts/probe_odom_best_effort.py` should be treated as the current Host `/odom` golden probe, not `ros2 topic echo`.
- Probe contract:
  - subscribes `/odom` with explicit BEST_EFFORT QoS;
  - prints host receive rate and source-stamp rate;
  - prints `Host_Now - Source_Stamp` latency mean/min/p95/max;
  - prints jitter and last-minus-first latency growth;
  - exits `2` if no first odometry packet arrives before `--first-timeout`.
- Bridge/startup idempotency contract:
  - before starting a new bridge, kill stale Host `final_bridge.py`;
  - if a cuVSLAM container exists, kill stale container-side `cuvslam_odometry_udp_exporter.py`;
  - use safe self-nonmatching patterns such as `pkill -f '[f]inal_bridge.py'` and `pkill -f '[c]uvslam_odometry_udp_exporter.py'`, not bare `pkill -f final_bridge.py`.
- `final_bridge.py` should not silently reuse UDP `127.0.0.1:19001`; a bind conflict now points to a stale bridge process and should be fixed through `scripts/fix_bridge.sh`.
- Latest Jetson validation:
  - `fix_bridge.sh` exited `0`;
  - `/tmp/fb.log` showed `bridged ... UDP msgs` with source stamp preserved;
  - `/odom` probe received `251` messages in 5 seconds at about `50.13 Hz` host rate and `48.11 Hz` source-stamp rate.
- Latest quality finding:
  - `planar_60fps` bridge data is functionally live but latency quality is poor in this run:
    - mean latency `141.10 ms`;
    - p95 latency `213.60 ms`;
    - max latency `433.36 ms`;
    - jitter `414.58 ms`;
    - status `unstable_or_backlogged`.
  - This supports the earlier suspicion that 60 fps is stressing timing; the next tuning step should compare lower-load profiles and use this probe as the pass/fail metric.

## Latest-Only Odometry Bridge — 2026-07-01
- Decision:
  - Use latest-only semantics for the Docker cuVSLAM -> Host `/odom` bridge.
  - For navigation, fresh odometry with skipped frames is safer than old odometry delivered at a nominally smoother rate.
- Implemented safeguards:
  - ROS 2 QoS uses `BEST_EFFORT + KEEP_LAST + depth=1` in Docker exporter, Host bridge, and `/odom` probe;
  - Host UDP socket is drained to the latest available datagram before JSON parsing/publishing;
  - Host bridge drops packets older than `150 ms` by comparing `time.time()` with cuVSLAM source `header.stamp`;
  - logs include publish latency and drop counters.
- Latest remote evidence:
  - previous bridge/probe run had p95 `213.60 ms`, max `433.36 ms`, status `unstable_or_backlogged`;
  - latest-only run logged bridge publish latencies around `22-43 ms` after startup;
  - `stale_drop=13` shows the stale firewall actually rejected old packets;
  - `drained_old=0` in this run means the biggest improvement came from QoS/stale-drop path rather than kernel UDP backlog, but the drain guard is still necessary under load spikes.
- Operational rule:
  - before handing `/odom` to navigation for a run, execute `python3 scripts/probe_odom_best_effort.py --duration 5 --first-timeout 2 --no-color`;
  - if latency p95 rises back above roughly `100-150 ms`, treat it as a real-time quality failure even if `/odom` is present.

## Autonomous SLAM + Navigation Feasibility — 2026-07-02
- Definition correction:
  - joystick/manual motion plus RViz trajectory is only SLAM/odometry validation;
  - the July 3 target should mean autonomous path execution: localization input `/odom` + TF, planner/controller output `/cmd_vel`, robot follows waypoint/route by itself, joystick only as safety takeover.
- Cached `origin/main` includes a real lightweight autonomous-navigation path:
  - `src/navigation/navigator.py` creates a `Navigator` that subscribes `/odom`, builds A* paths on the competition map, runs Pure Pursuit at 10 Hz, and publishes `/cmd_vel`;
  - `src/nodes/decision/task_manager.py` instantiates `Navigator` and sends named waypoints for phases such as `obstacle_exit`, `pos1_middle`, `grab_area`, and `placement_A/B/C/D`;
  - `launch/competition.launch.py` starts `task_manager` and navigation helper nodes when `enable_task_manager:=true enable_navigation:=true`;
  - `scripts/start_competition.sh` is intended to start cuVSLAM Docker, relays, bridge, `/odom` probe, then competition launch.
- Implementation readiness:
  - Feasible as a minimum autonomous path-following prototype if Jetson has the latest navigation code plus the newer UDP/latest-only bridge.
  - Not yet safe to claim competition-ready navigation without live Jetson verification of `/odom` latency, TF, `/cmd_vel`, and robot base command wiring.
- Main blockers/risks:
  1. Current session could not log into Jetson; Tailscale is active but SSH credentials/host-key path are not usable from this Windows session.
  2. GitHub `origin/main` still has the old text-parser `final_bridge.py`; the better UDP/latest-only bridge exists locally and was previously synced to Jetson, but current Jetson state is unverified.
  3. `competition.launch.py` starts `depth_publisher`, which can conflict with Docker RealSense/cuVSLAM if it opens D455 directly; for a first autonomous test, prefer disabling obstacle/depth or using Docker-derived depth relay only.
  4. `/cmd_vel` publishing exists in `Navigator`, but whether it is connected to Lite3's actual low-level motion interface is not confirmed from local static analysis.
  5. Obstacle avoidance via PointCloud2 `/camera/depth/points` is still weak/optional; July 3 minimum should be path following on a known route with safety stop, not full robust obstacle navigation.

## Jetson Live State After SSH Restore — 2026-07-02
- SSH access path:
  - Use the WeChat handoff `README_交接.txt` credentials with `paramiko` or an interactive SSH client.
  - Do not rely on current Windows OpenSSH key auth; it still fails without password.
- Current Jetson repo is not a clean GitHub checkout:
  - `/home/superwfx666/quadruped-robot-competition` is `main...origin/main [ahead 20, behind 5]`;
  - many competition integration files are local/untracked, including navigation, bridge, whz, launch, and Lite3 helper files.
- Important correction to prior static analysis:
  - Jetson remote has the newer UDP/latest-only `scripts/final_bridge.py`, not the old GitHub `origin/main` text-parser bridge.
  - Previous `/tmp/fb.log` confirms UDP bridge worked and published thousands of `/odom` messages with source timestamps and latest-only drop counters.
- Current runtime state:
  - no Docker cuVSLAM container or ROS competition nodes are running at inspection time;
  - Host ROS topic list only contains `/parameter_events` and `/rosout`;
  - this means the next autonomous test starts from a stopped state, not from a live partially running system.
- Autonomous July 3 feasibility is now stronger:
  - main workspace has the navigation executables installed;
  - the lightweight navigator publishes `/cmd_vel`;
  - the Lite3 transfer workspace exists and `transfer` is recognized after sourcing its own install setup;
  - `transfer` subscribes `cmd_vel` and sends UDP commands to the robot.
- Remaining verification before moving the robot:
  1. Start cuVSLAM + bridge only; run `python3 scripts/probe_odom_best_effort.py --duration 5 --first-timeout 2 --no-color`.
  2. Start `lightweight_navigator` or `task_manager` with transfer disabled and observe `/cmd_vel` without connecting the dog.
  3. Confirm `/cmd_vel` is sane: low speed, correct sign, no command bursts when odom is stale.
  4. Only then run `scripts/start_competition.sh --dog` or separately launch `transfer_launch.py`, with the robot lifted or in a safe open area.

## Current Jetson Workspace Module Map — 2026-07-02
- The current Jetson workspace should be understood as a live competition integration workspace, not a clean source repository.
- Main runtime chain:
  1. `scripts/start_competition.sh`
  2. Docker Humble `realsense2_camera + cuVSLAM`
  3. Docker relays write `latest_color.jpg`, `latest_depth.raw`, `latest_depth_meta.txt`
  4. UDP odom bridge publishes Host `/odom` and writes `/tmp/odom_latest.json`
  5. `task_manager` drives `Navigator`
  6. `Navigator` plans/follows waypoints and publishes `/cmd_vel`
  7. Optional `transfer` forwards `/cmd_vel` to Lite3 over UDP.
- Canonical module locations:
  - SLAM/camera runtime: `scripts/start_cuvslam_rviz_gui.sh`, `src/cv/realsense_camera/`.
  - Odom bridge: `scripts/final_bridge.py`, `scripts/cuvslam_odometry_udp_exporter.py`, `scripts/probe_odom_best_effort.py`.
  - Navigation core: `src/navigation/map_grid.py`, `astar_planner.py`, `pure_pursuit.py`, `local_obstacle.py`, `navigator.py`.
  - Navigation ROS wrappers: `src/nodes/navigation/lightweight_navigator_node.py`, `depth_publisher.py`, `initial_pose_publisher.py`.
  - Task state machine: `src/nodes/decision/task_manager.py`.
  - YOLO: `src/nodes/perception/yolo_detect_publisher.py`, `src/cv/yolo_detector/`, model at `src/cv/yolo_detector/projects/combined/model/best.pt`.
  - Cabinet/gauge CV: `src/whz/whz/*`, assets under `src/whz/assets/`, standalone service wrapper `src/nodes/perception/whz_standalone_inspect.py`.
  - Legacy gauge backup: `src/cv/gauge_detector/`.
  - Lite3 motion bridge: `Lite3_ROS-ros2-foxy/`, launched by `scripts/start_competition.sh --dog`.
- Main sources of confusion:
  - root-level stale copies: `competition.launch.py`, `task_manager.py`, `initial_pose_publisher.py`, `lightweight_navigator_node.py`, `navigation.launch.py`, `nav2_params.yaml`, `navi_nodes.py`;
  - duplicated scripts under both `scripts/camera` and `scripts/scripts/camera`, likewise `scripts/cv` and `scripts/scripts/cv`;
  - `navi/navi_map_data.py` and `navi/map/navi_map_data.py` both exist; current navigation imports the `navi/map` version;
  - `src/whz` is the canonical whz package, while old references may still mention top-level `whz`;
  - GitHub `origin/main` and Jetson workspace differ materially, so using only GitHub to reason about current behavior is unsafe.

## Jetson Action Recommendation — 2026-07-03
- Current live state:
  - cuVSLAM Docker and UDP bridge are running;
  - D455 and Lite3 network are both present;
  - multiple duplicate navigation/task/depth/initial-pose nodes are running at the same time;
  - CPU load is very high and odom stale-drop count is rising;
  - cuVSLAM frame timing warnings are severe under current load.
- Therefore the correct immediate task is not “start navigation again” and not “enable YOLO”.
- Recommended next order:
  1. Stop duplicate host processes with `bash scripts/stop_all.sh` while keeping Docker if desired.
  2. Confirm process counts are zero for `task_manager`, `depth_publisher`, `initial_pose_publisher`, `competition.launch`, and old `transfer` nodes.
  3. If a build is still active, let it finish or stop it before runtime testing.
  4. Restart a single clean run without YOLO/WHZ first, ideally without dog transfer until `/cmd_vel` is verified.
  5. Run `/odom` probe and check latency; if stale-drop remains high, reduce load before connecting Lite3.
  6. Only after single-instance `/odom` and `/cmd_vel` are sane should `--dog` be used for a short autonomous path test.
- Do not turn on YOLO/whz until the clean SLAM + Navigation base run is stable; both add CPU load and will make the stale odom issue worse.

## SLAM + Navigation Next Step After Manual Startup — 2026-07-03
- Current verified SLAM/bridge state:
  - cuVSLAM + bridge are alive after the user's manual startup.
  - `/odom` publishes from `final_bridge` with BEST_EFFORT QoS at about `59 Hz`.
  - Probe latency is mostly usable for first navigation validation: mean about `36 ms`, p95 about `58 ms`, max about `124 ms`.
  - No navigation/task/transfer process was running during the read-only check.
- Important safety constraint:
  - `src/navigation/navigator.py` directly sends Lite3 UDP motion commands to `192.168.1.120:43893` inside `_publish_cmd_vel`, in addition to publishing ROS `/cmd_vel`.
  - This means launching `quadruped_robot_competition lightweight_navigator` can move the dog if the Lite3 network is connected, even when `transfer` is not launched.
- Recommended next validation order:
  1. Do not launch `task_manager` yet; use `lightweight_navigator` first.
  2. Before launching it, either disconnect/isolate Lite3 network or patch/configure a direct-UDP-disable switch.
  3. Then publish one `/nav/goal` such as `obstacle_exit` and monitor `/nav/status` plus `/cmd_vel`.
  4. Treat this first run as command-generation validation only unless the robot is in a physically safe open area with emergency stop/takeover ready.

## Navigator UDP Exception / Interface Check — 2026-07-03
- `src/navigation/navigator.py` line-range around `_publish_cmd_vel()` already wraps the file-log and Lite3 UDP `sendto()` calls in `try: ... except Exception: pass`.
- Practical meaning:
  - Offline or disconnected Lite3 network should not crash `lightweight_navigator`.
  - ROS `/cmd_vel` is published before the UDP block, so `/cmd_vel` observation should still work if UDP fails.
- Weakness:
  - The broad silent `except` hides network errors and also hides whether the direct dog command path is active.
  - For safer dry-runs, a runtime disable switch for direct UDP is preferable to relying on unplugged network.
- `/nav/goal` is confirmed to be `std_msgs/String`; waypoint-name commands such as `obstacle_exit` match the lightweight wrapper.
- The lightweight navigator does not depend on TF lookup internally; it uses `/odom` and `/tmp/odom_latest.json`. Still, `tf2_echo odom base_link` remains a useful external bridge sanity check because `final_bridge.py` broadcasts that TF.

## Navigator / Driver Boundary Fix — 2026-07-03
- The current architecture has now been corrected on the Jetson side for the immediate safety issue:
  - `Navigator` default behavior is command generation only: publish ROS `/cmd_vel` and log the command.
  - Direct Lite3 UDP from `Navigator` is disabled by default.
  - Legacy direct UDP can still be explicitly enabled with `NAV_DIRECT_UDP=1`, but this should be treated as a bypass/debug mode, not normal competition architecture.
- `scripts/start_competition.sh --dog` now starts the existing Lite3 `transfer` driver, so the intended runtime path is:

```text
TaskManager / lightweight_navigator
  -> Navigator
  -> /cmd_vel
  -> transfer / jetson2motion
  -> Lite3 UDP
```

- Remaining architecture debt:
  - `transfer/src/Jetson2Motion.cpp` still exits on `sendto()` error and does not appear to own all safety semantics yet.
  - A proper `safety_gate` / `cmd_mux` layer is still recommended before real high-risk runs: estop, phase enable, velocity clamp, stale-odom timeout, and watchdog stop.
- Immediate validation consequence:
  - It is now reasonable to run `lightweight_navigator` for `/cmd_vel` dry-run without moving Lite3, as long as `NAV_DIRECT_UDP` is not set.
  - For real dog movement, use `--dog` only when the physical safety setup is ready because `transfer` will subscribe `/cmd_vel` and send to Lite3.
## 技术报告任务上下文 — 2026-07-03
- 用户新增 `技术报告/` 目录，其中 `technical_report_scoring_rubric.md` 是本次技术报告评分标准和关注点来源。
- 报告需结合当前 workspace，重点覆盖除机械臂以外的系统内容；机械臂代码当前不应写成已实现模块。
- 当前 PWF 记录显示项目核心可写内容包括：D455 + Isaac ROS Visual SLAM/cuVSLAM、UDP latest-only `/odom` bridge、轻量导航 `Navigator`、Lite3 `/cmd_vel -> transfer` 驱动边界、YOLO/仪表视觉、任务管理、语音播报、D455 支架 CAD 和 Jetson 部署验证。
- ByteRover 长期记忆本机不可用，无法做 L1-3 主动检索。

## 技术报告素材抽取 — 2026-07-03
- 评分标准权重：技术方案 40%、文档呈现 40%、工程代码 20%。报告应突出系统完整性、算法/优化深度、实测数据、图文排版、关键代码解释和工程规范。
- 本机 `README.md` 记录了 D455 输入链路实测：RGB/depth、IR 双目 + depth、accel/gyro IMU、`RealsenseCamera.for_cuvslam()` 短测通过；Jetson 环境为 Xavier NX / Ubuntu 20.04 / L4T R35.6.4 / CUDA 11.4 / Host ROS Foxy / Container ROS Humble。
- cuVSLAM runtime 采用容器隔离，RealSense ROS 输出 IR1/IR2 约 90Hz、IMU 约 200Hz；20 秒 bench 采样记录中 infra1=1732、infra2=1730、imu=3724、status=1739、odom=1735、`vo_state=1`。
- 导航桥接链路是 Docker `/visual_slam/vis/slam_odometry` -> UDP `127.0.0.1:19001` -> Host `/odom` + `odom -> base_link` TF；`final_bridge.py` 固定 Host 侧 frame contract，并保留 cuVSLAM source timestamp。
- Bridge 的先进性/工程优化点：Docker exporter、Host bridge、probe 均使用 BEST_EFFORT + KEEP_LAST depth=1；Host UDP socket drain 只处理最新包；超过 150ms 的旧 odom 被 stale-drop；`probe_odom_best_effort.py` 输出 host/source rate、latency mean/p95/max、jitter 和状态分类。
- 2026-07-03 PWF 中的 live 检查记录：`/odom` probe 5 秒收到 295 条，host rate 58.92Hz，source-stamp rate 58.46Hz，latency mean 36.06ms、p95 57.98ms、max 123.72ms。
- 仪表识别采用 OpenCV：CLAHE + 双边滤波 + HoughCircles 表盘定位；指针角度优先 HoughLinesP，失败时用暗色像素质心法；沿指针方向在彩色刻度环采样 HSV 区域，映射 yellow/green/red 到偏低/正常/偏高。
- 仪表 ROS 节点发布 `/gauge/status` JSON 和 `/gauge/detected` Bool；`live_validation.py` 用颜色覆盖率、三色区域像素数、方向采样分数、方向 margin 和连续稳定帧数过滤单帧误判。
- 远端 `origin/main` 已更新到 `72e3833`；该版本包含导航源码：`Navigator`、A*、Pure Pursuit、local obstacle detector、TaskManager、YOLO detect publisher、speech placeholder 等。
- `Navigator` 采用 2.5cm 栅格、8 邻接 A*、障碍膨胀、路径简化和 waypoint downsampling；控制层用 Pure Pursuit，保守限速约 `max_linear_vel=0.25m/s`、`max_angular_vel=0.5rad/s`，降低视觉 SLAM 失跟风险。
- 最新 `Navigator` 默认只发布 ROS `/cmd_vel` 并记录命令，直接 Lite3 UDP 只有 `NAV_DIRECT_UDP=1` 才启用；这体现了导航算法和底层驱动/安全边界解耦。
- `TaskManager` 状态机覆盖 START、PASS_OBSTACLE、INSPECT_GAUGES、FIND_RED_BAR、GRASP_BAR、PLACE_TO_ABNORMAL_ZONE、FINISH、ABORT；其中机械臂抓取/放置仍为 TODO/占位，不应在报告中写成已完成。
- YOLO 节点使用 combined model 类别 red/green/obstacle，支持 Docker relay JPEG 模式，避免 cuVSLAM 已占用 D455 时 Host 侧重复打开相机；发布 `/yolo/detections` JSON、`/yolo/image` 和 `/yolo/instance_count`。
- CAD 支架为 STEP-first 参数化设计，Lite3 三孔测量三角、D455 后部 95mm M4 孔距、45cm 总高、30 度下俯角；输出 PLA Tough 主结构和 TPU 隔振垫 STEP/STL，并有快照图用于报告插图。
- 用户后续要求报告不要添加任何图片，也不要继续看图片；技术报告应改为纯文字、表格和代码说明，不使用图片插图或 TikZ 图形。

## Tailscale 多电脑 SSH Jetson 方案核对 — 2026-07-04
- 用户目标：第三台电脑也能通过 Tailscale SSH 到 Jetson Xavier，同时只允许指定的第二/第三台电脑访问 Jetson，其他 tailnet 设备不应访问。
- 官方资料核对结论：
  - 多台电脑同时 SSH 到同一台 Jetson 是正常可行的；核心限制来自 Jetson 的 SSH 服务、Tailscale SSH 策略和 tailnet 网络访问策略。
  - Tailscale 不是“第二/第三台电脑接到第一台电脑下面”的链式模型；推荐所有授权电脑和 Jetson 加入同一个 tailnet，或将 Jetson 这台设备分享给外部用户。
  - 若使用 Tailscale SSH，Jetson 需要执行 `sudo tailscale up --ssh`，且 tailnet 策略里同时需要网络访问规则和 `ssh` 规则。
  - 若要按“具体电脑”限制访问，可用网络访问规则只放行指定电脑的 Tailscale IP/host alias 到 Jetson 的 `tcp:22`；Tailscale SSH 的 `ssh.src` 仍按用户/组/标签控制。
  - 若第二/第三台电脑属于外部账号，Tailscale 的设备 sharing 更适合：只分享 Jetson 设备给对方；被分享用户只能访问这台共享设备，不能看到整个 tailnet。
  - 若第二/第三台电脑都由自己管理，最简单方式是登录同一个 tailnet，然后在 Access controls 中只允许这些客户端到 Jetson `tcp:22`。

## Isaac ROS/cuVSLAM 版本约束核对 — 2026-07-04
- 用户要求核对 cuVSLAM 与 JetPack/Ubuntu/ROS 版本的关系，用于修订技术报告中的 Docker 方案说明。
- 官方 Isaac ROS Release Notes 显示：Isaac ROS 2.0 支持 JetPack 5.1.2，并提供面向 JetPack 5 的 ROS 2 Humble Debian packages；同一段 release notes 还说明 Humble 版本引入了 NITROS 的 type adaptation/type negotiation 能力，Foxy 已处于 deprecated 路线。
- 官方 Isaac ROS Release Notes 显示：Isaac ROS 3.1/3.2 转向 JetPack 6 / Ubuntu 22.04；Isaac ROS 3.1 的限制项明确移除了 JetPack 5.1.2、Ubuntu 20.04 和 Jetson Xavier 支持。
- 因此本项目报告中采用的表述应是：Jetson Xavier NX + JetPack 5.x + Ubuntu 20.04 + Host ROS2 Foxy 与 cuVSLAM 依赖的 Humble/NITROS 运行栈不匹配；为了同时保留比赛侧 Foxy 节点和运行 cuVSLAM，采用 Docker 容器承载 ROS2 Humble + Isaac ROS/cuVSLAM + CUDA runtime，再用 UDP bridge 返回 Host `/odom`。
- 参考来源：
  - https://nvidia-isaac-ros.github.io/releases/index.html
  - https://nvidia-isaac-ros.github.io/v/release-2.1/repositories_and_packages/isaac_ros_visual_slam/isaac_ros_visual_slam/index.html

## 技术报告写作口吻修订原则 — 2026-07-05
- 用户指出第四部分最大问题不是技术事实，而是口吻像“看完文件后指导学生调试”，不够像参赛学生在阐述自己的项目。
- 后续报告正文应优先使用“本项目采用 / 我们完成了 / 当前链路为 / 这组数据对应……”这类项目陈述句。
- 避免在正式报告正文中使用“需要注意的是 / 还需要 / 建议 / 推荐 profile / 不等价于”等外部评审或调试指导式表达。
- 技术边界仍要保留，但应写成阶段性事实和系统设计边界，例如“这组数据对应相机侧 SLAM 链路验证；整机定位按 `odom -> base_link` 组织”。
- 2026-07-05 追加：全文统一时应把“代码文件/远端分支/提交前替换/placeholder/TODO”等实现记录式语言，改成“模块已接入什么、控制链路怎么走、当前版本系统边界是什么”。例如语音写成“任务层保留统一接口，whz inline 流程支持预录音频播报”，机械臂写成“任务状态机已保留抓取/放置接口，实体执行链路尚未接入”。

## Lite3 底板螺丝 TPU 防松垫圈 — 2026-07-05
- 用户目标：在相机支架底板三颗固定螺丝与刚性底板之间增加 TPU 垫圈，降低强振动下螺丝松动风险。
- 现有支架参数来源：`cad/lite3_d455_mount_step/model.py` 中机器人侧三孔为 `(-52.5, 0)`、`(52.5, 0)`、`(0, -46.300648)`；结构孔径 `5.2 mm`；螺丝头沉孔直径 `10.5 mm`，沉孔深度 `5.0 mm`。
- 垫圈设计：
  - 单片外径 `10.0 mm`，比沉孔直径小 `0.5 mm`，留出 TPU 打印膨胀/装配余量。
  - 单片内径已按实物试拧反馈从 `5.6 mm` 收小到 `2.5 mm`，用于增强螺丝处 TPU 垫圈贴合。
  - 厚度 `1.0 mm`，作为第一版比 `0.5 mm` 更适合 FDM TPU 打印和压缩后仍保留弹性层。
  - 完整装配参考中垫圈位于 `z=5.0..6.0 mm`，即底座 `10 mm` 厚板的 `5 mm` 深沉孔底部，用于被螺丝头压住。
- 生成产物：
  - 单片：`cad/lite3_d455_mount_step/out/lite3_screw_tpu_washer.step` / `.stl`
  - 三孔排布：`cad/lite3_d455_mount_step/out/lite3_screw_tpu_washer_set.step` / `.stl`
  - 完整装配参考已更新：`cad/lite3_d455_mount_step/out/lite3_d455_mount_assembly.step` / `.stl`
- 验证结果：
  - CAD inspect 确认单片外圆半径 `5.0 mm`、内孔半径 `2.8 mm`、厚度 `1.0 mm`。
  - 三孔排布 frame 为 `(-52.5, 0, 0)`、`(52.5, 0, 0)`、`(0, -46.300648, 0)`。
  - 测量确认上边跨距 `105.0 mm`，左右孔到下孔欧氏距离约 `70.000000 mm`。
  - 快照视觉复核通过：单片为薄环，三孔排布与底板孔位一致，完整装配透明顶视可见三片垫圈围绕底板三颗螺丝孔。
## Navigation/Nav2 Restoration Assessment — 2026-07-05
- User context: SLAM/cuVSLAM is considered mostly done; current priority is moving Navigation from the custom A* / Pure Pursuit stack back toward official ROS2 Navigation2/Nav2.
- Local Windows repo could not fetch GitHub over HTTPS during this session: `github.com:443` timed out. Jetson GitHub SSH access was usable, so remote branch inspection was performed from Jetson.
- GitHub branch found from Jetson: `feature/nav2-restoration` at commit `72c23a3` (`feat: restore Nav2 navigation stack, remove custom navigator`).
- Jetson current worktree is not on that branch:
  - path: `/home/superwfx666/quadruped-robot-competition`
  - branch: `main`
  - HEAD: `82512c6`
  - status: `main...origin/main [ahead 20, behind 37]`
  - many current integration files are untracked in the dirty Jetson worktree.
- Current Jetson runtime state during inspection:
  - cuVSLAM Docker container running: `cuvslam_gui_20260705-163246`.
  - ROS topic list showed D455 camera topics and `/visual_slam/...` topics.
  - No host `/odom` topic was present.
  - No Nav2 nodes such as `map_server`, `planner_server`, `controller_server`, `bt_navigator`, or lifecycle manager were running.
  - `final_bridge.py` was not observed running; `/tmp/odom_latest.json` did not provide a current bridge check.
  - CPU was heavily loaded during `tegrastats`; `cuvslam_loop_metrics_recorder.py` was consuming about one CPU core and all six CPU cores reported high utilization.
- Jetson already has Foxy Navigation2 packages installed:
  - `ros-foxy-navigation2`, `ros-foxy-nav2-bringup`, `nav2_map_server`, `nav2_planner`, `nav2_controller`, `nav2_bt_navigator`, `nav2_lifecycle_manager`, `nav2_navfn_planner`, `nav2_regulated_pure_pursuit_controller`, `nav2_waypoint_follower`, `nav2_recoveries`, `nav2_voxel_grid`, plus `depth_image_proc` and `image_pipeline`.
- `feature/nav2-restoration` static checks in a temporary Jetson worktree passed:
  - `python3 -m compileall -q launch src navi scripts`
  - `bash -n scripts/start_competition.sh`
  - `bash -n scripts/stop_all.sh`
- `feature/nav2-restoration` effective content:
  - Restores `configs/navigation/nav2_params.yaml`, `launch/navigation.launch.py`, PGM maps, `navi/navigation_client.py`, `src/nodes/navigation/cmd_vel_bridge.py`, `cuvslam_bridge.py`, `ir_imu_bridge.py`.
  - Deletes the custom `src/navigation/*` A* / Pure Pursuit / lightweight navigator modules.
  - Integrates `NavigationClient` into `task_manager.py`.
  - Adds a `/cmd_vel -> Lite3 UDP` bridge as a separate node.
- Important branch relation:
  - `origin/main...origin/feature/nav2-restoration` is `2 1`; the feature branch is missing two current main commits, including `72e3833 fix: route navigator commands through driver node`, and adds one Nav2 restoration commit.
- Important Foxy compatibility gap:
  - Jetson Foxy has `nav2_recoveries`, not `nav2_behaviors`.
  - Jetson Foxy does not show `nav2_velocity_smoother`.
  - Foxy `nav2_bringup` uses `recoveries_server`, `default_bt_xml_filename`, and `goal_checker_plugin` singular.
  - Branch `nav2_params.yaml` currently uses `behavior_server`, `nav2_behaviors/*`, `velocity_smoother`, `default_nav_to_pose_bt_xml`, and `goal_checker_plugins` plural; lifecycle `node_names` also includes nodes not launched by `launch/navigation.launch.py`.
  - Directly launching this branch on Jetson Foxy is therefore likely to fail during lifecycle activation or BT/controller setup unless parameters and launch are corrected first.
- Important launch/package gap:
  - Branch `competition.launch.py` starts initial pose, static TF, depth publisher, and `cmd_vel_bridge`, then includes `navigation.launch.py`.
  - Branch `navigation.launch.py` also starts initial pose, static TF, and depth publisher, creating duplicate node intent.
  - `navigation.launch.py` runs Python scripts from `PROJECT_ROOT/src/...`; when launched from an installed package share path, that source path will not exist unless the launch is run directly from the source tree.
  - `setup.py` installs `configs/navigation` and `navi/map`, but not `configs/ros/competition_params.yaml`, while `competition.launch.py` expects that config under package/share-derived `PROJECT_ROOT`.
- Current recommendation:
  - Do not switch the dirty Jetson main worktree directly to `feature/nav2-restoration`.
  - Create a clean integration branch/worktree based on latest `origin/main`, selectively port the Nav2 restoration files, fix Foxy Nav2 compatibility and package launch paths, then test in layers.
  - Test order should be: clean runtime and single cuVSLAM container -> restore host `/odom` bridge -> launch Nav2 without dog movement -> verify lifecycle active, `/map`, `/plan`, `/cmd_vel` -> enable dog command bridge only on stand/blocked wheels at low speed -> field route phases.
## Mature Navigation Stack Research — 2026-07-05
- Official Nav2 documentation confirms NavFn Planner implements Dijkstra or A* as a holonomic planner: https://docs.nav2.org/configuration/packages/configuring-navfn.html
- Official Nav2 documentation describes Regulated Pure Pursuit as a Pure Pursuit variant targeting service/industrial robot needs, with curvature/obstacle proximity velocity regulation: https://docs.nav2.org/configuration/packages/configuring-regulated-pp.html
- Official Nav2 plugin-selection docs state Regulated Pure Pursuit is suitable for differential, ackermann, and legged robots; TEB can also be used for differential/omni/ackermann/legged robots: https://docs.nav2.org/setup_guides/algorithm/select_algorithm.html
- Official Nav2 tuning docs state RPP is good for exact path following, while DWB and MPPI can deviate from the path to avoid dynamic obstacles; DWB scores multiple trajectories with critics and supports omni/diff robot types out of the box: https://docs.nav2.org/tuning/index.html
- Official Nav2 docs describe Smac Planner as a family of A*-based planners: 2D A*, Hybrid-A*, and State Lattice, with support for legged vehicles in Hybrid-A*/Lattice modes: https://docs.nav2.org/configuration/packages/configuring-smac-planner.html
- Official Nav2 docs describe VoxelLayer as a costmap plugin using 3D raycasting for depth/3D sensors and projecting into 2D planning/control space: https://docs.nav2.org/configuration/packages/costmap-plugins/voxel.html
- Official Nav2 docs describe MPPI as a predictive sampling-based controller and note it entered Nav2 as a newer controller after Humble-era changes: https://docs.nav2.org/configuration/packages/configuring-mppic.html and https://docs.nav2.org/migration/Humble.html
- NVIDIA Isaac ROS Visual SLAM docs state Visual SLAM uses one or more stereo cameras and optional IMU to estimate odometry as input to navigation, GPU accelerated for real-time low-latency robotics: https://nvidia-isaac-ros.github.io/repositories_and_packages/isaac_ros_visual_slam/index.html
- NVIDIA Isaac ROS Visual SLAM docs also state it does not support standalone global localization and needs an external pose hint/system for localization in an existing map: https://nvidia-isaac-ros.github.io/v/release-3.2/repositories_and_packages/isaac_ros_visual_slam/isaac_ros_visual_slam/index.html
- NVIDIA Isaac ROS Nvblox docs state Nvblox consumes depth + pose to reconstruct a 3D scene and outputs a 2D costmap for Nav2; this is a vision-based obstacle avoidance route: https://nvidia-isaac-ros.github.io/repositories_and_packages/isaac_ros_nvblox/index.html
- NVIDIA Isaac ROS Nvblox RealSense tutorial specifically covers running Nvblox together with Isaac ROS Visual SLAM on an Intel RealSense camera: https://nvidia-isaac-ros.github.io/concepts/scene_reconstruction/nvblox/tutorials/tutorial_realsense.html
- Applicability judgment for this repo:
  - Near-term mature route: ROS2 Foxy Nav2 on host, using `/odom` from cuVSLAM bridge, PGM static map, NavFn A* or DWB/RPP, and Nav2 VoxelLayer/ObstacleLayer from D455 depth/PointCloud2.
  - Mid-term advanced route: move more navigation into Isaac ROS/Humble container and use Visual SLAM + Nvblox + Nav2; this is official and mature but higher integration/load risk on Xavier NX.
  - Avoid near-term custom MinSnap/MPPI chain because it would reintroduce custom planning/control complexity and does not match installed Foxy package availability.

## Nav2 Foxy+DWB Smoke Test Finding — 2026-07-05
- Jetson clean worktree `/home/superwfx666/quadruped-robot-competition-nav2-dwb` on branch `Stonefield/nav2-foxy-dwb-integration` can launch the Foxy Nav2 stack with the current package install layout.
- In isolated `ROS_DOMAIN_ID=87`, with fake `/odom` and `map -> odom -> base_link` TF, Nav2 lifecycle reached active for `map_server`、`planner_server`、`controller_server`、`recoveries_server`、`bt_navigator`.
- A NavigateToPose goal from `(3.80, 0.75)` to `(4.80, 0.75)` was accepted, and DWB published 80 nonzero `/cmd_vel` messages in an 8 second window.
- Observed command envelope in this test: `max linear.x = 0.190667 m/s`, `max abs angular.z = 0.0 rad/s`.
- `competition.launch.py --show-args` confirms `enable_cmd_vel_bridge` default is `false`; dry-run does not start the optional `/cmd_vel -> Lite3 UDP` bridge unless explicitly enabled.
- Practical conclusion: the first Navigation milestone is passed at software level. The next real integration risk is not DWB startup, but replacing fake odom/TF with the live cuVSLAM host `/odom` bridge while preserving `map -> odom -> base_link` consistency and keeping the Lite3 command bridge disabled.

## cuVSLAM camera_link -> base_link Transform Finding — 2026-07-05
- Project convention now treats Nav2 `base_link` as equivalent to the Lite3 public URDF root/body frame `TORSO`.
- D455 `camera_link` is the camera body frame, not an optical frame. Optical-frame rotations must not be folded into the robot mount transform.
- Current engineering initial extrinsic:
  - `base_link -> camera_link`
  - translation `(0.080, 0.000, 0.493)` meters
  - RPY `(0.0, -0.523599, 0.0)` radians
  - quaternion `(0.0, -0.258819, 0.0, 0.965926)`
- If cuVSLAM publishes an odometry pose whose child frame is `camera_link`, the correct Nav2 pose is:

```text
T_odom_base = T_odom_camera * inverse(T_base_camera)
```

- Simply changing `child_frame_id` to `base_link` is wrong because it moves Nav2's control point to the physical camera, about 49.3 cm above and 8 cm forward of the robot body frame.
- `cuvslam_bridge.py` in the Nav2 DWB worktree now applies this transform by default and passes through poses that are already `base_link`, preventing double transforms.
- The bridge's ROS callback test on Jetson verified that an identity camera pose at `(1, 2, 3)` becomes `odom->base_link` position `(0.684218, 2.0, 2.61305)` and quaternion `(0.0, 0.258819, 0.0, 0.965926)`.
- Next validation must use real cuVSLAM output to check timestamp continuity, `/odom` rate, TF availability, and Nav2 controller behavior before dynamic obstacle costmap work.

## cuVSLAM Base Frame Strategy Research — 2026-07-05
- Official Isaac ROS Visual SLAM docs say `base_frame` is the robot/camera-rig base, cameras are rigidly mounted to it, and estimated odometry/SLAM pose represents this frame.
- Official Isaac ROS Visual SLAM docs say `visual_slam/tracking/odometry` is the current odometry of `base_frame`; `visual_slam/tracking/vo_pose` is the current pose of `base_frame`.
- Official Isaac ROS Visual SLAM release-2.1 docs include `input_base_frame`, `input_left_camera_frame`, `input_right_camera_frame`, `input_imu_frame`, `base_frame`, and `publish_odom_to_base_tf`; this matches the Jetson Humble/container-era launch style better than the latest Jazzy examples.
- NVIDIA forum guidance says typical TF should be `map -> odom -> base_link -> input_left_camera_frame`, and `input_base_frame` should usually match `base_frame`.
- NVIDIA forum guidance also warns there must be a consistent static TF tree at runtime and no duplicate publisher for `map->odom` or `odom->base_link`.
- GitHub issue #21 and related forum threads show historical ambiguity/bugs around whether `input_base_frame` actually accounts for the base-to-camera transform in all versions. Therefore scheme B is architecturally best but must be verified on the actual Jetson image/version, not assumed.
- Nav2 docs say the required TF tree includes `map -> odom -> base_link -> sensor frames`, odometry should provide `odom -> base_link`, and Nav2 also requires `nav_msgs/Odometry` because it uses robot velocity; the odometry twist is in `child_frame_id`.
- Decision: prefer scheme B as the target, where Docker cuVSLAM publishes base-frame odometry directly. Keep the Python transform bridge as an automatic fallback/pass-through verifier: if incoming `child_frame_id=base_link`, it passes through; if incoming `camera_link`, it transforms to base.

## cuVSLAM/Nav2 Frame Ownership Recheck — 2026-07-05
- Current Isaac ROS Visual SLAM docs define `base_frame` as the robot or camera-rig base, with odometry and SLAM pose representing that frame; `odom_frame -> base_frame` is the odometry pose. This supports setting `base_frame=base_link` as the preferred target when the TF tree is valid.
- Isaac ROS Visual SLAM release-2.1 docs, which are closer to this Jetson Xavier NX + JetPack 5/Humble container stack, expose `input_base_frame`, `input_left_camera_frame`, `input_right_camera_frame`, `input_imu_frame`, `base_frame`, `publish_odom_to_base_tf`, and `publish_map_to_odom_tf`. The release-2.1 topic table describes `visual_slam/tracking/odometry` as odometry messages for `base_link`.
- Isaac ROS current release notes show newer 3.x/4.x lines moved beyond Jetson Xavier / Ubuntu 20.04 / JetPack 5 support. Therefore "newer Isaac ROS" is not automatically better for this project; the stable path remains the already-built release-2.1/Humble Docker stack on the Xavier NX.
- Nav2 documentation requires the REP-105 style tree `map -> odom -> base_link -> sensor frames`; `odom -> base_link` should come from the odometry system, and remaining sensor transforms should be static relative to `base_link`.
- ROS2 `nav_msgs/Odometry` defines pose in `header.frame_id` and twist in `child_frame_id`; this is the key reason a pure TF-only scheme is incomplete for Nav2/DWB. The odometry message itself must have correct `child_frame_id` semantics, not only a correct TF tree.
- Nav2's VIO integration tutorial recommends disabling direct VIO TF publication when fusing with other sources, remapping VIO odometry to a non-reserved topic, and letting `robot_localization` own the fused `odom -> base_link` output. This is a mature long-term upgrade path if Lite3 body odometry/IMU becomes available and trustworthy.
- Updated architecture judgment: best near-term plan is "B with verifier/fallback": configure cuVSLAM Docker to output base-frame odometry directly, avoid duplicate TF publishers, and keep the host bridge as a pass-through plus sanity gate. Best mid-term plan is "B + robot_localization": cuVSLAM publishes `/camera_odom` or equivalent, EKF fuses it with Lite3/IMU data, and EKF becomes the single owner of `/odom` and `odom -> base_link`.

## cuVSLAM Scheme B Jetson Dry-Run Result — 2026-07-05
- Jetson Nav2 worktree `/home/superwfx666/quadruped-robot-competition-nav2-dwb` was updated so `scripts/start_cuvslam_rviz_gui.sh` supports `CUVSLAM_MOUNT_MODE=robot`, `CUVSLAM_BASE_FRAME=base_link`, `CUVSLAM_INPUT_BASE_FRAME=base_link`, `CUVSLAM_INPUT_LEFT_CAMERA_FRAME=camera_link`, base-to-camera static TF, and configurable `publish_odom_to_base_tf`.
- Real Jetson cuVSLAM dry-run with `CUVSLAM_MOUNT_MODE=robot`, `CUVSLAM_PUBLISH_ODOM_TO_BASE_TF=false`, `CUVSLAM_PUBLISH_MAP_TO_ODOM_TF=false` verified Docker output:
  - `/visual_slam/tracking/odometry`: `header_frame_id=odom`, `child_frame_id=base_link`.
  - `/visual_slam/vis/slam_odometry`: `header_frame_id=map`, `child_frame_id=base_link`.
- Decision from the dry-run: Nav2 `/odom` must use `/visual_slam/tracking/odometry`, not `/visual_slam/vis/slam_odometry`. The `vis/slam_odometry` topic is suitable for visualization/backend-map pose inspection, but it must not be relabeled as odom.
- Updated defaults in the Nav2 worktree:
  - `src/nodes/navigation/cuvslam_bridge.py`
  - `scripts/final_bridge.py`
  - `scripts/cuvslam_odometry_udp_exporter.py`
  - `scripts/odom_relay_docker.py`
  - `scripts/start_competition.sh`
- Host Foxy DDS required `configs/ros/fastrtps_no_shm.xml` for reliable external subscription behavior on Jetson. Without it, `/odom` appeared in topic info and the bridge self-verified, but an external probe did not receive messages. With `FASTRTPS_DEFAULT_PROFILES_FILE=$PWD/configs/ros/fastrtps_no_shm.xml`, Host probe received `/odom` successfully.
- Host `/odom` probe result after no-shm:
  - `/odom.header_frame_id=odom`
  - `/odom.child_frame_id=base_link`
  - TF `odom -> base_link` was readable by `tf2_echo`.
- Real Nav2 dry-run result with Lite3 command bridge disabled:
  - Nav2 lifecycle reached active.
  - NavigateToPose goal `(x=4.8, y=0.75, yaw=0)` was accepted.
  - `/cmd_vel` sampling for 8 seconds produced `cmd_count=80`, `nonzero_count=80`, `max_linear_x=0.22 m/s`, `max_abs_angular_z=0.1184210526 rad/s`.
- New helper probes added in the Nav2 worktree:
  - `scripts/probe_cuvslam_odom_frames.py` for Odometry frame-id checks.
  - `scripts/nav2_goal_cmd_vel_probe.py` for NavigateToPose + `/cmd_vel` dry-run checks.
- Remaining issue before obstacle-zone work: `depth_publisher` on Host failed with `Device or resource busy` because cuVSLAM Docker already owns the D455. Dynamic obstacle/local costmap input should use Docker depth relay or another single-owner camera path instead of opening D455 again from Host.

## Nav2 `/plan` Probe Design — 2026-07-05
- A dedicated A* global-path probe now exists in the Nav2 DWB worktree: `scripts/nav2_goal_plan_probe.py`.
- Purpose: after sending one `NavigateToPose` goal, capture Nav2 `/plan` and produce concrete evidence of the global path: point count, start/end pose, XY path length, CSV, SVG plot, and summary JSON.
- CPU/resource decision: this should be an event-style probe, not a continuous high-frequency logger. Default behavior captures only the first non-empty `Path`, does no file I/O in the subscriber callback, cancels the goal after capture, and exits.
- Optional replanning observation is intentionally bounded by parameters: `--max-plans` limits the number of captured plans and `--min-plan-interval` throttles repeated captures.
- The probe has been syntax-checked locally and on Jetson, but has not yet been run against a live Nav2 `/plan` publisher in this session.

## Navigation Map Assets — 2026-07-06
- Current local working tree `HEAD` does not contain `navi/map/` files, so no local `*.pgm` map was initially visible.
- GitHub `origin/main` contains report-ready navigation map previews and A* route images under `navi/map/`, including:
  - `navi/map/navi_map_preview.png`
  - `navi/map/astar_start_to_obstacle_exit_phase1.png`
  - `navi/map/astar_obstacle_exit_to_pos1_middle_phase2.png`
  - `navi/map/astar_pos2a_upper_right_to_pos2b_lower_right_phase2.png`
  - `navi/map/astar_pos2b_lower_right_to_grab_area_phase2.png`
  - `navi/map/astar_grab_area_to_placement_A_phase2.png`
- GitHub `origin/feature/nav2-restoration` contains true Nav2 map files:
  - `navi/map/competition_field.pgm`
  - `navi/map/competition_field.yaml`
  - `navi/map/competition_field_phase1.pgm`
  - `navi/map/competition_field_phase1.yaml`
  - `navi/map/competition_field_phase2.pgm`
  - `navi/map/competition_field_phase2.yaml`
- Jetson main repo `~/quadruped-robot-competition` currently has `navi/map/navi_map_preview.png` and generation scripts, but no generated `competition_field*.pgm` or `competition_field*.yaml`.
- Jetson worktree `~/quadruped-robot-competition-nav2-dwb` on branch `Stonefield/nav2-foxy-dwb-integration` contains the full map set: `competition_field*.pgm`, `competition_field*.yaml`, `navi_map_preview.png`, and A* route PNGs.
- `competition_field.yaml` metadata: `resolution: 0.025`, `origin: [0.0, 0.0, 0.0]`, `mode: trinary`, `image: competition_field.pgm`.
- `competition_field.pgm` is a 226 x 240 grayscale occupancy map. It is valid as the Nav2/PGM source, but visually too bare for the technical report figure by itself.
- For technical report Figure 9, prefer using `navi_map_preview.png` as the main figure because it labels the field, observation positions, obstacle area, cones, placement zone, and start pose. Mention `competition_field.pgm + competition_field.yaml` in text as the generated Nav2 map source if needed.

## cuVSLAM Trajectory Figure Data — 2026-07-06
- Jetson latest cuVSLAM log directory checked in this session: `/home/superwfx666/cuvslam_lite3_logs/20260706-150429`.
- Local copy exists at `技术报告/cuvslam_csv/20260706-150429`.
- Report Figure 7 uses:
  - before optimization: `vo_pose_samples.csv` as front-end VO trajectory, 3150 samples, XY path about 61.2 m.
  - after back-end optimization: `slam_all_poses_latest.csv` as back-end SLAM all-poses trajectory, 20000 poses, XY path about 44.6 m.
- User clarified this run did not return to the starting point. Therefore the end-start distance or large closure-like value should not be interpreted as a loop-closure failure for this figure; the report should present it as trajectory shape/path-length evidence only.

## arm_new Mechanical Arm Workspace — 2026-07-06
- `arm_new/` is the real mechanical-arm workspace for the report, not a placeholder design. It can run as a standalone Python workspace on Jetson or through the ROS2 adapter package `arm_new_ros`.
- `arm_api` keeps the core logic independent of ROS2: `yolo_target.py` parses YOLO JSON and back-projects the selected red target; `transforms.py` applies 4x4 frame transforms from `config/frame_transforms.yaml`; `planner.py` / `planner_new.py` generate IK and `MotionStep` sequences; `buslinker.py` / `protocol.py` execute BusLinker serial commands.
- Public arm coordinates use ArmPi arm-base frame in meters: `+Y` forward, `+X` lateral, `+Z` upward. The arm service should not receive raw pixels or raw D455 optical-frame coordinates.
- `arm_new_ros/arm_grasp_node.py` subscribes `/yolo/detections` as YOLO JSON and exposes Trigger services: `/arm/debug_get_camera_target`, `/arm/debug_get_arm_target`, `/arm/dry_run_grab_red`, `/arm/grab_red`, `/arm/release_fixed`.
- Real motion is gated by `enable_motion`; this is a safety switch, not evidence that the arm is unintegrated. Dry-run remains useful for checking target coordinates, IK reachability and servo pulse sequences before enabling motion.
- Current grasp implementation uses `ArmGrabPlannerNew.plan_horizontal_face_grab()`: generate a horizontal pre-grasp point using `pre_distance` (default 0.05 m), interpolate approach steps (default 8), close gripper, hold, lift by `lift_height` (default 0.08 m), and optionally return home.
- Release is implemented as a fixed action through `/arm/release_fixed`: open gripper using `release_gripper_pulse` and optionally return to home.

## Technical Report Figure Mapping for Eraser Redraw — 2026-07-06
- User target is exactly report figures 2, 9, 10, 11, and 12.
- PDF-extracted mapping:
  - Figure 2: `自主巡检与任务执行总体链路` -> `技术报告/figures/system_pipeline.mmd`
  - Figure 9: `A* 全局路径规划流程框图` -> `技术报告/figures/astar_algorithm.mmd`
  - Figure 10: `DWB 局部轨迹评价流程框图` -> `技术报告/figures/dwb_algorithm.mmd`
  - Figure 11: `Regulated Pure Pursuit 轨迹跟踪流程框图` -> `技术报告/figures/rpp_control_algorithm.mmd`
  - Figure 12: `实车导航与运动控制运行链路` -> `技术报告/figures/robot_navigation_chain.mmd`
- Figure 8 is the navigation map preview and is not part of the requested Eraser redraw set.
- Current Codex session does not expose Eraser MCP tools; tool discovery returned no Eraser tools, so actual Eraser redraw/export is blocked until MCP authorization/tool exposure is restored.

## DWB/RPP Trajectory Figure Research — 2026-07-06
- Official Nav2 DWB Controller docs describe DWB as a controller that samples/evaluates local trajectories with critics and publishes velocity commands. For the report figure, an ideal DWB line should be shown as a locally optimized feasible rollout near the reference path, usually smoother than raw path samples and allowed to deviate slightly where local scoring prefers safer motion.
- Official Nav2 Regulated Pure Pursuit docs describe RPP as a Pure Pursuit path-tracking controller with regulation by curvature, obstacle proximity, and approach-to-goal constraints. For the report figure, an ideal RPP line should be shown as a close path-following curve that smooths sharp corners and reduces overshoot.
- Nav2 tuning guidance distinguishes path-following behavior from local-trajectory optimization: RPP is suitable when exact path following is preferred, while DWB can intentionally deviate from the path to avoid dynamic obstacles or satisfy local costs. Therefore the planned figure will plot `SLAM path` as the reference, `Regulated Pure Pursuit tracking` as a close smoothed tracking curve, and `DWB local trajectory optimization` as a slightly offset/smoothed local rollout.
- Sources checked:
  - https://docs.nav2.org/configuration/packages/configuring-dwb-controller.html
  - https://docs.nav2.org/configuration/packages/configuring-regulated-pp.html
  - https://docs.nav2.org/tuning/index.html
- Tool note: ByteRover lookup was attempted for `DWB Regulated Pure Pursuit trajectory figure technical report cuVSLAM SLAM path`, but `brv` is not available in the current Windows PATH, so this task proceeds from PWF context plus official Nav2 sources.

## Navigation Architecture Review — 2026-07-06
- User asked whether the proposed chain "Docker cuVSLAM odometry -> Navigation subscribes topic -> Nav2 A* -> DWB smoothing -> RPP/RRP final path" is reasonable.
- Local workspace status:
  - Current local `main` is behind `origin/main`; local files include the UDP latest-only cuVSLAM odometry bridge but do not include all current remote lightweight navigation files.
  - `origin/main` currently documents and implements a lightweight competition navigator: Docker/Humble cuVSLAM -> Host/Foxy `/odom` -> in-process A* grid planner -> Pure Pursuit controller -> `/cmd_vel`.
  - `origin/main:navi/README.md` explicitly states Nav2 was replaced because full Nav2 on Jetson Xavier NX reached high CPU load in this competition setup; lightweight A* + Pure Pursuit is the current remote mainline.
  - `origin/feature/nav2-restoration` contains the older/full Nav2 route with `nav2_navfn_planner/NavfnPlanner use_astar: true`, `nav2_regulated_pure_pursuit_controller`, costmaps, map server and waypoint follower.
  - Local `scripts/start_competition.sh` references `scripts/camera_relay_docker.py` and `scripts/depth_relay_docker.py`, but these files are absent in the current local working tree and present on `origin/main`; local branch synchronization is a practical risk.
- Technical correction:
  - In Nav2, NavFn/Smac are global planners, DWB/RPP/MPPI are controller plugins, and the smoother server is a separate component. DWB should not be described as a generic "smoother" feeding RPP in a serial chain.
  - A normal Nav2 chain should be one global planner -> optional smoother -> one controller plugin -> optional velocity smoother/collision monitor.
- External source summary:
  - Nav2 docs describe the system as modular servers/plugins for planning, control, behavior, smoothing, costmaps and behavior trees.
  - Nav2 tuning guidance separates exact path tracking from local trajectory optimization: Regulated Pure Pursuit is best when the robot should stay close to the path; DWB/DWB-like local planners can score and deviate based on local costs.
  - Nav2 NavFn supports A* via `use_astar`, and Smac Planner provides more modern 2D/hybrid/lattice planning options in newer Nav2 stacks.
  - NVIDIA Isaac ROS Visual SLAM/cuVSLAM plus nvblox plus Nav2 is the authoritative "vendor-supported" family for visual navigation on Jetson, but the clean version is to keep Nav2/nvblox in the same ROS distribution/container, not split Humble plugins into a Foxy host process.
- Working conclusion:
  - The most practical current competition route is to keep the already-working odometry bridge and current lightweight A* + Pure Pursuit stack, then add only the minimum obstacle safeguard needed for the random cone area.
  - If returning to Nav2, prefer `A*/Smac -> optional smoother -> RPP or MPPI`, not `A* -> DWB -> RPP`. On Foxy/Xavier NX, full Nav2 should be treated as a secondary branch unless CPU, launch compatibility and costmap inputs are proven on the robot.

## Stonefield Real-Loop Probe Sync — 2026-07-09
- SSH authorization to Jetson is restored for `superwfx666@100.126.48.49`; `BatchMode=yes` connections now succeed.
- Active real-loop worktree is `/home/superwfx666/quadruped-robot-competition-nav2-dwb` on branch `Stonefield/nav2-foxy-dwb-integration`.
- Local and remote contents match for the four real-loop files by SHA256:
  - `src/nodes/navigation/cmd_vel_bridge.py`
  - `scripts/lite3_udp_smoke.py`
  - `scripts/odom_direction_probe.py`
  - `scripts/depth_safety_gate_probe.py`
- `depth_safety_gate_probe.py` is not ignored by Git in the Stonefield worktree; it is currently an untracked file and must be explicitly staged later if these probe tools are committed.
- Safe next execution order remains: dry-run Lite3 UDP script, then only with explicit user confirmation run `--armed`; separately run `/odom` direction probe after cuVSLAM/final bridge is live, and depth safety gate after Docker depth relay is live.

## Stonefield Odom Direction Probe — 2026-07-10
- Jetson -> Lite3 UDP low-level motion was confirmed by user现场复测：`--armed` smoke makes the robot move.
- With cuVSLAM robot mount + Host final bridge active, sending positive Lite3 forward command (`vx=+0.03` for 1s) produced Host `/odom` delta `dx=-0.0398m`, `dy=+0.0017m`, `dyaw=+0.22deg`.
- This means the current Host `/odom` forward axis is opposite to the positive forward command convention expected by Nav2/cmd_vel.
- Before enabling Nav2 `/cmd_vel` bridge for closed-loop navigation, fix or explicitly compensate the odom frame/sign convention; otherwise the controller will close the loop in the wrong direction.
- Test cleanup was completed: cuVSLAM container, final bridge, and wrapper script processes were stopped after the probe.
- Implemented fix in `scripts/final_bridge.py`: default `--rotate-odom-z-pi` applies `T_fixed = Rz(pi) * T_raw` before publishing Host `/odom` and TF; `--no-rotate-odom-z-pi` is available for rollback.
- Verification after fix: positive Lite3 forward command (`vx=+0.03` for 1s) produced Host `/odom` delta `dx=+0.0268m`, `dy=-0.0100m`, `dyaw=+0.52deg`; the forward-axis sign is now correct for Nav2. Longer straight-line validation can be used later to quantify lateral drift.

## Stonefield Nav2 Dry-Run After Odom Fix — 2026-07-10
- Full `Rz(pi)` pose compensation fixed positive `dx` but rotated orientation too, making `map->base_link` yaw about `0°`; DWB then produced angular-only `/cmd_vel`. This is not suitable for the competition start pose, which expects yaw about `180°` facing left (-x).
- Final bridge behavior is translation-only by default: `--flip-odom-xy` flips X/Y position while preserving raw orientation. Optional `--rotate-odom-z-pi` remains available but is not default.
- With translation-only flip, `map->base_link` yaw returns to about `180°`, `/plan` probe succeeds with 46 points and path length about `0.585355m`, and clean `/cmd_vel` probe succeeds with `cmd_count=76`, `nonzero_count=76`, `max_linear_x=0.22m/s`.
- `nav2_goal_plan_probe.py` auto-cancel can interfere with a subsequent cmd_vel probe in the same Nav2 session. For evidence collection, run plan and cmd_vel probes in separate clean Nav2 sessions or later adjust probe cleanup behavior.
- Host `depth_publisher` still fails when cuVSLAM owns the D455. Dynamic obstacle/safety must use Docker depth relay or a single-camera-owner path.

## Stonefield Live Loop First Trial — 2026-07-10
- Low-speed live loop with `enable_cmd_vel_bridge=true` reached the real control stage: cmd_vel_bridge initialized Lite3 UDP and Nav2 accepted the waypoint.
- The command stream was nonzero (`cmd_count=121`, `nonzero_count=120`, `max_linear_x=0.10m/s`), so the Nav2-to-Lite3 execution path is active.
- The run did not complete successfully: Nav2 reported the robot out of the global costmap (`worldToMap failed: mx,my: 228,31` on a `226x240` map) and canceled the goal.
- This likely means the robot moved/localized toward the map +X/right boundary during live control, despite the intended target being forward-left from the start. Before another 0.5m run, use a shorter 0.15-0.20m target and record `map->base_link` over time to verify actual motion direction.
- The angular limit also needs verification: config says `max_vel_theta=0.15`, but the probe observed `max_abs_angular_z=0.45rad/s`.

## Stonefield Live Loop Retest After Moving Robot Into Map — 2026-07-11
- Retesting the same 0.5m target after the user moved the robot into the mapped area did not solve the failure.
- Before goal dispatch, `map->base_link` was approximately `(x=5.334, y=0.753, yaw≈180°)`, so the robot was inside the map but still very close to the right boundary of the 226-cell map: `226 * 0.025 = 5.65m`, leaving only about `0.32m` margin in +X.
- The repeated goal `(4.85, 0.75, yaw=0)` was accepted and produced bounded commands: `max_linear_x=0.10m/s`, `max_abs_angular_z=0.15rad/s`. Unlike the previous run, the observed angular command did not hit `0.45rad/s`.
- Nav2 still reported `Robot is out of bounds of the costmap` and `worldToMap failed: mx,my: 227/228,31, size_x,size_y: 226,240`, then triggered recovery `spin` before cancellation.
- After the run, `map->base_link` was approximately `x=5.75~5.78, y=-0.12`, outside the generated map. This points to a remaining localization/control-frame or initial-map-boundary problem, not merely "the robot started outside the map."
- Next technical step should be a non-goal or ultra-short controlled test that records `map->base_link` while sending a tiny known forward command, verifying whether physical forward motion from yaw≈180° decreases ROS map X as expected. Avoid repeating the 0.5m Nav2 goal until this sign/direction check is resolved.

## Nav2 Boundary Safety Follow-up — 2026-07-11
- The active `Stonefield/nav2-foxy-dwb-integration` worktree already has valid rectangular footprints in both costmaps: `[[0.50,0.25], [0.50,-0.25], [-0.50,-0.25], [-0.50,0.25]]`. The duplicate final vertex reported in the review is not present in the file that Nav2 launches.
- Recovery Spin remained configured at `0.45rad/s`, independently of DWB `max_vel_theta=0.15`; it is a credible source of the observed `0.45rad/s` angular command. It is now limited to `0.15rad/s` max, `0.05rad/s` min, and `0.4rad/s^2` acceleration while preserving the default BT recovery plugin contract.
- Added `scripts/map_base_link_trace.py` in the Nav2 worktree. It sends no robot command, samples `map -> base_link`, and writes a CSV plus summary including x/y/yaw deltas for the next live-loop diagnosis.
- Windows static verification passed Python bytecode compilation and Python 3.8 AST parsing. Runtime TF validation must occur on the Jetson because this Windows workspace has no `rclpy` installation.
- Synced the parameter file and trace script to `/home/superwfx666/quadruped-robot-competition-nav2-dwb` without starting Nav2 or commanding Lite3. On Jetson, `python3` outside the ROS environment cannot import `rclpy`; after `source /opt/ros/foxy/setup.bash`, the trace script compiled and displayed its CLI help successfully.

## Jetson Live-Loop Attempt — 2026-07-11
- The Jetson had no active cuVSLAM, final bridge, or Nav2 process at the start. No motion command was sent before localization readiness.
- Two cuVSLAM starts were attempted with `CUVSLAM_MOUNT_MODE=robot`, `CUVSLAM_PROFILE=planar_60fps`, no cuVSLAM-published `map->odom` or `odom->base_link` TF. The second attempt increased `WAIT_SECONDS` from 90 to 180.
- Both attempts timed out waiting for `/visual_slam/status` and automatically stopped their containers. The second log contains persistent image deltas around 33ms (with occasional 50-150ms), above `CUVSLAM_IMAGE_JITTER_THRESHOLD_MS=22`.
- The direct host D455 test `scripts/camera/realsense_cuvslam_input_test.py --seconds 2` passed RGB+depth, IR stereo+depth, accel+gyro, and `RealsenseCamera.for_cuvslam`. This separates current input availability from the cuVSLAM status-publication failure.
- Because `/visual_slam/status` and resulting host `/odom` never became available, final_bridge, Nav2, map trace, and the live `x=5.20, y=0.75, yaw=pi` goal were deliberately not started. Lite3 received no new velocity command in this attempt.
- Follow-up checks rule out the proposed USB2/RGB explanation: `lsusb -t` shows every D455 video interface at `5000M`, and the launch remaps cuVSLAM to IR1/IR2 at `640x360@60`, not the RGB `1280x720@30` stream. The Jetson is in `MODE_20W_6CORE`, not a highest-performance mode, which remains a performance variable but is not proof of cause.
- A third startup used `CUVSLAM_IMAGE_JITTER_THRESHOLD_MS=45.0`. It still timed out waiting for status; the visual-SLAM log continued to show 50-350ms gaps as well as 33ms gaps. Raising the threshold therefore did not restore odometry and must not be treated as a sufficient fix.

## Correction From Later Live Retest — 2026-07-11
- The prior inference that missing `/visual_slam/status` prevented a usable cuVSLAM odometry chain was incorrect. In the later field retest, keeping `WAIT_SECONDS=600` allowed the container to remain alive; `final_bridge.py` received Docker `/visual_slam/tracking/odometry` and continuously published Host `/odom` (`bridged XXXX UDP msgs`).
- With Nav2 active, `initial_pose_publisher` supplied `map -> odom`; before motion, `tf2_echo map base_link` reported approximately `x=5.334`, `y=0.753`, `yaw=180deg`. A live goal was accepted and `/cmd_vel` reached Lite3.
- The observed `max_abs_angular_z=0.15rad/s` confirms the recovery Spin limit change removed the earlier `0.45rad/s` behavior. The live failure was instead an out-of-bounds pose: after motion, TF reported about `x=5.75-5.78`, `y=-0.12`, beyond the 5.65m right map boundary, followed by costmap failure and cancellation.
- Correct priority: repair the status-based startup health check separately, but diagnose the live-loop failure through a very short open-loop direction test, a target orientation matching the current `yaw=pi`, and greater map-edge margin. Do not repeat the prior 0.5m goal as the next test.

## Open-Loop Direction Probe — 2026-07-11
- Recreated the usable odom path with `WAIT_SECONDS=600`: cuVSLAM container -> `final_bridge.py` -> UDP exporter. Bridge logged continuous packets and wrote `/tmp/odom_latest.json`. No Nav2 goal or cmd_vel bridge was used for the direction probe.
- Direct TF diagnosis found `map -> odom` present at `(5.35, 0.75, yaw=pi)`, but `odom -> base_link` was not discoverable from another TF listener. Despite final_bridge source calling `TransformBroadcaster.sendTransform`, `map -> base_link` could not be resolved. This dynamic TF visibility failure is separate from the bridge's own /odom self-verification.
- Enhanced `scripts/map_base_link_trace.py` to report each TF leg and, when TF/DDS odometry is unavailable to the recorder, read final_bridge's `/tmp/odom_latest.json` snapshot and compose it with the known map->odom transform.
- The first `vx=0.02m/s` for 1s sample showed only sub-micrometer-scale map delta. A second `vx=0.03m/s` for 1s sample still showed only `delta.x=+0.000061m`, `delta.y=-0.000031m`, far below the expected centimeter-scale displacement and in the wrong x sign for a confident forward-left conclusion. Do not authorize the Nav2 short goal from this data.
- Cleanup completed after the probe: Nav2, final_bridge, the current cuVSLAM wrapper, and its named Docker container were stopped. The bridge's exporter also previously exited when the status-wait script cleaned up its container (exit code 137), so status health check handling remains relevant.
## 2026-07-11 — cuVSLAM / TF 权威资料复核与纯软件隔离结论

- NVIDIA Isaac ROS Visual SLAM `release-2.1` 官方 RealSense launch 明确采用 D455 双目 IR `640x360x90`、IMU 200 Hz，关闭 color、depth 和 emitter，`img_jitter_threshold_ms=22.0`。当前自定义 launch 同时启用 color/depth，偏离官方基准，应优先回归官方输入组合，而不是先放宽 jitter 阈值。
- NVIDIA 官方 troubleshooting 要求：先用 `ros2 topic hz --window 100 <image_topic>` 验证输入帧率是否等于 launch 配置；频繁 tracking lost 时检查运动模糊、低照度、错误 camera_info、推荐的 firmware/realsense_ros、官方 RealSense 参数、关闭 emitter，并确保左右图像是 raw 未压缩数据。
- NVIDIA 官方实机 VSLAM 验证使用直线人工移动 1m，平移验收范围 `0.95m <= ||t|| <= 1.05m`，方向误差小于 15 度。此前 2-3cm 低速脉冲不足以作为官方精度或方向验证。
- ROS 2 Foxy `TransformBroadcaster.sendTransform()` 源码直接调用 `/tf` publisher 的 `publish()`；没有“必须 executor spin 才能发送 TF”的实现依据。
- ROS 2 Foxy 官方文档确认：不同 `ROS_DOMAIN_ID` 的节点不能相互发现，同一组进程必须使用相同 domain。NVIDIA 验证文档也要求每个终端一致设置该变量。
- 2026-07-11 在 Jetson 上用未加 heartbeat 的原版 `final_bridge.py` 做纯软件跨进程测试：发送 125 个假 UDP odometry，外部 probe 收到 125 个 `/odom`，成功 lookup `odom->base_link` 493 次，返回码 0。结论：bridge 的跨进程 DDS 和 TF 发布路径本身正常；此前 TF 不可见不是 UDP 循环饿死、缺 heartbeat 或 TransformBroadcaster QoS 的固有 bug，应转查当次启动环境、进程生命周期和 domain/RMW 配置。
- 权威来源：
  - https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/blob/release-2.1/isaac_ros_visual_slam/launch/isaac_ros_visual_slam_realsense.launch.py
  - https://nvidia-isaac-ros.github.io/repositories_and_packages/isaac_ros_visual_slam/isaac_ros_visual_slam/index.html
  - https://nvidia-isaac-ros.github.io/concepts/visual_slam/cuvslam/validating_cuvslam_setup.html
  - https://github.com/ros2/geometry2/blob/foxy/tf2_ros/src/tf2_ros/transform_broadcaster.py
  - https://docs.ros.org/en/foxy/Concepts/About-Domain-ID.html

### Jetson 官方基准实测补充

- 直接运行 Jetson 已安装的 NVIDIA `isaac_ros_visual_slam_realsense.launch.py`，官方 profile 实际打开 IR1/IR2 `640x360@90`、Accel/Gyro `200Hz`，USB 为 3.2，RealSense ROS/librealsense 为 4.54.1/2.54.1，D455 固件为 5.17.0.10。
- 使用 `qos_profile_sensor_data` 独立订阅 10 秒：IR1 `89.45Hz`（899 帧）、IR2 `89.35Hz`（897 帧）、合并 IMU `180.02Hz`（1798 条）。因此相机没有从 90FPS 自动降到 30FPS，先前“33ms 说明 D455 实际只出 30FPS”的判断已被实测否定。
- 官方完整 launch 静止运行时成功发布 odometry：约 34.4 秒记录 148 个 odom 样本，`tracking_lost=0`；同一日志仍有 203 条 `Delta between current and previous frame` warning。该 warning 可与可用 odometry 同时存在，不能作为 cuVSLAM 死锁或相机 30FPS 的单独证据。
- NVIDIA Developer Forum 版主说明 jitter warning 可能来自硬件没有给 VSLAM 节点足够运行时间，应检查电源、GPU/GPU memory 和相机要求；这是次级支持，优先级低于官方文档和本机实测。
- 现阶段最符合证据的解释：33ms/更大 delta 出现在 cuVSLAM 消费/调度链路，而不是 D455 物理输出链路。应保留 `22ms` 基准，先减少自定义 launch 的非必要 color/depth 流并检查 Jetson 资源，不用 `45ms` 掩盖 warning。
- 补充来源：https://forums.developer.nvidia.com/t/image-jitter-threshold-ms-parameter-of-isaac-ros-visual-slam/313716

### 自定义 robot-base A/B 边界

- 部署 color/depth 默认关闭、odometry-first 健康检查后，`robot + planar_60fps + input_left_camera_frame=camera_link` 在 180 秒内仍无 `/visual_slam/tracking/odometry`；日志显示 tracker 创建成功、316 条 delta warning、0 次 tracking lost、0 次 odometry mention。
- 保持 robot frames，切换为 `official_like`（90FPS、非 planar）仍在 140 秒内无 odometry，排除 60FPS/force-planar 是唯一根因。
- 依据 NVIDIA release-2.1 dual RealSense launch，将 left frame 定点改为 `camera_infra1_frame` 后仍无 odometry。连续三次定点 A/B 均失败，按停止规则不再继续猜参数。
- release-2.1 源码确认 `base_frame`、`input_base_frame`、`input_left_camera_frame` 均为正式支持参数；但当前自定义 robot-base 组合未达到可用状态。生产路径应暂时回到已验证的 NVIDIA 官方 camera-link launch。
- 官方 camera-link odometry 若供 Nav2 使用，必须通过 `T_odom_base = T_odom_camera * inverse(T_base_camera)` 的标准刚体关系转换；直接把 camera pose 的 frame 名改成 `base_link` 在语义上不成立。

## 2026-07-11 — 历史 robot 轨迹与当前 final_bridge 回归定位

- 用户此前“相机固定在狗身上、遥控走一圈、CSV 绘图良好”的记录已找到：`技术报告/cuvslam_csv/20260706-150429/`。
- 该记录不是 bench camera-link 模式，而是 `mount_mode=robot`、`expected_base_frame=base_link`、`robot_base_ready=true`；原始 `/visual_slam/tracking/odometry` 和 `/visual_slam/vis/slam_odometry` 的 `child_frame_id` 均为 `base_link`。
- 该轮 recorder 记录 3212 个 odometry 样本，XY 路径约 `61.29m`；这证明当时 cuVSLAM robot 模式和相机固定安装条件下确实能输出可用的本体轨迹。
- 仓库中已经存在正确刚体转换实现 `src/nodes/navigation/cuvslam_bridge.py`：当输入 child 是 `camera_link` 时执行 `T_odom_base = T_odom_camera * inverse(T_base_camera)`，当输入已经是 `base_link` 时直接透传，避免重复转换。历史回调测试验证 identity camera pose `(1,2,3)` 转换为 base pose `(0.684218,2.0,2.61305)`。
- 当前 `scripts/start_competition.sh` 并不启动上述 `cuvslam_bridge`，而是直接启动 UDP `scripts/final_bridge.py`。这是因为 Docker Humble 到 Host Foxy 改用了 UDP 桥接，但刚体转换/输入 frame 判定没有随架构迁移过去。
- `final_bridge.py` 当前无条件把输出 frame 写成 `odom/base_link`。2026-07-10 后又加入默认 `flip_odom_xy=true`，只把 position X/Y 取反，orientation 保持不变；这不是合法 SE(3) 刚体变换，会使位姿平移方向与姿态不一致。
- 时间线支持回归判断：优秀 robot CSV 采集于 2026-07-06；默认 translation-only flip 是 2026-07-10 为短方向 probe 后加入；随后 live Nav2 出现朝地图边界运动并 out-of-bounds。
- 修复优先级：先禁用 translation-only flip，恢复 robot-mode `base_link` 原始 odometry 透传；随后把 `cuvslam_bridge.py` 已验证的 frame-aware camera-to-base 逻辑迁移进 UDP final bridge，确保 camera 输入转换、base 输入透传且绝不重复转换。

### UDP final bridge 修复结果

- 已从 `scripts/final_bridge.py` 删除 `flip_odom_xy`、`no-flip-odom-xy` 和 `rotate_odom_z_pi` 相关半套坐标补偿。
- 已迁移旧 `cuvslam_bridge.py` 的四元数、位姿和 twist 刚体转换逻辑，并基于 UDP payload 的 `child_frame_id` 严格分流：
  - `base_link` -> `base_passthrough`
  - `camera_link` -> `camera_to_base`
  - 空或未知 frame -> 丢弃并告警
- 数值探针通过：base pose `(1,2,3)` 完全透传；identity camera pose `(1,2,3)` 转成 base pose `(0.68421788,2.0,2.61304955)`，与旧 bridge 历史测试一致；未知 frame 被拒绝。
- Jetson 正式部署后跨进程测试通过：102 个假 UDP 包全部收到 `/odom`，TF lookup 成功 399 次，日志明确为 `source_child=base_link mode=base_passthrough`。
- 正式 Jetson `final_bridge.py` SHA256：`c4bd01a024afd4ff476f0eeb644fc3f2ff2b21442402c49b40df64ce17a91236`。

### 2026-07-11 趴地拖行对照结论

- 最新真实拖行 CSV：`技术报告/cuvslam_csv/20260711-194155-live-infra1-drag/final_bridge_odom_compare_infra1.csv`。
- 本轮输入仍是 `source_frame_id=odom`、`source_child_frame_id=base_link`，`transform_mode=base_passthrough`；raw 与 Host 最大位置误差为 `0`，四元数分量误差仅约 `2.96e-8`。
- 用户说明本轮机器狗是趴着被手动向前拖行，没有遥控或电机行走，因此这是定位链路的被动平移验证，不含 Nav2 或 Lite3 控制闭环。
- 运动段 Host 位移为 `dx=+0.642227m`、`dy=-0.042903m`、`dz=+0.589783m`，yaw 仅变化约 `-0.299deg`。XY 平面距离约 `0.643658m`，3D 距离约 `0.873007m`。
- X/Z 相关系数 `0.998519`，说明前向拖行几乎同步投影到了 Z 轴；这不是 UDP bridge 的 X/Y flip 回归，也不是重复 camera-to-base 转换造成的，因为本轮全程 base passthrough。
- 对 Nav2 平面导航而言，当前 `base_link` odometry 不能直接恢复 live goal。下一步应核查 cuVSLAM robot/base 参数、`base_link -> camera_*` 静态外参、D455 实际安装 pitch/朝向，以及是否应临时使用官方 camera-link odometry 加旧 bridge 的刚体转换路径作为导航输入。

### base_link -> camera_link pitch 符号结论

- Lite3 公开 URDF 没有单独 `base_link`，根链路为 `TORSO`；当前导航栈将 `base_link` 作为 `TORSO` 等价 frame 合理。
- D455 官方 xacro 中 `camera_link` 是相机机身 frame；`camera_infra1_frame` 的父 frame 是 `camera_link`，平移/旋转为零；`camera_infra1_optical_frame` 才应用 `rpy(-pi/2,0,-pi/2)`。
- 因此外参里的 30 度俯仰应施加在 `base_link -> camera_link`，不能混入 optical frame 的旋转。
- 按 ROS fixed-axis RPY，`pitch=-0.523599` 会让 `camera_link` 的 X 轴上仰 30 度；相机实际向下看 30 度应为 `pitch=+0.523599`。
- 修正后 `base_link -> camera_link` 四元数为约 `(qx=0, qy=+0.258819, qz=0, qw=0.965926)`；`competition.launch.py` 已同步使用该四元数。
- 这能解释 cuVSLAM robot/base 输出出现明显 X/Z 投影的方向性问题。下一轮验收应只启动 cuVSLAM + final_bridge，让用户再次手动直线拖行，期望 XY 位移仍为 0.5-1m 量级但 Z 变化显著下降；未验证前继续禁止 Nav2 live goal。

### pitch 修正后 robot-mode 无 odometry 的潜在原因 — 2026-07-11

- 已联网复核 NVIDIA Isaac ROS Visual SLAM 文档、cuVSLAM validating setup 和 release-2.1 官方 RealSense launch。官方基准仍是先验证 D455 输入、topic rate、camera_info、raw IR 图、固件/驱动、光照/模糊，再做 1m 人工移动验证；当前 D455 输入短测 PASS，但 robot-mode 没有发布 `/visual_slam/tracking/odometry`。
- `base_link -> camera_link` pitch 改号本身不应让 ROS launch 失败；更可能的机制是：cuVSLAM 在 robot mode 需要通过 TF 在 `input_base_frame`、`input_left_camera_frame`、IMU frame 与 `base_frame` 之间建立一致树。pitch 改号后若实际安装方向、传感器 frame 或 `static_transform_publisher` 参数顺序有一处不一致，VSLAM 可能完成 node 初始化但不进入 tracking/odometry 输出。
- 当前 robot 模式还有一个变量：`input_left_camera_frame` 已设为 `camera_infra1_frame`，而历史可用记录与当前脚本版本之间可能不完全一致。由于 `camera_link`、`camera_infra1_frame`、optical frame 的语义差别很小但关键，下一轮应做最小 A/B：只变 pitch；保持历史可用的 left camera frame 与 profile 不变。
- 狗下位机不是 cuVSLAM 直接依赖。cuVSLAM odometry 主要依赖 D455 IR/IMU、RealSense ROS、TF 和容器算力。狗重启若改善问题，通常是间接原因：供电、电磁/USB 状态、CPU/GPU 负载、后台进程、相机占用或机身姿态/稳定性改变。
- 解决策略优先级：1) 先恢复官方 camera-link launch，确认基础 cuVSLAM 仍能出 odom；2) 从历史可用 robot 启动配置做单变量回滚/前滚；3) 对比 `view_frames`/`tf2_echo base_link camera_link` 和生成 launch 文件，确认静态 TF 数值与参数顺序；4) 若 robot mode 继续不出 odom，走官方 camera-link odometry + Host bridge 刚体转换，避免让 cuVSLAM 自己处理 robot-base frame。

### 官方 camera-link + Host camera-to-base 验证结论 — 2026-07-11

- 官方 camera-link cuVSLAM baseline 能发布 `/visual_slam/status` 和 `/visual_slam/tracking/odometry`；因此 D455、官方 RealSense launch、Isaac ROS Visual SLAM runtime 本身不是当前阻塞点。
- Host `final_bridge.py` 可正确接收官方 camera-link odometry 并走 `camera_to_base` 分支；本轮 3882 条样本全部为 `source_child=camera_link`、`transform_mode=camera_to_base`。
- 但是拖行结果仍有显著 Z 投影：raw camera 全段 `dist_xy=1.460962m`、`dz=0.460827m`、`corr_xz=0.994519`；Host base 全段 `dist_xy=1.493099m`、`dz=0.519918m`、`corr_xz=0.997005`。
- 这说明单纯把 camera pose 通过固定外参转换到 base pose，并不能消除 cuVSLAM 估计中的前向/Z 轴耦合。问题更像是视觉里程计输出坐标系/场地平面约束/机身姿态估计在导航平面上的投影问题。
- Nav2 live goal 仍应暂停。更稳的导航输入路线是：将 cuVSLAM 作为视觉里程计来源，但在 Host 侧生成平面化 `odom -> base_link`：保留 XY 和 yaw，抑制 Z/roll/pitch；或接入 `robot_localization` 的 `two_d_mode`，以 IMU/腿部里程计辅助稳定 yaw 与平面位姿。

### 站立启动复测对重力初始化假设的影响 — 2026-07-11

- 站立状态下启动官方 camera-link cuVSLAM 并通过 Host `camera_to_base` 转换后，X/Z 耦合没有下降：Host base `dist_xy=1.611164m`、`dz=0.881972m`、`corr_xz=0.999959`、`dz/dist_xy=0.547413`。
- 与趴地拖行的 Host base `dist_xy=1.493099m`、`dz=0.519918m`、`corr_xz=0.997005`、`dz/dist_xy≈0.348` 相比，站立复测的 Z 泄漏比例更高。
- 因此“启动瞬间狗趴着导致 gravity alignment 偏差”不是充分解释；它仍可能影响结果，但不是当前唯一主因。更强嫌疑转向：D455 IMU/视觉内部标定、场地视觉平面/低视角几何、实际推动过程机身 pitch 变化、或 cuVSLAM 输出坐标系与导航平面之间需要显式平面约束。
- 工程决策不变：比赛链路不应继续等待原始 3D odom 变干净，应尽快实现 planar odom / EKF `two_d_mode`；硬件/标定排查作为并行长期项。

### camera-start world rebase + planar odom 结论 — 2026-07-11

- 倾斜安装 D455 不要求因为安装角本身重做相机内部标定；关键是不能把官方 camera-link cuVSLAM 的 camera-start world 直接当作机器人水平 odom world。
- 已验证新 Host bridge 处理链路：官方 camera-link odometry -> `camera_world_rebase=base_start` -> `camera_to_base` -> `planarize_output`。该链路使 camera 起点输出为 base 原点，并将 Nav2 不需要的 Z/roll/pitch 清除。
- 实测 raw camera 仍存在 Z：`dist_xy=1.143106m`、`dz=0.346589m`、`corr_xz=0.941022`；但 Host rebase+planar 输出为 `dist_xy=1.144117m`、`dz=0`、`z_span=0`。
- 这证明问题可以在 Host 侧工程处理，不必先陷入 D455 标定/IMU 对齐排查。长期仍可做 RealSense health check 和 IMU calibration，但比赛导航应使用 rebase+planar/EKF 路线。
- 下一步风险点是 TF 单一发布者：若 `final_bridge.py` 直接发布 `/odom` + `odom -> base_link`，则 EKF `publish_tf` 应为 false；若要让 EKF 输出最终 TF，则 bridge 应发布中间 topic（例如 `/visual_odom_planar`）且不发布 `odom -> base_link`。

### Stonefield Nav2 planar dry-run 结论 — 2026-07-12

- 当前最稳短期 TF 架构是：Docker cuVSLAM 使用 camera-link 输出 `/visual_slam/tracking/odometry`；Host `final_bridge.py --camera-world-rebase base_start --planarize-output` 负责 camera-to-base、world rebase 和 planarize，并直接发布唯一 `/odom` 与 `odom -> base_link`。EKF 暂缓，避免第二个 `odom -> base_link` 发布者。
- `start_competition.sh` 不应默认启用 `task_manager` 或 `auto_advance`。实测未带 `--dog` 时 task_manager 仍会自动发任务 goal，使 recoveries_server spin 约 120 秒；若未来带 `--dog`，这种默认行为会变成真实运动风险。任务状态机应通过显式 `--task-manager` 或 `--auto-advance` 启用。
- Host `depth_publisher` 不应随 Nav2 默认启动。D455 已被 Docker/cuVSLAM 占用时，Host depth publisher 会直接打开设备并报 `xioctl(VIDIOC_S_FMT) failed, errno=5`；动态障碍/深度安全应走 Docker depth relay 或后续独立链路。
- 最终 dry-run 证据：`map -> base_link` 在地图内且 `z=0`，约 `(5.351, 0.751, yaw=pi)`；Nav2 lifecycle 全 active；0.22m、`yaw=pi` goal 输出 `/cmd_vel` 为 `max_linear_x=0.10m/s`、`max_abs_angular_z=0.0079rad/s`，没有复现原地转圈型输出。此前 0.15m goal 只出角速度，原因更可能是目标距离等于 `xy_goal_tolerance=0.15`，Nav2 认为位置已到而只做 yaw 对齐。
- `/plan` 对同一 0.22m goal 生成 17 点、约 `0.230m` 路径。下一步 live 验证仍应从 0.15-0.20m 上架/低速开始，不能直接恢复 0.5m live goal。

### Stonefield 0.18m live 尝试结论 — 2026-07-12

- Stonefield 当前没有构建好的 `Lite3_ROS-ros2-foxy/install/setup.bash`，因此 `--dog` 默认路径无法启动 transfer driver；若不显式启用 fallback，Nav2 `/cmd_vel` 不会到 Lite3。
- 已新增 `start_competition.sh --cmd-vel-bridge` 显式 fallback。该路径由 launch 内 `cmd_vel_bridge_node` 订阅 `/cmd_vel` 并直接发送 UDP 到 `192.168.1.120:43893`；默认仍关闭，避免误下发。
- 0.18m、`yaw=pi` live 尝试中，Nav2 命令形态是安全的：40 条非零 `/cmd_vel`，最大线速度 `0.0733m/s`，最大角速度 `0.0079rad/s`，没有复现原地转圈型大角速度。
- 但定位侧没有观测到可见位移：`map->base_link` 和 `/tmp/odom_latest.json` 在 goal 前后仍接近起点。这可能意味着狗没有实际移动、移动太小/太短而 cuVSLAM 未反映，或 Lite3 UDP/姿态模式未真正执行 MotionComplexCMD。
- 下一步不应扩大到 0.3m/0.5m。应先由现场确认是否有轻微物理移动；若无，优先用 `lite3_udp_smoke.py --armed` 或独立 `cmd_vel_bridge` 小速度直发验证 Lite3 命令链路，再回到 Nav2 live。

### cmd_vel_bridge 自动初始化姿态风险 — 2026-07-13

- 现场反馈显示：狗原本已站立，但启动 `--dog --cmd-vel-bridge` 后自己趴下；这不是电池没电，也不是 Nav2 goal 后的移动问题，因为本轮没有发送导航目标。
- 日志确认 `/cmd_vel_bridge_node` 启动时默认 `init_dog=True`，会发送 heartbeat、`CMD_AUTO_MODE=0x21010C03` 和 `CMD_MOTION=0x21010D06`。该初始化序列虽然不包含 `lite3_init.py` 的 `CMD_STAND_UP=0x21010202` toggle，但仍可能改变 Lite3 当前姿态/控制模式。
- `lite3_init.py` 的 `CMD_STAND_UP=0x21010202` 明确是 toggle：站立时发送会趴下，趴下时发送会站起。任何自动启动流程都不能默认发送该命令。
- 后续复测发现，仅关闭 `init_dog` 还不够：旧 `cmd_vel_bridge` 即使未收到 Nav2 goal，也会定频发送 heartbeat + `FWD 0.0`；该空闲 UDP 输出也可能影响 Lite3 当前姿态。
- 安全决策：fallback `cmd_vel_bridge` 默认不再自动初始化狗；新增显式 `cmd_vel_bridge_init_dog` / `--bridge-init-dog`，只有现场明确需要切入 auto/motion 时才使用。同时 bridge 启动后必须静默，直到收到第一个非零 `/cmd_vel` 才发送 UDP；收到命令后超时只短暂发 stop，再恢复静默。
- Jetson fake-IP 回归：`dog_ip=127.0.0.1` 时，空闲期 UDP 包数为 `0`；发布非零 `/cmd_vel` 后才出现 UDP 包。下一轮 live 目标前，必须先由现场确认狗已稳定站立，并避免把启动初始化和 Nav2 goal 放在同一个未知变量里。

### cmd_vel_bridge 诊断仪表化结论 — 2026-07-14

- 单看 Nav2 probe 采到 `/cmd_vel` 不能证明 Lite3 收到了命令；必须同时验证 `cmd_vel_bridge` 是否在同一 `ROS_DOMAIN_ID`/`RMW_IMPLEMENTATION` 下订阅 `/cmd_vel`，以及是否实际发送 UDP。
- 已给 `cmd_vel_bridge.py` 增加节流诊断日志，核心字段包括：`recv`、`motion`、`ignored_zero`、`send_ticks`、`stale_ticks`、`udp_simple`、`udp_complex`、`udp_errors`、`last_recv`、`last_send`、`seen_motion`。
- 启动日志现在会打印 `ROS_DOMAIN_ID`、`RMW_IMPLEMENTATION` 和 `FASTRTPS_DEFAULT_PROFILES_FILE`，用于复查历史上“bridge ready 但 `/cmd_vel` subscription count 为 0”的 domain/RMW 不一致问题。
- Jetson `dog_ip=127.0.0.1` 回归证明：在 `ROS_DOMAIN_ID=77`、`RMW_IMPLEMENTATION=rmw_fastrtps_cpp` 一致时，bridge 对 `/cmd_vel linear.x=0.05` 可形成接收和 UDP 发送计数，且 `udp_errors=0`。
- 下一轮真机判据：
  - 若 Nav2 probe 有 `/cmd_vel` 但 bridge `[diag] recv=0`，优先查 ROS domain/RMW、launch 继承环境、节点是否在同一图。
  - 若 `recv>0` 但 `udp_complex=0` 或 `udp_errors>0`，优先查 bridge gating、socket/目标地址。
  - 若 `recv` 与 `udp_complex` 都正常但狗不动，优先查 Lite3 motion mode、`CMD_AUTO_MODE`/`CMD_MOTION` 初始化状态、MotionComplexCMD 形态或速度幅值。

### Nav2 0.5m clean single-shot 诊断结论 — 2026-07-14

- 本轮已排除 `/cmd_vel` subscriber 断链：`/cmd_vel` subscription count 为 1，subscriber 是 `/cmd_vel_bridge_node`，bridge 与 Nav2 同在 `ROS_DOMAIN_ID=0` / `rmw_fastrtps_cpp`。
- 本轮已排除 bridge 不发 UDP：0.5m Nav2 goal 期间，probe 采到 `121` 条 `/cmd_vel` 且全为非零；bridge 诊断达到 `recv=151`、`motion=150`、`udp_simple=607`、`udp_complex=607`、`udp_errors=0`。
- 本轮命令幅值并非纯零或纯转向：最大 `linear.x≈0.093m/s`，最大 `abs(angular.z)≈0.055rad/s`，bridge 最后发送值多次为 `(0.093, 0.000, -0.055)`。
- `/tmp/odom_latest.json` 在 goal 前后几乎不变，说明若现场没有看到物理移动，问题已下沉到 Lite3 侧执行状态；若现场看到物理移动，则问题转向 cuVSLAM/planar odom 对运动的观测。
- `bt_navigator` 仍出现历史 `send_goal failed`，但不是本轮“没有 UDP 下发”的原因：该错误前后 bridge 都在持续收到 `/cmd_vel` 并发送 UDP。后续仍需单独修 Nav2 action 稳定性，但当前阻塞优先级低于 Lite3 motion mode/命令执行验证。

### Lite3 高层速度控制握手门槛 — 2026-07-14

- 仅发 `/cmd_vel` 转成的 MotionComplexCMD 不足以让 Lite3 执行运动；即使 UDP 计数正常、官方三轴顺序 `320/325/321` 正常发送，狗也可能不动。
- 已验证可行握手顺序：heartbeat 预热 -> `0x21010C03` Auto/Nav mode -> heartbeat 等待 -> `0x21010D06` Motion mode -> heartbeat 等待 -> 官方三轴速度命令 -> 三轴零速 -> heartbeat 收尾。
- 握手脚本全程不发送 `0x21010202`，因为该命令是起立/趴下 toggle，不是“确保站立”。
- 用户现场反馈握手脚本后狗动了，因此当前最可信根因是：此前 Nav2/bridge 缺少模式准备握手，速度包到达但被下位机状态机门控丢弃。
- 设计决策：不要让 `cmd_vel_bridge` 默认自动切模式或发站立 toggle。应新增独立、显式的 Lite3 motion mode prepare 步骤；成功后再启动/启用 Nav2 速度转发。
- 已在 Stonefield worktree 新增 `scripts/prepare_lite3_motion_mode.py`，并在 `scripts/start_competition.sh` 中接入 `--prepare-lite3-motion` 显式开关。该开关默认关闭，且准备脚本默认不做前进测试，只做模式握手和零速收尾。

### Lite3 0.5m 直发运动闭环 — 2026-07-14

- `start_competition.sh --dog --cmd-vel-bridge --prepare-lite3-motion` 已证明模式准备脚本可在完整比赛栈内运行，且不触发起立/趴下 toggle。
- 握手准备后，通过当前 `cmd_vel_bridge_node` 直接发布 `/cmd_vel linear.x=0.05` 持续 10 秒，用户现场确认狗前进约 0.5m。
- 软件侧同时闭环：bridge 诊断 `udp_errors=0`，`/tmp/odom_latest.json` 显示 `x≈0.490m`、`y≈0.025m`、`z=0`。
- 因此底层速度链路已经成立：Lite3 状态机握手 -> `/cmd_vel` -> UDP -> 物理运动 -> planar odom。
- 当前新主问题是 Nav2 action/BT 链路：同一栈中 `NavigateToPose` goal accepted 后立刻出现 `bt_navigator send_goal failed`，导致 controller 未发布 `/cmd_vel`。这应作为下一阶段单独调试对象。

### Nav2 clean single-shot 规程复核 — 2026-07-15

- `bt_navigator send_goal failed` 不能单独视为新的 BT XML 或 action 链路缺陷；历史记录已证明 `/plan` probe 抓到路径后自动 cancel，若同一 Nav2 session 继续跑 `/cmd_vel` probe 或 direct FollowPath，可能造成 `send_goal failed`、`cmd_count=0` 或 bt crash。
- 最新复测在完整栈 `--dog --cmd-vel-bridge --prepare-lite3-motion` 下按严格 clean single-shot 执行：清残留、启动栈、只做 lifecycle/action/topic 轻量检查、不跑 `/plan`、不跑 direct FollowPath、只发一次 `NavigateToPose`。
- 0.5m goal `(x=4.85, y=0.75, yaw=pi)` 返回 `accepted=true`、`cmd_count=78`、`nonzero_count=77`、`max_linear_x=0.1m/s`、`max_abs_angular_z≈0.134rad/s`，软件 odom 从约 `x=-0.076` 到 `x=0.329`。
- 后续真机 Nav2 验证默认采用 clean single-shot 规程；只有在该规程下仍出现 `cmd_count=0 + send_goal failed`，才进入 BT/action server 深挖。
- 用户随后现场确认：0.5m clean single-shot Nav2 真机闭环已经 OK。因此该规程可作为后续直线 0.8-1.0m、分段小目标和场地航点测试的基线，不应再回退到混跑 `/plan` probe/direct FollowPath 的调试方式作为常规测试入口。

### Nav2 clean single-shot 1.0m 前进测试 — 2026-07-15

- 在 clean single-shot 规程下，当前 `map->base_link≈(5.371,0.771,yaw≈pi)` 时，向前 1.0m 对应地图目标约 `(4.371,0.771,yaw=pi)`，不是 x 增加 1.0m。
- 本轮 `NavigateToPose` goal accepted，18 秒采样内 `/cmd_vel` 输出稳定：`cmd_count=152`、`nonzero_count=151`、`max_linear_x=0.1m/s`、`max_abs_angular_z=0.15rad/s`。
- 停止后 planar `/odom` 显示约 `x=0.813m, y=0.026m, z=0`，说明 1.0m 目标没有退化成 0 命令或原地旋转，且定位侧观测到明显前进。
- 由于 `max_linear_x` 限制为 0.1m/s 且 probe 18 秒后会 cancel goal，实测位移小于完整 1.0m 可能来自加减速、Nav2 控制/取消时机、现场摩擦/步态或定位尺度误差。下一步应结合现场观察判断是否需要延长采样时间、调整目标距离，或改为两个 0.5m 分段航点。
- 用户现场确认该 1.0m 目标测试方向和实际表现正确；因此当前基线可以升级到分段航点测试，而不是继续在单段直线 1m 上排查底层链路。

### 同一 session 连续 goal 行为 — 2026-07-15

- 同一完整启动栈内连续运行两次当前 `nav2_goal_cmd_vel_probe.py` 时，第一段 0.8m 正常：`accepted=true`、`cmd_count=149`、`nonzero_count=148`，并产生约 `0.59m` planar odom 位移。
- 第二段 0.8m 目标同样 `accepted=true`，但 `cmd_count=0`、`nonzero_count=0`，位姿停在第一段后位置，说明 controller 没有输出 `/cmd_vel`，而不是 Lite3/UDP/odom 链路单独失败。
- 该现象与历史“同 session 混跑 `/plan` probe/direct FollowPath/取消 goal 后可能污染 BT Navigator 状态”的模式一致。当前 `nav2_goal_cmd_vel_probe.py` 会在采样时间结束后 cancel goal，因此它不等价于真实任务管理器的“到达目标后自然成功，再发送下一航点”。
- 下一步若要验证连续航点，优先新增或改造一个 waypoint/sequence 测试脚本：等待第一个 `NavigateToPose` 自然 result success 或 timeout，而不是采样后主动 cancel；或每段之间 clean restart，分别验证单段稳定性。

### Nav2 自然完成连续航点 probe 结论 — 2026-07-23

- 新增 `scripts/nav2_waypoint_sequence_probe.py` 后，连续航点测试不再在固定采样窗口后主动 cancel goal，而是等待 `NavigateToPose` 自然 result。
- 自动 `--forward-distances` 模式必须等待真实 `map -> base_link` TF；不能用 `/tmp/odom_latest.json` fallback 生成 map goal。实测当 `map` frame 尚不存在时，fallback 目标会导致第一段立即 `ABORTED` 且 `cmd_count=0`，这不是运动链路问题。
- 最终 clean 真机 run `/home/superwfx666/competition_logs/nav2_sequence_live/20260723-162009` 证明：
  - 第一段 0.5m 自然完成：`SUCCEEDED`，`cmd_count=66`，`nonzero_count=65`，位移约 `0.357m`。
  - 第二段 0.5m 已进入 controller：`cmd_count=31`，`nonzero_count=31`，不是历史的 `cmd_count=0`。
  - 第二段最终 `ABORTED`，位移约 `0.097m`，且 delta `x=+0.095m` 与目标方向 `x` 减小相反，伴随 yaw 约 `-0.117rad` 变化。
- 因此“cancel 型 probe 污染连续航点判断”被基本证实；当前剩余问题应收窄为第二段自然 goal 的中途 abort / progress checker / yaw 或 map-odom 稳定性，而不是 Lite3 UDP、`cmd_vel_bridge` subscriber 或 cuVSLAM planar odom 基础链路。
- 后续复测建议：
  - 在第一段 `SUCCEEDED` 后增加 5-10 秒稳定等待，确认 `map->base_link` yaw 和 TF timestamp 更新后再发第二段。
  - 将第二段距离降到 0.25-0.30m，分离“连续 action 状态”与“长距离/路径跟踪”变量。
  - 捕获 BT/controller 的详细日志；当前 `~/.ros/log` 只保留 launch process started，未看到 controller abort 细节。

### `/cmd_vel` CSV 后的连续航点判断修正 — 2026-07-23

- `nav2_waypoint_sequence_probe.py` 已新增逐条 `/cmd_vel` CSV，用于区分纯旋转、纯直线和边走边转。
- 复测 `0.5m + 等 8s + 0.25m` 时，第一段 0.5m 即 `ABORTED`，未进入第二段；日志目录为 `/home/superwfx666/competition_logs/nav2_sequence_live/20260723-212522`。
- 第一段 `/cmd_vel` 不是原地旋转：
  - `cmd_count=73`、`linear_x_nonzero_count=73`、`angular_z_nonzero_count=73`。
  - 73 条命令全部是 `linear.x` 与 `angular.z` 混合。
  - 平均 `linear.x≈0.090m/s`，最大 `linear.x=0.1m/s`；平均 `angular.z≈-0.0116rad/s`，最大角速度约 `0.0868rad/s`。
- 因此“RotateToGoal 导致纯原地转，SimpleProgressChecker 15 秒后 abort”不能解释本轮；至少本轮 abort 前控制器一直在命令前进。
- 更关键的新异常是方向：该段目标按 `yaw≈-3.129` 外推应让 map `x` 减小，但实测 `map->base_link` delta 为 `x=+0.120m, y=-0.043m`。这说明本轮存在“命令前进方向”和 map 中位姿变化方向不一致的风险。
- 后续应先复核方向链路：
  - clean 启动后不发 Nav2 goal，短时直发低速 `/cmd_vel linear.x>0`，记录 `map->base_link` delta。
  - 若低速直发也使 map `x` 增加，而当前 yaw/goal 逻辑认为前方应是 `x` 减小，则优先查 TF/yaw 初始化、`base_link` 朝向、map->odom 初始位姿或 final bridge frame 语义。
  - 若低速直发方向正常，则再回头查 DWB/BT/controller 为什么在该起点生成了导致反向位移的速度序列。

### Nav2 初始 pose 内移决策 — 2026-07-25

- 当前“现场看狗在前进，但 map 中目标/位移解释出现矛盾”的最强嫌疑不是底层 Lite3 后退，也不是 PGM/YAML 的 origin/resolution 立刻错误，而是 Nav2 初始 pose 与现实摆放点不一致。
- 原 `ROBOT_START_POSE` 对应 ROS map `(5.35,0.75,yaw=pi)`，其中 `x=5.35m` 位于 `FIELD["width"]=5.0m` 的主场地右边界外；这来自估计的外部出发区。
- 用户确认现实起点在主场地内部，因此已先将 `ROBOT_START_POSE["x_mm"]` 调整为 `4850.0`，对应 ROS map `(4.85,0.75,yaw=pi)`。
- 这次不改 `competition_field_phase1.yaml` / `.pgm`，因为右侧外部小块可行区域本身可以保留；当前需要修正的是 Nav2 启动时发布的 `map -> odom` 初始对齐点。
- 后续实测若仍出现“实际前进但 map delta 与目标方向相反”，再回到 TF/yaw/localization 方向链路复核。

### Nav2 起点 4.65m 微调 — 2026-07-25

- 用户确认 `x=4.85,y=0.75,yaw=pi` 的起点方向与现实一致，但认为位置仍偏地图右边线。
- 当前 Nav2 worktree 已将 `ROBOT_START_POSE["x_mm"]` 进一步调整为 `4650.0`，对应 ROS map `(4.65,0.75,yaw=pi)`。
- 本次仅修改初始 pose 数据和离线校准图，不改地图 `origin/resolution`，也不执行运动测试。

### Nav2 连续航点前置阻塞：cuVSLAM topic 存在但无 odom 消息 — 2026-07-25

- 当前不能直接判定连续航点逻辑，因为本轮测试在发 goal 前就被定位输入阻塞：Host 没有 `/tmp/odom_latest.json`，TF 中 `map` 与 `base_link` 不连通。
- D455 硬件链路本身正常：独立 `scripts/camera/realsense_cuvslam_input_test.py --seconds 2 --warmup-frames 5` 显示 RGB/depth、IR stereo、IMU 和 `RealsenseCamera.for_cuvslam` 全部 PASS。
- 默认 `CUVSLAM_IMAGE_JITTER_THRESHOLD_MS=22.0` 对本轮实际图像节奏过严；日志中出现大量 33ms、50ms、100ms 级 image delta warning，容器最终超时等待 `/visual_slam/tracking/odometry`。
- `CUVSLAM_IMAGE_JITTER_THRESHOLD_MS` 必须传 double，例如 `200.0`，不能传整数 `200`；整数会导致 Isaac ROS 参数类型错误，visual_slam component constructor 失败。
- `200.0` 可让 visual_slam node 加载并出现 `/visual_slam/tracking/odometry` 等 topic，但本轮这些 topic 没有实际消息，`final_bridge.py` 收不到 UDP odometry packet。
- 因此下一步应先解决 cuVSLAM 实际 odom 发布问题，再继续 Nav2 多航点。不要在 `map->base_link` 缺失时发 NavigateToPose。

### cuVSLAM 7月25日启动失败复核 — 2026-07-26

- 这次 Navigation2 多航点没有真正进入导航阶段；直接阻塞点是 cuVSLAM 没有产生第一条可用 `/visual_slam/tracking/odometry` 消息，导致 Host `final_bridge.py` 收不到 UDP odometry、`/tmp/odom_latest.json` 不生成、`map -> base_link` 不连通。
- D455 独立输入短测已经 PASS，因此当前证据不支持“相机硬件坏了”或“Nav2 起点 4.65 改坏 cuVSLAM”。起点只影响 `map -> odom` 初始对齐，不会让 Docker 内 cuVSLAM 不发布 odom。
- 历史记录里有两类必须同时考虑的事实：
  - `640x360x60` 曾在 2026-06-25 造成 RealSense topic 已出现但 `Frames didn't arrived within 5 seconds`、cuVSLAM 没到 tracker、无 odom，随后恢复到 `640x360x90` 才通过 smoke。
  - 后续修复 RealSense internal TF 后，`planar_60fps` 又在 bench/chair 测试中成为有效 profile，并在 2026-07-12 至 2026-07-23 的 Nav2 基线中多次启动正常。
- 因此更准确的定位不是“60fps 永远不能用”，而是：当前 `start_competition.sh` 默认仍走 `CUVSLAM_PROFILE=planar_60fps -> CUVSLAM_CAMERA_PROFILE=640x360x60`，这条链路对启动时序/RealSense frame-flow/容器残留更敏感；本轮复现了“topic 或节点存在但没有真实 odom”的历史故障形态。
- `CUVSLAM_IMAGE_JITTER_THRESHOLD_MS=200.0` 只证明参数类型要用 double，不能证明 jitter 是根因；因为调大后 topic 出现但仍无实际 odom，Host bridge 仍没有第一包。
- 下一次恢复测试应先做 cuVSLAM-only preflight：彻底清理容器和 D455 占用，显式指定一个基准 profile（优先 `CUVSLAM_PROFILE=planar_90fps` 或官方 camera-link baseline；如要比较再跑 `planar_60fps`），并以 `ros2 topic echo /visual_slam/tracking/odometry --once`、`/tmp/odom_latest.json`、`map -> base_link` 为通过条件；通过前不要发 Nav2 goal 或 `/cmd_vel`。

### Navigation-only 最小链路恢复 — 2026-07-26

- 当前短期路线应继续使用已验证过的 cuVSLAM 技术栈，把问题收窄到点到点 Navigation2；识别链路暂不接入，因此 Docker->Host 跨边界只需要传 odometry。
- `scripts/start_competition.sh` 之前无条件启动 camera/depth relay，即使 `YOLO=false`、`WHZ=false` 也会额外传图像/深度数据。该行为会干扰 Navigation-only 测试，增加 CPU 和 Docker 边界复杂度。
- 已将 camera/depth relay 改为显式开关，默认跳过。Navigation-only 启动日志应出现 `CAMERA_RELAY=false`、`DEPTH_RELAY=false`，并打印 `Camera relay: skipped`、`Depth relay: skipped`。
- 2026-07-26 无运动验证证明：在跳过 camera/depth relay 后，`planar_60fps` 仍能成功发布 `/visual_slam/tracking/odometry`，Host `final_bridge.py` 生成 `/tmp/odom_latest.json`，`map -> base_link` 为 `(4.65,0.75,yaw=pi)`，Nav2 lifecycle 全 active。
- 无狗 dry-run goal `(4.15,0.75,yaw=pi)` 返回 `accepted=true`、`cmd_count=80`、`nonzero_count=80`，且 `/cmd_vel` subscription count 为 `0`，说明 Nav2 action/controller 链路可出速度，且本轮没有触碰 Lite3。
- 后续实机 single-shot 前必须 clean restart；不要在无狗 dry-run 后直接复用同一个 Nav2 session 上狗运动，以免历史上的 cancel/probe 状态污染。

### Navigation-only 0.3m single-shot 真机结论 — 2026-07-26

- 在默认跳过 camera/depth relay、YOLO、WHZ、task_manager 的最小栈下，`planar_60fps` cuVSLAM + Host planar bridge + Nav2 + Lite3 prepare + `cmd_vel_bridge` 已完成真实上狗闭环。
- `nav2_waypoint_sequence_probe.py --forward-distances 0.3` 返回 `action_status=SUCCEEDED`，不是历史上的 `cmd_count=0` 或 odom 缺失。
- `/cmd_vel` 和 UDP 证据完整：`cmd_count=108`、`nonzero_count=107`，bridge `udp_simple=486`、`udp_complex=486`、`udp_errors=0`，最后发送零速。
- TF 方向正确：起点向前目标按 yaw≈pi 应使 map x 减小，本轮 delta 为 `x=-0.1609m`、`y=+0.0057m`。
- 本轮目标 0.3m 但 TF 位移约 0.16m 后 action success，说明下一轮需要结合现场观察和 Nav2 `xy_goal_tolerance` 判断是否要缩小 goal tolerance、增大目标距离，或先接受该容差作为比赛低速点到点的安全策略。
- 当前不应再把“cuVSLAM odom 不出第一包”作为本轮主阻塞；下一阶段主问题是连续航点自然完成稳定性与场地路径分段策略。

### 任务首目标 direct point-to-point 第二次实机结论 — 2026-07-26

- clean Navigation-only 真机栈下，直接发送 `obstacle_cross_target` 绝对 goal `(0.5,0.75,yaw=pi)`，Nav2 action 能被接受，且 controller 能输出非零 `/cmd_vel`。
- 本轮 direct goal 失败形态不是 `cmd_count=0`：实际 `cmd_count=31`、`nonzero_count=31`、`max_linear_x=0.1m/s`、`max_abs_angular_z≈0.0868rad/s`，随后 action `ABORTED`。
- 关键异常是方向：起点 `map->base_link≈(4.6499,0.7502,yaw≈pi)`，目标 x 为 `0.5`，期望初始前进应让 map x 减小；实际 delta 为 `x=+0.0856m,y=-0.0189m`，即反向偏移。
- 因此当前直接点到点首目标的问题应定义为“长距离 absolute NavigateToPose 起步阶段的控制/方向一致性问题”，而不是 cuVSLAM 无 odom、Nav2 未接收 goal、`cmd_vel_bridge` 未订阅或 Lite3 UDP 完全不发。
- 后续若继续追求比赛路线落地，分段小目标仍更符合已验证事实；若坚持单个长 goal，需要优先诊断 DWB/controller 局部路径跟踪、yaw/TF 语义和起点附近局部代价地图。

### cmd_vel_bridge 三轴完整状态修复结论 — 2026-07-26

- 现场观察“狗明显前进而非原地转”修正了上一轮假设：旧 bridge 的单轴优先逻辑不应简单理解为“只会执行 angular velocity”；更可信风险是 Lite3 底层按轴保存运动状态，单轴 UDP 命令无法完整覆盖 FWD/LAT/YAW。
- 已将 bridge 默认改为每周期发送三轴完整状态：`FWD=linear.x`、`LAT=linear.y`、`YAW=-angular.z`；stale 后持续发送三轴零速；退出时发送 heartbeat + 三轴零速 burst。
- 复测证明该改动显著改善 direct 首目标起步和长距离行进：
  - 修复前 direct goal：`cmd_count=31` 后 `ABORTED`，TF delta `x=+0.0856m`，方向异常。
  - 修复后 direct goal：`cmd_count=362`，连续行进约 `3.526m`，TF delta `x=-3.526m`，方向正确。
- 修复后仍未到达 `obstacle_cross_target`：终点 `x≈1.049,y≈0.795`，距目标 `(0.5,0.75)` 约 `0.551m` 时 `ABORTED`。
- 当前主问题已从“速度桥接/起步方向异常”转移到“目标前 0.5m 左右 Nav2 abort”：下一步应优先查该终点附近局部代价地图、目标点是否压线/靠近障碍、DWB critics、progress/oscillation 触发，以及是否应把任务首目标改成更保守的中间航点或分段进场。

### Nav2 目标中心点贴边不可达验证 — 2026-07-27

- 官方 Nav2 语义下，NavigateToPose 的 goal 是 `base_link` 位姿中心目标；机器人实际占地由 costmap footprint 表示，而不是由 goal 点表示“前缘/头部到达某处”。
- 本项目当前 footprint 长度为 `1.0m`，即 `base_link` 到机身前/后边缘各 `0.50m`，并有 `footprint_padding=0.02`；原 `obstacle_cross_target=(0.5,0.75)` 紧贴场地左侧，若要求 `base_link` 到达该点，机身会越过左边界。
- 2026-07-27 clean 实测发送内移目标 `(1.05,0.75,pi)`，Nav2 返回 `SUCCEEDED`，终点 `x=1.189,y=0.764`，距离 goal 约 `0.140m`，刚好在当前 `xy_goal_tolerance=0.15` 内。
- 因此当前最可信根因是目标点语义错误：`(0.5,0.75)` 应作为“左侧安全走廊/通过区域”的任务语义点或前缘判定点，不应直接作为 Nav2 `base_link` 中心点 goal。短期比赛实现应将首段导航目标设为约 `(1.05,0.75,pi)`，或使用分段航点到达该中心点后再由任务逻辑判断通过状态。
### Navigation-only 全目标路线策略 — 2026-07-27

- 当前应先把导航作为独立系统跑通：只保留 cuVSLAM 所需 IR 双目 + IMU、Host odom/TF bridge、Nav2、`cmd_vel_bridge` 和 Lite3 motion prepare；RGB/depth relay、YOLO、WHZ、仪表识别、task_manager 感知条件暂不接入。
- Nav2 `NavigateToPose` 的 goal 是 `base_link` 位姿中心，不是任务物体中心、场地区域中心或机器人前缘到达点。所有比赛 waypoint 都应区分“任务语义点”和“机器人中心可达接近点”。
- 原 `obstacle_cross_target=(0.5,0.75)` 更适合作为左侧通过区域/前缘语义点，不适合作为 `base_link` 中心目标；2026-07-27 真机实测 `(1.05,0.75,pi)` 已成功，短期应以它作为越障接近点。
- 场地 mm 坐标系是 `+y` 向下，而 ROS map 是 `+y` 向上；若 `yaw_deg` 按场地图纸语义书写，则转换成 ROS yaw 时应取负号。该问题会影响 `±90°` 观察位朝向，`180°` 因等价于 `-180°` 不明显。
- 抓取区和放置区在 PGM 中是墙/禁入区，不能把 `grab_area` 或 `placement_A/B/C/D` 设为区域内部中心；应设为靠近目标但 footprint 不压墙的接近点。
- 离线 footprint 检查显示旧 `pos2a_upper_right` / `pos2b_lower_right` 的 x=2.20m 过近，机器人朝左时前半身会压进巡检柜体墙；右移到 x=2.60m 后 phase1/phase2 静态墙体均 clear。
- task_manager 不能在 `obstacle_cross_target` 接近点成功后立刻切 Phase2 地图，因为 Phase2 会把 obstacle 区域封闭，而该接近点在 Phase2 下仍可能被 obstacle wall 覆盖。更稳的流程是到达 `pos1_middle` 后再切 Phase2 地图。

### Nav2 第二段 abort 网络检索与地图定位 — 2026-07-27

- 官方 Nav2 `Controller Server` 文档说明 controller server 会调用 controller、progress checker、goal checker，并承载 local costmap；`computeVelocityCommands` 抛异常可导致 `FollowPath` action 失败。因此 `NavigateToPose` accepted 且 `/cmd_vel` 有输出后再 `ABORTED`，通常应优先查 controller/progress/costmap，而不是 action 发送链路。
- 官方 `SimpleProgressChecker` 只检查 positional progress：机器人必须在 `movement_time_allowance` 内移动超过 `required_movement_radius`。当前配置是 `0.10m / 15s`，第 2 段已有 `0.871m` 位移，不像一开始就被 progress checker 卡死；但后续 yaw-only 转身仍可能触发该类问题。
- 官方 `PoseProgressChecker` 支持同时用平移和旋转判断 progress；GitHub issue #5159 也有人提出 SimpleProgressChecker 只看 x/y，在原地旋转时不计 progress。这意味着 `pos1_middle -> pos1_middle_turned` 这种 180 度原地转身，按当前 `max_vel_theta=0.15rad/s` 和 `movement_time_allowance=15s` 有后续失败风险。
- 官方 DWB 文档列出 DWB 会用 velocity/acceleration 参数和 trajectory critics 评分候选轨迹；当前配置 `max_vel_theta=0.15`、`max_vel_y=0`、`PathAlign.scale=32`、`GoalAlign.scale=24`、`PathDist.scale=32`、`GoalDist.scale=24`，在窄通道大转向时可行候选更少。
- Nav2 tuning guide 强调非圆形机器人应使用真实 footprint，并说明 DWB 通过 critics 对多条 trajectory 评分、可偏离路径但需要针对平台调参；这与当前 1.0m x 0.5m footprint 在柜体角点附近中途 abort 的形态一致。
- 本地 `progress.md` 最新真机结果：第 2 段 `pos1_middle=(1.5,3.25,pi/2)` 从 `(1.080,0.757)` 开始，最终 abort 在约 `(0.570,1.469,yaw=1.407)`；该点正处于下巡检柜体左下角附近。下巡检柜体在 ROS map 中约为 `x=1.0..2.0, y=1.5..2.5`，说明全局路径实际把机器人导向了左侧窄通道。
- 静态 footprint 采样：失败终点 footprint 离下巡检柜体最近约 `0.10m`，远小于当前 `inflation_radius=0.30m`；候选右侧绕行点 `(2.70,0.95,0)`、`(2.70,2.85,pi/2)`、`(2.25,3.25,pi)` 在 phase1 map 下为 clear，估算最小余量分别约 `0.36m`、`0.45m`、`0.50m`。短期优先改 route 让第二段从右侧宽通道绕过下巡检柜体。

### nav-only-full 最新真机阻塞点 — 2026-07-27

- 在 `0.70m x 0.50m` footprint、Navigation-only 最小栈下，完整 `nav-only-full` 本轮成功通过前两段：`obstacle_cross_target` 与 `pos1_middle` 均 `SUCCEEDED`。
- 第 3 段 `pos1_middle_turned=(1.5,3.25,-pi/2)` 失败：`accepted=true`、`action_status=ABORTED`，Nav2 日志报 `bt_navigator: Action server failed while executing action callback: "send_goal failed"`。
- 第 3 段不是零速度链路问题：`cmd_count=248`、`nonzero_count=248`、`angular_z_nonzero_count=248`、`max_abs_angular_z=0.15rad/s`；形态是同点/近同点大角度转身持续角速度输出后 abort。
- 结论：第 2 段旧阻塞已被 footprint/waypoint 调整显著改善；当前最优先问题转为 `pos1_middle -> pos1_middle_turned` 的近原地 180 度转身稳定性，下一步应围绕 DWB yaw-only 行为、progress checker 对旋转是否计入 progress、RotateToGoal/oscillation 配置或“用小半径绕行替代原地转身”做处理。

### nav-only staged-turn 实施结论 — 2026-07-27

- 用户指出 Lite3 实际旋转不是绕 `base_link` 质心定心旋转，而是伴随 XY 漂移；因此第三段不能只归因于 `SimpleProgressChecker` 看不到 XY 位移。
- 修正判断：第三段更像 DWB `RotateToGoal` 进入近目标 yaw-only 状态后，与 Lite3 转身会漂移的真实运动学不匹配。机器人起点已在 `xy_goal_tolerance=0.15m` 内，DWB 倾向只修 yaw；但实机转身漂移后，Nav2 又没有有效平移纠偏空间，最终 abort。
- 已采用路线级规避：默认 `nav-only-full` / `nav-only-inspection` 不再使用同 XY 的 180° 转身；改为插入 `pos1_turnout_right=(1.90,3.45,0.0)`，再到右移后的 `pos1_middle_turned=(1.90,3.25,-pi/2)`。
- 正式 task_manager 也同步同一语义：新增 `pos1_turnout_right` 过渡步骤，`transit=True`，不做拍照识别；并修正巡检阶段必须等待 Nav2 result 后才识别或推进。
- 静态检查显示新 staged 点在 phase1/phase2 PGM 中 footprint clear；下一步只差 Jetson SSH 恢复后的远端同步和真机复测。

### SSH 恢复后 nav-only-full 复跑发现 — 2026-07-27 21:00

- 远端当前 `nav-only-full` preset 已包含 staged-turn 结构，且 `pos1_turnout_right` 当前 yaw 为 `None`；但本轮失败发生在第 2 段 `pos1_middle`，未进入该过渡点，所以本轮数据不能用于评价过渡点 yaw 是否合理。
- 第 1 段 `obstacle_cross_target` 仍能成功，说明本轮 cuVSLAM/TF/Nav2 action/bridge/Lite3 运动链路并非整体失效；第 2 段在 `accepted=true` 且 `/cmd_vel` 连续非零后约 `0.213m` 位移即 `ABORTED`。
- 第 2 段失败时姿态从约 `(1.193,0.730,yaw=2.953)` 到 `(0.981,0.751,yaw=2.547)`，主要表现为继续向 map x 负方向移动并转向，而不是稳定进入通往 `y=3.25` 的路径。
- `/tmp/competition.log` 在 abort 点附近只给出 BT 层 `Action server failed while executing action callback: "send_goal failed"`，controller 日志没有给出更细的 DWB critic/progress 原因；下一步若继续定位，优先开启 DWB/controller 更详细日志或保存 local/global plan/costmap 快照。
- `start_competition.sh` 会在启动完成后退出，自动化运行时应把“日志出现启动完成/节点已 active/TF 可用”作为 ready 条件，不能要求该启动脚本进程常驻。

### staged-turn 默认路线回滚决定 — 2026-07-27

- 提交 `09d4609ca14438bba84ba1b5c53b618994a6a3bf` 把第三段规避实验直接放进了默认 `nav-only-full` / `nav-only-inspection`，导致后续复测时第一段、第二段问题和第三段原问题混在一起，失去清晰对照基线。
- 已按用户要求通过 `git revert` 撤销该提交，保留其他提交不变。新的本地 HEAD 为 `43c2015`。
- 回滚后的预期基线：第一段 `obstacle_cross_target` 和第二段 `pos1_middle` 应回到已知可通过状态，第三段 `pos1_middle_turned` 同点/近同点 180° 转身仍是待解决问题。

### revert 后复测未完全恢复历史基线 — 2026-07-27 21:28

- 本地核对 `5f1fb59..HEAD` 对 3 个 route/task 文件无 diff，且 Jetson 已同步并构建，说明 `09d4609` 的 staged-turn 默认路线改动已经从当前复测代码路径中撤掉。
- 复测结果仍在第 2 段 `pos1_middle` abort：从约 `(1.201,0.764,yaw=-3.053)` 到 `(0.834,2.822,yaw=0.778)`，已移动 `2.091m`，但未到达 `(1.5,3.25,pi/2)`。
- 这个形态比 revert 前“第 2 段只移动 `0.213m` 即失败”更接近历史运行，但仍未复现“第 1、2 段成功，第 3 段失败”的最好一次基线。
- 因代码基线已确认一致，下一步不应继续把问题归因于 `09d4609` 残留；更应检查实机条件差异：起点 yaw/位姿漂移、cuVSLAM 短时跳变、DWB 在柜体左下角附近的 local costmap/critic、以及第二段末端是否落入 inflation/costmap 边缘。

### 进一步缩小 footprint 的取舍 — 2026-07-29

- 当前为了优先让第二段通过，已将 Nav2 collision footprint 从 `0.70m x 0.50m` 进一步收为 `0.60m x 0.50m`，只缩短前后长度，不缩窄左右宽度。
- 这样做的预期收益是给第二段经过巡检柜体附近时更多 longitudinal clearance，降低 DWB/local costmap 在柜体角点附近判定不可行的概率。
- 代价是 Nav2 碰撞模型比实体更乐观；如果现场存在真实侧边/前后刮碰风险，仍应靠低速、人工观察和必要时外层 safety gate 控制。

### 0.60m footprint 复测暴露 action/controller 时序矛盾 — 2026-07-29

- `20260729-192236` clean `nav-only-full` 复测在第 1 段 `obstacle_cross_target` 即 `ABORTED`，没有进入第二段，因此本轮不能评价 0.60m footprint 是否能让第二段通过。
- 关键异常不是单纯“无 `/cmd_vel`”：route probe summary 的 `/cmd_vel` 采样为 0，但同一轮 `/tmp/competition.log` 里 `cmd_vel_bridge` 明确记录 `recv=62`、`motion=62`、`udp_simple=244`、`udp_complex=732`、`udp_errors=0`。
- 时间线显示 `bt_navigator` 在 `1785324317.837` 报 `send_goal failed` 并 abort；`controller_server` 在 `1785324317.821` 已收到 FollowPath goal；`cmd_vel_bridge` 从 `1785324317.933` 起记录非零速度。这说明 BT/action result、controller 执行和 probe 采样窗口存在时序不一致。
- 后续判断不能只看 `summary.json` 的 `cmd_count=0`；需要同时核对 `cmd_vel_bridge` 诊断和 controller 日志。若继续排查，应先加一轮更直接的单段 `obstacle_cross_target` probe，并在 route 脚本中延迟停止 `/cmd_vel` 采样或等待 controller goal settle，以免把 action 早 abort 后的残余 controller 输出漏记。

### 0.70m footprint 基线复跑结果 — 2026-07-29

- local/global footprint 恢复为 `0.70m x 0.50m` 后，clean `nav-only-full` 的第 1 段 `obstacle_cross_target` 再次稳定完成：TF 前进约 `3.454m`，Nav2 返回 `SUCCEEDED`。
- 同一启动栈中的第 2 段 `pos1_middle` 在 accepted 后立即 `ABORTED`，没有可观测位移，probe 未采到 `/cmd_vel`；日志只给出 BT Navigator 的 `send_goal failed`。
- 本轮事实说明恢复原 footprint 能让首段回到成功状态，但完整路线仍未跑通，当前停止点是第 2 段 goal 切换时刻。按用户要求，本轮不继续修改 BT/action/probe 或其他导航参数。

### Nav2 Foxy `send_goal failed` 根因复核 — 2026-07-29

- 仓库实测不是单一故障，而是三类问题叠加：
  1. 当前第 2 段 accepted 后立即 abort、无 `/cmd_vel`/无位移，属于 BT 子 action goal 确认失败；
  2. 历史第 2 段有持续 `/cmd_vel` 后在柜体附近 abort，仍可能包含 DWB/local costmap/路径余量问题；
  3. 历史第 3 段同点 180 度转身持续旋转后 abort，属于 RotateToGoal 与 Lite3 转身漂移不匹配。
- `5f1fb59` 的 2026-07-27 成功基线确实是第 1、2 段 `SUCCEEDED`，第 3 段才 `ABORTED`；但随后相同 route/task 文件基线的第 2 段分别在约 `0.213m`、`2.091m` 和 `0m` 处失败。失败位置高度不一致，说明当前退化不是一个固定地图碰撞点能够单独解释。
- Nav2 Foxy `bt_action_node.hpp` 对 `async_send_goal()` 使用 `spin_until_future_complete(..., server_timeout_)`；未在期限内拿到 action goal handle 就直接抛出 `runtime_error("send_goal failed")`。Foxy `bt_navigator.cpp` 将该 blackboard timeout 硬编码为 `10ms`，当前 YAML 未提供可覆盖参数。
- Foxy 默认 `navigate_w_replanning_and_recovery.xml` 以 `1Hz` 重算全局路径；`ComputePathToPose` 成功后设置 `path_updated=true`，`FollowPathAction::on_wait_for_result()` 据此把 `goal_updated_=true` 并重新发送 FollowPath goal。因此一次长距离 NavigateToPose 内也会反复触发 10ms action 确认窗口，不只是相邻 waypoint 切换时触发。
- ROS 2 issue `ros2/ros2#1074` 和 Nav2 issue `navigation2#2272` 记录了同一 Foxy/Fast-RTPS 随机故障。维护者确认 `send_goal failed` 是 `spin_until_future_complete` 超时/中断的客户端症状，并报告低成本 aarch64 机器随系统负载可从约 `4ms` 抖到 `50ms+`；同代码可能连续成功，也可能随机失败。Jetson + cuVSLAM/RealSense/bridge/Nav2 的运行负载与该触发条件吻合。
- `navigation2#2272` 还记录了与本项目 0.60m footprint 那轮一致的危险形态：外层 NavigateToPose 已 abort，但内层 FollowPath 仍继续执行。PR `navigation2#2271` 改善了异常后的 BT halt/清理，但维护者明确表示该大重构不会主动回移 Foxy，只进入 Galactic 及后续版本。
- 因此当前第 2 段立即失败的首要原因不是 `0.70m x 0.50m` footprint，也不是 `pos1_middle` 固定不可达，而是 Foxy 10ms action acknowledgement deadline 在非实时 Jetson 负载下偶发超时。2026-07-27 的成功是可行性证据，不是稳定性证据。
- 潜在解决方案优先级：
  1. 比赛期最小修复：从源码覆盖 Foxy `nav2_bt_navigator`/`nav2_behavior_tree`，将 action server timeout 参数化并从 `100ms` 起验证，同时记录返回值区分 `TIMEOUT`/`INTERRUPTED`；同步回移异常后 halt-all-actions 修复，防止外层 abort 后机器狗继续运动。
  2. 减少触发次数：静态比赛地图使用“ComputePathToPose 一次 + FollowPath 一次”的无 1Hz 重规划 BT；代价是失去周期性全局重规划，需要独立安全停止机制。
  3. 长期方案：把 Nav2 迁移到 Humble 或更新版本容器/工作区，避开已停止维护的 Foxy action/BT 实现。Galactic 已同样 EOL，不应作为新迁移目标。
  4. 辅助缓解：继续保持 jetson_clocks、Navigation-only 最小栈，降低不必要的相机/可视化负载；切换 DDS 或增加 inter-goal pause只能降低概率，不能消除 10ms deadline 根因。
  5. action 稳定后再处理路径控制：若第 2 段仍在有连续 `/cmd_vel` 时靠近柜体 abort，再用右侧宽通道分段航点/DWB debug解决；第 3 段则继续采用小半径移动转身，避免同点 180 度 RotateToGoal。
- 网络来源：Nav2 issue `https://github.com/ros-navigation/navigation2/issues/2272`、ROS 2 issue `https://github.com/ros2/ros2/issues/1074`、Foxy BT action source `https://github.com/ros-navigation/navigation2/blob/foxy-devel/nav2_behavior_tree/include/nav2_behavior_tree/bt_action_node.hpp`、Foxy default BT `https://github.com/ros-navigation/navigation2/blob/foxy-devel/nav2_bt_navigator/behavior_trees/navigate_w_replanning_and_recovery.xml`、PR `https://github.com/ros-navigation/navigation2/pull/2271`。
### Foxy BT action timeout 最小回移的安全边界 — 2026-07-30

- 仅把 `server_timeout` 从 10ms 增到 100ms 不足以保证异常收尾：首次 goal acknowledgement 超时时 `goal_handle_` 仍为空，随后直接 `haltAllActions()` 会进入旧 `should_cancel_goal()` 的空指针路径；result callback 也存在同类空句柄解引用风险。因此参数化、异常转 failure 和空句柄保护必须作为一个最小补丁组部署。
- PR #2271 在 `BehaviorTreeEngine::run()` 捕获 `std::exception` 并返回 `FAILED`，随后 Foxy `BtNavigator::navigateToPose()` 的既有代码会调用 `haltAllActions()` 并 terminate outer action；不需要回移 PR 中大规模 navigator/nav2_core/nav2_msgs 重构。
- `default_server_timeout=100ms` 已在 Jetson 实际运行日志中确认，且 `/proc/<bt_navigator>/exe` 与 maps 均指向独立 overlay；这排除了“构建成功但启动仍使用 `/opt/ros/foxy` apt 二进制”的假阳性。
- 无运动 action smoke 证明 patched stack 的 NavigateToPose send/cancel 基本链路正常，但不能替代多 waypoint + 1Hz replanning 的长时间真机压力测试。是否消除随机第二段 `send_goal failed`，仍须在锁频后 clean 运行 `nav-only-inspection-staged` 判断。

### action 修复后暴露的第二段确定性路径/终点问题 — 2026-07-30

- 锁频后的 `nav-only-inspection-staged` 真机运行持续 120s、经历大量 1Hz `ComputePathToPose` / `FollowPath` 更新，未再出现 `send_goal failed` 或 BT exception；Foxy action acknowledgement overlay 的目标已经达到，后续不应继续放大 timeout 或修改 action 生命周期。
- 第二段不是单纯“目标不可达”：轨迹曾进入目标 XY `0.084m`，但 yaw 仍差 `1.159rad`，没有任何采样同时满足 `SimpleGoalChecker` 的 `0.15m + 0.30rad`。
- 首次 `GridBased` 规划失败发生在 `(0.773,2.593)`，几何上位于下巡检柜体左上角 `(1.0,2.5)` 附近。默认 recovery 的 `Spin(1.57)` 对会产生 XY 漂移的 Lite3 并不适合作为该位置的恢复动作；它让机器人绕柜角漂移并显著压缩了最后的航向收敛时间。
- Foxy `RotateToGoalCritic` 源码会用 `in_window_ = in_window_ || ...` 和 `rotating_ = rotating_ || ...` 锁存终点旋转状态；一旦进入 XY 窗口并停下，候选轨迹只允许 `linear.x/y=0`。这与 Lite3 原地转向伴随 XY 漂移存在机制冲突；Humble 和当前 Nav2 主线仍保留该锁存语义，不能把配置中的 `FollowPath.stateful` 当作退出锁存的开关。
- RPP 在 Foxy 已存在，但 `use_rotate_to_heading=true` 时同样在路径初始/终点输出 `linear=0` 的原地转向；直接从 DWB 换成 RPP并不能自动解决 Lite3 的转身漂移。Savitzky-Golay smoother 只能平滑几何路径，也不能修复终点 goal-checker / 原地旋转运动学冲突。
- 当前最小验证方案是路线级约束：保留 legacy 基线，只在 staged preset 的第二段前插入左侧净空航点，使全局路径在到达 `y>2.5m` 后再越过柜角；待能够稳定到达 `pos1_middle` 后，再验证既有两段移动式 180° 转身。

### staged 第三段实测：短对角 waypoint 不是有效转身圆弧 — 2026-07-30

- `pos1_left_clear=(0.60,2.90,pi/2)` 让前 3 段连续 `SUCCEEDED`，证明第二段柜角规划阻塞已被路线级约束解决；该点应保留在 staged preset。
- 当前 `pos1_middle=(1.50,3.25,+pi/2) -> pos1_turnout_right=(1.90,3.45,0)` 不是几何一致的四分之一圆：若半径取 `0.20m`，四分之一圆切点应约为 `(1.70,3.45,0)`；现有点同时使用 `dx=0.40m` 和 `dy=0.20m`，会给 DWB 一个短而方向突变的对角 goal。
- 真机在该段前 20s 已越过目标到 `(2.251,3.633,yaw=-1.525)`，说明控制器没有形成预期的 `+90 -> 0` 单次移动转向，而是继续旋转并越调；随后全局路径在当前位置不可生成，默认 BT 的 Spin recovery 又进一步放大漂移。
- 当前最优先修复不应是增加 goal timeout，也不应换 Savitzky-Golay smoother：前者只让回环持续更久，后者不改变 goal orientation 和 RotateToGoal 的零线速度约束。
- 下一轮应把 180 度转身改成几何一致、距离足够的移动轨迹，并避免在该实验段调用默认 Spin recovery；可选实现包括多段轴对齐/圆弧 waypoint，或基于 TF 的低速闭环曲线机动后再交回 Nav2。应先用本轮前 50s 轨迹选择最小方案。

### Lite3 顺时针转向漂移的经验 waypoint — 2026-07-30

- 在旧 Segment 4 的前 10s，命令以 `angular.z=-0.15rad/s` 为主，位姿从 `(1.467,3.258,yaw=1.325)` 变为 `(1.816,3.658,yaw=-0.111)`；这给出了比理想 unicycle 模型更有用的实机转向落点。
- 第一四分之一转向目标取 `(1.72,3.50,0)`，使机器人在实测轨迹约 7-10s 时同时进入 XY/yaw tolerance，而不是继续绕过目标。
- 第二四分之一转向沿相同漂移方向取 `(2.10,3.50,-pi/2)`，再以同航向直行到 `(2.10,3.25,-pi/2)`；这比旧的单个短对角 `(1.90,3.45,0)` 更符合机器狗实际运动。
- staged 诊断阶段应显式使用无 recovery 的 replanning BT。对该平台，规划失败后的原地 Spin 不是恢复动作，而是会改变 XY 的额外扰动；直接 abort、零速、重新规划下一轮更可控。

### 固定经验转弯点对前段终点波动不鲁棒 — 2026-07-30

- 无恢复 BT 复测证明 `pos1_left_clear` 能稳定解决柜角问题：前三段再次全部 `SUCCEEDED`，且 100ms action overlay 在长时间 1Hz replanning 下仍无 `send_goal failed`。
- 新 Segment 4 的实际起点 `(1.369,3.134,yaw=1.841)` 与用于标定经验点的旧起点 `(1.467,3.258,yaw=1.325)` 相差约 `(-0.098m,-0.124m,+0.516rad)`。`pos1_middle` 的 XY/yaw 容差允许这种终点变化，因此从一次旧轨迹取出的固定绝对转弯点不能稳定复用。
- 到 `pos1_turn_quarter_1=(1.72,3.50,0)` 的 13.34s 轨迹主要在修正 yaw，同时沿 +Y 漂移；最近目标仍有 `0.3517m`。当 yaw 已接近 0 时，机器人已到 `(1.46,3.76)`，下一次重规划无法从漂移后的当前位姿生成有效路径。
- `navigate_w_replanning_time.xml` 达到了预期安全语义：首次 `ComputePathToPose` 失败即使 NavigateToPose abort、取消 FollowPath 并零速，没有调用 Spin/Wait。它避免了二次漂移，但不会修复 DWB/Lite3 的运动学不匹配。
- 下一方案必须消除“固定小绝对点依赖固定起始姿态”这一假设。优先候选是基于实时 TF 的低速闭环曲线运动原语；若仍坚持纯 Nav2 waypoint，则需要更长的空间尺度和能够吸收前一段终点容差的进场几何，而不是继续微调当前 0.35-0.50m 的短转弯点。

### 最新路线可视化的事实边界 — 2026-07-30

- 最新真机运行的原始 5Hz `trace.csv` 只存在于 Jetson 日志目录 `20260730_130157`，本机没有副本；当前网络策略又拒绝 SSH，因此不能诚实恢复完整连续曲线。
- 可确认的最新路线状态是：起点 `(4.65,0.75,pi)`，航点 1 `(1.05,0.75,pi)`、航点 2 `(0.60,2.90,pi/2)`、航点 3 `(1.50,3.25,pi/2)` 成功；航点 4 `(1.72,3.50,0)` 失败。
- 航点 4 的已知实测关键点为起点 `(1.369,3.134,1.841)`、yaw 接近 0 时约 `(1.46,3.76,0)`、停止点 `(1.494,3.781,-0.129)`；这些点足以显示主要问题是向 `+Y` 漂移并越过目标，而不是只在目标附近原地转向。
- Phase 1 地图中越障区域是可通行区；随机锥桶没有进入当前 costmap obstacle layer。路线图不应把整个越障区画成墙，也不应把示例锥桶画成实时感知障碍。

### 联网调研后的闭环控制结论 — 2026-07-30

- NVIDIA Isaac ROS 官方说明：cuVSLAM 使用一个或多个双目相机，并可结合 IMU，输出给导航使用的 odometry；它会用连续双目帧跟踪关键点并估计相机三维运动。因此当前 Nav2 虽然只消费 `/odom`/TF，D455 图像仍已在 cuVSLAM 上游参与位姿估计，不是“完全没用相机”。来源：`https://nvidia-isaac-ros.github.io/repositories_and_packages/isaac_ros_visual_slam/index.html`。
- Nav2 官方 DWB 文档将 DWB 定义为 Dynamic Window Approach，`RotateToGoalCritic` 官方说明是“足够接近目标位置后，只允许机器人转到目标朝向”。当前配置又明确 `max_vel_y=0`，所以 Lite3 转向产生 XY 漂移时，终点阶段没有平移自由度回拉位置。来源：`https://docs.nav2.org/configuration/packages/configuring-dwb-controller.html` 与 `https://docs.nav2.org/configuration/packages/trajectory_critics/rotate_to_goal.html`。
- 当前 Nav2 Rotation Shim 官方说明其适用对象是“能够原地转动”的差速/全向机器人；它在起步或终点仍执行 in-place rotation。Lite3 已实测原地转向伴随明显平移，因此该插件不满足本机前提，而且 Foxy `foxy-devel` 分支也没有 `nav2_rotation_shim_controller` 包。来源：`https://docs.nav2.org/configuration/packages/configuring-rotation-shim-controller.html` 与 Navigation2 官方 GitHub Foxy 分支。
- RPP 在 Navigation2 `foxy-devel` 中存在，官方 Foxy README 明确支持 legged robot，并通过曲率、临近障碍和接近终点调低线速度；可作为后续长距离路径跟踪替代项。但它的 pure rotation 仍不能自动补偿 Lite3 的 XY 漂移，所以不能单独解决当前失败。来源：`https://github.com/ros-navigation/navigation2/blob/foxy-devel/nav2_regulated_pure_pursuit_controller/README.md`。
- MPPI 当前官方实现支持 differential、omnidirectional 和 Ackermann motion model，也支持控制延迟建模；但 Navigation2 `foxy-devel` 没有 `nav2_mppi_controller` 包。为这一个转向问题升级 ROS/Nav2 的迁移风险明显高于收益，暂不采用。来源：`https://docs.nav2.org/configuration/packages/configuring-mppic.html` 与 Navigation2 官方 GitHub Foxy 分支。
- 选定架构：Nav2 保留地图规划和长距离运输；新增三轴 SE(2) 低速闭环负责近端精确 `(x,y,yaw)`，用实时 `map->base_link` 反馈同时修正转向与漂移；Nav2 `/cmd_vel_nav2` 和精调 `/cmd_vel_precision` 必须先经过 lease/watchdog 仲裁，再由唯一 `/cmd_vel` 驱动 Lite3。
- 180 度目标显式指定 `clockwise` 并跟踪连续 yaw，避免 `wrap()` 在起始 yaw 波动时选择相反方向。控制律在本体系使用 `vx=kx*ex+wz*ey`、`vy=ky*ey-wz*ex`，抵消 yaw 变化造成的本体系位置误差耦合。
- 仍需真机确认的唯一执行轴假设是 `CODE_LAT=325` 的正方向。未确认前只允许低速短脉冲；若 ROS `+Y` 与实际方向相反，使用 `--se2-vy-sign -1`，不得靠增大增益掩盖方向错误。
### 当前闭环路线可视化口径 — 2026-07-30 15:09

- 当前未提交实现新增 `nav-only-full-se2` / `nav-only-inspection-se2`：Nav2 到达 `(1.50,3.25,pi/2)` 后，由独立 SE(2) 控制器在同一目标 XY 上闭环顺时针转到 `-pi/2`，再交回 Nav2；路线图默认展示这一当前方案。
- 路线图中的蓝色虚线只编码 waypoint 顺序，不是 Nav2 global/local plan 的连续采样；最新真机视图的橙色实线也只连接已确认关键点，不是缺失的 5 Hz `trace.csv`。
- 图中使用 Phase 1 占用语义：越障区为可通行地面；不把示例锥桶画成实时障碍物。

### 横移方向校准脚本的安全语义 — 2026-07-30 16:40

- 本地审查发现初版 `lite3_udp_smoke.py --test-lateral` 会在横移脉冲之外继续执行原有前进和 yaw 探针，不符合真机前“只确认 CODE_LAT 正方向”的最小动作原则。
- 已将 `--test-lateral` 改为独立序列：三轴零速 → 单次正向横移 → 三轴零速；显式跳过 forward/yaw 探针，退出时仍发送三轴零速 burst。
- 本机非 armed dry-run 只输出 `stop / slow_lateral_positive / stop_after_lateral`，因此现场命令不会夹带额外前进或转向动作。
- 新增两条纯软件回归测试，分别锁定 lateral-only 序列和原默认 forward/yaw 序列；当前全套标准库 `unittest` 为 11/11 通过。
- Jetson 在同步该最后改动前变为 SSH/Tailscale 不可达；`tailscale status` 明确显示 `superwfx666-desktop` offline、last seen 43m。当前不能声称远端脚本已更新，恢复网络后需先同步并再次 dry-run，再考虑 `--armed`。

### SE(2) 真机结果与 TF 延迟判定 — 2026-07-30

- `CODE_LAT` 正方向已由现场确认，路线固定使用 `--se2-vy-sign 1`。
- SE(2) resume 将位姿从约 `(1.448,3.154,1.076)` 控制到 `(1.532,3.262,-0.478)`，位置误差最低约 `0.027m`；XY 没有发散，说明三轴控制律和横移符号正确。
- 两次停止分别由单帧 TF age `0.234s`、`0.321s` 触发。cuVSLAM exporter 时间戳仍持续推进，bridge `udp_errors=0`，因此这是 Host 链路偶发延迟，不是定位冻结。
- 可以有限提高 `se2_tf_max_age` 以容纳传输延迟，但 `se2_tf_freeze_timeout=0.20s`、跳变门禁、控制走廊和速度上限必须保持；若提高到 `0.40s` 后仍只因 age 停止，应重构为分别判定“时间戳在推进但有固定传输延迟”和“时间戳停止推进”，不再继续放宽绝对 age。

### Jetson 重启使 resume 失效 — 2026-07-31

- 当前定位采用 `final_bridge.py --camera-world-rebase base_start`。Jetson/定位栈重启后，机器人当时的物理位置会成为新的 odom 起点，重启前的 `map -> base_link` 坐标不可继承。
- 因此 `nav-only-full-se2-resume` 只适用于同一未重启定位栈中的安全停止恢复；重启后必须把机器人放回官方起点并跑完整 preset，或另行提供可靠的全局重定位，不能仅凭昨晚停止点坐标继续。

### 混合闭环覆盖不能只限于第一个 180 度转身 — 2026-07-31

- 从 `(1.077,3.165,1.179)` 开始的走廊 SE(2) 恢复成功到 `(1.519,3.266,-1.452)`，最近 XY 误差 `0.0196m`、yaw 误差 `0.129rad`；证明三轴闭环能够从约 `0.43m + 2.75rad` 的组合误差中收敛，并通过右上/右下巡检尾段。
- 纯 Nav2 的 `pos1_left_clear -> pos1_middle` 仍可能失败：最近 XY 只有 `0.172m` 时 yaw 差 `2.168rad`，yaw 接近时 XY 又差 `0.287m`。单纯增加 timeout 不会消除 DWB RotateToGoal 与 Lite3 转向漂移的机制冲突。
- 同一问题在 `pos2b_lower_right(yaw=pi) -> grab_area_approach(yaw=0)` 再次出现：线位移仅 `0.5m` 但目标航向反转，机器人先漂到 `(2.212,2.174,0.725)`，随后 GridBased 因当前位置靠近/进入柜体 footprint 边界而无法规划。
- 因此完整路线不能只把第一个 `pos1_middle` 转身换成 SE(2)。所有“短距离 + 大航向变化”的相邻航点都应拆成：Nav2 长距离位置运输到有余量的接管区，再由带静态走廊门禁的 SE(2) 完成位置/航向联合收敛；否则同一故障会在后续段重复出现。
- 当前停止位姿靠近下巡检柜右侧。在静态 map 已判 footprint 可能重叠时，只能先由现场确认物理净空，再执行方向明确、单调远离柜体的低速 `+X` 脱离，禁止直接重发原 Nav2 goal。

### 机器狗接触柜体后的停机边界 — 2026-07-31 15:39

- 用户现场确认实际已接触柜体后，原先“确认净空再低速 `+X` 脱离”的候选方案失效；不能仅根据最后 TF `(2.212,2.174,0.725)` 推断无碰撞方向，也不能自动发任何脱困速度。
- `scripts/stop_all.sh` 能停止导航与运动桥，但本次未停止命名为 `cuvslam_gui_20260731-151130` 的运行中容器；急停后的完整核查必须同时检查 ROS/运动进程和 `docker ps`，必要时显式停止定位容器。
- 三次成功的 Lite3 `stop_burst()`、导航栈停止和空残留核查只证明软件侧不再主动下发运动，不能替代现场对“完全静止、柜体是否持续受力、机械结构是否卡住”的人工确认。
- 接触事件后的恢复边界：先人工解除接触并把机器狗移到已知安全位置；若定位栈已停止，则旧 map 原点和 TF 均不可用于续跑，下一次必须从官方起点 clean 启动。
### Lite3 旋转中心联网核查（进行中）— 2026-07-31

- 当前宿主没有内置 Web Search，也未安装 `infsh`，因此改用公开搜索页和官方站点/GitHub 做只读核查。
- 已确认官方入口：DEEP Robotics 官网 `https://www.deeprobotics.cn/`，官方 GitHub 组织 `https://github.com/DeepRoboticsLab/`。
- 首轮公开搜索未找到“遥控器旋转中心”或 `base_link/TORSO` 原点的直接官方说明；后续将直接核对官方 Lite3 ROS2 仓库、通讯协议和机器人模型。
- 官方 GitHub 组织包含 `Lite3_ROS`、`Lite3_MotionSDK`、`deep_robotics_model`、`gamepad` 和 `Lite3_Navigation` 等仓库。
- 官方 `Lite3_ROS` README 将 `/cmd_vel.linear.x/y` 和 `/cmd_vel.angular.z` 直接定义为运动主机的纵向、横向和偏航速度；其说明要求启动转换节点后通过 App 切到 auto mode，运动主机再执行这些速度命令。来源：`https://github.com/DeepRoboticsLab/Lite3_ROS`。
- 这说明当前 `CODE_YAW=0x0141` 使用的是 Lite3 运动主机的高层角速度接口，不是仓库自定义的关节级旋转算法；但 README 没有说明该接口和遥控器是否自动选择完全相同的步态/旋转中心。
- 官方 `deep_robotics_model` 仓库提供 `Lite3/urdf/Lite3.urdf`，可用于核对 `TORSO` link、惯性原点和腿部几何。来源：`https://github.com/DeepRoboticsLab/deep_robotics_model`。
- 官方 Lite3 URDF 的 `TORSO` link 使用空 `<origin/>` 的惯性原点；机身碰撞几何以 `TORSO` 为中心，前后髋关节相对 `TORSO` 的 x 坐标为 `+/-0.1745m`，左右 y 坐标为 `+/-0.062m`。来源：`https://github.com/DeepRoboticsLab/deep_robotics_model/blob/main/Lite3/urdf/Lite3.urdf`。
- 该模型只定义机身/关节几何，不定义“遥控器旋转时的瞬时支撑中心”或每种步态的旋转中心；因此不能仅凭 URDF 证明开发模式和遥控器的旋转中心完全相同。
- 官方 `Lite3_ROS` 的 ROS2 Foxy 源码在一次 `/cmd_vel` 回调中依次发送 `320=linear.x`、`325=linear.y`、`321=-angular.z`；当前项目 `cmd_vel_bridge.py` 的三轴发送顺序和符号与官方实现一致。来源：`https://github.com/DeepRoboticsLab/Lite3_ROS/blob/ros2-foxy/src/transfer/src/Jetson2Motion.cpp`。
- 同一官方源码把遥控器状态上报为 `left_axis_forward`、`left_axis_side`、`right_axis_yaw`，但没有显示遥控器内部如何生成运动主机控制指令。
- 官方通讯协议区分两套转向入口：移动模式轴指令 `0x21010135`（摇杆/轴值）与持续运动的指定角速度 `0x0141`（rad/s）；当前开发桥使用后一种。公开资料未证明两种入口内部使用完全相同的步态调度、死区或转向中心策略。
- 官方 `protocol.hpp` 的遥控器状态同时含摇杆轴值 `right_axis_yaw` 和运动主机生成的 `goal_vel_yaw`，说明“摇杆输入”和“最终目标角速度”是两个不同字段；但官方 `Jetson2Motion.cpp` 发布 `/handle_state` 时只保留轴值，没有发布 `goal_vel_*`。来源：`https://github.com/DeepRoboticsLab/Lite3_ROS/blob/ros2-foxy/src/transfer/include/protocol.hpp`。
- 官方 `Lite3_ROS` issue 中没有检索到 rotation/turn/angular drift 的公开已知问题。
- 当前工程的 `base_link` 被定义为官方 `TORSO` 原点，D455 外参假设为 `(x=0.080,y=0,z=0.493,pitch=+30deg)`；这组外参转换数学一致，但仍是“工程初始外参”，没有通过“遥控器纯旋转时相机轨迹拟合旋转中心”做过独立标定。
- 最近失败段 `pos2b_lower_right=(2.60,2.00,pi) -> grab_area_approach=(3.10,2.00,0)` 同时包含 `0.50m` 平移和 `180deg` 航向变化，不是纯 yaw 实验；仅凭其终点漂移不能反推出实际旋转中心。
- 若 `base_link` 与真实旋转中心仅相差当前假设的相机前向偏置 `0.08m`，纯旋转造成的报告点位移上限约为 90deg 时 `0.113m`、180deg 时 `0.160m`。更大的位移需要更大的外参误差、实际平移指令、运动主机步态差异或视觉定位误差共同解释。

### 开发接口最小纯 yaw 脉冲边界 — 2026-07-31

- 已验证开发接口可在 `vx=0, vy=0` 时单独发送 `az=0.05rad/s`，持续 `0.5s`，且动作前后完整发送三轴零速。
- 该脉冲理论转角仅约 `1.43deg`，本轮又未启动 cuVSLAM 或记录运动主机位姿，因此不能从这次测试估计旋转中心，也不能比较遥控器与开发接口。
- 正式结论仍依赖同一空旷场地、相近转角的遥控器纯 yaw / 开发接口纯 yaw A/B，并同时记录 `map -> base_link` 与 `RobotState.pos_world`（若可用）。
- 延长测试已以同一 `az=0.05rad/s` 持续 `5.0s` 成功执行，理论转角约 `14.3deg`；由于仍未记录定位轨迹，该轮适合确认肉眼可见的转向/平移现象，但仍不足以拟合旋转中心。
- 用户现场确认该 `5.0s` 开发接口测试看起来是纯转弯、没有明显漂移。这使“Lite3 的 `0x0141` 纯角速度入口本身采用错误旋转中心”降为低优先级；此前路线中的大幅 XY 漂移更应优先检查上层在转弯阶段是否混入线速度、DWB 的连续重规划/终点旋转行为，以及 cuVSLAM/外参报告的厘米级位移。

### cuVSLAM 开启后的开发接口纯 yaw 量化结果 — 2026-07-31

- 测试隔离条件成立：启动栈为 `DOG=false`、`CMD_VEL_BRIDGE=false`、`TASK_MANAGER=false`，`/cmd_vel` 的唯一 publisher 是 arbiter、subscription count 为 `0`；真正运动仅来自 `lite3_udp_smoke.py` 直发的 `vx=0, vy=0, az=0.05rad/s`，持续 `5.0s`。
- cuVSLAM/bridge 测得 yaw 从约 `-1.38deg` 到 `+13.53deg`，变化约 `14.91deg`，与理论 `14.32deg` 一致，说明角速度执行和角度观测基本一致。
- 同一转动窗口内，Host `odom->base_link` 从约 `(-0.0006, +0.0075)` 变到 `(-0.1282, -0.0177)`，报告 `dist_xy=0.1301m`；随后静止基线稳定在约 `(-0.1690,-0.0265)`，相对初始累计偏移约 `0.172m`，连续 5 秒首末位置在 4 位小数上相同。
- 原始 camera pose 在转动窗口也报告约 `0.1517m` 三维位移，因此不能把全部平移简单归咎于 Host planarize；但 `0.130m` 与相机高度 `0.493m * sin(14.9deg)≈0.127m` 同量级，必须优先核查 cuVSLAM 输出 frame、camera orientation 语义及 `camera_to_base + base_start` 的外参组合。
- 由于 `/cmd_vel` 没有 Lite3 订阅者，本轮报告位移不可能由 Nav2/SE(2) 混入 `linear.x/y` 导致。若现场确认本轮仍是肉眼纯转弯，则证据将直接指向定位/frame 链路，而不是底层步态真实平移。
- `map_base_link_trace.py` 因 TF 初始缺失 fallback 行字段超出固定 CSV schema 而写盘失败；bridge 比较 CSV 不受影响，已持久化到 `/home/superwfx666/competition_logs/pure_yaw_cuvslam/20260731_1721/final_bridge_odom_compare.csv`，同时保存 `final_bridge.log` 和启动日志。
- 用户现场确认本轮机器狗肉眼看起来只有旋转，没有约 `13-17cm` 的实际平移。因此本轮定位报告的平移可判定为 frame/外参/视觉位姿链中的伪位移；Lite3 `0x0141` 纯角速度接口和“Nav2 混入线速度”不再是当前主因。

### NVIDIA `release-2.1` 官方资料核对（外部资料）— 2026-07-31

- NVIDIA 官方 `isaac_ros_visual_slam` `release-2.1` README 明确：VSLAM 使用连续双目帧跟踪关键点并估计“camera 的 3D motion”，再输出 odometry 给导航；因此不能仅凭 topic 名把原始 `/visual_slam/tracking/odometry` 当作已转换好的机器人 `base_link` 位姿。来源：`https://raw.githubusercontent.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/release-2.1/README.md`。
- 官方仓库树显示参数和 frame 行为应继续以 `isaac_ros_visual_slam/src/visual_slam_node.cpp`、`include/.../visual_slam_node.hpp` 及 `launch/isaac_ros_visual_slam_realsense.launch.py` 为准；根 README 只链接包级 Coordinate Frames/API 文档，没有给出 `input_left_camera_frame` 的完整定义。来源：`https://api.github.com/repos/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/git/trees/release-2.1?recursive=1`。
- `release-2.1` 官方 `visual_slam_node.cpp` 明确 frame 层级是 `map -> odom -> base_link -> ... -> camera`，`base_frame` 默认 `base_link`，`force_planar_mode` 默认 `false`；官方 RealSense launch 仅将 `base_frame` 改为 `camera_link`，没有设置 `input_left_camera_frame`，也没有开启 `force_planar_mode`。来源：`https://raw.githubusercontent.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/release-2.1/isaac_ros_visual_slam/src/visual_slam_node.cpp` 与同分支 `launch/isaac_ros_visual_slam_realsense.launch.py`。
- NVIDIA 最新包级 API 文档将 `base_frame` 定义为“robot or camera rig 的 base”，将 camera optical frame 定义为镜头中心、ROS optical 轴约定（z 前、y 下），并明确 `/visual_slam/tracking/odometry` 是当前 `base_frame` 的 odometry。该页面是当前 4.x 文档，只用于核对持续不变的 frame 概念，`release-2.1` 的具体参数名仍以对应分支源码为准。来源：`https://nvidia-isaac-ros.github.io/repositories_and_packages/isaac_ros_visual_slam/isaac_ros_visual_slam/index.html`。
- `release-2.1` `visual_slam_impl.cpp` 显示：`input_base_frame` 为空时回退到 `base_frame`；只有 `input_left_camera_frame` 非空才读取 `base -> left` TF。当前 bench 配置两者均为 `camera_link`，得到 identity，与官方 RealSense 示例留空时的实际输出变换等价，因此该参数覆盖本身不能解释本轮 `15.17cm` raw position 变化。
- 同一源码显示 `configuration.planar_constraints = force_planar_mode ? 1 : 0`，它直接改变 cuVSLAM tracker，而不是只对 ROS 输出做平面化。当前工程 `planar_60fps` 默认 `true`，官方 `release-2.1` RealSense 示例使用源码默认 `false`；这是下一轮最小 A/B 应隔离的唯一配置变量。来源：`https://raw.githubusercontent.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/release-2.1/isaac_ros_visual_slam/src/impl/visual_slam_impl.cpp`。
- 离线分解 `seq 7600 -> 8190`：Host `0.1301m` 平移中，旋转后的 raw position 贡献 `0.1517m`，外参姿态杠杆项仅 `0.0276m` 且部分抵消；raw 相对 quaternion 与“相机下倾 30°、机身纯 yaw”理论 quaternion 的总角误差约 `2.57°`。因此 Host bridge 数学不是主误差源，cuVSLAM tracker 的 raw translation 才是当前待修对象。

### `force_planar_mode=True` 基线启动日志核验 — 2026-07-31

- 基线持久日志 `/home/superwfx666/cuvslam_lite3_logs/20260731-171628/` 的生成 launch 明确设置：`force_planar_mode=True`、`base_frame=camera_link`、`input_base_frame=''`、`input_left_camera_frame=camera_link`、`input_imu_frame=camera_gyro_optical_frame`、`enable_imu_fusion=True`。
- `launch.log` 中 `Visual tracking is lost=0`、`ERROR=0`；因此基线 `15.17cm` raw translation 不是一次显式 tracking-lost/relocalization 跳变。
- 同一日志有 542 条 `Delta between current and previous frame ... above threshold 22ms`，覆盖 363.69 秒，约 89.42 条/分钟。多数 delta 为约 33.4ms，并有 50/66/83ms 等漏帧倍数。
- 另有 6 条 RealSense WARN，其中启动期出现两条 `Motion Module failure` hardware notification。因为这些输入时序与 IMU 状态也可能影响 VIO，下一轮必须保留并对比这些指标；但单变量 A/B 不同时修改帧率、jitter threshold 或 IMU 参数。

### `force_planar_mode=False` 首轮测试为何尚不能作为 A/B — 2026-07-31

- 启动与隔离门禁成立：生成 launch 明确为 `force_planar_mode=False`，其他 frame、IMU、`planar_60fps` 和 Host bridge 设置与基线一致；`/cmd_vel` 只有 arbiter publisher、subscription count 为 0，测试仍由底层 `vx=0, vy=0, az=0.05rad/s` 持续 5 秒完成。
- 完整 14,566 行 comparison CSV 中，Host yaw 全程跨度只有 `0.03939deg`，raw quaternion 相对初始的最大总转角只有 `0.089568deg`；raw 最大位移 `0.001656m`，Host 最大位移 `0.001274m`。
- 这不是可直接宣称“关闭 planar 修复伪平移”的有效 A/B，因为 cuVSLAM 数据里没有出现基线所见的约 `14.9deg` 旋转刺激。必须先区分“Lite3 本轮没有实际执行转动”和“机器狗实际转了但 cuVSLAM 在非 planar 模式完全没有观测到”。
- false 轮日志 `Visual tracking is lost=0`、`ERROR=0`、Motion Module failure=0；frame-delta 告警为 677 条/309.38 秒，约 `131.29/min`，高于 true 基线的 `89.42/min`。输入时序状态并不完全同质，进一步说明不能只比较最终位移。
- 远端静态日志目录：`/home/superwfx666/competition_logs/pure_yaw_cuvslam_force_planar_false/20260731_1747/`；本机静态 CSV：`C:\Users\111\AppData\Local\Temp\qrc_pure_yaw_force_planar_false_20260731_static.csv`。

### Lite3 底层状态独立记录依据（官方源码）— 2026-07-31

- 当前 `scripts/test_leg_odom_pid.py` 虽定义 `DOG_STATE_PORT=43897` 且注释称读取 `RobotState UDP`，实际实现只轮询 `/tmp/odom_latest.json`，不能独立确认 Lite3 是否执行了角速度。
- DEEP Robotics 官方 `Lite3_ROS` `ros2-foxy` 的 `protocol.hpp`：`RobotState` 含 `rpy[3]`、`pos_world[3]`、`vel_world[3]`、`vel_body[3]`；`HandleState` 含摇杆轴与 `goal_vel_forward/side/yaw`。来源：`https://github.com/DeepRoboticsLab/Lite3_ROS/blob/ros2-foxy/src/transfer/include/protocol.hpp`。
- 官方 `Jetson2Motion.cpp` 默认在 Jetson `43897/UDP` bind 接收多种帧，按包长区分；`RobotStateReceived` code 为 `2305`，`HandleStateReceived` code 为 `2309`。但官方 `/handle_state` 只发布 `left_axis_*`/`right_axis_yaw`，没有发布结构中已有的 `goal_vel_*`，所以需要只读原始 UDP 记录器。来源：`https://github.com/DeepRoboticsLab/Lite3_ROS/blob/ros2-foxy/src/transfer/src/Jetson2Motion.cpp`。
- 新增的只读探针在 Jetson 静止 3 秒内收到 6616 个 UDP 包：code/length 包括 `2305/212=600`、`2309/60=601` 等。HandleState 六个 double 正确解出，`goal_vel_forward/side/yaw` 均为 0。
- 真机 code 2305 的 wire length 是 212、header `size=200`，与按公开 `protocol.hpp` 局部 pragma 直接推导的 216 不一致；虽然当前假定偏移能接受包长，但 rpy/pos 解出非物理数，说明 payload ABI 仍不对。RobotState 在取得 raw hex并与官方 MotionSDK 对齐前不得用于运动结论。
- GitHub REST API 匿名限额已耗尽；改用 `git clone --depth 1` 获取 DEEP Robotics 官方 `Lite3_MotionSDK`，当前官方 `main` HEAD 为 `b30a3ec09619e1dd0f3cfa6c49a50eb59670f141`，临时只读副本在 `C:\Users\111\AppData\Local\Temp\Lite3_MotionSDK_official_20260731`。
- MotionSDK 的公开 `receiver.h` 只暴露 `RobotData` 高层接口，UDP 解包在预编译 `.so` 中；README 只确认运动主机向开发机 `target_port=43897` 上报数据，没有提供 code 2305 wire struct。
- 真机首帧 hex + header `size=200` 明确显示当前固件 wire payload 与 `Lite3_ROS protocol.hpp` 的差异：payload 起始只有 `robot_basic_state`、`robot_gait_state` 两个 int，公开头文件中的第三个 `robot_policy_state` 不在 wire 中；随后 `rpy[3]` 从包绝对偏移 20 开始。删除该 4 字节后，pack(4) 布局恰好为 payload 200 / packet 212 字节。
- 修正后静态解码得到物理合理值：`rpy≈(-0.001,0.056,28.514)deg`、`pos_world≈(-0.657,-0.065,0.324)m`、`battery=41%`，证明 RobotState 关键字段布局正确。
- 在不启动 cuVSLAM 的 16 秒底层对照中，记录器先运行 3 秒，再执行 5 秒 `az=0.05rad/s`。3193 帧 RobotState 的 yaw 范围只有 `28.4952..28.5336deg`（span `0.0384deg`），rpy_vel_z 为约 `-0.005..0.0065` 静态噪声；3193 帧 HandleState 的 `goal_vel_forward/side/yaw` 全程均为 0。
- 因而 `force_planar=false` 首轮不是“机器狗真实旋转但 cuVSLAM 不跟踪”，而是本次运动主机没有接受/执行角速度；不能把 1mm 级 VSLAM 位移计入 A/B。当前需先恢复 Lite3 可接受速度命令的 auto/motion 状态。
- `stop_all.sh` 只终止进程，不发送 Lite3 模式切换；`lite3_udp_smoke.py` 的 heartbeat→auto→motion 与 bridge 初始化指令相同，但时序比 `prepare_lite3_motion_mode.py` 略短。下一步优先运行后者的无运动准备序列并记录 basic/gait/motion state，不使用非幂等的 stand/lie toggle。
- 纯模式准备探针成功发送 50 个 simple 包和 48 个三轴零速 complex 包、`errors=0`；但完整 2400 帧 RobotState 的状态组合始终为 `robot_basic_state=1, robot_gait_state=0, robot_motion_state=0`，没有任何短暂切换。因此不是 smoke 初始化等待时间过短，当前 auto/motion 简单指令本身未改变运动主机状态。
- 官方 Lite3_ROS 使用说明要求先通过 App 切到 auto mode 后再执行 SDK 速度命令；结合本轮状态证据，下一步需要现场 App/遥控端切换，而不是继续远程重发相同指令或冒险发送 stand/lie toggle。
### 有效 `force_planar_mode=false` A/B 结论 — 2026-08-02

- 本轮 Lite3 底层状态证明确实执行了纯 yaw：`goal_vel_yaw` 非零约 5 秒，RobotState yaw 变化 `14.435deg`；cuVSLAM 同期 yaw 为 `14.911deg`，旋转刺激与基线可比。
- Lite3 `pos_world` 同期变化 `0.04752m`，说明机器自身估计/实际步态并非数学意义上的零平移；但 cuVSLAM raw/Host 稳定净位移分别为 `0.126875m` 和 `0.129515m`，仍显著更大。由于二者坐标系和估计来源不同，不能直接做标量相减后宣称剩余值就是 VSLAM 误差。
- `force_planar_mode=true` 基线 raw/Host 为约 `0.15169/0.13011m`；false 轮为约 `0.12688/0.12952m`。Host 结果几乎不变，raw 虽略降但仍为 12.7cm 量级，因此 planar constraint 不是伪平移根因。
- false 轮无 tracking lost、无 ERROR，但 frame-delta 约 `132.57/min` 且出现 2 次 D455 Motion Module failure。结合 true/false 两轮均有大量 frame-delta、均在开启 IMU fusion 时出现同量级平移，IMU 输入/外参/时序是下一项应核验的变量，而不是继续调整 Host bridge 掩盖 raw pose。
- 下一步先离线计算：用 Lite3 `pos_world + yaw` 估计 base 运动，再用 `base_link -> camera_link=(0.08,0,0.493,pitch=+30deg)` 推导纯刚体 camera 轨迹，与 cuVSLAM raw `0.126875m` 对比。完成官方 `release-2.1` IMU frame/外参核对后，再决定是否执行 `enable_imu_fusion=false` 单变量测试。

### `release-2.1` IMU 配置官方源码核对 — 2026-08-02

- NVIDIA 官方 `release-2.1` RealSense launch 使用 `unite_imu_method=2`、`base_frame=camera_link`、`input_imu_frame=camera_gyro_optical_frame`、`enable_imu_fusion=True`，并将 `visual_slam/imu` 重映射到 `camera/imu`。当前 bench 配置与这组官方 IMU 接法一致。来源：`https://raw.githubusercontent.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/release-2.1/isaac_ros_visual_slam/launch/isaac_ros_visual_slam_realsense.launch.py`。
- 同版本 `visual_slam_node.cpp` 中 `enable_imu_fusion` 的参数默认值为 false，但官方 RealSense launch 显式开启；IMU callback 在 tracker 未初始化或该参数为 false 时直接返回。来源：`https://raw.githubusercontent.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/release-2.1/isaac_ros_visual_slam/src/visual_slam_node.cpp`。
- 同版本 `visual_slam_impl.cpp` 仅在融合开启时从 TF 树读取 left-camera 到 `input_imu_frame` 的变换，并设置 `configuration.enable_imu_fusion=1`；关闭时设置为 0，不注册 IMU。故 `enable_imu_fusion=false` 能作为下一轮单变量 A/B，不需要同步修改 frame 或 bridge。来源：`https://raw.githubusercontent.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/release-2.1/isaac_ros_visual_slam/src/impl/visual_slam_impl.cpp`。
- 有效 false 轮日志显示 `left_camera_pose_imu reading from TF Tree`、`Enable IMU Fusion: true`，说明当前配置的 IMU 外参查询成功；同时 D455 启动期出现两条 `Motion Module failure`，但该日志本身不能证明随后的 IMU 数据错误。

### Lite3/相机刚体几何初步分解 — 2026-08-02

- 依据 `goal_vel_yaw`，有效动作窗口为 `6.8428..11.8427s`，RobotState 的 motion state 约在 `12.6881s` 回稳。取动作前 `5.8..6.7s` 与回稳后 `13.0..14.0s` 的中位姿态，Lite3 `pos_world` 平移约 `0.04897m`，yaw 变化约 `14.841deg`。
- 将 `base_link -> camera_link` 平移 `(0.08,0,0.493)` 随 Lite3 实测 RPY 旋转，外参杠杆项约 `0.02328m`；与 base 平移按方向合成后，理论 camera 刚体位移约 `0.06548m`。该数值约为 cuVSLAM raw 稳定净位移 `0.12688m` 的一半，说明实测步态平移和相机偏置能解释一部分，但不能解释全部 raw translation。
- 纯 yaw 在姿态不变时只会通过相机水平偏置 `0.08m` 产生约 `2*0.08*sin(14.84deg/2)=0.02066m` 的相机弧弦位移；相机高度 `0.493m` 不会因纯 yaw 自动变成水平位移，只有机身 roll/pitch 改变时才参与杠杆项。此前用 `0.493*sin(yaw)` 解释 13cm 的直觉不符合刚体旋转几何，应废弃。
- Lite3 与 bridge CSV 没有共同时间戳字段；上述几何分解直接使用 Lite3 同一记录器的时间轴，cuVSLAM 只比较该轮已统计的稳定净位移，不冒充逐帧硬同步。

### `enable_imu_fusion=false` 真机 A/B 结论 — 2026-08-02

- IMU-off 轮与有效 IMU-on/planar-off 轮的运动刺激可比：Lite3 yaw `14.804deg` vs `14.435deg`，`pos_world` 稳态位移 `0.05068m` vs `0.04752m`；两轮 `goal_vel_forward/side` 都始终为 0。
- IMU-off 的 cuVSLAM raw/Host 稳态位移为 `0.14970/0.15217m`，IMU-on 为 `0.12688/0.12952m`。关闭融合没有降低伪平移，反而在这一次重复中高约 2.3cm；单轮差值不能证明 IMU 有益，但足以否定“IMU fusion 是约 13cm 平移的必要根因”。
- IMU-off 日志无 tracking lost、ERROR、Motion Module failure，frame-delta 约 `82.86/min`，低于 IMU-on 的 `132.57/min`；因此本轮较大的平移不能归因于更差的上述日志指标。
- 源码行为与运行日志一致：融合关闭后不读取 `left_camera_pose_imu`，日志中该条为 0 次，tracker 显示 `Enable IMU Fusion: false`。这轮确实隔离掉了 IMU，不是参数未生效。
- IMU-off 的 Lite3 几何预测 camera 位移约 `0.06712m`（base `0.05068m` + 外参杠杆 `0.02229m` 按方向合成），仍仅为 cuVSLAM raw `0.14970m` 的约 45%。主要未解释量仍位于视觉 pose/坐标 frame 或 Lite3 `pos_world` 作为实际运动代理的不足，不能在 Host bridge 里裁掉。
- 当前优先级转向 frame 语义核验：官方 `release-2.1` RealSense launch 没有显式设置 `input_left_camera_frame`，而当前 bench profile 显式设为 `camera_link`。必须从源码确认留空时是否使用真实 image header optical frame，以及这是否改变 cuVSLAM pose 发布/标定变换，再决定下一轮单变量测试。

### `input_left_camera_frame` 留空/显式设置源码等价性 — 2026-08-02

- `release-2.1` 初始化时先令 `in_base_link=input_base_frame`，为空则回退到 `base_frame`；只有 `input_left_camera_frame` 非空才查询 `in_base_link -> input_left_camera_frame` TF。当前 `base_frame=camera_link,input_base_frame=''`，若留空则 `base_link_pose_left=identity`；显式设为同一个 `camera_link` 时查询 `camera_link -> camera_link`，仍为 identity。
- odometry 计算为 `initial_odom_pose_left * ros_vo_pose * base_link_pose_left.inverse()`，`child_frame_id` 始终写 `base_frame`。因此当前显式 `camera_link` 与 NVIDIA RealSense launch 的留空行为在 tracker/odometry 数学上等价，不会自动改用图像消息的 optical `header.frame_id`。
- IMU 开启时，留空的 `input_left_camera_frame` 会把 `left_cam_frame` 回退到同一个 `in_base_link=camera_link`；显式 `camera_link` 也从 `camera_link` 查询到 `camera_gyro_optical_frame`。IMU 外参路径同样等价。
- 结论：不执行“仅清空 `input_left_camera_frame`”真机 A/B；它不是有效变量。若后续测试官方内部 robot-base 变换，必须整体使用 `base_frame/input_base_frame=base_link` 与真实 `input_left_camera_frame=camera_infra1_frame`，而这会改变多个 frame 参数，不能伪装成单变量。

### NVIDIA 官方 issue 中的 D455 drift 线索 — 2026-08-02

- 官方仓库 issue #67 报告 D455 在 `848x480x60` 下出现明显 drift/scale 偏差；NVIDIA 维护者首先要求关闭 RealSense IR emitter，并建议使用更新后的官方 RealSense launch。当前工程已设置 `depth_module.emitter_enabled=0`，该项无需再测。来源：`https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/issues/67`。
- issue #67 提问者指出其与更新 launch 的主要差异是分辨率/帧率，并询问 90 FPS 是否为合理 drift 的必要条件；该问题没有维护者后续定量答复，不能把 90 FPS 当作已知修复，但可作为官方配置对齐的单变量 A/B。
- issue #183 的 D455 pose jump 案例同样提到 emitter 和正确分辨率的重要性，但其表现是米级/百米级突跳；当前三轮无 tracking lost、无 pose jump，症状不完全相同。来源：`https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/issues/183`。
- issue #21 的参与者在 Isaac ROS `2.1.0` 实测 `base_frame/input_base_frame` 变换已正常，和当前阅读到的 `release-2.1` 源码一致；旧版本 frame bug 不能直接套到当前运行栈。来源：`https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/issues/21`。
- 下一项测试采用 `640x360x90`，显式保持 `force_planar_mode=false`、`enable_imu_fusion=true`、bench frame、emitter off、Host bridge 和同一 5 秒纯 yaw 不变。与有效 60 FPS IMU-on 轮比较，可直接检验更高视觉采样率是否降低旋转中的 translation drift。

### 90 FPS A/B 与三轮 SE(3) 统一分解 — 2026-08-02

- 90 FPS 轮生成 launch、RealSense 开流日志均确认双 IR 为 `640x360x90`；IMU fusion=true、planar=false、emitter off。运动刺激有效且线速度目标严格为零：Lite3 yaw `14.73deg`，`pos_world` 位移 `0.05524m`。
- 90 FPS cuVSLAM raw/Host 稳态位移 `0.11754/0.12086m`，比 60 FPS IMU-on 的 `0.12688/0.12952m` 低约 7%；但仍为 12cm 量级，不能视为解决。日志无 tracking lost/ERROR/Motion Module failure，frame-delta 约 `189.20/min`。
- 将三轮 Lite3 `pos_world` 位移旋回每轮动作开始时的机身坐标，得到约 `(-0.0467,-0.0148)`、`(-0.0481,-0.0160)`、`(-0.0527,-0.0166)m`。方向和数量级高度一致，说明“线速度命令为零”不等于 Lite3 步态/自身里程计中的平移为零；用户肉眼主要看到旋转并不能排除约 5cm 的系统性步态漂移。
- 使用完整 `T_world_base * T_base_camera` 预测 camera 相对运动，三轮理论平移为 `0.06548/0.06712/0.07033m`，cuVSLAM raw 为 `0.12676/0.14964/0.11754m`；raw 减预测的向量残差范数分别为 `0.06130/0.08266/0.04801m`。对应姿态误差仅 `1.27/2.40/2.19deg`，主要问题仍是 translation，而非 yaw 完全跟丢。
- 当前不能把 4.8–8.3cm 残差全部叫作 VSLAM 误差，因为 Lite3 `pos_world` 不是外部 ground truth；但也不能把 12–15cm 全归因于相机杠杆或 Host bridge。下一项高信息量测试应是同一定位会话中的正反 yaw 闭合：若 Lite3 回到原点而 cuVSLAM 不回，则直接证明 VSLAM 不闭合；若两者都有同向残差，则底层步态净漂移占主导。

### 正反 yaw 闭合测试门禁修正 — 2026-08-02

- 当前 `planar_90fps` 生成 launch 用 `depth_module.profile='640x360x90'` 配置双 IR；没有同时生成 `depth_module.infra_profile`。启动日志明确报告 `CUVSLAM_CAMERA_PROFILE=640x360x90`，且生成 launch 同时为 `force_planar_mode=False`、`enable_imu_fusion=True`。
- 因此自动化门禁只应验证真实生成字段和运行日志，不能要求不存在的冗余字段。误断言发生在运动前，失败清理后 Lite3 仍为三轴零速，未污染闭合数据。

### 90 FPS 正反 yaw 闭合结论 — 2026-08-02

- 同一定位会话内的实际底层刺激成立：`+0.05rad/s` 与 `-0.05rad/s` 各约 `4.99s`，两段 `goal_vel_forward/side` 始终为 0，Lite3 yaw 分别变化 `+14.747deg/-13.805deg`。
- Lite3 `pos_world` 在两种 yaw 方向下都沿近似同一机身方向累加：正转 XY `4.826cm`、反转 XY `5.729cm`，最终净 XY `10.526cm`，净 yaw 仅 `+0.942deg`。这排除了“反向 yaw 会把底层平移自动抵消”的假设。
- cuVSLAM/Host 的角度也基本回到起点，但位置没有闭合：raw 最终净 XY/三维位移 `20.822/23.689cm`，Host 最终净 XY `23.661cm`，Host 净 yaw `+1.561deg`。正转和反转的 Host 位移分别约 `13.259cm/10.762cm`，同样是累加而非抵消。
- 两个独立估计源都给出同方向净漂移，说明底层步态实际平移或 Lite3 自身里程计系统偏差占显著部分；cuVSLAM 的净平移约为 Lite3 XY 的 `2.25x`，说明视觉定位仍有额外不闭合。由于 Lite3 `pos_world` 不是外部真值，不能把两者差值直接定义为 VSLAM 误差。
- 不能根据本轮直接在控制器中加入 `vx` 前馈：若现场肉眼观察仍认为机身基本未平移，则 Lite3 与 cuVSLAM 可能都在高估。下一项必须使用独立外部基准（地面标记/俯视固定相机/固定标靶测距）量测机身中心的真实闭合位移，再决定补偿增益。

### 完整 NavOnly 原地转向的 DWB 位置修正假设 — 2026-08-02

- 用户补充观察：单独纯 yaw 脉冲时机身基本绕质心转动；完整 NavOnly 流程在同类转向时伴随 XY 漂移，怀疑 DWB 在旋转同时继续修正目标位置。
- 当前 Nav2 DWB 配置确实允许该行为：`max_vel_x=0.10`、`max_vel_y=0`、`max_vel_theta=0.15`，`xy_goal_tolerance=0.15m`、`yaw_goal_tolerance=0.30rad`，critics 包含 `RotateToGoal`、`PathAlign`、`PathDist`、`GoalDist`。
- NVIDIA/ROS Nav2 官方 DWB `RotateToGoalCritic` 源码显示：未进入 XY 容差时 `scoreTrajectory()` 直接返回 0，不限制平移；进入容差后先要求减小平移速度，当前速度达到 `trans_stopped_velocity` 后才将任何非零 `vx/vy` 判为非法，只保留旋转。来源：`https://raw.githubusercontent.com/ros-navigation/navigation2/main/nav2_dwb_controller/dwb_critics/src/rotate_to_goal.cpp`；文档：`https://docs.nav2.org/configuration/packages/trajectory_critics/rotate_to_goal.html`。
- 因此完整流程中如果姿态尚未进入 `xy_goal_tolerance`，DWB 可能输出 `vx!=0` 与 `angular_z!=0` 的组合命令。虽然 `max_vel_y=0` 禁止机身侧向速度，但机身前向速度在旋转后映射到世界坐标会表现为 X/Y 漂移。单独纯 yaw 脉冲没有 Nav2 的目标误差闭环，二者不是同一个控制条件。
- DWB `stateful=true` 只表示进入 XY 容差后记住该状态并继续终端旋转；它不能阻止“进入容差之前”的平移修正。当前 `xy_goal_tolerance=0.15m` 和实时 cuVSLAM 漂移足以让控制器长时间处于位置修正阶段。
- 现有 2026-07-30 纯 DWB 实测已经有同方向证据：同点转向段命令中 `angular_z_nonzero_count=987`，同时 `linear_x_nonzero_count=373`，从 `(1.369,3.134,1.841)` 漂到 `(1.494,3.781,-0.129)`，XY 漂移约 `0.659m`；这与“DWB 旋转中仍给前向修正”一致，但不能单独证明全部漂移都来自 DWB，因 Lite3 步态和 cuVSLAM 也有独立漂移。
- 高信息量 A/B：保持地图、起点、目标和底层 bridge 不变，记录 `/cmd_vel` 与 `map->base_link`；比较完整 NavOnly 的原始 DWB 段和“到达 XY 后取消 Nav2、由仅 yaw 控制器接管”的段。若后者漂移明显下降，DWB 位置修正就是主要增量；若仍接近纯 yaw 闭合结果，则底层步态/定位误差占主导。
- 临时参数验证可把 `RotateToGoal.xy_goal_tolerance`/goal checker 的位置容差与目标点设计分开做 A/B，但不能把 `max_vel_x=0` 直接作为比赛修复：它会让距离 XY 目标的 Nav2 goal 无法收敛。更稳妥的是采用已实现并验证过的 SE(2) precision takeover，在明确达到位置条件后显式发送 `vx=0, vy=0, wz`，并保留 TF 新鲜度、跳变和安全走廊门禁。
- 机器人状态估计研究的共同结论是：接触/关节腿式里程计与视觉/IMU 用 EKF/InEKF 融合可降低短时漂移，但融合两个有偏的里程计不会自动得到绝对真值；必须先标定协方差、时间戳、`base_link` frame，并通过外部标记/激光或回环提供绝对约束。参考：`https://arxiv.org/html/2504.20615v1`、`https://proceedings.mlr.press/v164/lin22b/lin22b.pdf`。

### `nav-only-full` 实测对 DWB 混合控制假设的验证 — 2026-08-02

- 本轮前 5 段成功、第 6 段超时，说明当前 Navigation-only 主链路、cuVSLAM bridge、Nav2 action 和 Lite3 UDP 下发均可连续工作约 7.8 分钟；故失败不是启动链路或 UDP 零输出。
- 同点 180 度第 3 段有 58.5% 命令样本同时满足 `linear.x!=0` 与 `angular.z!=0`；实际 XY 位移 0.281m。该直接命令证据确认完整 NavOnly 中并非纯 yaw，而是 DWB 持续边转边修位置。
- 第 3 段最小 XY 误差仅 0.003m 时 yaw 误差仍 2.614rad；最小 yaw 误差 0.005rad 时 XY 误差已扩大到 0.352m；全段只有 1 个样本同时满足 `xy<=0.15m` 与 `|yaw|<=0.30rad`，最终以 `xy=0.143m,yaw=0.298rad` 擦边成功。这是位置与朝向交替满足、难以同时收敛的定量证据。
- 第 6 段 `grab_area_approach` 最小 XY 误差为 0.180m，始终未进入 0.15m 目标窗口；最接近 XY 时 yaw 误差 2.85rad，yaw 最接近目标时 XY 误差 0.402m。最终 `xy=0.193m,yaw=0.229rad`，即朝向已满足但位置仍超容差。
- 第 6 段后期 `GridBased` 无法从漂移后的 pose 规划至 `(3.10,2.00)`，但 final bridge 延迟稳定 17-23ms、UDP errors=0。因此应优先处理 `grab_area_approach` 的大角度终端姿态与位置耦合/目标点可达性，而不是继续调整 cuVSLAM传输或加大超时。
- 下一轮高价值改动仍是两阶段控制：Nav2 先到安全 XY 接近区，随后取消 DWB，由 yaw-only 或有明确安全走廊的 SE(2) precision controller 完成姿态；本轮数据已经提供可对照的 DWB 基线。

### 2026-08-03 `pos1_middle_turned` 回归证据

- 两轮最新日志 `20260803_140405_full_nav_manual`、`20260803_141402_full_nav_manual` 都在 `pos1_middle_turned` 超时；`obstacle_cross_target`、`pos1_middle` 均成功。失败段起点分别约 `(1.53,3.11,1.28)`、`(1.52,3.16,1.28)`，与昨晚成功轮起点同一量级。
- 今天两轮失败段均出现持续 `linear.x=0.1m/s` 与 `angular.z=-0.15rad/s` 重叠，线速度非零比例为 `2788/5241=53.2%`、`3038/5236=58.0%`，最终向 `x=1.10/1.12m` 漂移约 `0.40m`，yaw 仍在 `1.18/1.07rad`，没有接近目标 `-1.57rad`。
- 昨晚成功轮 `20260802_205944_full_nav_manual` 同段仅 `595/2003=29.7%` 线速度非零，角速度正负切换，最终 `(1.49,3.23,-1.85)`。因此“转圈直到超时”对应的是 DWB 终端平移与旋转耦合进入不同控制分支，具备明显运行间非确定性。
- 不能仅增加 timeout；增加时间会让弧线漂移继续扩大。应在 `pos1_middle` 位置条件满足后取消 DWB，接管 `vx=0,vy=0` 的 yaw-only 或 SE(2) 精调，并保留 TF 新鲜度、跳变和安全走廊门禁。

### 2026-08-03 SE(2) 未接管与 1Hz 重规划重置

- `nav-only-full` 与 `nav-only-full-se2` 是两个不同 preset：前者的 `pos1_middle_turned` 为普通 `kind=nav2`；后者才使用 `kind=se2_pose` 并向 `/cmd_vel_precision` 发布。昨晚最佳轮和今天两轮都运行前者，三份 summary 中没有任何 SE(2) segment/control mode。
- `cmd_vel_arbiter` 不负责根据位姿自动切换控制器。它只做话题优先级：有新鲜 `/cmd_vel_precision` 时覆盖 `/cmd_vel_nav2`，没有 precision 输入时转发 Nav2。因此“仲裁器节点在线”不等于“SE(2) 精调已生效”。
- Nav2 Foxy 默认 `navigate_w_replanning_and_recovery.xml` 每 1 秒计算新路径。Controller Server 的 `setPlannerPath()` 每次调用 controller `setPlan()` 后调用 `goal_checker_->reset()`；DWB `setPlan()` 又逐个 `critic->reset()`。这会同时清除 SimpleGoalChecker 的 XY 锁存和 RotateToGoalCritic 的 `in_window_/rotating_` 锁存。
- 三轮第 3 段初始 XY 误差为 `13.8cm`（昨晚成功）、`17.8cm`（今天失败）、`12.5cm`（今天失败），恰好跨越 `15cm` 门限。即使起点在门限内，转动中的 cuVSLAM/Lite3 报告位移也可在下一次 1Hz reset 前后把估计推到门限外，使 DWB 从纯旋转重新退回平移+旋转。
- 当前 DWB `min_vel_x=0,max_vel_x=0.10,max_vel_y=0`，不能后退或横移；门限外的位置修正只能主要依靠正向弧线。该弧线又改变目标位置误差和 yaw，形成对定位噪声、起始误差与重规划相位敏感的混合控制循环。
- 昨晚成功不代表参数稳定：它只是某次轨迹在重置间隔内短暂同时满足了位置和 yaw 判定。今天两轮在 130 秒内均曾分别接近位置或 yaw，但没有在 Controller Server 20Hz 判定周期内稳定完成联合条件。
- 当前 `se2_pose` 也不是 yaw-only：默认允许 `vx<=0.06m/s`、`|vy|<=0.04m/s`、`|wz|<=0.12rad/s` 来同时修正 XY/yaw。它比 DWB 更明确且有走廊/TF门禁，但若要隔离“只转不走”，仍需独立 yaw-only 控制模式。

### 推荐的 precision turn 状态机

- `NAV_APPROACH`：Nav2 到 `pos1_middle=(1.50,3.25,+pi/2)`，action 自然结束。
- `TAKEOVER_STOP`：向 `/cmd_vel_precision` 连续发布三轴零速约 `0.5s`，确认 arbiter 有订阅者并取得 precision lease。
- `COARSE_YAW`：当 `|yaw_error|>0.35rad` 时固定 `vx=0,vy=0`，仅输出 `wz=clamp(k_theta*yaw_error,0.12rad/s)`，角加速度限制约 `0.30rad/s^2`。
- `FINE_POSE`：进入小角度区后才允许低速 XY/yaw 联合修正；建议先以 `|vx|<=0.03m/s`、`|vy|<=0.02m/s`、`|wz|<=0.06rad/s`、位置容差约 `0.12-0.15m` 验证，避免重新制造大弧线。
- `SETTLE`：yaw/position 条件连续满足约 `1s` 才成功；期间保持三轴零速。
- `ABORT`：离开预验证走廊、anchor 位移过大、TF 连续陈旧/冻结、无进展或总超时均三轴零速退出。单个陈旧 TF 周期只零速等待，不继续沿用旧命令。
- 生产 preset 应显式包含 precision kind，并在 summary/trace 记录 `control_mode`；没有该字段就直接判定本轮 precision 未运行。

### yaw-only 生产接管实现结论 — 2026-08-03

- 生产入口现在直接使用既有命令名 `nav-only-full` / `nav-only-inspection`，但第 3 段已明确变为 `kind=yaw_only`；原 DWB 行为改名为 `*-dwb-baseline`。这比增加另一个容易选错的 hybrid preset 更能消除“仲裁器在线但 precision 没接管”的操作风险。
- yaw-only 不是 Nav2 action，也不调用 DWB，因此不受 1Hz 路径重规划、GoalChecker reset 或 `RotateToGoalCritic` reset 影响。它从 `pos1_middle` 完成时的实时 TF 建立 anchor，固定目标位置为观测用途，不尝试用线速度追踪 XY。
- 大角度和细调阶段都严格保持 `vx=vy=0`；区别仅为 `|wz|<=0.12rad/s` 与 `|wz|<=0.06rad/s`。这次没有启用此前建议的 `FINE_POSE` 三轴修正，因为当前首要目标是隔离并验证纯转向接管，避免在小角度区重新引入平移耦合。
- `/cmd_vel` 线速度监视是端到端门禁：只要 arbiter 输出中出现非零 `linear.x/y`，该段立即零速退出。它能捕获错误 lease、其他发布者或意外混入 Nav2 命令，而不只依赖控制器内部输出断言。
- `--describe-route` 在 `rclpy.init()` 前返回，使测试前可以机械确认 route kinds。Jetson 实测生产路线前 3 段为 `nav2, nav2, yaw_only`，可作为真机启动前的固定门禁。
- 无狗 ROS 图确认当前仲裁拓扑正确：arbiter 是 `/cmd_vel` 唯一发布者，precision 与 Nav2 输入均只有 arbiter 订阅；bridge 关闭时 `/cmd_vel` 无订阅者，因此本轮构建和图验证不能驱动 Lite3。
- 当前剩余不确定性仅在真机动力学和 cuVSLAM 转动漂移：离线/图验证不能证明约 165 度转向会在 40 秒内满足 `0.12rad` yaw 容差。首次真机应只验证前两段加该 yaw-only 段，并以 trace 中 `kind=yaw_only`、全程 `command_vx=command_vy=0`、走廊未越界作为成功判据。

### yaw-only 首轮失败根因 — 2026-08-03

- 真机证据证明新控制链实际生效：第三段 `kind=yaw_only`、precision lease acquired、线速度非零计数严格为 0，角速度按 `-0.12rad/s` 顺时针输出。故本轮不是旧 DWB preset、仲裁未接管或混入平移。
- 失败门禁为 TF freshness：有效控制约 1.1 秒后遇到 `age>0.20s`，连续等待上限 `0.50s` 后中止。中止前 yaw 已按正确方向变化约 `-0.164rad`，XY anchor 误差仅 `0.058m`。
- `final_bridge` 正常不等于 probe 的 TF buffer 正常：前者同期持续接收/发布，而 probe 的 Nav2 trace 已出现 1.9-3.9 秒 TF age 峰值。这说明延迟主要发生在 probe 本地 callback 消费路径，不是 UDP 传输持续中断。
- Foxy 行为是确定的：`rclpy.spin_once(node)` 文档与源码明确一次只执行一个 callback；`tf2_ros.TransformListener` 构造默认 `spin_thread=False`。当前 probe 同时消费 `/cmd_vel`、`/odom`、action future、`/tf` 和 `/tf_static`，手动 spin 频率不足时会形成 callback backlog，TF buffer 取到旧 transform。
- 修复优先级：首先解耦 TF listener 与主 probe callback 调度，并保证 `/cmd_vel` 端到端安全监视也不会积压；其次记录每个 stale hold 周期的 stamp/age/hold elapsed；最后才根据修复后的真实 TF age 分布决定是否调整 `0.20s/0.50s` 门限。
- 单纯把 hold timeout 调到 2-4 秒会让这轮更可能继续，但不保证 callback backlog 被追平，也会延长真实定位中断时的等待窗口，因此不能作为生产修复。
## 2026-08-03 — callback 饥饿修复与压力验证

- 根因不是 `0.20s` TF 门限过严，而是 probe 主节点用有限次数 `rclpy.spin_once()` 消费 action、cmd、odom、TF；Foxy 每次只处理一个 ready callback，TF listener 默认又不自旋，高频输入下 TF buffer 会落后于实际发布流。
- 修复采用职责隔离：TF 由独立 listener spin thread 持续更新；odom 由独立 executor 线程消费；主 node 只承担 action future 与 `/cmd_vel` 端到端安全门禁。这样保持原安全门限，同时消除调度队列相互阻塞。
- Jetson 压力测试用 60Hz TF、60Hz odom、40Hz cmd 重现生产输入量级，末段最大 TF age 仅 `0.0225s`，显著低于 `0.20s` 门限；241 条 cmd 与持续 odom 更新证明三个通道均未被饿死。
- 新增 `nav-only-turn-validation` 是下一次真机唯一允许的验证入口，只包含 `obstacle_cross_target -> pos1_middle -> yaw_only pos1_middle_turned`。完整 `nav-only-full` 在该最小验证通过前仍禁止直接运行。
- 短时真实反馈 dry-run 暴露清理问题：`final_bridge` 对 `SIGINT` 未退出，其启动的 `cuvslam_odometry_udp_exporter.py` 会成为残留子进程。后续 wrapper 清理应先发 `SIGTERM`，超时后再升级，且按命令行精确核对 PID；不能因此停止测试前已存在的 cuVSLAM 容器。
- 本轮已验证可用的精确清理方式：对已确认容器执行 `docker exec <container> pkill -TERM -f '[c]uvslam_odometry_udp_exporter.py'`，随后同时用容器内和 host `pgrep -af` 复核。该操作只终止 exporter，不会停止 cuVSLAM 容器。
## 2026-08-03 — callback 修复后的新阻塞：第 2 段规划失败

- callback 隔离修复后的两次 clean 真机运行都未再出现 probe TF stale，但都在 `obstacle_cross_target -> pos1_middle` 段提前 abort，尚未到达 yaw-only。这说明当前失败不是仲裁器、yaw-only 或 probe callback 饥饿。
- 完整路线第 2 段终点 TF age 仅 `0.057s`，bridge 延迟正常且 UDP errors=0；Nav2 日志明确为 `GridBased failed to generate a valid path to (1.50, 3.25)`。
- 机器人在第 2 段已经移动到 `(0.764,2.380,1.456)`，距离目标仍约 `1.14m`。规划器在该中途 pose 无法继续生成路径，优先检查 global costmap 障碍膨胀、走廊几何和从障碍区左侧进入巡检中点的路径拓扑。
- 原样重复完整路线不会验证 yaw-only，只会再次暴露同一第 2 段问题。下一轮应先离线/无狗验证新中间航点，再只跑前两段到达性测试。

## 2026-08-03 — 下巡检箱体左通道清障航点

- phase1 地图中下巡检障碍块占 `x=1.0..2.0m, y=1.5..2.5m`；左侧场地边界为 `x=0`，因此左绕通道总宽约 1.0m。
- 两次失败轨迹均在通道下半段保持 `x≈0.48..0.60`，接近箱体上沿时提前向 `pos1_middle` 斜切至 `x≈0.70..0.76`；以 `0.70×0.50m` footprint 和 yaw≈pi/2 计算，右侧边缘会到达或越过箱体 `x=1.0` 边界。
- 代码中 staged/SE2 路线已有 `pos1_left_clear=(0.60,2.90,pi/2)`，其注释正是“保持左侧直到 footprint 越过下柜左上角”。该点在 yaw=pi/2 时距左边界约 0.35m、距箱体左边约 0.15m，且中心已超过箱体上沿 0.40m，是当前窄通道内较均衡的约束点。
- production yaw-only 和 DWB baseline 路线尚未包含该点，导致 planner 直接从 `(1.05,0.75)` 规划到 `(1.50,3.25)`。修复应在两个前缀中插入 `pos1_left_clear`，使所有路线的接近段保持一致。
- 实现后 production `nav-only-full` 共 11 段，第 2 段固定为 `pos1_left_clear`，第 3 段才是 `pos1_middle`，第 4 段才进入 yaw-only。下一轮可用同一 `nav-only-turn-validation` preset 只验证这四段。
- 真机证明该航点有效：箱体纵向范围内轨迹中心 x 被约束在 `0.411..0.480`，第 2 段自然成功；此前失败轨迹接近上沿时 x 增至约 `0.70..0.76`。因此不能撤销或右移 `pos1_left_clear`。
- 新阻塞发生在 clear 点之后：DWB 从 `(0.548,2.850,1.326)` 去 `(1.50,3.25,pi/2)` 时长时间同时输出 vx/wz，最终停在 `(1.115,3.166,0.957)`。这与箱体贴边问题不同，应单独设计 clear-to-middle 过渡。

## 2026-08-03 — `pos1_middle` 沿 Y 拆点方案可行性

- 官方 Nav2 Waypoint Follower 文档说明，它按顺序处理一组 waypoint，并对每个 waypoint 使用 `NavigateToPose`；本仓 probe 也确实逐段发送独立 `NavigateToPose.Goal`。因此拆出的每一个普通 tuple 都是需要独立完成的位置+朝向目标，不是自动无停顿的路径控制点。来源：`https://docs.nav2.org/configuration/packages/configuring-waypoint-follower.html`、`https://docs.nav2.org/commander_api/index.html`。
- 官方 `RotateToGoalCritic` 文档明确：只有机器人足够靠近 goal 的 XY 位置后，才只允许其旋转到目标朝向；本仓 `SimpleGoalChecker` 又要求 XY 与 yaw 同时通过（`0.15m` / `0.30rad`）。来源：`https://docs.nav2.org/configuration/packages/trajectory_critics/rotate_to_goal.html`。
- 本仓两个观察动作的功能朝向仍相差 180°：看上柜需要 `+pi/2`，看下柜需要 `-pi/2`。若仅保持同一 X、把两个点放在 Y 上下两侧，按任一顺序连接，直线运动方向最多只能与起点朝向或终点朝向之一相同；另一端仍必须完成约 180° 朝向反转。拆点能移走“同 XY 转身”，但不会消除转身本身，且顺序发送两个 `NavigateToPose` 时很可能把原地转向搬到第一个点离开前或第二个点到达后。
- phase1 两柜之间的 ROS Y 走廊约为 `2.5..4.0m`。0.70×0.50m footprint 加 0.02m padding 的旋转扫掠半径约 `0.45m`，因此中心可安全旋转的几何带约为 `y=2.95..3.55m`，上下拆点最大实用间距只有约 `0.6m`；在 inflation cost 与真机漂移下余量会更小。
- 当前 clear-to-middle 目标本身不是 180°：从已验证终点 `(0.559,2.878,yaw=1.291)` 到 `(1.50,3.25,yaw=pi/2)`，连线方位约 `21.6°`，起始需约 `-52.4°`，末端需约 `+68.4°`。它失败的直接原因是前进-only DWB 在短距离横向过渡中长期边走边转，而不是这个 segment 被要求单次 180° 原地转向。
- 若目标是完全避开单点 180°，需要让路线形成有 X 偏置的 U 形/回环，使 yaw 沿路径分段变化；仅 Y 拆点不够。本仓已有 staged 路线采用 X/Y 偏置的两次四分之一转弯，但 2026-07-30 真机曾在第一段转弯漂移并 abort，说明需重新按当前实际终点和走廊余量设计，不能直接启用旧坐标。
- 若只是修复当前 `pos1_left_clear -> pos1_middle` 收敛，可把中间点设计成真正的 pass-through/position-only 约束并把最终观察 pose 单独处理；但本仓 `yaw=None` 目前只是写入 identity quaternion，`yaw_set` 字段没有被发送路径消费，并不是真正忽略 yaw。实现前必须明确使用 `NavigateThroughPoses`/合适 goal checker 或 precision controller，而不是把普通 `NavigateToPose` tuple 当途经点。

## 2026-08-03 — split-Y 实验坐标

- 初选 `y=3.50/3.00` 的静态扫掠余量只有约 `0.063m`，不足以覆盖定位/步态漂移；收回为 `pos1_upper_view=(1.50,3.40,+pi/2)` 与 `pos1_lower_view=(1.50,3.10,-pi/2)`。两点同 X、Y 相差 0.30m，围绕原 `y=3.25` 对称，分别更靠近 ROS +Y 的上柜底面与 ROS -Y 的下柜顶面。
- 右侧转弯列使用 `x=2.60m`，而非旧 staged 的 `x=2.10m`：现有生产右侧观察位已因 0.70m 机身净距从 2.20m 外移到 2.60m，实验路线复用这一更保守横向余量。
- phase1 PGM 静态检查已完成：对 `0.70x0.50m + 0.02m padding` 的圆形旋转扫掠近似，最小余量为 `0.111m`，两个观察位余量为 `0.163m`，右侧过渡点余量约 `0.416m`。
- Jetson 17/17 ROS/控制测试和构建通过，实验 preset 明确强制无 Spin recovery BT；剩余未验证项是真实 DWB/Lite3 动力学。
- 静态余量不能覆盖未建模的柜体实际偏位、定位误差和 Lite3 步态漂移，因此真机前仍必须现场确认完整矩形路线净空。

## 2026-08-04 — 完整生产路线再次受 yaw-only 定位漂移门禁阻断

- `nav-only-full` 本轮前三个 Nav2 段全部成功，说明新增 `pos1_left_clear` 与当前 `pos1_middle` 接近段在这次运行中均可收敛；阻塞已经推进到第 4 段 `yaw_only`。
- 第 4 段端到端命令证据严格为 `vx=vy=0`，但 cuVSLAM 的 `map->base_link` 在约 132° 顺时针旋转期间报告约 `0.30m` XY 位移，最终触发 `left SE2 safety radius (0.302m)`。这与此前“肉眼纯转但视觉定位产生平移”的结论一致，不能通过放宽 Nav2 timeout 解决。
- 本轮运行的是生产 `nav-only-full`，其中第 4 段仍为独立 `yaw_only`；它没有执行新建的 `nav-only-split-y-validation`。因此本轮失败不能用来否定 split-Y/右侧矩形回环方案，后者仍需从官方起点单独跑六点实验验证。
### 当前导航最佳基线与 split-Y 实验核查 — 2026-08-04

- 导航 worktree `quadruped-robot-competition-nav2-dwb` 当前位于 `1991aa4`，其上还有未提交的 `nav2_waypoint_sequence_probe.py` / `test_nav2_waypoint_callback_stress.py` 改动；未提交内容只新增隔离 `nav-only-split-y-validation` 路线和结构断言。
- 生产导航行为的最佳历史基线是 `753f5b3`（2026-07-31），若需要包含后续只读漂移诊断工具则取 `1efbcd6`；`1efbcd6` 没有修改 waypoint 路线。
- 该基线在 2026-08-02 的 `nav-only-full` 真机运行中前 5 段均 `SUCCEEDED`，第 6 段 `grab_area_approach` 超时取消；因此它是“目前最佳可复现基线”，不是全路线完成基线。
- 后续 `fb9e09a` 将生产第 3 段改为 yaw-only，`1991aa4` 又加入 TF/odom 回调隔离和 `pos1_left_clear`；2026-08-04 生产路线前三段成功，但 yaw-only 因视觉定位报告约 `0.302m` XY 漂移触发安全半径退出。
- 未提交 split-Y 实验的远端摘要 `/home/superwfx666/competition_logs/nav2_waypoint_sequence/20260804_144513_split_y_validation/summary.json`：第 1-4 段成功，第 5 段 `pos1_split_y_lower_right` 在 130 秒后取消，终点约 `(2.640,3.424,-0.728)`，目标 `(2.60,3.10,-pi/2)`。该结果说明拆点没有消除 DWB 的位置/终端 yaw 耦合。
- 因此后续不应继续在 `1991aa4` + 未提交 split-Y 上叠加生产改动；应先以 `753f5b3`（或带诊断的 `1efbcd6`）建立隔离恢复点，再逐个 cherry-pick/验证单一实验。
### 使用 Git revert 恢复导航基线 — 2026-08-04

- 用户明确要求回到 `1efbcd6`，同时保留后续原提交历史，因此采用逐提交 `git revert`，未使用 reset/rebase。
- 操作前导航分支相对 `1efbcd6` 有三个提交：`fb9e09a`、`1991aa4`、`10b43e5`；工作区干净，无需丢弃或 stash 未提交内容。
- 按逆序创建 `aafa17f`、`9580616`、`88b4eeb` 三个 revert 提交后，`HEAD^{tree}` 与 `1efbcd6^{tree}` 同为 `9c3dd6222f275fcaaad40d5cecfac0db94249204`，证明源码内容完全恢复但历史未改写。
### Jetson `1efbcd6` 基线运行准备 — 2026-08-04

- Jetson 导航目录不是可直接 fast-forward 的干净 Git checkout：分支名为 `Stonefield/nav2-foxy-dwb-integration`，但 `HEAD=72e3833` 且依靠大量 staged/untracked 文件构成实际 Nav2 工作区，因此不能用 pull/reset 恢复而不破坏现场文件。
- 与本地 `1efbcd6` 比对后，启动脚本、停止脚本、Nav2 参数和 launch 文件 SHA 已一致；仅后续三个实验触及的 probe、SE(2) controller、SE(2) test、callback stress test 不一致。已备份并只同步这 4 个目标。
- Jetson `nav-only-full` 静态断言为 10 个航点：`obstacle_cross_target -> pos1_middle -> pos1_middle_turned -> pos2a_upper_right -> pos2b_lower_right -> grab_area_approach -> placement_A/B/C/D_approach`。
- Jetson 测试为 10 pass、1 fail。唯一失败是 `test_lite3_udp_smoke` mock 的 `SimpleNamespace` 缺少基线代码访问的 `test_closed_yaw`；生产启动链没有引用 `lite3_udp_smoke.py`，所以它是测试夹具缺口，不是 Nav 构建或入口失败。
- `colcon build --symlink-install --base-paths <repo> --packages-select quadruped_robot_competition` 成功。
### `1efbcd6` 基线全航点真机结果 — 2026-08-04

- 运行目录：`/home/superwfx666/competition_logs/nav2_waypoint_sequence/20260804_154450_full_nav_baseline_1efbcd6/`；`summary.json ok=false`。
- Segment 1 `obstacle_cross_target` 成功：`(4.740,0.765,-3.120) -> (1.189,0.726,-3.129)`。
- Segment 2 `pos1_middle` 成功：`(1.187,0.738,3.142) -> (1.528,3.182,1.284)`。
- Segment 3 `pos1_middle_turned` 超时取消：`(1.520,3.153,1.310) -> (1.128,3.204,0.845)`；5240 条 `/cmd_vel` 样本中 `linear.x` 非零 2785、`angular.z` 非零 5199，最大值分别 `0.10m/s`、`0.15rad/s`。
- 本轮证明 revert 后运行的确是旧 DWB 基线，也再次重现其非确定性终端转向失败；不能把“回到曾经前五段成功的源码”理解成“每次都能重复前五段成功”。
- 结束后无导航、bridge、相机或 Docker 残留；Lite3 只读反馈 `robot_basic_state=6`、`robot_motion_state=0`、电量 76%。
- 安全操作错误：收尾时误将 `lite3_udp_smoke.py --armed` 当作零速工具，默认序列实际包含 1 秒 `vx=0.04` 和 1 秒 `wz=0.12`。发现后立即通过底层 client 仅发送 3 秒三轴零速。该工具以后禁止用于停机归零，必须使用显式 zero-only 入口。
### Nav2 前进速度上限提高至 `0.12m/s` — 2026-08-04

- 原生产速度存在三层串联限制：DWB `max_vel_x/max_speed_xy=0.10`、arbiter `max_vx=0.10`、bridge `hard_max_vx/hard_max_speed_xy=0.10`。只改其中一层不会改变最终输出。
- 五项已统一提高到 `0.12m/s`，保持 `acc_lim_x=0.35m/s^2`、`decel_lim_x=-0.45m/s^2`、`max_vel_theta=0.15rad/s`、横移限制和 SE(2) 精调速度不变。
- 新增 `tests/test_navigation_speed_limits.py`，使用标准库 AST 和局部 YAML 数值解析检查五个限制值一致，避免以后配置漂移。
- 速度提高不会解决 `pos1_middle_turned` 的 DWB 终端控制耦合；该段同时输出 `linear.x/angular.z` 时，允许更大的前进速度可能增加弧线漂移，下一次不能把超时改善预设为必然结果。
## 2026-08-04 — 显式 proximity takeover 实现设计

- 现有 `CmdVelArbitration.accept_precision()` 对零命令同样取得 precision lease，并在 precision 过期后强制进入 `precision_release` 零速间隔；因此接管顺序可以落实为“零速 lease → 端到端停稳 → cancel Nav2 → yaw-only”。
- 现有 `run_nav2_segment()` 只等待 action 自然完成或总超时，不能表达“XY 进入半径即成功接近”；需要新增复合段，在 action 执行期间用实时 `map->base_link` 计算到 approach target 的 XY 距离。
- `pos1_middle` 的复合目标应区分 `approach_yaw=+pi/2` 与 `target_yaw=-pi/2`；进入半径后 yaw-only 的 target XY 必须取接管时实时锚点，而不是继续追 `(1.50,3.25)`，从控制职责上保证转身期间不修正 XY。
- 已知真机在纯 yaw 命令下仍报告约 `0.30m` TF XY 漂移，因此保持现有 anchor/corridor/TF freshness 门禁，并把首轮 coarse yaw 上限从历史 `0.12rad/s` 降至 `0.08rad/s`；不通过放宽安全半径换取跑完。
- 从 `1efbcd6` 恢复后 probe 又回到单线程 TF callback；显式接管若继续使用该结构会重新暴露已确认的 callback 饥饿。实现需同时恢复已验证的 TF/odom callback 隔离，但不放宽 `0.20s` TF freshness 门限。
## 2026-08-04 — 显式 DWB → yaw-only 接管实现结果

- 控制职责现在是一个原子复合段而非两个独立 route step：Nav2 action 仍带 `approach_yaw=+pi/2` 以便规划，但其成功条件被外层 XY 距离 `<=0.22m` 截断；DWB 尚未进入自身 `0.15m` XY GoalChecker/RotateToGoal 区时，precision 已先接管最终速度出口。
- “取得 lease”不再仅靠 publisher subscription count 推断。arbiter 每周期发布 `idle/nav2/precision/precision_release`，probe 同时要求 mode=`precision` 与最终 `/cmd_vel` 三轴连续零速，再取消 action；释放时反向要求 mode=`idle` 与最终零速。
- cancel 等待期间 probe 继续按 `10Hz` 发布 precision 零速，避免 `precision_timeout=0.25s` 过期后 DWB 在 action 尚未终止时重新获得输出权。
- yaw-only anchor 取 cancel 后 5 个连续稳定 TF 样本的最后一帧，target XY 与该 anchor 完全相同且控制器没有线速度字段；这与 `se2_pose` 同时修正 XY/yaw 明确隔离。
- 首轮真机速度默认由历史 `0.12rad/s` 下调为 coarse `0.08rad/s`、fine `0.04rad/s`，理论 165° 转身需要约 40-45 秒，因此 yaw-only 总 timeout 调整为 `55s`；TF freshness `0.20s`、TF hold `0.50s`、anchor safety radius `0.30m` 均未放宽。
- `turn_delta` 单独记录 anchor→end 的 TF XY/yaw 变化，可直接量化转身期间 cuVSLAM 报告漂移，不再与 Nav2 approach 位移混在 segment 总 delta 中。
- Jetson 当前运行的生产栈仍是同步前版本，不含新 mode topic 或 takeover；未完成生产同步/build 前，不能据当前在线节点判断新实现已部署。
## 2026-08-04 — 完整真机 Nav 启动前的物理起点约束

- `base_start` camera-world rebase 会在 host final bridge 冷启动时把当时机器人物理位置映射到预设地图起点。若机器人实际仍在 `(4.08,0.79)` 附近就重启，TF 可能看起来恢复到 `(4.65,0.75)`，但地图与真实场地会整体错位约 `0.57m`，软件门禁无法识别该物理偏差。
- 因此“TF 冷启动后显示官方起点”不能替代人工把机器狗放回场地官方起点。完整路线发 goal 前必须先完成物理归位，再启动/rebase，再核对 TF、lifecycle、速度拓扑和 precision mode topic。
- 当前新代码已经部署并构建，但尚未经过新栈 ROS 图验证或任何真机 motion。用户下一条确认应同时覆盖：官方起点、站稳、完整路线净空、急停人员就位。
## 2026-08-04 — proximity takeover 首次真机暴露 Nav2 提前成功

- 新接管安全条件有效：当 Nav2 approach action 提前结束而实时 TF 距接管目标仍为 `2.519m` 时，probe 返回 `TAKEOVER_ABORTED`，precision lease、cancel、yaw-only 和后续航点均未执行。
- 第 2 段不是 goal 未接受：action `accepted=true`，约 0.9 秒内有 36 条最终 cmd 样本，其中 33 条非零，最大 `vx=0.096m/s`、`|wz|=0.071rad/s`；随后 Nav2 result status 为 `SUCCEEDED`。
- probe 的 5Hz trace 在该段始终看到 TF 位于第 1 段终点附近，范围约 `(1.188..1.222,0.751..0.766)`，没有接近 `(1.50,3.25)`。当前证据尚不能排除 5Hz 采样间隙内的短时 TF 跳变，也不能证明 Behavior Tree/action result 错配。
- 下一步只读诊断应检查 Nav2 controller/BT 原始日志、是否存在跨 goal 状态残留，以及能否从 cuVSLAM/bridge 数据恢复 10Hz 以上的 pose；在根因明确前不得把“远距 SUCCEEDED”改成自动重发 goal。

## 2026-08-04 — 单 DWB 与未启用 Smoother 的只读评估

- 实际导航 worktree `quadruped-robot-competition-nav2-dwb` 使用 ROS 2 Foxy：NavFn A* 全局规划、Controller Server 仅注册一个 `FollowPath=dwb_core::DWBLocalPlanner`，默认 `navigate_w_replanning_and_recovery.xml` BT；launch/lifecycle/package 中均没有 `smoother_server`、`nav2_smoother` 或 `nav2_velocity_smoother`。
- 当前 DWB 自带速度/加速度采样约束（`max_vel_x=0.12`、`max_vel_theta=0.15`、`acc_lim_x=0.35`、`decel_lim_x=-0.45` 等），但这不等价于独立 Velocity Smoother 的输出插值、死区和开/闭环速度整形。
- 官方 Nav2 迁移文档确认 Controller Server 原生支持注册多个 controller plugin，但单插件不是错误；是否需要多个插件取决于是否确有不同运动阶段需要不同控制律和 BT/controller selector，而不是数量越多越好。
- 官方 Nav2 Smoother Server 文档说明其处理的是 planner 输出的几何路径；Velocity Smoother 文档处理的是 `/cmd_vel` 的速度、加速度、死区和插值。两者职责不同，评估时不能统称为一个 Smoother。
- 结合本项目真机数据：DWB 同点末端转向出现平移/转动耦合与约 `0.28m` XY 漂移；这属于控制律/四足底盘执行及定位问题，路径 Smoother 不会直接修复。近期远距 `SUCCEEDED` 也属于 action/BT/GoalChecker/TF 状态问题，任何 Smoother 都不能作为根因修复。
- 初步工程判断：保留单 DWB 作为当前 Foxy 比赛基线是合理的；不启用路径 Smoother 在静态、规则地图和 NavFn 路径已经足够平顺时可以接受，但应以曲率/角点/跟踪误差证据决定；不启用 Velocity Smoother 对四足真机的合理性较弱，值得先做旁路录包与离线参数验证，再进行可回退 A/B 真机测试。
- 外部资料来源（只作研究数据）：https://docs.nav2.org/migration/Eloquent.html ，https://docs.nav2.org/configuration/packages/configuring-controller-server.html ，https://docs.nav2.org/configuration/packages/configuring-smoother-server.html ，https://docs.nav2.org/configuration/packages/configuring-velocity-smoother.html 。
- Foxy 版本边界已由官方源码/rosdistro 交叉确认：Foxy 正式发行版本为 Navigation2 `0.4.7-1`；其 package 清单与上游 `0.4.7` 根目录均没有 `nav2_smoother` 或 `nav2_velocity_smoother`，默认 BT 仅含 `ComputePathToPose -> FollowPath`。现代 Smoother 文档不能直接当作 Foxy 已安装能力，加入这些功能属于回移植、升级 ROS 2，或在现有速度链自研受限速率器。
- 当前输出链实际为 DWB 10Hz `/cmd_vel_nav2` + precision `/cmd_vel_precision` -> arbiter 40Hz -> `/cmd_vel` -> bridge 40Hz ZOH/限幅/死区 -> Lite3 UDP。arbiter 与 bridge 都没有 slew-rate/加速度插值，所以 40Hz 重发不是速度平滑，只是零阶保持。
- 若增加速度整形，安全插入点应优先限定在 Nav2 分支：`/cmd_vel_nav2_raw -> velocity smoother/rate limiter -> /cmd_vel_nav2 -> arbiter`。不应默认放在 arbiter 之后，否则可能把 precision 接管零速、watchdog stop 或紧急停机也变成缓降，破坏当前已验证的安全语义。
- Foxy 官方来源（只作研究数据）：https://raw.githubusercontent.com/ros/rosdistro/master/foxy/distribution.yaml ，https://github.com/ros-navigation/navigation2/tree/0.4.7 ，https://github.com/ros-navigation/navigation2/blob/0.4.7/nav2_bt_navigator/behavior_trees/navigate_w_replanning_and_recovery.xml 。
- “只用了一个控制器”只对 Nav2 Controller Server 成立，对整套生产系统不成立：当前 production route 使用 `nav2_yaw_takeover`，由 DWB approach 显式切到自研 `YawOnlyController`；另有 opt-in `Se2PoseController` 路线。两类 precision 控制器都有 `rate_limit()`，分别限制角加速度及线/角加速度。因此架构实质是“单 Nav2 controller plugin + 独立精调运动原语 + 安全仲裁”。
- 这个混合方案比单纯为了数量再注册第二个 Nav2 controller 更符合现有故障：DWB 负责低速长距离路径跟踪，yaw-only/SE(2) 处理 DWB `RotateToGoal` 与四足转身漂移。Path Smoother 无法替代该职责分离。
## 2026-08-04 — 第二段远距 `SUCCEEDED` 的 BT 状态复用调查（继续）

- 生产 launch/参数确认仍使用 Foxy 默认 `navigate_w_replanning_and_recovery.xml`；该树通过 `PipelineSequence` 串接 `ComputePathToPose` 与 `FollowPath`。
- Jetson overlay 源码确认 `BtNavigator::loadBehaviorTree()` 在 XML 文件名不变时复用现有树，goal 结束后只调用 `BehaviorTreeEngine::haltAllActions(tree_.rootNode())`；是否完全重置成功子节点仍需结合 BehaviorTree.CPP `ControlNode::halt()` 语义确认。
- 本地导航 worktree 当前仅保留显式接管实现涉及的 5 个预期文件改动，尚未修改 Jetson Nav2 overlay；因此后续可先在 overlay 侧做最小、可回滚的回归修复。
## 2026-08-04 — BehaviorTree.CPP halt 语义确认

- Jetson `/opt/ros/foxy/lib/libbehaviortree_cpp_v3.so` 反汇编显示 `ControlNode::halt()` 直接调用 `resetChildren()`；`haltChild()` 即使子节点原状态为 `SUCCESS` 也会调用 `TreeNode::resetStatus()`，因此 `PipelineSequence::halt()` 本身不是“只清理 RUNNING 子节点”的缺陷。
- `RateController::tick()` 只在自身状态为 `IDLE` 时重置计时/首 tick；正常 halt 后节点应回到 `IDLE`，但 BehaviorTree blackboard 中的 `{path}` 输出值不会由通用 halt 自动清除。
- 第二目标的 `controller_server` 在收到 FollowPath 后没有新的 `Passing new path`，约 0.835 秒即 `Reached the goal`；因此需要通过每个新 NavigateToPose 强制重建 BT，确保 ComputePathToPose 首 tick 重新规划，避免旧黑板 path 被复用。
## 2026-08-04 — overlay 编译超时

- 首次执行 `colcon build --symlink-install --packages-select nav2_behavior_tree nav2_bt_navigator --event-handlers console_direct+` 在 120 秒命令上限内未返回，工具以 `Exit code 124` 结束；目前不能将其判定为源码编译失败，需先检查是否有残留编译进程/日志。
## 2026-08-04 — BT 强制重建修复与无运动回归

- Jetson Nav2 overlay 已修改 `BtNavigator::loadBehaviorTree(..., force_reload)`；`navigateToPose()` 对每个新 action 强制重建同名 XML 的 BT。原文件备份：`/home/superwfx666/quadruped-robot-competition-nav2-dwb/tmp/nav2_bt_force_reload_backup_20260804_1825/`。
- `nav2_behavior_tree`、`nav2_bt_navigator` overlay 构建成功，新 `libbt_navigator_core.so` 时间为 `2026-08-04 18:45:18 +0800`，运行环境 `ros2 pkg prefix` 指向 overlay install。
- 无狗回归目录：`/home/superwfx666/competition_logs/nav2_waypoint_sequence/20260804_185035/`。第 1 个当前位姿 goal 正常 `SUCCEEDED`；第 2 个 `(1.50,3.25,1.571)` goal 产生 155 条非零 DWB cmd、TF 保持不动，5 秒后由 probe 取消，状态 `CANCELED`，未再远距 `SUCCEEDED`。
- `/tmp/competition.log` 证实两个 goal 分别重新初始化 `ComputePathToPose`/`FollowPath`；第 2 个 goal 在运行中有 3 条 `Passing new path to controller`，证明不再复用第 1 个终点 path。
- 验证时 `/cmd_vel` 为 1 publisher / 0 subscriber，且无 `cmd_vel_bridge`、`motion_sender`、Lite3 transfer，因此没有向机器狗发送动作。验证后已运行 `stop_all.sh`，只保留既有 cuVSLAM 容器。
## 2026-08-04 19:00 — 真机启动后定位门禁未通过

- 用户确认四项物理门禁后启动 `--dog --cmd-vel-bridge --prepare-lite3-motion`；Lite3 prepare 为 `simple=50 complex=48 errors=0`，但未发送 waypoint。
- 五个 Nav2 lifecycle 均 `active`，`/navigate_to_pose` 唯一 server，速度拓扑为 arbiter→bridge；当前 bridge 诊断 `motion=0` 且三轴零速。
- TF 分解显示 `map→odom=(4.650,0.750,yaw=pi)` 正常，但 `odom→base_link≈(0.043,0.776,yaw=-0.25)`，组合得到 `map→base_link≈(4.618,-0.045,yaw≈2.89)`，与官方起点约偏离 Y `0.80m` / yaw `0.25rad`。
- `/tmp/competition.log` 从约 19:00 起持续报告 `nav2_costmap_2d: Robot is out of bounds of the costmap!`。当前必须先处理/确认定位链，不得用放宽 costmap 或安全阈值代替。
## 2026-08-04 19:05 — 定位偏差根因收窄为 cuVSLAM 世界未冷启动

- `tf2_echo map odom` 为固定 `(4.650,0.750,yaw=pi)`；`tf2_echo odom base_link` 为 `(0.043,0.776,yaw=-0.25)`，因此组合 TF 偏到 `(4.62,-0.05)`。
- final bridge 日志显示 `world_rebase=base_start`，但源码 `camera_pose_to_base_pose()` 仅使用静态 `t_base_camera/q_base_camera` 变换，没有记录当前 cuVSLAM 世界首帧并动态减去它。
- 启动脚本检测到既有 `cuvslam_gui_20260804-175643` 容器后不会重启；该容器保留了上一轮视觉世界坐标，导致本轮 final bridge 输入不是新起点坐标。Nav2 随后持续报告 costmap out-of-bounds。
- 处理方案：停止导航栈，再仅停止旧 cuVSLAM 容器（不删除数据卷），让启动脚本冷启动新容器后重新检查 TF；不通过放宽地图/安全阈值绕过偏差。
## 2026-08-04 19:37 — 冷启动后 nav-only-turn-validation 真机结果

- 冷启动新 cuVSLAM 后动作前 TF 稳定为 `(4.650,0.750,yaw=pi)`，costmap out-of-bounds 计数为 0；Lite3 prepare `simple=50 complex=48 errors=0`，bridge 初始三轴零速。
- 运行目录：`/home/superwfx666/competition_logs/nav2_waypoint_sequence/20260804_193726/`；BT 路径为 `/opt/ros/foxy/share/nav2_bt_navigator/behavior_trees/navigate_w_replanning_time.xml`。
- Segment 1 `obstacle_cross_target` 成功：`(4.625,0.737,3.115) -> (1.189,0.765,-3.032)`，Nav2 日志明确 `Reached the goal`/`Navigation succeeded`。
- Segment 2 `nav2_yaw_takeover` approach 已正确收到 `(1.50,3.25)`，随后进入 precision/yaw-only；TF 从接管锚点约 `(1.324,3.292)` 漂移到 `(1.602,3.420)`，达到 `0.303m` 安全半径，状态 `TAKEOVER_ABORTED`，没有发送后续 waypoint。
- probe 已执行停栈，当前无 Nav2/arbiter/bridge/probe/motion sender/final bridge，仅保留本轮冷启动的 cuVSLAM 容器 `cuvslam_gui_20260804-190315`。
## 2026-08-04 19:37 trace 阶段统计

- `trace.csv` 共 452 行：`nav2_approach=139`、`post_cancel_anchor=1`、`yaw_only=170`。
- yaw-only 170 行全部 `arbiter_mode=precision`、`control_mode=coarse_yaw`；`command_vx` 和 `command_vy` 的 min/max 均为 `0.0`，`wz=-0.0002..-0.08`；TF age `0.024..0.052s`，因此不是 TF stale 或 callback 饥饿。
- yaw-only 首帧锚点 `(1.3236,3.2920,yaw=0.2183)`，末帧 `(1.6027,3.4011,yaw=-1.0335)`，位置误差 `0.29964m`；随后状态摘要为 `left SE2 safety radius (0.303m)`。
- 结论：纯转身指令与仲裁约束有效，cuVSLAM 原地旋转时仍报告约 `0.30m` XY 漂移；不得因想完成全路线而放宽安全半径。
## 2026-08-04 — 手动 Navigation-only 指南需要同步

- `学习/Navigation-only 全航点手动测试.md` 当前仍描述 `1efbcd6 + 0.12m/s` 旧 DWB 终端转向，并要求启动后直接跑 `nav-only-full`；这与当前已部署的显式 `nav2_yaw_takeover`、Jetson per-goal BT 重建补丁及最新真机结果不一致。
- 指南需要新增/更新：先运行 `nav-only-turn-validation`；只有其 `summary.json ok=true` 才允许 `nav-only-full`；动作前增加 costmap out-of-bounds 检查；说明必须冷启动 cuVSLAM，不能复用上轮视觉世界坐标；补充 overlay 两包构建/安装检查。

## 2026-08-05 — 用航点重排绕开同点 180° 转向

- 当前生产巡检顺序仍把 `pos1_middle(+pi/2)` 与同坐标 `pos1_middle_turned(-pi/2)` 连续执行；这会强制触发已确认不可靠的同点 180° 转向。纯 yaw 控制虽严格保持 `vx=vy=0`，但 cuVSLAM 在真机上仍报告约 `0.303m` XY 漂移，因此继续放宽转向门限不是可靠方向。
- 最小替代顺序可采用 `pos1_middle(+pi/2) -> pos2a_upper_right(pi) -> pos1_middle_turned(-pi/2) -> pos2b_lower_right(pi)`：两个 middle 观察目标不再相邻，且按点间几何计算，每次离开已完成观察位去下一个点时只需约 `41-49deg` 的方向变化，不再要求原地反向。
- 该顺序仍需隔离真机验证：Nav2 实际路径会绕柜体而非走直线，必须检查全局规划、0.70x0.50m footprint 净距及右侧观察位的终端姿态；若终端姿态仍过大，可在观察位东侧加入非观察用途的 approach/transit 点。
- 仓库已有 `scripts/map_base_link_trace.py`，能只读记录 `map -> base_link` 的 `x/y/yaw` 与 TF 链，但目前仅连续输出 CSV，尚无“到位触发、稳定窗口统计、命名航点输出”功能。
- 遥控标定可在现有记录器上增加：到位站稳后采样 2-5 秒，使用 XY 中位数和 yaw 圆均值，输出带样本离散度的 YAML/JSON；只有 TF 新鲜且位置/朝向窗口稳定时才接受。记录前必须把狗放在官方起点并冷启动 cuVSLAM，使 `base_start` 地图坐标与生产运行一致。
- 遥控标定得到的是当前定位链下的可重复导航位姿，不是独立物理真值。鉴于旋转伪平移已被实测确认，最终点还应以相机画面中的仪表居中/清晰度、机身包络净距和场地实测距离交叉验收。

## 2026-08-05 — 箱体视觉定位码方案调研前置事实

- 当前代码没有 AprilTag/ArUco/Charuco/fiducial 检测器或对应 ROS topic；标记方案需要新增独立视觉节点/库和位姿融合接口。
- `scripts/gauge_status_node.py` 仅启动 D455 彩色流（默认 640x480@30），写临时 JPEG 后调用 HoughCircles/HoughLinesP + HSV 颜色规则，发布 `/gauge/status` JSON 与 `/gauge/detected` Bool；当前没有框选 ROI、识别箱体 ID 或输出相机/箱体 6DoF pose。
- cuVSLAM 使用 D455 红外双目 + IMU，经过 Docker→UDP→`final_bridge.py` 提供 `/odom`/TF 给 Nav2；贴码不会自动改善 cuVSLAM，必须做标记检测与 `map↔camera/base_link` 重定位或任务级到位校验。
- 既有路线在约 5m×6m 场地、0.70×0.50m footprint 和固定箱体观察位工作；真机已实测原地 yaw 产生约 0.30m 的 cuVSLAM XY 伪漂移，因此标记应优先作为近箱体最终定位/身份确认锚点，而不是替代全场导航。

### 联网检索记录（第一轮）

- infsh/Tavily Search Assistant 未能提交任务，CLI 返回账户余额不足；未将该输出当作资料。
- 本机 tvly fallback 命令未安装。
- OpenCV 4.x 文档 URL 可访问但被 Cloudflare challenge 替换，不能直接引用页面正文。
- GitHub API 成功确认 christianrauch/apriltag_ros 为 ROS 2 AprilTag detection 节点，默认分支 master，仓库更新时间为 2026-08-04；后续从其 raw README/源码提取接口事实。

### 联网检索记录（第二轮）

- AprilRobotics/apriltag README：AprilTag 3 包含更快检测器、对小标签更高的检测率、灵活布局和姿态估计；多数应用推荐 tagStandard41h12。提高 quad_decimate 会提速但牺牲检测距离；远距离/小标签应降低 decimate，必要时调 decode_sharpening。
- 同一 README：姿态估计可直接使用已知 tagsize、fx/fy；tagsize 定义为检测角点/黑白边界之间的边长，不能把外部白边或整张纸尺寸误当作 tagsize。
- christianrauch/apriltag_ros README：节点订阅 rectified image 与 CameraInfo，使用与图像同时间戳的 CameraInfo.P 计算单标签位姿；发布 /tf 和 apriltag_msgs/msg/AprilTagDetectionArray，消息含 homography、hamming 和 decision_margin；YAML 支持 family、默认 size，以及按 ID 指定 frame/size。

### 联网检索记录（第三、四轮）

- AprilTag ICRA 2011 官方论文页：系统通过单幅图像提供特征的完整 6DoF 定位，并强调对遮挡、透视变形和镜头畸变的鲁棒性。
- AprilTag 3 README 的 Flexible Layouts：标准布局在标签边框外增加数据位，提高数据密度和可用 ID 数，但代价是检测距离略降；因此本项目不应为“每面贴两个”而盲目选高密度家族。
- AprilTag 3 README：tagStandard41h12 是大多数应用的推荐；若确实需要更多标签才考虑 tagStandard52h13；仓库也集成原生 ArUco family。
- apriltag_ros 的 tags_36h11.yaml 示例展示了同一 family 下按 ID 指定 frame 和 size，并可设置 max_hamming、decimate、sharpening、PnP 姿态估计方法。
- Intel D455 产品页本轮请求连接中断；当前设计不把网上二手 FOV 数字当硬约束，而要求启动时使用真实 /camera/.../camera_info 的内参和图像尺寸做可见性/像素尺寸标定。仓库技术报告本地记录 D455 深度约 0.6–6m，仅作为现有项目背景。
- apriltag_ros 当前 master 的 package.xml 为 3.4.0，要求 rclcpp/rclcpp_components、sensor_msgs、tf2_ros、apriltag_msgs、apriltag、image_transport、cv_bridge 和 Eigen；CMake 要求 AprilTag 3.2、OpenCV core/calib3d、C++14。需针对 Jetson Foxy 做源码构建验证，不能直接假定最新 master 可由系统 apt 包安装。

## 2026-08-05 — feature/vision-change 分支对贴码方案的修正

- 用户指定视觉工作以远端 feature/vision-change 为准。已只读浅克隆提交 89c2828276cf78b354f7713ffee4d7fabb423e02（2026-08-04 13:10 +08:00，Calibrate）到系统临时目录，未切换当前工作区。
- 分支没有 AprilTag、ArUco、ChArUco 或 fiducial 实现；出现的 marker 仅为 Matplotlib/RViz/地图绘图语义。
- 分支正式视觉架构是 Docker 内唯一 RealSense ROS 驱动：原始 RGB/Raw Depth/CameraInfo/TF 供 Docker YOLO 3D 节点消费，结果以 UDP 127.0.0.1:19002 返回 Host。README 明确旧 Host 相机节点不能与 Docker RealSense 同时打开 D455。
- docker/d455_perception/d455_yolo_3d_node.py 已提供可复用模式：订阅 RGB、Depth、两路 CameraInfo、TF，按原始时间戳配对，在 camera_link 输出结构化 UDP 包。贴码检测更适合在同一 Humble Docker 内新增节点并复用这一跨 ROS 版本桥接模式。
- Host color_image_publisher.py 从 Docker relay 的 latest_color.jpg 读取 JPEG，以 Host 当前时刻重新打 Image/CameraInfo 时间戳，并硬编码 640x480 的 fx=fy=617、零畸变。它适合预览/轻量识别，不应作为高精度 AprilTag PnP 的首选输入。
- 分支 gauge_status.py 仍会通过 RealsenseCamera.for_gauge() 直接打开 D455；若 Docker 正占有相机，该节点存在资源冲突风险。贴码实现不得复制这种直接开相机方式。

## 2026-08-05 — AprilTag 真实职责：全局重定位与最终接近闭环

- 用户明确不需要用 Tag 识别箱体 ID/确认观察面；全部箱体和固定观察顺序已知，Tag ID 的价值是把观测关联到预先测量的场地绝对锚点。
- 当前系统并非控制意义上的完全开环：Nav2 仍用 cuVSLAM odometry 做局部闭环；问题是 VIO 没有可靠外部绝对观测，地图层误差会累积。因此准确目标是“保持 odom→base_link 局部连续，由 Tag 提供 map→odom 的稀疏绝对校正”。
- 已知 T_map_tag、检测得到 T_camera_tag、已有标定 T_base_camera 后，可以计算 Tag 观测下的 T_map_base；Tag 自身 PnP 已包含相机到标签的三轴平移和姿态，不只是 ID。
- D455 Raw Depth 应作为独立距离/平面约束：在 Tag 四角多边形内部采样深度，经腐蚀、有效比例、离群裁剪和中值/平面拟合得到量测；不能只取中心像素。分支已有 YOLO Raw Depth→Color 稀疏投影与稳健统计代码可复用。
- 系统应形成两层闭环：远程/航点间由 cuVSLAM+Nav2 连续控制；到达 Tag 可见区后，稳定检测并校正 map→odom；最终接近/抓取阶段以 Tag 相对位姿和深度直接计算期望驻停距离、横向偏差、yaw 偏差，进入局部视觉伺服。
- 全局校正不应在运动中无门控硬跳 TF。应在静止或低速、连续多帧稳定、hamming/decision margin/重投影误差/深度有效率/与当前 VIO 残差通过门限后更新，并确保 map→odom 只有一个发布者。
-

## 2026-08-05 — AprilTag 重定位与抓取闭环方案收敛

- 不用 Tag ID 决定箱体巡检顺序，不等于可以让不同箱体复用相同 ID。全局重定位必须把检测结果唯一关联到预先标定的 `T_map_tag`；因此每个物理 Tag 仍应使用唯一 ID，ID 只作为地图锚点查表键。
- 预先标定的数据必须是 Tag 在 `map` 中的完整 6DoF 位姿，而不只是“箱体前航点”的 XY/yaw。航点位姿可以由 Tag 位姿加期望驻停外参推导；只记录航点无法严谨地反算相机/机身绝对位姿。
- 单个尺寸充足、平整安装、四角完整可见的 Tag 已可由已知边长和相机内参给出 `T_camera_tag`。一个大 Tag 是最低可用配置，也优于两个因空间不足而缩小的 Tag。
- 主抓取面若空间允许，推荐两个仍保持足够物理尺寸、间距较大的唯一 Tag，作为一个预先标定的刚性双码板。双码提高部分遮挡、斜视和单码瞬时失败时的可用性，也可用两个独立位姿做一致性检查；它不是把两次单码结果简单平均。
- 不要求每个箱体的每个表面都贴两个码。只在路线实际使用的主观察/抓取面布置；若机器人会从两个相邻方向接近，则在相邻两面各放一个大 Tag，形成转角可视覆盖。
- AprilTag PnP 的三轴平移已经包含相机到 Tag 的光学距离和前向距离。D455 深度应作为第二传感器量测：在 Tag 内部腐蚀区域做多像素稳健统计或平面拟合，并检查与 PnP 距离的一致性；不能以单个中心深度像素直接闭环。
- 控制分为互斥模式：`NAV` 由 Nav2/cuvSLAM 做粗导航；`RELOCALIZE_HOLD` 在零速稳定窗口内接受 Tag 绝对观测并更新 `map→odom`；`VISUAL_SERVO` 冻结本轮全局校正，由精确控制器独占速度出口，按 Tag 相对前向、横向和 yaw 误差低速闭环；稳定到位后进入 `GRASP_HOLD` 并持续零速。
- 最终接近控制不应直接追逐每帧跳动的全局航点。应在 `base_link` 或控制约定坐标中计算相对目标误差，设置死区、限速、限加速度、稳定保持时间；Tag 丢失、深度无效、PnP/Depth 不一致、观测超时或速度仲裁失效时立即零速并退出。
- 适配视觉分支时，Tag 检测应消费 Humble Docker 中的原始 RGB 和真实同步 CameraInfo；深度使用同一 RealSense 驱动的 Raw Depth/投影关系。结构化结果可沿用 YOLO 3D 的 UDP bridge 模式传回 Foxy Host，不能另开一个 D455 进程。

### 本轮资料核验补充

- AprilTag 官方 README 明确：已知 `tagsize`、`fx/fy/cx/cy` 可估计 Tag pose，并推荐多数应用使用 `tagStandard41h12`；Tag 尺寸必须按检测角点对应的黑白边界测量。
- ROS2 `apriltag_ros` 明确：使用与图像同时间戳的 `CameraInfo.P` 计算 pose，输出 TF 及包含 `hamming`、`decision_margin` 的检测消息；这些字段可作为本项目质量门控输入。
- 本轮 `infsh` 辅助搜索因 PowerShell JSON 引号解析失败，未把失败输出当作证据；上述结论来自已直接读取的 AprilRobotics/apriltag 与 christianrauch/apriltag_ros 官方原始文档。

## 2026-08-06 — 仪表区禁贴定位码后的无标记精确观察方案

- 用户进一步确认比赛规则：仪表盘识别区域不能贴定位标识码；抓取/放置区域允许贴二维码。因此仪表区不能依赖 AprilTag/二维码做绝对锚点或最终对准。
- 历史真机数据已经证明，继续优化固定 `map` 航点不能根治观察位误差：纯 yaw 精确控制期间 cuVSLAM 曾报告约 `0.303m` XY 漂移；遥控标定航点也只是当前定位链下的可重复坐标，不是运行时独立物理真值。
- `feature/vision-change@89c2828` 的当前 `GaugeDetector` 已返回 A/B/C/D 与 red/yellow/green 的 bbox；`Inspector` 还检查字母是否位于仪表上方。但 `GaugeStatusNode` 发布的 JSON 只保留类别和置信度，丢弃 bbox、源时间戳、图像尺寸、深度和柜面姿态，因此当前链路不能用于视觉伺服。
- 推荐把仪表任务目标从“到达精确地图点”改为“达到合格观察质量”。Nav2 只负责进入宽松 staging/可见区域；停车后由仪表本体作为自然视觉目标，独立精确控制器根据相机相对仪表的误差完成最终对准。
- 最小闭环量测可以由现有 letter/gauge bbox 联合 ROI 提供：中心像素误差用于目标居中，bbox 尺寸和 D455 ROI 深度用于距离，完整入框边距/清晰度/置信度/多帧一致性用于判断能否识别。该层可先显著扩大对 SLAM 漂移和航点误差的容忍度。
- 仅靠 bbox 中心无法区分“机身侧移”和“斜着看”。若要求近似正视，应在仪表/柜面 ROI 的 Raw Depth 点上做鲁棒平面拟合，使用平面法向估计 yaw；深度不足时可用预先采集的理想参考图做自然特征/边缘 homography，对图像透视矫正或生成姿态误差。动态指针/颜色区域应从特征匹配中屏蔽。
- 推荐优先数字矫正而不是物理移动：只要目标完整入框且像素尺寸足够，先透视裁正并多帧识别；只有目标被裁切、距离不足或斜视超过算法验收阈值时，才取得 `/cmd_vel_precision` lease 做低速 RGB-D 视觉伺服。这会减少在狭窄柜体附近的额外运动风险。
- 视觉伺服应使用相机/`base_link` 相对误差，不依赖漂移的 `map→base_link`：前向误差来自柜面距离与期望距离，横向误差来自反投影后的目标中心，yaw 误差来自柜面法向或参考图 homography。现有 `Se2PoseController` 的限速、限加速度思路和 `cmd_vel_arbiter` 的 precision 优先级可复用，但控制输入必须改为视觉相对误差，而不是固定世界坐标目标。
- 安全模式应为：`NAV_STAGE -> ZERO_HOLD -> ACQUIRE -> VIEW_SERVO -> VIEW_READY -> CAPTURE`。进入 precision 前取消/停止 Nav2并确认最终三轴零速；检测丢失、图像/深度过期、深度有效率不足、目标出框或安全距离不足时立即三轴零速，不得沿最后一次视觉误差盲走。
- `VIEW_READY` 应基于连续多帧门限，而不是单帧检测：预期字母和仪表空间配对正确、完整入框、最小像素尺寸、清晰度、置信度、距离、平面角度以及稳定保持时间全部通过后，再从一段图像中选最清晰帧或做投票识别。
- 若到达 staging 后完全看不到目标，只允许在预先验证的局部净空内做限角、限时、低速搜索；每次失去检测立即归零。不得继续依赖漂移的全局 TF 做大范围盲目精调。
- 第一阶段不建议用自然仪表观测直接更新 `map→odom`。任务只要求看清仪表，局部相对视觉伺服更直接、风险更低。只有当累计漂移大到 staging 区也无法保证目标进入视野时，才进一步训练柜体四角/关键点或用 RGB-D 柜面几何估计完整自然地标位姿，再评估 markerless 全局重定位。
- 当前视觉分支中 `GaugeStatusNode` 仍直接打开 D455，和 Docker 单一 RealSense 驱动约束冲突。后续实施应让仪表几何检测在 Humble Docker 内订阅原始 RGB、Raw Depth、真实 CameraInfo/TF，并沿用 YOLO 3D 的最新帧和结构化 UDP bridge 模式传给 Foxy Host。
- Nav2 官方 Docking Framework 的流程提供了架构佐证：先导航到 staging pose，再启动外部检测，持续 refine pose，并在独立 vision-control loop 中完成最后接近。当前项目是 Foxy，不直接引入当前主线 Docking Server，只复用其职责分层。
- 官方资料：https://raw.githubusercontent.com/ros-navigation/navigation2/main/nav2_docking/README.md
## 2026-08-05 — 真实场地全路线标定的官方资料核对

- Nav2 Waypoint Follower 官方文档/源码说明：航点以有序列表执行；Waypoint Follower 的 `global_frame_id` 默认是 `map`，并支持在航点处执行等待、拍照等任务。因此“重新标定整条路线并保留任务顺序”符合 Nav2 的模型。
- Nav2 坐标变换文档说明：`base_link` 是机器人底盘坐标，传感器有独立 frame，导航目标应在全局坐标与机器人底盘坐标之间通过 TF 解释。标定应保存 `map -> base_link` 的最终机身位姿，而不是相机 frame 的未经外参转换坐标。
- Nav2 Map Server 官方 README 保留地图 YAML 的 `resolution`、`origin` 等元数据；PGM 只是栅格图像，地图原点和分辨率共同决定栅格到 `map` 坐标的映射。若真实场地与 PGM 存在整体平移/旋转，优先校正 map/TF 或对全部航点施加同一个 SE(2) 变换，不应逐点产生互相不一致的补丁。
- SLAM Toolbox 官方 README 说明 SLAM/定位发布 `map -> odom`，机器人底盘位姿由 `map` frame 中的 pose 表示，并支持从已保存地图/位姿图重新定位。因此“标定会话”和“正式导航会话”必须使用同一个地图版本、同一个起点/初始定位策略。
- 若差异是局部障碍物位置变化，重新采样航点不能修复 PGM 的障碍边界；应更新/重建地图或调整 costmap/keepout，并重新检查机器人 footprint 的净空。
- 资料来源：
  - https://docs.nav2.org/configuration/packages/configuring-waypoint-follower.html
  - https://docs.nav2.org/setup_guides/transformation/setup_transforms.html
  - https://raw.githubusercontent.com/ros-navigation/navigation2/main/nav2_map_server/README.md
  - https://raw.githubusercontent.com/ros-navigation/navigation2/main/nav2_waypoint_follower/README.md
  - https://raw.githubusercontent.com/SteveMacenski/slam_toolbox/ros2/README.md

## 2026-08-06 — 真实场地全路线航点标定器实现

- 导航 worktree 新增纯模块 `src/nodes/navigation/waypoint_calibration.py`：使用标准库 JSON 结构化写入 JSON-compatible YAML；支持普通 YAML 的可选 PyYAML fallback；提供跨 `+-pi` yaw 圆均值、XY 中位数、稳定窗口拒绝、配置校验和命名路线解析。
- 新增 `scripts/waypoint_calibration_recorder.py`：交互式逐点采样 `map -> base_link`，默认 3 秒/10Hz、至少 20 个新鲜样本，默认最大 XY 偏差 `0.04m`、最大 yaw 偏差 `0.06rad`；每个候选点需人工确认后原子保存。脚本未导入 Twist、未创建 publisher，不具备速度下发路径。
- `configs/navigation/waypoints_real.yaml` 定义 `inspection_interleaved` 与 `full_interleaved`；巡检顺序为 `obstacle -> left_clear -> middle(+向) -> upper-right -> middle(-向) -> lower-right`，完整路线随后进入抓取和 A/B/C/D 放置，共 11 个导航目标；`start` 作为坐标基准另行标定但不作为路线目标。
- `nav2_waypoint_sequence_probe.py` 新增显式 `--waypoint-file + --waypoint-route` 数据源。配置在 ROS 初始化前校验：两参数必须成对、`map_id` 非空、frame 匹配、路线点全部存在，实际执行还要求 `calibration.status=complete`；只读 `--describe-route` 可在完成前检查内容。默认内置 preset 未改变。
- 现有配置文件在标定 session 开始时备份到 Git 忽略的 `configs/navigation/calibration_backups/`，不会被 setup.py 的 `*.yaml` 安装 glob 一并打包。
- 本机验证：新标定测试 6/6、既有 takeover 3/3、SE(2)/yaw-only 12/12、速度一致性 1/1；`py_compile`、`git diff --check`、JSON 模板解析和合成 11 目标路线解析均通过。未启动 ROS、Jetson 或真机运动。

## 2026-08-06 — 仪表区无人工标记的全局重定位架构

- 最新比赛规则由用户确认：AprilTag/二维码只允许布置在抓取区和放置区，仪表识别区不能布置人工定位标记。
- 当前导航实现的 `initial_pose_publisher.py` 使用静态广播器持续发布固定起点 `map -> odom`；`final_bridge.py` 发布连续的 `odom -> base_link`。因此当前系统没有运行中更新全局校正量的所有权节点，仪表区也不可能仅靠现有设置完成重定位。
- 推荐将全局定位从仪表识别器中独立出来：保留 cuVSLAM 负责连续 `odom -> base_link`，新增唯一 `global_pose_manager` 负责动态 `map -> odom`。起点先验、仪表区自然特征观测、抓取/放置区 AprilTag 都只向它提交绝对位姿候选，不允许多个节点直接广播同一 TF。
- 若仪表柜/变压器在 `map` 中的位置和朝向固定且赛前可测量，可把官方物体本身作为自然地标：检测柜体边框、固定字母、仪表圆环等静态几何，屏蔽会变化的指针/颜色区域，结合真实 CameraInfo、`solvePnPRansac` 或 RGB-D 平面拟合估计 `T_camera_panel`，再由已知 `T_map_panel` 与相机外参计算绝对 `T_map_base`。
- 若仪表柜的位置或朝向每场随机，则它不能作为绝对地图锚点；此时必须改用与任务物体无关的固定场地特征做全场定位，例如预建 RGB-D 自然特征地图的 localization 模式，或 D455 深度投影到二维扫描后与固定占据地图做 AMCL。没有已知地图对应物或人工锚点时，单帧局部观测在信息论上无法给出唯一全局位姿。
- 全局校正必须在零速保持、多帧稳定、时间同步、重投影/深度/残差门控通过后更新。计算关系为 `T_map_odom = T_map_base_measured * inverse(T_odom_base_current)`；更新后清理或刷新全局/局部 costmap 并重新规划，禁止运动中硬跳 TF。
- 仪表识别最终对准仍使用相对视觉伺服，不依赖刚更新后的世界航点。全局重定位负责让机器人回到正确 staging 区，相对 RGB-D 视觉闭环负责完整入框、距离和正视角度，两者职责不能合并。
- 现阶段最关键的规则确认项是：仪表柜/变压器的场地位姿是否固定。固定时优先自然地标 PnP/RGB-D 方案，改动较小；随机时优先全场预建自然特征地图定位，工作量与算力风险更高。

## 2026-08-06 — 运动中全局重定位官方资料核验

- ROS REP-105 明确：`odom` 应连续但允许长期无界漂移；`map` 作为长期全局参考可以在新传感器观测到来时发生离散跳变；定位组件应读取 `odom -> base_link`，并发布 `map -> odom`。因此运动中纠漂的标准结构不是重置 odom，而是保持局部里程计连续并持续更新全局校正。
- NVIDIA Isaac ROS Visual SLAM 官方 `release-2.1` 分支 commit `a2e2cc979b47e1fa344450b20f3a51cfd7f481d4` 明确支持 `enable_localization_n_mapping`、`publish_map_to_odom_tf`、`visual_slam/save_map` 和 `visual_slam/load_map_and_localize`。后一个 action 会加载已保存的 landmark/pose-graph 地图，并要求 `localize_near_point` 作为平移位置提示；官方文档将其描述为“given a prior pose”，不是无提示的全场 kidnapped-robot recovery。
- 同一版本源码在每帧 `CUVSLAM_Track` 后读取连续 VO pose；SLAM 模式额外调用 `CUVSLAM_GetSlamPose` 得到 loop-closure rectified pose，并计算 `T_map_odom = T_map_base_slam * inverse(T_odom_base_vo)`。源码明确注释 rectified pose 会因 loop closure 发生 sudden jumps，这正符合 REP-105 的 map/odom 分工。
- 当前 Nav2 worktree 的生产启动显式设置 `CUVSLAM_PUBLISH_MAP_TO_ODOM_TF=false`，`final_bridge.py` 默认桥接 `/visual_slam/tracking/odometry`，而 `initial_pose_publisher.py` 静态发布起点 `map -> odom`。所以当前生产链只有连续 VIO/VO，相对场地地图没有运行中视觉地图校正；用户指出的长期漂移风险成立。
- 对当前 `release-2.1 + Xavier NX + Humble Docker/Foxy Host`，首选验证路径是复用 cuVSLAM 自带持久视觉地图：赛前在正式场地建图并闭环覆盖路线，保存 map；比赛启动时用官方起点作为 prior 调 `load_map_and_localize`；运行中保留 tracking odometry 为 `odom -> base_link`，同时把 SLAM map pose 与同时间戳 tracking pose桥接到 Host，计算并唯一发布动态 `map -> odom`。
- 由于 Foxy Host 与 Humble Docker 当前通过 UDP 桥接，不能直接简单打开第二个 TF 发布者。Host 侧应同时接收 `T_map_base_slam` 和 `T_odom_base_vo`，以同时间戳计算 `T_map_odom`；必须停止 `initial_pose_publisher` 的静态 `map -> odom`，避免 TF 双发布者冲突。
- Nav2 当前 local costmap 使用 `odom`、global costmap 使用 `map`，结构上适合 REP-105：小幅 map 校正可在线接受；大幅位置/朝向跳变应触发零速、清理 costmap 并重新规划，不能让控制器在全速行走时吞下大跳变。
- NVIDIA 当前文档明确指出 cuVSLAM 本身的 map localization 需要外部 pose hint，并推荐另一个 Visual Global Localization 包完成无提示全局定位。官方 `isaac_ros_mapping_and_localization` 仓库最早只有 `release-3.2`，不存在 `release-2.1`，因此不能把当前 cuVGL 能力直接套到本项目的 JetPack/Isaac ROS 2.1 环境。
- RTAB-Map 官方 `foxy-devel` launch 的 `localization=true` 会设置 `Mem/IncrementalMemory=false`、`Mem/InitWMWithAllNodes=true`，读取已保存数据库，并持续计算/发布 `map -> odom`；可用 cuVSLAM tracking odometry 作为外部 odom，是 cuVSLAM 持久地图链验证失败后的合理备选，但会增加 RGB-D 特征处理、跨容器数据和 Xavier NX 算力压力。
- Nav2 AMCL 官方文档确认其订阅 `scan` 与 `map`、按平移/旋转阈值更新粒子滤波，并可发布 global frame 到 odometry frame 的 TF；官方 `depthimage_to_laserscan` 可把深度图转换为 LaserScan。因此 D455 Depth+AMCL 在接口上成立，但本项目相机向下倾斜约 30 度、视场非 360 度且场地含随机物体，不能直接把单行深度当水平激光扫描，需先做 base frame 点云投影/高度切片并验证地图可观测性，优先级低于视觉地图定位。

### 官方来源

- https://www.ros.org/reps/rep-0105.html
- https://nvidia-isaac-ros.github.io/v/release-2.1/repositories_and_packages/isaac_ros_visual_slam/isaac_ros_visual_slam/index.html
- https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/tree/release-2.1
- https://nvidia-isaac-ros.github.io/repositories_and_packages/isaac_ros_mapping_and_localization/isaac_ros_visual_global_localization/index.html
- https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_mapping_and_localization
- https://github.com/introlab/rtabmap_ros/tree/foxy-devel
- https://docs.nav2.org/configuration/packages/configuring-amcl.html
- https://github.com/ros-perception/depthimage_to_laserscan/tree/ros2

### 技术论坛与上游 Issue 交叉核验

- NVIDIA 工程师在 Developer Forums 明确说明：`LoadMapAndLocalize()` 会加载 landmark pose graph、用 hint 在图中定位，成功后会在机器人移动过程中继续报告地图内位姿，不需要沿途重复调用该 action。来源：https://forums.developer.nvidia.com/t/isaac-ros-vslam-localization-and-imu-questions/235218/7
- Isaac ROS Visual SLAM issue #72 中 NVIDIA 工程师说明：`enable_mapping_and_localization=true` 才会使用 landmark map 输出 rectified pose；识别 landmark、闭环和历史位姿修正会带来离散跳变。视觉 landmark map 与 Nav2 静态占据地图不是同一张地图，二者必须有固定坐标变换；视觉地图原点保持静态。来源：https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/issues/72
- issue #142 中 NVIDIA 维护者再次区分：VO path 平滑但会漂移，SLAM path 相对 `map` 更准确但可能跳变。这支持将 `/visual_slam/tracking/odometry` 用作连续 `odom -> base_link`，将 SLAM pose 仅用于求动态 `map -> odom`。来源：https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/issues/142
- issue #137 针对 `release-2.1` 指出：`LoadMapAndLocalize` 只有在当前视角特征能匹配已保存 landmarks 时才成功；倾斜安装和与建图视角相差较大的 yaw 会降低成功率。项目 D455 固定下倾约 30 度，因此赛前地图必须保持同一安装外参、覆盖正式路线的预计朝向，并在已知起点静止验证，不能假设只给平移 hint 就能从任意朝向恢复。来源：https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/issues/137
- issue #155 与对应 Developer Forum 记录了 `LoadMapAndLocalize` 在高负载、加载时机或定位失败路径上的崩溃/竞态案例；比赛链必须把 action 成功、输出帧连续和视觉地图匹配健康作为 fail-closed 前置条件，并设置进程 watchdog，不能仅检查 action server 存在。来源：https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/issues/155 与 https://forums.developer.nvidia.com/t/isaac-ros-visual-slam-loadmapadnlocalize-crashes/292250
- Developer Forum 的 Nav2 集成讨论确认：VSLAM 保存的是供自身定位使用的视觉特征地图，Nav2/Nvblox 使用的是另一类导航地图；两者都需保存/加载并完成 frame 对齐。来源：https://forums.developer.nvidia.com/t/isaac-ros-vslam-nvblox-usage-with-nav2/303717
- 当前主工作目录的未跟踪启动脚本与历史 Nav2 worktree 不一致：`scripts/start_competition.sh` 关闭 `CUVSLAM_PUBLISH_MAP_TO_ODOM_TF`，且调用 `final_bridge.py` 时未指定 topic；当前 `final_bridge.py` 默认订阅 `/visual_slam/vis/slam_odometry`，随后重标成 `odom -> base_link`。该 map-frame rectified pose 可能跳变，不应占用连续 odom 职责。实施前必须先确认 Jetson 实际部署分支，再将平滑 tracking odometry 与 SLAM map pose 分成两路同时间戳桥接。

## 2026-08-06 — 航点标定功能 Jetson 部署结果

- Jetson 上未跟踪的 `scripts/nav2_waypoint_sequence_probe.py` 包含此前已部署的 yaw-takeover/SE(2) 改动；与本地当前文件做 no-index diff 后，差异仅为本次标定路线接入的 65 行新增和 7 行调整，因此同步没有覆盖 Jetson 独有控制逻辑。
- 7 个目标文件同步后 SHA-256 与本地逐项一致；远端备份清单同时记录原有 3 个文件哈希和 4 个缺失文件，可从 `tmp/waypoint_calibration_sync_backup_20260806_125943/` 回退。
- Windows `scp -p` 将源文件的 Windows 权限映射成远端 `0666`；已依据 Jetson 原文件及 Git 模式统一恢复为 `0644`。后续从 Windows 同步到 Linux 后必须显式复核并修正 mode。
- Jetson Python 3.8、Foxy 环境和项目 overlay 能加载新模块；26 项相关测试、合成标定路线 CLI 描述及限定包 colcon 构建全部通过。仓库模板保持 `not_calibrated`，在填写 `map_id` 和全部航点前会 fail closed，不会误执行路线。

## 2026-08-06 — YAML 交错路线本地预演边界

- 当前 `waypoints_real.yaml` 已列出交错顺序，但 `waypoints` 为空；真正的内置 `nav-only-full/nav-only-inspection` 仍使用同点 yaw-takeover 生产 preset。因此要预演新顺序，必须显式加载带坐标的 YAML，不能把内置 preset 的结果当成已重构路线。
- `competition_field.pgm` 为 `226 x 240` 像素、分辨率 `0.025m`、原点 `[0,0,0]`，对应约 `5.65m x 6.00m`。现有 PGM preset 坐标均在地图范围内，可用于本地拓扑预演，但不能冒充重新遥控标定后的真实坐标。
- 本轮采用独立 `waypoints_reordered_preview.yaml`：写入旧 PGM 坐标和交错观察顺序，`calibration.status=preview`。现有 probe 的执行门禁只接受 `complete`，因此该文件只能做 `--describe-route`、测试和地图预览，不会被误用于真机导航。
- PGM 叠加预览显示，`middle -> upper-right -> middle-turned` 的直线连接位于上方柜体右侧，`middle-turned -> lower-right` 位于下方柜体右侧，拓扑上绕开了同点反转。该虚线仅表示航点顺序；仓库现有 A* 图片属于旧路线，不能据此宣称 Nav2 已生成或可通过这些路径。
- 离线完整路线解析得到 11 个目标、航点间直线距离合计约 `13.01m`，所有相邻转场都不是“距离 <=0.05m 且 yaw 变化 >=150deg”。四个观察动作顺序为 `upper_gauge -> upper_side -> lower_gauge -> lower_side`。
- 27 项相关回归全部通过，说明新增 YAML 没有破坏现有 yaw-takeover、SE(2)/yaw-only、速度仲裁和速度限制逻辑。由于本轮未运行 Nav2 planner/controller，这只能证明数据顺序和离线契约正确，不能证明真实 footprint 净距、规划成功率或现场到位效果。

## 2026-08-06 — Jetson 交错巡检试跑前安全事实

- Jetson 同步前完整进程表没有 Nav2、waypoint probe、cmd_vel bridge/arbiter、motion sender、final bridge 或 cuVSLAM 运动栈进程；目标 worktree 与上一轮部署一致。
- 试跑必须使用 `scripts/start_competition.sh --dog --cmd-vel-bridge --prepare-lite3-motion`：脚本先执行 `stop_all.sh`，再启动 cuVSLAM、final bridge、Nav2、cmd_vel arbiter 和狗侧 bridge；未启用 task manager，避免任务自动推进。
- `stop_all.sh` 会在杀进程前分别向 `/cmd_vel_precision` 和最终 `/cmd_vel` 连续发布三轴零速；这条清理链必须在 probe 成功、失败、超时或 SSH 中断后的最终核查中执行。
- 本次只允许运行 `inspection_interleaved` 六点路线；YAML 的 `action` 仅写日志，probe 不执行抓取、放置或视觉任务。真实目标发出前仍必须检查 Lite3 网络、D455/cuVSLAM 跟踪、Nav2 lifecycle、`map -> base_link`、costmap 边界、速度单一出口和最终零速。

## 2026-08-06 — Jetson 交错巡检真实试跑结论

- 试跑前 ROS/TF/costmap/速度出口门禁通过，初始 `map -> base_link` 约为 `(4.491, 0.639, 3.105)`；启动日志给出五个 Nav2 managed nodes active，Lite3 网络 0% 丢包。
- `inspection_interleaved` 实际只完成前两点：`obstacle_cross_target` 和 `pos1_left_clear` 均返回 `SUCCEEDED`。两点终点 XY 误差约 `0.144m` 和 `0.143m`，均贴近当前约 `0.15m` 容差边界。
- 第三点 `pos1_middle=(1.50,3.25,yaw=pi/2)` 在 130 秒级超时后安全取消，末端 `(1.239,3.182,yaw=1.121)`，XY 误差约 `0.270m`、yaw 误差约 `0.450rad`。因此 `pos2a_upper_right -> pos1_middle_turned -> pos2b_lower_right` 没有被发送，无法据此声称新路线六点全通。
- 这次结果区分了两个问题：路线重排确实消除了同点反向 middle 位姿的直接 180 度相邻关系；但 middle 的真实可达/收敛仍失败，当前旧 PGM 坐标不能作为已标定真实观察位。下一步应先重新遥控标定并确认 middle 的实际坐标与 yaw，或先做更短的到位/停稳单点验证，再决定是否启用完整交错路线。
- 运动期间 probe 采样 TF age 约 `0.02-0.12s`，cmd_vel bridge 统计 `udp_errors=0`；失败是到位超时而非 TF stale 或 UDP 下发错误。`stop_all.sh` 已发布零速并清理 Nav2、bridge、arbiter、probe；cuVSLAM 容器按脚本约定保留。

## 2026-08-06 — cuVSLAM 全局校正 Stage A 审计发现

- Jetson 的生产目标文件虽然位于大量未提交部署改动中，但本阶段六个关键文件与本地 DWB worktree SHA-256 完全一致；实现应继续以该 worktree 为源，同时保留远端既有未跟踪文件，不做整树覆盖。
- 实际 cuVSLAM 后端已启用 localization/mapping，且同时输出连续 VO `odom -> camera_link` 与 rectified SLAM pose `map -> camera_link`；两路约 60Hz、source stamp 可直接配对。因此 Stage C 不需要改变 cuVSLAM 后端，只需新增独立 exporter/Host bridge。
- 当前 `map` 是 cuVSLAM 内部视觉地图 frame，不是 Nav2 占据地图的已验证同源 frame。第二路 Host topic 必须重命名为显式 `vslam_map` 语义，后续仍需独立的 `T_nav_map_vslam_map` 标定文件。
- `publish_map_to_odom_tf=false` 和 `publish_odom_to_base_tf=false` 在实际 launch 中已生效；采样窗口没有动态 TF 边，当前不会与 Host 的未来唯一 global pose manager 冲突。
- Host Foxy 无 Isaac ROS 专用消息接口，审计与运行桥接应优先使用标准 `nav_msgs/Odometry`、`tf2_msgs/TFMessage` 或容器内专用客户端，不依赖 Host 直接解析 `/visual_slam/status`。

## 2026-08-06 — cuVSLAM 全局校正 Stage B A/B 结论

- A 组（可视化开）与 B2 组（可视化关）在相同 D455 640x360x60、IMU 200Hz、planar、localization/mapping=true 条件下，VO bridge `/odom` 均维持约 60Hz、`odom -> base_link`、invalid drop=0；关闭三项可视化没有造成 tracking 输出回归。
- 稳定窗口资源对比：A Docker 约 108% CPU/721MiB，B2 约 113% CPU/558MiB；tegrastats A RAM 3.17-3.21GB、GR3D 31-64%，B2 RAM 3.15-3.18GB、GR3D 30-54%，温度均约 32-35C。短窗口内 B2 不劣于 A，不能据此声称完整路线或长期热稳态已经验证。
- bridge 的 stale drop 主要发生在启动/SSH 查询竞争阶段；稳定段 A 增约 2、B2 增约 2，source stamp 延迟约 15-30ms。Stage C 应把 source stamp、receive time、stale_drop 和配对结果结构化记录，不依赖当前日志抽样推算 p95。
- `start_cuvslam_rviz_gui.sh` 在实际运行中第 900 行打印 `topic_list_cmd: command not found`，但脚本继续执行。该现存缺陷必须在生产切换前修复或显式证明是旧分支残留；它不影响本次已完成的 cuVSLAM A/B 结论。
- 启动脚本通过前台 `docker run` 持有容器生命周期；测试期间不可杀启动脚本 PID 来“清理”容器，应先按 bridge/exporter、容器、脚本的生命周期顺序停止，并最后检查无残留进程。

## 2026-08-06 — cuVSLAM 全局校正 Stage C 双轨桥接结论

- 新 SLAM bridge 的 output contract 是 `/cuvslam/slam_pose`、`header.frame_id=vslam_map`、`child_frame_id=base_link`；payload 额外保留 `source_frame_id=map`、source stamp、sequence、receive time。这样不会把 cuVSLAM 视觉 `map` 偷换成 Nav2 `map`。
- Jetson 无运动运行中，VO `/odom` 与 SLAM `/cuvslam/slam_pose` source stamps 精确一致（10 秒采样配对 max=0ms），两路均由独立 bridge 产生；`/odom` 只有 `final_bridge` publisher，SLAM topic 只有 `cuvslam_slam_pose_bridge` publisher。
- `/tf` 采样只有 `odom->base_link`，没有 `map->odom`；topic info 虽显示 `visual_slam_node` 作为 `/tf` publisher endpoint，但该配置窗口实际没有消息边，且 cuVSLAM launch 明确两个 TF 参数 false。生产切换前仍应把 authority/edge 采样纳入 watchdog。
- identity 对齐下的候选 `vslam_map->odom` 约 `(0.08m, 0, 0)` 是 camera/base 外参与两路 pose 的一致性信号，不是 Nav2 地图对齐结果。必须用至少两个远离起点的已知控制点和地图/版本哈希生成 `T_nav_map_vslam_map`，否则 manager 继续 pending/legacy。
- 本阶段没有运行 `global_pose_manager` 动态模式；配置和 launch 只证明唯一所有权门禁可用，真正回环纠偏、costmap 清理/重规划和持久地图生命周期仍未验收。

## 2026-08-06 — cuVSLAM 全局校正 Stage D-F 接口与安全结论

- Jetson 安装的是 Isaac ROS 2.1.0、仓库 commit `a2e2cc979b47e1fa344450b20f3a51cfd7f481d4`。实际 action 名为 `/visual_slam/save_map` 和 `/visual_slam/load_map_and_localize`；前者 goal 只有 `string map_url`，后者 goal 是 `string map_url + geometry_msgs/Vector3 localize_near_point`，结果才包含 `bool success + geometry_msgs/Pose pose`。
- `localize_near_point` 是保存的 cuVSLAM 数据库坐标，不是 Nav2 `map` 坐标，且该接口没有 yaw hint。正确流程必须先用审核后的 `inverse(T_nav_map_vslam_map)` 转换 Nav2 起点，只把转换后的平移发送给 action；成功后再把返回 pose 变回 Nav2 map，并独立检查 XY/yaw 与起点 prior 的一致性。
- 正式 alignment bundle 的有效性取决于 Nav2 YAML、其引用的 PGM、非空视觉地图、D455 外参、起点 prior、map ID 和多控制点拟合结果。只校验文件存在或只记录 hash 而不比对都不够；任何内容/path/hash 变化必须使加载 fail closed。
- lifecycle guard 不是唯一信任边界：`global_pose_manager` 在读取 `status=complete` 配置时必须再次核对顶层/内层 status、`mode=cuvslam_global` 和全部 artifact hash。否则手工改一个 status 就可能绕开比赛启动前的离线 guard。
- ROS 两个约 60Hz topic 的 callback 会交替触发 manager；若只按“连续 update 次数”计稳定帧，同一 source-stamp pair 可能被重复消费。核心必须记录 pair key 去重，稳定帧只能由新的 VO/SLAM 时间对推进。
- 当前离线 manager 能将 medium correction 置 `relocalize_hold`、large correction 置 `fault_hold`，但还没有完成“零速 lease → cancel goal → 应用校正 → 清 costmap → 重规划”的 ROS/Nav2 协调器。正式动态 `map -> odom` 在该协调器和真实 alignment 验收前不能启用。

## 2026-08-07 — 首轮真实路线未触发视觉闭环

- 物理返回起点不等于 cuVSLAM 已闭环。完整优化 pose graph 的起点为 `(0,0)`，返回后的终点约为 `(9.116,1.539)`，XY 闭环误差 `9.245m`；实时 rectified SLAM pose 也稳定在约 `(8.32,1.57)`，两项证据一致表明后端没有把当前起点视角匹配回初始 landmarks。
- 旧 rolling `/visual_slam/tracking/slam_path` 在末端静止时只保留重复点，会产生“零闭环误差”的假象；真实判定必须优先使用 `/visual_slam/get_all_poses` 的完整优化 pose graph，并保留 `rolling_slam_path_static_while_get_all_poses_moved` 注记。
- 本轮 tracking 连续、`vo_state=1`、没有 tracking-lost，不代表地图全局一致。tracking health 和 loop-closure quality 是两项独立门禁。
- 当前不应保存正式视觉地图。下一次补拍应在物理起点附近缓慢走约 `0.5m` 小环或小弧线，覆盖建图开始时的正前、左侧和右侧视角，最后回到相同位置与朝向；随后再次查询完整 pose graph。若仍是米级误差，应放弃本轮并冷启动重建，而不是用对齐器吸收错误。

## 2026-08-07 — 启动问题与建图问题边界

- 启动不是主失败点：相机、IMU、status 和 odometry 已持续发布，单次 `Motion Module failure` 与 frame-delta warning 后 tracking 仍保持健康。`ExternalShutdownException` 是 CLI echo 被外部结束的表现；真正需要修的是 recorder 参数版本错配和脚本输出/退出管理。
- `GetAllPoses` 属于重型后验查询，不应以 5-10 秒周期和大 `max_count` 在正式建图中运行。日志中每次调用附近的 frame delta 从常见约 `33-100ms` 上升到约 `484-718ms`，可能挤占 tracking 调度；正确方式是在线禁用该服务，只在停稳后单次查询。
- 建图失败的直接证据是优化 pose graph 返回起点误差 `9.245m`，而不是 tracking 丢失。可能原因包括返回起点时位置/yaw/观察方向不一致、路线反走时相机看到的是相反视角、起点与关键转角缺少左右扫视和近距离小闭环、移动过快导致模糊，以及视野中过多低纹理地面或可移动箱体；这些是待下一轮通过采集规程逐项消除的假设。
- 即使下一轮闭环误差通过，也仍需至少 3 个分散、非共线控制点及 Nav2 实测坐标完成 alignment；单纯“走完整路线并回起点”只能验证视觉地图自洽，不能完成 Stage D 正式标定。

## 2026-08-07 — recorder 分层修复与无运动实测

- DWB Jetson 工作树的旧 recorder 只有 342 行且不接受启动脚本传入的 `--mount-mode`、`--expected-base-frame`，导致 recorder 随栈启动失败；cuVSLAM 主体仍能启动。修复后在线 recorder 只订阅轻量 topic，显式不依赖 `isaac_ros_visual_slam_interfaces`，并以 `robot_base_ready` 检查 `odom/base_link` 契约。
- 完整 `GetAllPoses` 查询必须由独立 `cuvslam_get_all_poses_once.py` 显式触发；无运动实测返回 15943 poses，报告 `service_calls=1`，没有周期性服务调用。该工具的 post-run 目录与在线报告分离，避免重型后验查询挤占 tracking。
- Jetson 同步前备份为 `tmp/cuvslam_recorder_sync_backup_20260807_133100/`；远端 4 个文件 SHA-256 与本机一致。无运动启动仅运行 cuVSLAM/recorder，约 60Hz odometry、`robot_base_ready=true`，无 Nav2/cmd_vel/bridge/motion 进程；清理后 Docker、PID 和启动脚本均为空。
- 静止查询的 `frame_id` 为空是 Isaac ROS 2.1 `GetAllPoses` 返回 PoseStamped header 未填 frame 的接口表现；报告保留空值而不猜测地图 frame，后续真实路线应以 launch/frame 契约交叉核验。
- 启动过程中出现一次 RealSense `Motion Module failure` 硬件告警，但 status/odometry 持续发布、未出现 tracking-lost；本轮未触发 `save_map`，因为轨迹仅约 `0.106m`，属于静止工具验收而非建图闭环验收。

## 2026-08-07 — 建图规程执行边界

- 真机建图必须把在线轻量 recorder、停稳后一次性 `GetAllPoses` 和最终 `save_map` 分成三个阶段；不能在运动中用完整 pose graph 查询代替健康监控。
- `save_map` 的 action client 需要在 cuVSLAM 容器内执行，且 `map_url` 必须是容器内绝对路径；将其放在 `/logs/maps/` 才能通过 Docker 日志卷持久化到 Jetson 主机。
- 物理回到起点不等于视觉闭环。只有完整优化 pose graph 的 `xy_closure_error_m < 0.20m` 才允许候选保存，`<=0.10m` 才接近项目正式目标；`xy_path_length_m < 5m` 时只能判定“运动不足”。

## 2026-08-07 — 正式路线提前 Ctrl+C 的后果

- `loop_metrics_latest.txt` 的 `odometry.path_length_m=38.048m` 只能证明 odometry 采集到了运动；rolling `slam_path` 的约 `0.0566m` 路径不是完整优化 pose graph，不能代替闭环判断。
- 在 `/logs/postrun_metrics_full/loop_metrics_latest.txt` 产生前按 `Ctrl+C` 会销毁 cuVSLAM 容器并结束内存中的本轮地图；若没有 `save_result.json`，本轮不能恢复或加载为候选地图。
- 下一轮必须把“停稳 10 秒 → 一次性 GetAllPoses → 读取 XY 闭环 → 通过后才 save_map → 最后 Ctrl+C”作为不可跳过的顺序。

## 2026-08-07 — 51m 路线首次后验闭环结果

- 本轮完整优化 pose graph 返回 17845 个 pose，XY 路径长度 `51.121018m`，终点相对起点约 `(0.720329,-0.014735)`，XY 闭环误差 `0.720479m`；相比上一轮 `9.245m` 明显改善，但仍超过 `0.50m` 可用上限，不能保存为候选视觉地图。
- 物理回到起点与 tracking 持续健康仍不足以证明有效闭环；当前应保持同一 cuVSLAM 会话，在起点附近补采初始正前、左侧和右侧视角，再查询优化 pose graph，观察误差是否因后端 landmark 匹配而收敛。

## 2026-08-07 — 起点补拍只能部分收敛闭环误差

- 起点补拍后完整 pose graph 增至 26041 个 pose、XY 路径 `60.778652m`，XY 闭环误差由 `0.720479m` 降至 `0.559822m`；改善幅度约 `0.161m`，但没有跨过 `0.50m` 可用门限，更未达到 `<0.20m` 的保存目标。
- 补拍带来连续改善不等于已触发可靠回环；在误差仍为 `poor` 时保存地图会把未闭合的全局几何固化，当前必须继续拒绝 `save_map`。

## 2026-08-07 — 多次起点补拍未形成稳定视觉闭环

- 同一 cuVSLAM 会话内三次完整优化 pose graph 的 XY 闭环误差为 `0.720479m -> 0.559822m -> 0.692829m`。第一次补拍改善后，第二次局部视角恢复反而回退，说明误差变化不是稳定 landmark 闭环收敛，不能用单次接近 `0.50m` 的数值作为保存依据。
- 本轮最终 pose graph 含 38104 个 pose、XY 路径 `69.612491m`，但终点仍被估计在相对起点约 `(0.613099,0.322679)`；完整路线和起点附近左右小弧补拍都未把后端拉回原点。
- 正式视觉地图必须继续执行 `<0.20m` 的闭环保存门禁，并要求补拍后的重复查询保持或继续收敛；误差反弹时应直接拒绝保存和清理会话，而不是继续累积局部运动或把误差交给 alignment 吸收。

## 2026-08-07 — D455 安装倾角与四足视觉 SLAM 联网核验

- NVIDIA Isaac ROS Visual SLAM 官方文档没有要求相机必须水平。坐标系契约要求相机刚性安装到 `base_frame`，并通过静态 `base_frame -> camera_optical_frame` 变换表达实际安装姿态；因此约 30 度下倾在几何上受支持，前提是外参方向和数值正确。来源：https://nvidia-isaac-ros.github.io/repositories_and_packages/isaac_ros_visual_slam/isaac_ros_visual_slam/index.html#coordinate-frames
- NVIDIA 明确说明 cuVSLAM 依赖在尺度、方向、透视、光照变化下仍可重复检测的 distinctive keypoints；大块单色/低纹理视野会缺少关键点。SLAM 回环只有在重新识别多个历史 landmarks 后才会建立 pose-graph 边并优化全轨迹；IMU 在短时视觉退化时只能维持 VIO，不能代替长期视觉回环。来源：https://nvidia-isaac-ros.github.io/repositories_and_packages/isaac_ros_visual_slam/index.html 和 https://nvidia-isaac-ros.github.io/concepts/visual_slam/cuvslam/index.html
- NVIDIA `release-2.1` 官方排障列出快速运动造成的 motion blur、低照度、错误 CameraInfo，以及 RealSense 发射器造成漂移等风险；提高帧率和正确相机参数有帮助，但没有把水平安装列为必要条件。来源：https://nvidia-isaac-ros.github.io/v/release-2.1/repositories_and_packages/isaac_ros_visual_slam/isaac_ros_visual_slam/index.html
- NVIDIA issue #137 中维护者指出，`LoadMapAndLocalize` 若当前 viewing angle 的特征与已存 landmarks 不匹配就会失败；用户报告倾斜安装及同点大 yaw 变化更容易失败。该 issue 是案例证据，不等同于官方宣称倾斜安装不受支持。来源：https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/issues/137
- Intel 官方 D455 规格为双目深度、深度视场约 `86 x 57` 度、标称工作范围 `0.6-6m`。当前相机高度约 `0.493m`、下倾约 30 度时，垂直视场约从地平线下 `1.5` 度到 `58.5` 度，光轴与平地交点约 `0.85m`；画面仍能在顶部看到远处，但像素分配明显偏向近地面。来源：https://www.intel.com/content/www/us/en/products/sku/205847/intel-realsense-depth-camera-d455/specifications.html
- WALK-VIO 四足 VIO 论文摘要明确指出，天空或地面提取到的 extraneous features 会导致 tracking failures，四足步态 wobbling 也会降低相机/IMU定位精度。这支持单相机采用中等下倾、避免画面被天空或近地面任一方主导，而不是机械规定绝对水平。来源：https://arxiv.org/abs/2111.15164
- VILENS 在 1.8km ANYmal 实验中依靠视觉、IMU、LiDAR 与腿里程计紧耦合来跨越黑暗、灰尘和 feature-deprived 场景，说明工程级四足定位通常不把单一路向视觉作为唯一绝对来源。来源：https://arxiv.org/abs/2107.07243
- 本轮最终 XY 闭环比值 `0.692829 / 69.612491 = 0.995%`，接近 NVIDIA 公布的 KITTI VO 平移误差 `0.94%`。两者场景不可直接横比，但数值形态支持“前端 VO/VIO 正常累计、后端未形成有效回环”的解释；30 度下倾可能是重要促成因素，但现有数据不能证明它是唯一根因。

## 2026-08-07 — 新一轮改进采集仍未形成后端闭环

- 本轮在冷启动后先做起点小环，再按低速、关键转角左右扫视和场地边缘回起点的改进规程完成正式路线；起点小环阶段前端 XY 回起点误差仅 `0.0333m`，说明初始局部运动和物理复位可以做到较好。
- 完整路线结束时前端 odometry 路径为 `40.817m`、XY 回起点误差 `0.3901m`；唯一一次完整优化 pose graph 则为 `33380` poses、XY 路径 `48.045740m`、终点 `(0.816912,0.375257)`、XY 闭环误差 `0.898979m`。后端结果比前端更偏离起点，没有出现把全局轨迹拉回原点的有效闭环证据。
- 与上一轮最终 `0.692829m` 相比，本轮 `0.898979m` 更差；即使起点小环本身闭合、正式路线增加扫视，当前单 D455/cuVSLAM 配置仍不能稳定满足 `<0.20m` 保存门槛。继续重复同一采集流程的边际价值很低，下一步应改变可观测性或定位方案变量，而不是再保存不合格地图。
- 本轮严格只调用一次 GetAllPoses，未调用 save_map，完整证据保存在 `/home/superwfx666/cuvslam_lite3_logs/20260807-154031/postrun_metrics_full/`。

## 2026-08-07 — 联网调研：D455 漂移案例（进行中）

- NVIDIA Isaac ROS Visual SLAM issue #67 报告 D455 在室外出现约 `1.2m/10s` 漂移和 `0.7-0.8x` 尺度偏差。NVIDIA 社区首先要求关闭 RealSense IR emitter，因为投射到左右 IR 图像中的主动纹理会随相机移动，可能被 VSLAM 当成场景特征；本项目下一轮必须机械核验 emitter 实际状态，而不能只依赖默认参数假设。来源：https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/issues/67
- 同一 issue 中 NVIDIA 维护者要求改用更新后的官方 `isaac_ros_visual_slam_realsense.launch.py`；报告者指出其旧设置为 `848x480@60`，官方更新配置使用更高帧率，并追问 `90fps` 是否为合理漂移所必需，但该讨论没有给出“90fps 是硬门槛”的结论。可将 `60/90fps` 作为受控 A/B 变量，不能直接视为已证实修复。
- 报告者还称 VINS-Fusion 标定提示 IR cameras 与 IMU 有时间偏差，加入时间差补偿后 VINS-Fusion 表现正常；issue 未给出 cuVSLAM 对应时间偏差参数或最终闭环结论。这是需要用 rosbag/时间戳统计独立验证的社区线索，不是 NVIDIA 已确认根因。

## 2026-08-07 — 联网调研：cuVSLAM 官方机制与 RealSense 验收

- NVIDIA 官方说明只有当 cuVSLAM 重新识别到多个历史 landmarks 时，才会向 PoseGraph 添加闭环连接并触发全图优化；因此“开启 mapping/localization”或物理回到起点都不会自动保证回环。官方同时说明多相机可显著提高 featureless 环境鲁棒性，IMU 只能在严重视觉退化时提供约 `<1s` 的短期保持，不能代替长路线视觉闭环。来源：https://nvidia-isaac-ros.github.io/concepts/visual_slam/cuvslam/index.html
- 官方列出 `/visual_slam/vis/loop_closure_cloud`、`pose_graph_edges`、`pose_graph_nodes` 等诊断 topic。下一轮短路线实验应临时离线记录这些 topic，以直接判断是否真的添加过 loop-closure edge，而不是只从首尾误差反推；实时可视化仍应关闭，避免增加 Jetson 负载。
- NVIDIA 最新 RealSense+IMU 教程的验收示例为 IR 图像约 `59.9Hz`、IMU 约 `200Hz`、visual_slam odometry 约 `59.9Hz`，且 20 帧窗口的图像/odometry 间隔约 `16-17ms`。本项目本轮 launch 日志频繁出现 `33-83ms`，并有 `116-367ms` 峰值，明显偏离该示例；不能仅凭配置写了 `60fps` 就认为实际链路稳定，必须在运动前后分别测三路 `topic hz --window 20` 和时间戳间隔/丢帧。来源：https://nvidia-isaac-ros.github.io/concepts/visual_slam/cuvslam/tutorial_realsense.html
- 同一官方教程要求依据 IMU 数据手册或标定工具获得 IMU noise model 参数，并建议 Jetson 上不要用实时 RViz评估；应离线 rosbag 记录 IR/IMU/status/odometry、loop_closure_cloud、pose_graph nodes/edges 等完整证据。本项目已关闭可视化，但仍需重新核验当前 gyro/accel noise 参数是否来自这台 D455 的有效模型，而不是未验证默认值。

- NVIDIA 论坛的 D455 Z-axis drift 帖只确认用户在 IMU active/passive 两种模式都看到 Z 漂移，官方回复仅要求核对是否使用 RealSense 示例，未提供根因或最终修复；该帖不能作为参数修改依据。其相关主题中存在 `Lost IMU msgs: 6, Frame time delta = 0.033387s, drop ratio = 100%` 的直接丢帧案例，需进一步读取。来源：https://forums.developer.nvidia.com/t/vslam-drift-issue-in-the-z-axis/283782

- 相关 NVIDIA 论坛案例在约 `33.38ms` 图像间隔下反复报告每帧丢失 `1-6` 条 IMU、drop ratio `16.7%-100%`，用户同时观察到 odometry 漂移或突然 teleport；其参数启用了 IMU fusion、ground constraints，并把 `image_jitter_threshold_ms` 放宽到 `40ms`，说明单纯调大 warning threshold 并不等于解决数据丢失。公开页面未展开后续回复，论坛 JSON 又被站点拦截，不能声称已有官方修复。来源：https://forums.developer.nvidia.com/t/lost-imu-msgs-6-frame-time-delta-0-033387-s-drop-ratio-100-000000/329984
- 针对本项目，下一轮诊断应新增“每个 stereo frame 时间区间内收到的 IMU 样本数、drop ratio、IR/IMU header stamp 差与 host arrival jitter”，并将其与 `33/50/66/83ms` frame-delta 簇关联；只统计 topic 平均 Hz 可能掩盖成簇丢帧。

- NVIDIA 论坛维护者明确说明 `/visual_slam/status.vo_state=1` 仅表示某一 stereo pair 的 visual tracking 成功，与 SLAM/loop closure 无关；要观察回环，应同时开启 localization/mapping 和 SLAM visualization，并查看 `/visual_slam/vis/loop_closure_cloud` 中“当前图像与地图特征匹配”的点云。本项目过去用 `vo_state=1` 作为 tracking 健康证据是合理的，但不能把它当成回环成功证据。来源：https://forums.developer.nvidia.com/t/how-to-tell-if-i-am-localized-and-loop-closure-has-happened-using-only-cuvslam/302769
- 为避免实时可视化负载，下一轮可仅在短路线诊断配置中发布并 rosbag 记录 `loop_closure_cloud + pose_graph_edges/nodes`，不启动 RViz；若首尾误差大且全程没有 loop_closure_cloud/新增闭环边，即可直接把问题定位到 landmark re-observation，而不是继续猜测优化器。

## 2026-08-07 — 联网调研：D455 标定博客与一手核验

- Jesse's Blog 将 VIO 标定拆为相机内参、IMU bias/scale/misalignment、camera-IMU 外参和时间偏移四类，并建议从 RealSense 出厂外参开始，轨迹异常时再用 Kalibr/Basalt 做独立时空标定。该分层思路适合本项目：先只读导出设备外参和时间戳，再决定是否进入复杂标定，不应同时改多个参数。来源：https://jiashuaixu.github.io/posts/realsense-d455-calibration-alternatives/
- 该博客关于“直接对 D455 使用 `rs-imu-calibration`”的建议不能直接采纳。Intel/librealsense 官方工具 README 明确写的是 intended to calibrate IMU built in **D435i**，并会把系数写入 EEPROM；官方页面没有在该处声明 D455 支持。下一步只能先做只读数据采集/离线分析，未经型号兼容性核验和备份不得写 D455 EEPROM。来源：https://github.com/IntelRealSense/librealsense/tree/master/tools/rs-imu-calibration
- 博客中“时间偏移 10ms 会在高速运动时造成严重错位”和“标定时充分激励各轴、覆盖全视野”的方向符合 VIO 常识，但其定量例子并非 cuVSLAM/D455 官方验收数据；只能作为设计离线 Kalibr/Basalt 对照实验的社区经验，不能直接解释本轮 `0.899m` 闭环误差。

## 2026-08-07 — 联网调研：Isaac ROS 2.1 原始排障基线

- 项目实际版本对应的 Isaac ROS `release-2.1` 文档把 `img_jitter_threshold_ms` 默认值列为 `33.33ms`；本项目自定义为 `22ms`，因此日志中的单个约 `33ms` warning 比官方默认更敏感，不能逐条等同于严重故障。但 `60Hz` 理想帧间隔仍是约 `16.7ms`，成簇的 `33/50/66/83ms` 和 `116-367ms` 峰值仍值得按实际时间戳统计。来源：https://nvidia-isaac-ros.github.io/v/release-2.1/repositories_and_packages/isaac_ros_visual_slam/isaac_ros_visual_slam/index.html
- 官方排障顺序包括：核对实际输入 image Hz 与 launch 配置；排除快速运动造成的 motion blur、低照度和错误 CameraInfo；确认左右图是 raw、未压缩/编码；RealSense emitter 必须关闭；必要时提高采集帧率，低照度噪声大时才开启 `denoise_input_images`。这支持按单变量 A/B 诊断，而不是直接调整优化器或保存门槛。
- release-2.1 文档要求 RealSense firmware `>=5.14.0`、`realsense-ros` 使用 `4.51.1` tagged release 和官方 RealSense tutorial 参数。本项目固件 `5.17.0.10` 满足最低要求，但 ROS wrapper 为 `4.54.1`，并使用自定义 launch；下一步应在同一短 rosbag/短路线下对照“官方 2.1 launch 基线 vs 当前自定义 launch”，不能仅依据“版本更新”假定 4.54.1 更适配旧 Isaac ROS 2.1。
- NVIDIA Developer Blog 的聚焦搜索未找到针对 D455/cuVSLAM 回环排障的具体参数文章；命中的 R2D2/Isaac Perceptor 宣传性文章与本次故障距离较远，因此不纳入建议依据。

## 2026-08-07 — 联网调研：大视角变化的回环边界

- PRIOR-SLAM 项目把“显著视角变化下仍能闭环”本身作为研究问题，并通过从单目图像提取场景结构、集成到 ORB-SLAM3 来改善这一问题；其示例还专门比较随视角变化增大的特征匹配。这支持一个保守工程结论：重访同一地点但观察方向、俯仰或距离差异很大时，经典外观/特征回环更难触发。来源：https://github.com/wangyizhao/PRIOR-SLAM
- PRIOR-SLAM 不是 cuVSLAM、D455 或双目 VIO 的直接参数指南，不能据此宣称调整某个 cuVSLAM 参数即可解决。本项目可落地的做法是让短回环测试的重访视角尽量复现首次经过时的方向、高度、俯仰和速度，再单独测试反向进入或大 yaw 差，测量回环边是否显著减少。

## 2026-08-07 — 联网调研：曝光资料筛选边界

- 面向 `D455 visual odometry motion blur exposure` 的通用搜索主要返回泛化的设备/点云介绍和聚合文章，没有给出可复现的曝光设置、图像质量指标或 VIO 对照结果，因此不纳入参数建议。后续只采用 RealSense 官方知识库、librealsense 一手讨论，或明确给出测试条件的工程记录。
- librealsense 的 D455 issue 搜索命中 `#14759`：报告者称 `5 FPS` 运动时出现 motion-dependent ghosting，而 `30 FPS` 消失；该 issue 截至页面所示仍为 open，尚不能作为官方定论。它只支持把“帧率/曝光变化是否改善原始 IR 清晰度”纳入 A/B，并要求用同一路线、同照明和原始图像证据验证，不能由单个社区案例推导固定参数。来源：https://github.com/realsenseai/librealsense/issues/14759
- `#14759` 的完整后续显示，报告者按建议测试 FPS、手动曝光和分辨率后仍未消除重影，并因同条件 D555 正常而怀疑该台 D455 的个体硬件问题；因此该案例不能证明提高帧率是通用修复。若本项目原始 IR 发现固定重影/拖尾，除了软件 A/B，还应加入另一台相机或静态/运动标靶对照来排除设备个体问题。
- RealSense 官方“High-speed capture mode”白皮书讨论场景/相机运动对 D400 深度性能的影响，并重点介绍 D435 的 300 FPS 模式。它能支持“运动速度、曝光与帧率要联合验证”的一般原则，但型号、数据流和目标算法均与 D455/cuVSLAM 不同，不能把其中的高速模式或参数直接迁移到本项目。来源：https://dev.realsenseai.com/docs/high-speed-capture-mode-of-intel-realsense-depth-camera-d435/

## 2026-08-07 — 联网调研：后端优化后首末距离变大的解释边界

- 项目脚本的 `0.3901m` 是在线 `/visual_slam/tracking/odometry` 序列的首末 XY 距离，`0.898979m` 是 `GetAllPoses` 返回的优化轨迹首末 XY 距离；二者不是对同一目标函数的“优化前后 cost”。脚本只是各自取 `poses[0]` 与 `poses[-1]` 求欧氏距离，不能据此断言优化器内部总残差上升。位置：`scripts/cuvslam_loop_metrics_recorder.py` 的 `summarize_pose_track` 与 `summarize_pose_stamped_list`。
- 鲁棒位姿图优化项目 Kimera-RPGO 专门提供 odometry check、loop consistency check 和 outlier rejection，相关论文也以回环离群值拒绝为目标；这说明错误/不一致回环能破坏普通位姿图优化，是现实风险。但这只构成诊断假设，不能证明本轮 cuVSLAM 已加入错误回环。必须用 `loop_closure_cloud` 与 pose-graph edges 的时间序列区分“完全没回环”“正确回环但首末指标不等价”和“错误回环拉坏全图”。来源：https://github.com/MIT-SPARK/Kimera-RPGO
- GTSAM 官方 Pose2 SLAM 教程把问题建模为先验因子、连续 odometry between-factors 和 loop-closure between-factor，并为因子配置噪声模型；优化求的是给定全部约束后最可能的整组 poses，而不是最小化“第一帧与最后一帧的 XY 欧氏距离”。因此后端总图误差可以下降，同时项目自定义的首末距离变大，两者数学上不矛盾。来源：https://borglab.github.io/gtsam/pose2slamexample/
- cuVSLAM 官方说明 SLAM 与 VO 在独立线程并行；只有识别多个旧 landmarks 后才添加 PoseGraph 连接，随后才优化当前及历史 poses。由此，在线 odometry 与事后 `GetAllPoses` 本就不是同一估计流。若没有记录回环事件和图边，仅凭两条轨迹的首末距离不能判断“优化器成功/失败”。来源：https://nvidia-isaac-ros.github.io/concepts/visual_slam/cuvslam/index.html
## 2026-08-07 — D455/cuVSLAM 60fps 丢样根因已定位到组合负载

- D455 硬件、USB 3.2 和 Motion Module 不能解释当前主要丢样：librealsense 直连 10 秒得到 accel `202.66Hz`、gyro `199.67Hz`，唯一帧号缺口均为 0，且无硬件通知。
- RealSense ROS v4.54.1/librealsense 2.54.1 单独运行时，左右 IR 为 `59.81Hz`、严格同 timestamp，合流 `/camera/imu` 为 `199.66Hz`。因此 wrapper 单独运行也不是瓶颈。
- 只有加入 cuVSLAM 11.4 后，`640x360@60` 的 `/camera/imu` 多次降到约 `178-196Hz`；即使关闭三项 visualization、移除 recorder、终止 ROS daemon，最终干净窗口仍只有 `186.77Hz`、最大间隔 `54.98ms`。这证明 60fps 组合存在处理/调度余量不足，而非单一诊断进程造成。
- 同一硬件与算法参数只把双目改为 `640x360@30` 并把 jitter warning 阈值对应调到 `40ms` 后，IR/odometry 均约 `29.99Hz`、IMU `199.66Hz`，没有 `>2.5x` 大间隔，每个图像区间都有 6-7 个 IMU 样本。30fps 是下一轮运动 A/B 的首选候选，但静止结果不能替代 tracking 与闭环验收。
- 当前 60fps 完整路线的回环失败不能全部归因于 landmark 可观测性；输入时序余量不足已成为独立、可复现的前端风险。下一轮不应继续原样重复 60fps 完整路线。
- 启动脚本的逐 topic `ros2 topic list` 会卡死并额外占用一个以上核心；在线 recorder 订阅滚动 1024-pose Path 也会占用近一个核心。二者已从默认诊断路径移除/降载，但移除后 60fps IMU仍异常，因此它们是放大因素而非根因。
- 在线 recorder 的初始化零 pose 会污染从进程启动开始计算的首末差；稳定窗口表明静止位置可保持到亚毫米级。正式结论应从 tracking ready 后的窗口或完整 `GetAllPoses` 计算，不能直接使用含初始化重锚的首末差。
- wrapper 日志的 `IMU Calibration is not available` 与 `HID timestamp not found, switching to Host timestamps` 是待核验风险；因 wrapper-only 仍约 200Hz，现有证据不能把它们定为 60fps 丢样根因。

## 2026-08-07 — 启动 rate probes 默认关闭

- `ros2 topic hz` 启动探针会依次运行多个最长 12 秒的 ROS CLI 订阅，并可能留下 ROS daemon；在 Xavier NX 的 60fps 组合已证明调度余量不足后，不应把这类测量负载放在默认运行路径。
- `STARTUP_RATE_PROBES=false` 只改变诊断默认值，不删除能力；需要定点测量时可显式开启。30fps 运动验收应优先使用专用输入时序探针和受控记录窗口，避免启动阶段测量反过来扰动被测系统。
- 该默认值已在本机与 Jetson 的静态/单元测试中验证，远端脚本通过原生 `bash -n`，同步文件哈希一致。

## 2026-08-07 — 30fps 开启 SLAM 图诊断的静止 A/B

- 用 `640x360@30`、IMU 融合、平面模式、`img_jitter_threshold_ms=40.0` 启动成功，D455 为 USB 3.2、IR 双路 30Hz、IMU 200Hz，cuVSLAM 11.4 节点正常加载。
- 为获得 `loop_closure_cloud`、`pose_graph_nodes/edges`，临时开启 `ENABLE_SLAM_VISUALIZATION=true`，关闭 landmarks/observations、RViz、在线 recorder 和 rate probes。
- 首个 20 秒输入探针：IR/odom `29.84Hz`，各一次 `133.3ms` 间隔；IMU `195.93Hz`，最大 `44.78ms`、23 个 `>2.5x` 缺口。
- 稳定复测：IR/odom 仍各一次 `133.35ms` 间隔；IMU `199.41Hz`，最大 `53.49ms`、3 个 `>2.5x` 缺口；双目有一次 `33.34ms` 同步偏差。说明图诊断发布增加了不可接受的调度风险，不能带此配置进入运动。
- 诊断 topic 均出现在 topic list，但“存在”不等于应在实时路径中开启；下一 A/B 关闭全部 visualization，以已通过的低负载 30fps 配置优先保证输入连续性。

## 2026-08-07 — 30fps 低负载输入时序的重复窗口

- 在相同硬件、参数和无 visualization/recorder 条件下，20 秒窗口结果从“仅一次 `12.55ms` IMU 小缺口”到连续出现 `133.35ms`、`166.70ms` 图像/odom 间隔，IMU 最大间隔达到 `69.57ms`、`88.68ms`。
- 每个已收到的图像区间仍至少有 3-6 个 IMU 样本，说明不是完全断流；但偶发成簇丢帧具有可重复性，不能把一次通过窗口外推为当前稳定基线。
- 当前证据更支持先解决 Xavier NX 频率/调度余量或改测更低采集负载；在未重新获得连续稳定窗口前，不应启动机器狗运动或完整路线。

## 2026-08-07 — nvpmodel 性能档位边界

- 当前 `MODE_20W_6CORE` 并不是 1.9GHz CPU 档：配置文件明确将三个 Denver cluster 的 CPU Max 固定为 `1.4208GHz`，即便 `jetson_clocks` 锁频也只能锁在该上限。
- 同一 `/etc/nvpmodel.conf` 中，`MODE_20W_2CORE`（ID 6）提供两核 `1.9072GHz`、GPU `1.10925GHz`、EMC `1.866GHz`；`MODE_20W_4CORE`/`6CORE` CPU Max 都是 `1.4208GHz`。2-core 可能提高单核调度余量，但会降低并行度，必须单独 A/B，不能直接视为更优。

## 2026-08-07 — 官方性能资料与启动脚本

- NVIDIA 官方 Xavier NX 产品页确认 Xavier NX 系列最高约 `21 TOPS` AI 算力：<https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-xavier-nx/>。
- NVIDIA 官方 Jetson Modules 页面同样说明 Xavier NX 系列最高约 `21 TOPS`：<https://developer.nvidia.com/embedded/jetson-modules>。
- NVIDIA Jetson Linux R35.4.1 官方 Clocks 文档可访问，说明时钟/电源管理由 Jetson Linux 工具控制：<https://docs.nvidia.com/jetson/archives/r35.4.1/DeveloperGuide/text/SD/Clocks.html>。
- 本板实际 `/etc/nvpmodel.conf` 是最终约束：ID 8 `MODE_20W_6CORE` 为六核 `1.4208GHz`，ID 6 `MODE_20W_2CORE` 为两核 `1.9072GHz`，GPU/EMC 在两种 20W 档均为 `1.10925GHz/1.866GHz`。因此不存在“六核同时 1.9072GHz”的已配置档位。
- 桌面脚本默认选择六核吞吐，CPU 峰值档必须显式 `--cpu-peak`；相机/ROS FPS 仍由 launch 配置决定，不能把 60fps 当成板级性能开关。

## 2026-08-07 — 六核 30fps 静止窗口再次确认成簇缺帧

- 新会话 `cuvslam_gui_20260807-223609` 在 GPU warm-up 完成后，仅运行只读 `cuvslam_input_timing_probe.py` 20 秒；未启动 Nav2 或任何运动出口。
- IR1/IR2/odometry 观测约 `29.78-29.80Hz`，各出现一次 `166.66ms` 间隔；IMU 约 `199.31Hz`，最大 `104.99ms`，3 次超过 `2.5x`，估计缺失 `42` 个样本，且有 `8` 个图像区间没有 IMU。双目同步绝大多数为 `0ms`，但最大偏差 `33.44ms`。
- 该窗口与此前 30fps 低负载窗口的 `133-166ms` 图像缺口、`69-88ms` IMU 峰值一致，说明六核 `MODE_20W_6CORE` 的当前组合仍存在可复现调度/处理余量问题。不能仅凭平均 Hz 通过输入门禁，也不能进入低速短环。
- 清理后 `nvpmodel -q` 确认为 `MODE_20W_6CORE`（ID `8`）；先前记录的 2-core 状态是更早时点，非本轮诊断配置。

## 2026-08-08 — SLAM 技术路线换型评审边界

- 当前证据不能归因于 D455 硬件或 USB：librealsense 直连及 RealSense ROS wrapper 单独运行时，双目与 IMU 输入均基本达到目标频率；成簇缺帧只在叠加 cuVSLAM 后稳定复现。因此故障对象首先是当前 Xavier NX 上的“驱动 + ROS 2/DDS + cuVSLAM + 容器/诊断”组合负载和调度链路，而不是已经证明的相机本体故障。
- 直接把同一 ROS 输入接给 ORB-SLAM3 或 VINS-Fusion，不能自动修复时间戳断流；任何候选方案必须先通过与现探针等价的静止输入门禁，再进入运动 tracking/闭环测试。
- 仓库已有 `tech_stack_analysis.md` 推荐原生 Foxy 的 RTAB-Map 预建图定位，但其中 CPU 占用、ARM64 包可用性、424x240@15 配置和小场地重定位可靠性仍是估算，尚不能直接作为换型结论。
- 技术路线应拆为两层决定：先决定是否冻结当前 cuVSLAM 主线；再用短时无运动/手持运动 A/B 选 RTAB-Map RGB-D、ORB-SLAM3 stereo-inertial 或降载 cuVSLAM。评估指标必须统一为输入完整性、跟踪失效、CPU/GPU/内存余量、闭环误差和 Nav2 接口成本。
- 2026-08-08 查询 RTAB-Map 官方 ROS 2 仓库时，当前 `ros2` 分支 README 明确标注 `ROS2 Humble minimum required`；ROS Index 当前维护条目也从 Humble 开始，显示 Humble 版本 `0.23.7`、`humble-devel` 分支。仓库原方案中“Host Foxy 直接安装当前 RTAB-Map”不是当前官方支持路径，必须另行验证旧 Foxy 版本，或把升级主机 ROS 作为迁移成本。来源：https://github.com/introlab/rtabmap_ros 与 https://index.ros.org/p/rtabmap_ros/
- 同一官方 README 确认提供 stereo/RGB-D 传感器示例及 Nav2 集成示例，并在 GUI/topic 频率看似卡顿时建议排查 DDS、可尝试 Cyclone DDS。这支持 RTAB-Map 的接口可行性，也再次表明 DDS/调度必须纳入 A/B，而不能只比较 SLAM 算法名称。
- ROS Index 的历史发行视图确认 RTAB-Map ROS 2 存在 `foxy-devel` 0.21.1，最后更新于 2023-04-09。它使“锁定旧版在 Host Foxy 试跑”具备可行入口，但该版本已停止跟随当前主线，必须先验证 Jetson ARM64 二进制/源码构建、D455 同步和 Nav2 接口，不能按当前 Humble 文档直接套参数。来源：https://index.ros.org/p/rtabmap_ros/#foxy
- ORB-SLAM3 官方仓库支持 monocular/stereo/RGB-D 的 visual-inertial 和 multi-map SLAM，并提供 D435i standalone 示例；但官方 ROS 示例只声明测试于 ROS Melodic/Ubuntu 18.04，仓库主版本仍标为 2021-12，且 README 建议强力 i7 以保证实时稳定。对 Xavier NX + ROS 2 Foxy，它需要自行完成 ROS 2 封装、D455 时空标定和算力验收，不是低风险替代。来源：https://github.com/UZ-SLAMLab/ORB_SLAM3
- 当前主 worktree 的 `scripts/start_cuvslam_rviz_gui.sh` 仍无条件开启 SLAM visualization 并串行执行多次 `ros2 topic hz`，且不存在 PWF 所述的 `scripts/cuvslam_input_timing_probe.py`；近期 PWF 明确记录相关修复发生在 `quadruped-robot-competition-nav2-dwb` worktree 并部署到 Jetson。正式 A/B 前必须固化实际 Jetson 文件哈希/参数并把所需诊断代码合并到同一受控基线。
- 仓库 README 记录 Lite3 已发布 `/imu/data`、`/leg_odom`、`/leg_odom2`，现有 EKF 配置也预留了机器人本体里程计与机身 IMU 融合。新方案可采用“腿部里程计 + 机身 IMU 保短时连续，视觉地图定位提供全局纠偏”的分工，降低单次 D455 IMU 断流直接击穿导航的风险；但 Lite3 里程计的 frame、单位、协方差与真实漂移尚需单独标定。

## 2026-08-08 — 探针统计口径与换型决策

- `cuvslam_input_timing_probe.py` 的 stream 门禁按消息 `header.stamp` 计算源时间间隔；ROS callback 的 `time.monotonic()` 到达间隔仅落盘，不参与 `clustered_gaps` 判定。因此 166.6ms/105.0ms 是上游消息时间轴在 ROS 侧的可观测断档，不能单独区分相机驱动丢帧、DDS/订阅队列丢帧或 cuVSLAM 发布暂停。
- 双目同步指标对 `CameraInfo.header.stamp` 做跨序列最近邻匹配，未使用硬件 frame number、曝光时间或一对一匹配；最大 33.4ms 应表述为“ROS 双目时间戳配对风险”，不能直接宣称左右传感器物理曝光相差一帧。librealsense 直连帧号零缺口和 wrapper-only 严格同步使硬件异步尚未成立。
- 因此当前最强结论是“cuVSLAM 组合负载下的输入/调度链路不满足运动门禁”，而不是“D455 硬件坏了”或“所有 SLAM 算法都会失败”。
- 决策建议：冻结 cuVSLAM 作为比赛主线，不再用它进行完整路线；保留 30fps/低负载配置做基准对照。新主线优先验证 RTAB-Map ROS 2 `foxy-devel` 0.21.1 的 RGB-D localization + Lite3 `/leg_odom`/`/imu/data` EKF，先不依赖 D455 IMU；ORB-SLAM3/VINS-Fusion 暂不作为主线。

## 2026-08-08 — D455 `640x360@20` 官方规格核验

- RealSense 2026 年 3 月版 D400 Series Datasheet 的 Table 4-3 明确适用于 `D450/D455/D455f/D456`。
- D455 的 `Y8 [8 bits]` 左右红外图像在 `640 x 360` 分辨率下只支持 `5, 15, 30, 60, 90 FPS`；`Z16` 深度流在同分辨率下也是同一组帧率。官方表中没有 `20 FPS`。
- RealSense ROS 官方 issue #2327 显示，驱动收到不支持的流配置时会告警 `Given stream configuration is not supported by the device`；该旧版 wrapper 然后回退到默认 profile。当前项目版本不应假定回退细节相同，但 `640x360x20` 仍属于硬件不支持的 profile。
- 若目标是降低 D455 采集、USB、ROS 及 SLAM 链路的真实负载，下一个原生候选应是 `15 FPS`，而不是 `20 FPS`。从 30 FPS 软件丢帧成 20 FPS 不会降低相机/驱动端负载，且容易产生非均匀帧间隔，不宜直接作为立体 VIO/cuVSLAM 输入。
- 官方数据手册：https://www.realsenseai.com/wp-content/uploads/2026/03/RealSense-D400-Series-Datasheet-Mar-2026.pdf
- RealSense ROS 官方 issue：https://github.com/realsenseai/realsense-ros/issues/2327

## 2026-08-08 — D455 直连帧号缺口复核（进行中）

- 用户报告：在 `pyrealsense2` 直连路径观测到精确丢失 22 个 Frame Number。该观察排除 ROS 2、DDS 与 cuVSLAM 的下游影响，但仍覆盖 librealsense、内核 UVC/xHCI、USB 链路、系统调度与 SDK 消费队列。
- 与本仓库稍早“10 秒直连 IMU 零帧号缺口”的记录冲突；本轮不沿用任一结论，先以可保存的原始计数器、设备时间戳、主机单调时钟与内核日志重建基线。
- `power/control=on` 是低风险 runtime-PM A/B 候选；autosuspend、USB 3 U1/U2 LPM 与周期性 USB 拓扑扫描不是同一机制，不能在测试前假定 30.5 秒周期的根因。
- Jetson 只读基线：D455 位于 `/sys/bus/usb/devices/2-3.4`，以 USB 3 5Gbps 经一层 Hub 接入 `tegra-xusb`；同一 USB2 树是独立的 `icspring camera`，不是 D455 的上游路径。
- D455 当前 `power/control=auto`、`autosuspend_delay_ms=2000`、`runtime_status=active`，启动以来 `runtime_suspended_time` 约 `10.4s`；父 Hub 为 `auto/0ms/active`、约 `10.1s` suspend。D455 的硬件 LPM 为 U1 enabled/U2 disabled，Hub 为 U1/U2 enabled。当前日志只含启动枚举，无 USB reset、disconnect、UVC 或 xHCI error。
- 现有直连探针使用 librealsense 回调，记录 accel/gyro Frame Number、设备/主机时间戳与通知，消费路径足够轻；但通知的 `serialized_data` 未转为字符串，100 秒采集遇到通知后在最终 JSON 序列化失败。已修复全部通知字段的显式类型转换。
- 修复后 5 秒验证：accel `202.91Hz`、gyro `199.68Hz`，两路 Frame Number 缺口、估计缺样、非单调时间戳和设备通知均为 0。
- 100 秒纯 IMU `auto` 基线：accel `20192`、gyro `19866` 个样本，两路硬件 Frame Number 缺口均为 0，设备时间戳最大间隔约 `4.95/5.02ms`，无通知。采集前设备空闲时确实为 runtime `suspended`，但推流期间没有周期性断流证据。
- 初版双 IR+IMU 5 秒探针在启动阶段观测到双目共同 `4→11`（各缺 6 帧），设备时间戳跳 `281ms`，主机到达间隔仅 `8.8ms`，IMU 无硬件缺口；这是 Pipeline 启动瞬态，不能用于判定 30.5 秒运行期断流。
- 新增 3 秒 warm-up 并仅统计稳定窗口后，10 秒 `640x360@30` 双 IR+200Hz IMU：四路 Frame Number 缺口均为 0，左右各 301 帧且时间戳严格同步，每个 IR 区间均有 6–7 个 accel/gyro 样本。
- 100 秒 `640x360@30` 双 IR+200Hz IMU `auto` 基线仍全部连续：IR1/IR2 各 3000 帧、accel 20279、gyro 19970，四路硬件 Frame Number 缺口均为 0，2999 个图像区间均含 IMU。
- 10 秒 `640x360@60` 双 IR+200Hz IMU预检同样四路零缺口，左右各 600 帧且严格同步；将继续运行 100 秒窗口覆盖三个 30.5 秒周期。
- 100 秒 `640x360@60` 高负载直连：IR1/IR2 各 5988、accel 20277、gyro 19974，四路 Frame Number 缺口、估计缺样、非单调时间戳和设备通知全部为 0。
- 70 秒 `640x360@60` + runtime-PM 监测：140 次采样全部为 `active`，`runtime_suspended_time` 始终为 `790983`，`runtime_active_time` 增加约 `70040ms`；同时四路 Frame Number 仍零缺口。当前条件下推流期间 autosuspend 没有发生。
- 内核在多次 Pipeline 启停附近记录 `uvcvideo: Failed to query (GET_CUR) UVC control 1 on unit 3: -32 (exp. 1024)`；告警成批贴近初始化时点，不按 30.5 秒周期出现，且对应稳定窗口数据连续。现阶段只能视为 UVC 扩展控制查询兼容性告警，不能作为 payload 丢帧证据。
- 结论：当前可复现证据排除“`control=auto` 在持续推流中每 30.5 秒挂起”这一机制；不支持继续做 powered Hub、线缆或固件回退。用户先前的 22 帧观察需要原始命令、完整输出和流配置才能与本轮基线做条件差分。

## 2026-08-08 — ROS 上游硬件 Frame Counter 探针口径

- RealSense ROS `realsense2_camera_msgs/msg/Metadata` 只有 `header` 与 `json_data`；必须结构化解析 JSON，不能从 `Image` 消息推导硬件 Frame Counter。
- 当前 D455/Wrapper 4.54.1 的 IR1/IR2 metadata 包含真实 `frame_counter`、`frame_number`、`hw_timestamp`、`sensor_timestamp` 等字段；accel/gyro metadata 仅有 `frame_number`、`frame_timestamp`、`backend_timestamp`、`time_of_arrival` 和 `clock_domain`。因此左右 IR 可做硬件计数门禁，融合 `/camera/imu` 只能用 header 时间连续性和每图像区间样本数判断成簇缺样。
- Python rclpy 同时反序列化双路 `640x360@30` Image、200Hz IMU 和 4 路 metadata 会在 Xavier NX 上成为测量瓶颈，产生自身队列丢样；即使 4 线程仍无法覆盖完整窗口。该结果不能用于给 Wrapper 定责。
- 原生 C++ rclcpp 探针在同配置 10 秒对照中达到 IR 各 300 帧、IMU `199.65Hz`，左右硬件计数零跳号且每个图像区间都有 IMU，证明该实现具备进入 120 秒分层 A/B 的最低观测能力。

## 2026-08-08 — ROS 到 cuVSLAM 第一处丢帧点与静止门禁结论

- Wrapper-only 与 Wrapper + cuVSLAM 低负载各自连续 `120 秒 x 3` 均通过，说明在关闭 visualization、recorder、RViz 和 ROS CLI topic/rate 探针后，当前 30 FPS 生产输入链具有静止连续运行能力。
- 1 秒重型系统快照能稳定增加调度压力：三轮中第三轮首先在 ROS metadata hardware counter 观测到左右 IR 各缺 5 帧，同时 cuVSLAM 报相同的 `266.497315ms` frame delta，odometry 也出现同窗断档。因此第一处可观测丢帧不在 cuVSLAM 内部 odometry 计算线程之后。
- 故障窗 CPU 六核接近饱和而 GPU 仅 `1%`，xHCI IRQ 计数连续，UDP `RcvbufErrors` 同窗上升。证据优先支持“CPU 调度尖峰导致 Wrapper/发布链暂停，并使 Fast DDS 接收队列承压”，不支持 USB/xHCI 中断停滞，也不支持 cuVSLAM 内部计算线程单独阻塞。
- UDP drops 不是充分条件：Round 2 在 drops 增长时仍通过。后续若再次自然复现，必须同时对齐 hardware counter、CPU 线程、DDS socket/`RcvbufErrors` 与 cuVSLAM warning，不能只凭单个 UDP 累计计数定责。
- 只把重型系统快照请求间隔从 `1s` 调为 `5s` 后，同一配置连续 `120 秒 x 3` 全部通过，IMU 最大间隔为 `8.52/8.15/8.98ms`。该修复证明高频诊断本身是当前 CPU 余量下的充分触发因素；它不等于已经完成手持运动或机器狗低速短环验收。
- 当前不应更换 Hub、线缆、固件或 SLAM 路线。下一阶段仅在用户现场确认站稳、路线净空和急停后，依次进行手持运动与机器狗低速短环；若自然断档再次出现，再按 DDS/队列或 CPU 调度单变量 A/B 继续。

## 2026-08-08 — 最终遥控建图验收设计

- 短闭环、半程和完整路线必须使用三个独立冷启动会话。若在同一 pose graph 上逐级扩大，前一级轨迹会污染后一级判定，同时会迫使同一会话多次调用重型 `GetAllPoses`，无法满足“一会话一次后验查询”的低负载边界。
- 关闭在线 recorder 后，单次 `GetAllPoses` 只能量化后端优化 pose graph，不能直接给出 tracking odometry 的首末累计漂移。运动前后各抓取一条 odometry 是区分“前端自身稳定”和“后端把误差拉回”的最低开销观测方式。
- tracking drift 是诊断量，不应单独替代保存门槛：保存仍只由物理回到起点、后端 `xy_closure_error_m <0.20m`、无 tracking lost/原生时间断档共同决定。当 tracking drift 大而后端误差明显更小时，才有后端全局纠偏的直接证据。
- cuVSLAM launcher 每次把独立时间戳日志目录挂载到容器 `/logs`。地图保存后完全重启时，旧地图不会自动出现在新容器；runbook 必须记录旧 `HOST_LOG_DIR`，把地图复制到新容器，再调用 `load_map_and_localize`。
- 2026-08-08 只读预检确认 Jetson 当前是干净起点：D455 已枚举、Docker 和相关进程为空、六核 CPU 与 GPU 均锁频。远端 Git HEAD 落后于本机 DWB worktree，但生产启动脚本、单次 pose graph 工具和时序工具的 SHA-256 完全一致；真机验收应以部署文件哈希和 `runtime_config.env` 为证据，不只看 HEAD。

## 2026-08-08 — 最终配置无运动 smoke 结论

- 两条 tracking odometry 在 `22.005s` 内只有 `3.50e-6m` XY 漂移和 `0.000101deg` yaw 漂移，证明轻量快照工具、`odom -> base_link` 契约和静止 tracking 局部稳定性正常；该结果不能覆盖输入时序门禁。
- 在 recorder、startup topic/rate checks、RViz、ROS daemon 和重型探针全部关闭时，cuVSLAM 原生日志仍在 GPU warm-up 后约每 `30.5s` 报一次 `66.64-167.08ms` frame delta。周期从第一次快照之前已经存在，排除两次单样本订阅为起因。
- 当前结果与先前低负载 `120秒 x 3` 全通过存在条件差异或非确定性冲突，但已经足以阻止立即移动机器狗。下一步必须先对本次最终启动命令与 Phase 35 通过命令做逐参数/环境/进程差分，并以单变量静止 A/B 解释 30.5 秒周期；不能直接进入短闭环。
- 启动时 RealSense 报一次 `Motion Module failure` hardware notification，但 wrapper 后续正常发布且 tracking 可用。它与周期性 frame delta 是否同源尚未证明，不能单独定责。

## 2026-08-08 — `30.5s` 周期断档复现强度

- 第二轮在不复制/运行 tracking 快照工具、不执行 ROS 订阅和系统探针的条件下，仍连续复现约 `30.44-30.51s` 周期的 `66.66-166.69ms` frame delta，已排除上一轮两次单样本订阅为触发因素。
- 第二轮没有 D455 `Motion Module failure`，周期断档仍存在；该启动 hardware notification 不是故障必要条件。
- 两轮独立冷启动都在最终低负载配置下复现，周期相位各自从新会话开始形成。当前应把问题视为可重复的定时任务/资源竞争或链路周期行为，而不是单次随机丢帧；但尚未定位具体责任层。
- 真实运动门禁保持失败。下一步应先把本次最终启动环境与 Phase 35 `120秒 x 3` 通过环境做机器可读差分，再选择一个变量做静止 A/B，不能直接继续遥控短闭环。

## 2026-08-08 — `gnome-control-center` 单变量 A/B 与根因边界

- Jetson 上用户进程 `gnome-control-center`（PID `3973`）每约 `30.5s` 请求激活 `org.freedesktop.timedate1`；无探针复现轮的六次主 frame warning 均在对应请求后约 `3.66-3.75s` 出现，形成固定相位。
- 单变量只向 PID `3973` 发送 `SIGTERM`；`iio-sensor-proxy` 保持运行，`systemd-timedated` 按正常空闲生命周期退出，其他 cuVSLAM 参数与复现轮完全一致。
- tracker 启动瞬态结束后的 `130s` 稳定窗口内，`launch.log` 行数保持不变，没有 frame delta 或 tracking lost；确认 GNOME 设置窗口是当前环境约 `30.5s` 周期断档的触发源。
- 稳定窗口结束后执行一次全量 `journalctl` 扫描，约 4 秒后出现 `167.64ms` frame delta；该事件早于 Docker SIGTERM 约 6 秒，不能归为 shutdown 瞬态。这说明重型系统读取同样能触发断档，底层仍是 Xavier NX 余量有限时的调度/资源竞争，而不是 `systemd-timedated` 单独故障。
- 该 A/B 解决的是周期性静止输入异常的运行门禁，不证明已经解释历史遥控建图的全部漂移或回环误差；后者仍需在新门禁下执行短闭环、半程和完整路线分级验收。
- `docs/cuvslam_mapping_runbook_zh.md` 已固化两项约束：启动前确认 `GNOME_CONTROL_CENTER_OFF`，cuVSLAM 运行期间禁止全量 `journalctl`、`systemctl status` 或桌面设置查询。

## 2026-08-08 — GNOME 设置 A/B 因果边界

- 单变量关闭 `gnome-control-center` 后，相同 cuVSLAM 配置的 130 秒稳定窗口新增原生日志为零；此前两轮在相同长度内均稳定出现约 `30.5s` 周期 frame delta。该 A/B 足以确认 GNOME 设置是当前系统中的周期触发源。
- `iio-sensor-proxy` 在通过轮继续运行，因此当前没有理由进入“停止 iio-sensor-proxy”分支。`systemd-timedated` 未被手工干预，但 GNOME 关闭后没有再被周期激活。
- 窗口结束后的全量 `journalctl` 查询约 4 秒后触发一次 `167.64ms` gap，且发生在 Docker stop 之前。这说明更底层的必要条件可能是系统查询引起的 CPU/IO/调度瞬态，GNOME/timedated 是周期触发链之一；“RealSense 全局时间同步被 timedated 改变”尚未得到直接证据。
- 操作规则应升级为：cuVSLAM 验收前关闭 Ubuntu“设置”，运行期禁用 journalctl/systemctl/桌面查询和重型探针；不要禁用 timedated 或 iio-sensor-proxy。只有 cuVSLAM 会话停止后才读取系统日志。
- 解决该周期输入异常不等于解决历史运动回环漂移。下一阶段仍必须通过独立冷启动的遥控短闭环判断后端能否把 tracking odometry 漂移拉回；历史 `0.899m/9.245m` 误差不能仅归因 GNOME。

## 2026-08-09 — 最终短闭环对后端纠偏能力的判定

- 在已消除 GNOME `30.5s` 周期触发、无 recorder/ROS daemon/topic 探针/系统探针的最终低负载配置下，短闭环运动窗口没有 tracking lost 或原生图像时间断档。这把本轮失败从周期输入异常中分离出来。
- 物理回到起点后，tracking odometry 的平面累计误差为 `0.134938m`、yaw 为 `13.486deg`；`dz=0.239906m` 来自用户主动让机器人起立，不能误判为视觉高度漂移。
- 唯一一次 `GetAllPoses` 返回的后端 `xy_closure_error_m=0.257547m`，路径长 `6.992375m`、优化位姿 `11283`。后端误差超过 `<0.20m` 门槛且大于 tracking XY 误差，当前短路线没有证据表明 pose graph 把前端误差拉回，反而给出更差的起终点一致性。
- 该结果不足以直接套用“完整路线仍为 `0.5-0.9m` 即放弃 cuVSLAM”的终局条件，因为本轮是短闭环且误差为 `0.258m`；但按既定分级协议已足以停止本次验收，不得进入半程或保存地图。后续若继续 cuVSLAM，必须先重新设计能够解释 yaw/物理回位精度和后端退化的单变量实验，不能原样重跑或扩大路线。
- `GetAllPoses` 日志行之后约 `3.42s` 出现一次 `133.29ms` frame delta；它不属于运动窗口，却与此前 `journalctl` 后触发断档的现象一致，说明后验全图查询本身也会消耗当前 Xavier NX 的有限调度余量。

## 2026-08-09 — 短闭环确认性重复的解释边界

- 在上一轮同配置失败后，再做一次完全相同的短闭环可用于判断结果是否稳定复现，但不能单凭第二轮通过就宣称 cuVSLAM 已可靠通过。
- 本轮只复测 `short`，不进入半程、不保存地图；门槛和证据采集方式保持不变，避免因放宽阈值或增加在线探针改变实验条件。

## 2026-08-09 — 第二次短闭环确认后端误差可重复

- 第二轮 tracking 前端只漂移 `0.031289m/1.398deg`，运动窗口无 tracking lost 或 frame delta；因此 `0.358549m` 后端闭环误差不能由明显的前端终点漂移或输入断档解释。
- 两轮后端结果分别为 `0.257547m / 6.992375m = 3.6833%` 与 `0.358549m / 9.908336m = 3.6187%`。第二轮路线比第一轮长，绝对误差增大，但归一化误差只差约 `0.0646` 个百分点，呈现近似线性且可重复的后端 pose graph 起终点不一致。
- 两轮中后端误差都比 tracking XY 漂移更大，第二轮达到约 `11.46x`。现有证据不支持继续把同一 cuVSLAM 配置扩大到半程或完整路线；下一步应转向解释错误回环/坐标约束，或切换全局定位方案，而不是原样第三次绕圈。
- 两轮唯一一次 `GetAllPoses` 后都在数秒内触发 frame delta，说明该服务本身是可重复的重负载触发源；它适合作为停稳后的单次后验工具，不应在线持续调用。

## 2026-08-09 — 第二次短闭环同窗校正

- 用户按 tracking 起止时间戳筛选 GetAllPoses pose 后，同窗后端指标为 `xy_closure_error_m=0.356863m`、`yaw_drift_deg=0.459deg`、`xy_path_length_m=9.900975m`、XY 误差率 `3.604%`。此前 `0.358549m/9.908336m` 是整份 pose graph 首末点统计，数值接近但口径不严格，后续分析以同窗指标为准。
- 第二轮无 Z 方向姿态变化，因此可以排除“起立导致 tracking/pose graph 起终点不可比”。后端改善了 yaw，却将 XY 从 tracking 的 `0.031289m` 恶化为 `0.356863m`。
- 两次查询后的 frame delta 均发生在 GetAllPoses 返回之后，不能倒因果解释运动窗口中的后端 XY 误差；本轮运动窗口也没有复现 `30.5s` 周期断档。
- 最可能的可检验分支是“没有建立有效回环边”与“建立了错误或过弱的回环边”。在离线确认边类型之前，不做第三次短环、不进入半程或完整路线。
- GetAllPoses CSV 的原始时间约为 tracking UNIX 秒的 `1/1000`；当前工具必须显式应用 `×1000` 并报告 scale，否则无法稳定筛选同一运动窗口。

## 2026-08-09 — GetAllPoses 同窗分析工具契约

- 当前 cuVSLAM/Isaac ROS 组合的 GetAllPoses pose stamp 不是可直接与 tracking header 比较的 UNIX 秒；已验证 `normalized = raw × 1000`。工具同时保留 normalized/raw 两列并在 JSON/TXT 记录 scale，避免静默单位转换。
- 同窗选择采用 tracking `[start_header_stamp_sec, end_header_stamp_sec]` inclusive 边界；第二轮选中 `5126/11677` poses，首个同窗 pose 晚于起点约 `0.033s`，最后一个与终点在浮点精度内对齐。
- 判定对象必须是 `tracking_window` summary；`all_poses` summary 包含 tracker 创建前和终点快照后的 pose，只适合作全图审计。两者本轮数值接近是偶然事实，不能作为混用口径的理由。
- timestamp scale 是当前 cuVSLAM 版本的接口事实，不应假设跨版本永久成立。更换 Isaac ROS/cuVSLAM 版本后必须用已知 tracking 时间重新校验 scale，不能自动沿用 `1000`。

## 2026-08-09 — Phase 38 回环边接口初步证据

- Jetson Isaac ROS Visual SLAM 源码把 `/visual_slam/vis/loop_closure_cloud` 声明为 `PointCloud2`，`pose_graph_nodes` 声明为 `PoseArray`，`pose_graph_edges` 与 `pose_graph_edges2` 均声明为 `visualization_msgs/Marker` publisher。
- `isaac_ros_visual_slam_interfaces/srv/GetAllPoses.srv` 的注释明确其用途是查询全局优化后的 poses；它与 pose graph edge 可视化 publisher 是独立接口。必须读取完整响应字段后再正式判定能否携带边。
- 完整 `GetAllPoses.srv` 已核对：请求只有 `int32 max_count`；响应只有 `bool success` 与 `geometry_msgs/PoseStamped[] poses`。该服务不返回 edge、节点 ID、协方差或回环类型，无法凭服务响应恢复 pose graph 边集合。
- 当前源码搜索只发现 RViz 配置、publisher、可视化 helper 和 `GetAllPoses` 接口；尚未发现可直接作为“回环已发生”计数的 ROS status/metrics 字段。
- `VisualSlamStatus.msg` 只有 `vo_state`、node/track 当前、均值和最大执行时间，不含 loop closure 或 PGO 字段。
- 原生 `cuvslam.h` 的 `CUVSLAM_SlamMetrics` 包含时间戳、瞬时 `lc_status`、`pgo_status` 以及 selected/tracked/PNP/good landmarks 四个计数；它没有累计回环次数。只有在事件期间采样并保存，才可能用它确认某次 LC/PGO 成功。
- 原生 `CUVSLAM_PoseGraphEdge` 确实包含 `node_from`、`node_to`、相对 `transform` 和 `covariance[36]`；`CUVSLAM_PoseGraphRef` 返回完整节点/边数组。
- `PoseGraphVisHelper` 将所有边压成两个 `LINE_LIST` Marker：`pose_graph_edges` 连接优化后节点位置，`pose_graph_edges2` 从起点画到 edge transform 预测终点。ROS Marker 中不保留 node ID、协方差或边类型，因此即使有 Marker 载荷，也只能依据线段几何/索引做近似分析，不能等价于原生边导出。
- `CallbackGetAllPoses` 只调用 `CUVSLAM_GetAllPoses` 并逐项转换 pose/timestamp；实现路径没有读取 pose graph 或 metrics。
- 最终两轮 `runtime_config.env` 与生成 launch 均明确 `enable_slam_visualization/landmarks/observations=false`、online recorder=false；对应 `launch.log` 除 `GetAllPoses` 外没有 loop closure/PGO/pose graph 原生日志，目录也没有 bag/Marker 载荷。
- 历史完整路线 `20260807-154031` 的生成 launch 也为 `enable_slam_visualization=false`。`topic_check.txt` 的 OK 和 `topics.txt` 只能证明 publisher 已注册；`pose_graph_nodes` 的 rate 探针明确提示尚未发布，`loop_closure_cloud` 探针仅留下 `ExternalShutdownException`，没有频率或消息载荷。
- `cuvslam_loop_metrics_recorder.py` 名称容易误导：源码只订阅 tracking odometry、slam_path、vo_path 并计算几何闭环指标，明确不在线调用 GetAllPoses，也完全没有调用原生 `CUVSLAM_GetSlamMetrics` 或订阅 Marker/loop cloud。
- 全部 cuVSLAM 日志根目录未发现 `.db3/.mcap/.bag`；也未发现保存的 pose-graph edge TXT/CSV/JSON/YAML。按文件名命中的 `loop/marker` 主要是 recorder 脚本、几何 summary、topic-hz 文本和运动窗口空 marker。
- 196 个历史生成 launch 为 visualization=true、18 个为 false。6 个旧轮次的 `loop_closure_cloud` rate 文件确实记录过非零消息率；其中若干同时有 pose graph nodes 消息。
- `LandmarksVisHelper` 对相同 `landmarks.timestamp_ns` 明确跳过，只在数据层时间戳变化时发布；结合 `LL_LOOP_CLOSURE` 的“last loop closure event 可见 landmarks”定义，这些旧轮次可作为“cuVSLAM 曾产生 LC-layer 更新”的旁证。但 rate 文件没有点云宽度/内容、metrics、edge 或运动窗口，不能证明最终两次短环产生了有效起终点约束。

## 2026-08-09 — Phase 38 最终判定与下一次诊断出口

- 最终判定：`现有证据不足`。已证明最终两轮没有保存能回答“是否建立有效起终点回环边”的数据；这不等价于证明“无边”，也不等价于证明“有错误边”。可确认的仍只有行为结果：后端 yaw 改善、XY 恶化到 `0.356863m`。
- 全库 `launch.log` 与小型 TXT/JSON/LOG/YAML 搜索未发现 `lc_status`、`pgo_status`、原生 node/edge 字段；未发现 `.db3/.mcap/.bag/.slamdb/.db/.sqlite/.pb/.bin` 或 debug dump。wrapper 源码也没有调用 `CUVSLAM_GetSlamMetrics`。
- tracker 已销毁，最终两轮也没有保存地图/数据库，无法从当前磁盘文件恢复当时的 pose graph。继续离线推断会把轨迹形状误当成边证据，应停止。
- 最低负载且可判别的未来 exporter 设计：将 `enable_reading_slam_internals` 与 RViz/全量 visualization 解耦；在 wrapper 跟踪回调中读取 `CUVSLAM_SlamMetrics`，只记录 LC/PGO 状态变化；初始化时保存一次原生 graph edge pair 基线，在 `lc_status/pgo_status` 成功事件与停稳后各抓一次 `CUVSLAM_PoseGraphRef`，输出 JSONL：event timestamp、metrics、node IDs/poses、`node_from/node_to/transform/covariance` 和相对上一快照新增边。
- 该 exporter 不启 RViz、PointCloud、rosbag、ROS CLI rate 探针或系统日志扫描。实现后先做静止负载 A/B，确认不引入 frame delta，再由用户决定是否安排一条新的诊断路线；当前冻结第三次短环、半程和完整路线。

## 2026-08-09 — Phase 39 wrapper 实现审计

- Jetson 源码 `/home/superwfx666/workspaces/isaac_ros-dev/src/isaac_ros_visual_slam` 位于干净的 `release-2.1`，HEAD `a2e2cc979b47e1fa344450b20f3a51cfd7f481d4`，没有现有用户 diff；本机比赛仓库没有该 wrapper 源码镜像。
- node 参数集中在 `VisualSlamNode` 构造器声明并保存到 header 成员，适合增加默认关闭的 diagnostics bool/path/poll 参数，不需要改 ROS interface package。
- `VisualSlamImpl::Exit()` 先停止所有异步 helper，最后才 `CUVSLAM_DestroyTracker`；新增 helper 可在 Reset/Exit 中安全完成最终 graph snapshot，再清空 handle。
- 当前 visualization helper 已采用独立线程、condition variable 与 Start/FinishReading API。diagnostics 应沿用异步生命周期，但不能把 graph snapshot 放到主 Track 回调中，以免回环发生时阻塞 30 FPS 输入。
- CMake 显式列出每个源文件，已有 `ament_cmake_gtest`。新增 helper 源文件需加入 library；edge diff/序列化应拆成可离线测试的纯函数，避免单元测试依赖相机或 tracker。
- 活跃 DWB worktree 已有 Phase 37 的 4 个未提交修改：runbook、GetAllPoses 工具及两个测试；本轮必须在其上增量编辑，不能回退。
- 生产 launcher 由 shell 生成 Python launch 与 `runtime_config.env`，并把宿主日志目录挂载为容器 `/logs`。diagnostics 参数需同时进入环境变量、生成 launch 和运行配置；输出路径固定在 `/logs` 可直接持久化到每轮独立日志目录。
- launcher 当前没有统一正整数校验 helper；diagnostics 的三个整数参数需要在生成 Python 前显式校验，避免非法 shell 输入产生不可加载的 launch 文件。功能开关默认 `false`，输出固定 `/logs/cuvslam_slam_diagnostics.jsonl`。
- wrapper helper 的 data-layer 读取方式与既有 `PoseGraphVisHelper` 一致：每次快照前 Enable，成功 Start 后 Finish，退出时 Disable。初审发现 `node_distance_m` 直接输出 `double`，当节点平移含 NaN/Inf 时仍会产生非法 JSON；需改为有限值守卫并补纯函数/序列化测试边界。
- `enable_reading_slam_internals` 仅在 visualization 或 diagnostics 任一开启时为 1；diagnostics 默认 false，因此既有 visualization=false 生产配置不会隐式开启内部层。停机顺序为 diagnostics join/final snapshot 在 tracker destroy 之前，满足句柄生命周期。

## 2026-08-09 — Phase 39 首版 Request changes

- `MetricsStateEquals` 未比较 `timestamp_ns`，相同状态/landmark 数的独立 LC/PGO 事件可能被合并。事件身份必须考虑原生时间戳，并覆盖“相同内容、不同 timestamp”测试。
- `CaptureGraph` 仅在 edge ID 集合变化时写非最终记录；PGO 只更新节点 pose、edge transform 或 covariance 时会丢证据。事件窗口快照必须强制写完整 nodes/edges，即使 diff 为空。
- 异步 SLAM 下 metrics 先于 graph 生效；单次立即抓图不能可靠关联。采用有界两次事件窗口：在全图最小间隔限制下抓当前/后续两次，并在 JSON 中显式列出关联 metrics event ID/timestamp。
- landmark 计数变化不能直接触发无上限 graph 读取。metrics 可按 33ms 采样，但 graph attempt 必须由独立最小间隔限制，默认不超过 1Hz；非法周期应拒绝而不是压到 1ms。
- `num_nodes/num_edges >= max_items_count` 视为可能截断。截断图的 diff 必须标无效，且不得覆盖上一份可靠 baseline；事件/最终快照仍可落盘并明确 `possibly_truncated=true`。
- 所有浮点值必须经有限数序列化，包含派生的 `node_distance_m`。现有三项测试不足，需增加时间戳、事件窗口、限频、截断、PGO 强制快照、JSON 非有限值与配置范围测试。
- 本机重构后，metrics 计数更新只写 `metrics_update`，只有 signal 初现、clear 后重现或原生 `timestamp_ns` 改变才创建新 event window；graph attempt 使用独立时钟限频。每个 event 在两次 graph attempt 后过期，快照 JSON 显式带 `event_id + metrics_timestamp_ns`。
- 复审补充：同一原生 timestamp 下 LC/PGO status 可能分阶段变化；status 变化也应新建/续开 event window，避免 PGO 晚于首个窗口时漏图。仅 landmark 数量变化继续只写 metrics_update，不触发 graph。
- `graph_event` 强制包含完整 nodes/edges，故 PGO 即使 edge ID 集合不变也会落 pose/transform/covariance；截断图的 `edge_diff_valid=false` 且不更新 `previous_edge_ids_`/可靠 baseline。
- 为本机编译验证查询 llvm-mingw 官方 GitHub release API，当前返回 tag `20260616`、资产 `llvm-mingw-20260616-ucrt-x86_64.zip`、大小 `187504083` 字节。计划仅解压到仓库 `tmp`，不安装 WSL、不修改 Jetson。
- 便携包已下载，长度 `187504083`；本地 SHA-256 `b9b68a4d276e16fa25802aaba458e4638f64b3884c290aaccdc2d87083b6ca35` 与 GitHub release API 的资产 digest 完全一致，可安全解压。
- ShellCheck 官方 latest API 返回 `v0.11.0`，Windows 资产为通用名 `shellcheck-v0.11.0.zip`，大小 `8068167`，SHA-256 digest `8a4e35ab0b331c85d73567b12f2a444df187f483e5079ceffa6bda1faa2e740e`。
- Phase 39 本机便携工具已实际解压到仓库 `tmp/toolchains/`：LLVM 根为 `llvm-mingw-20260616-ucrt-x86_64/llvm-mingw-20260616-ucrt-x86_64`，ShellCheck 根为 `shellcheck-v0.11.0`；未修改系统 PATH、注册表或 WSL。

## 2026-08-09 — Phase 39 本机复审最终结论

- 真实 API 的 `CUVSLAM_SlamMetrics.timestamp_ns` 是 `int64_t`；event ref 若用 `uint64_t` 会在负值时回绕。现已端到端改为 signed 类型并验证 JSON 保真。
- 六项首版阻断问题均已闭合：新事件身份包含 timestamp 与 LC/PGO status；事件触发图即使 edge ID 不变也完整落盘；每事件保持两次受 1 Hz 硬限频约束的 graph attempt；landmark-only 更新不触发全图；截断图不产生可靠 diff 或覆盖 baseline；pose/covariance/派生距离均用 finite guard。
- 本机测试可以证明接口类型、纯函数、生命周期、异常重试、限频和 JSON 契约，但不能替代 Jetson ROS/cuVSLAM 链接构建或 Xavier NX 静止负载 A/B。因此当前结论是“允许进入隔离部署/构建阶段”，不是“允许路线测试”。

## 2026-08-09 — Phase 39 Jetson 构建与 A/B 测量链校正

- 当前补丁已在 Jetson Xavier NX 的真实 aarch64、ROS Humble 和 cuVSLAM 链接环境中完整编译；新增 helper gtest 及两个既有 gtest 均通过，节点与 `libvisual_slam_node.so` 没有缺失动态依赖。由此闭合“仅本机 stub 验证”的剩余构建风险，但尚未闭合运行负载风险。
- Isaac workspace 下保存 package 形态的备份/staging 会被 colcon 默认递归发现，造成 duplicate package；在不移动备份的情况下，可靠构建入口是显式 `--base-paths /workspaces/isaac_ros-dev/src`。
- launcher 输出“Manual GUI test is running”早于 `CUVSLAM_WarmUpGPU/CreateTracker` 日志完全落盘，不能作为 130 秒稳定窗口起点。A/B readiness 必须以 `launch.log` 已出现 `CUVSLAM_CreateTracker()` 为准，再等待 10 秒。
- `launch.log` 的原生丢帧文本是 `Delta between current and previous frame [...] is above threshold`；只搜索 `frame delta` 会漏报。稳定窗口必须按保存的 baseline/end 行号精确截取，不能在关机后简单 tail 到 EOF，否则会把正常 shutdown 日志混入窗口。

## 2026-08-09 — Phase 39 静止 A/B 最终结论

- 有效 A/B 都在真实 Jetson、D455 `640x360x30`、IMU/planar/mapping 开启及 visualization/recorder/probes/RViz/运动出口关闭条件下独立冷启动；逐行配置 diff 证明唯一变量是 diagnostics bool。
- diagnostics=false 与 true 的约 131.66 秒稳定窗口都保持 `launch.log=59` 行，frame delta 和 tracking lost 均为 0。B 单点 CPU 只比 A 高 1.26 个百分点，内存高约 6.3MiB，没有观察到 exporter 引入持续调度断档或异常负载。
- 静止 B 轮产生两个 `pgo_status=1` metrics signal，间隔约 60 秒；每个信号均落两次带同一 event ref 的完整 graph snapshot。图从 2 nodes/1 edge 增至 3 nodes/2 edges，说明 exporter 在无路线运动时也能捕获初始化/静止图演进，不能把任意 `pgo_status=1` 或新增顺序边直接解释为有效起终点回环。
- JSONL 停机前已有 8 条，优雅退出追加 `graph_final` 与 `session_stop`；全文件严格 JSON 解析通过，无 NaN/Infinity。final 图未截断且 diff 有效，证明正常停止路径可落最终快照。
- Phase 39 的结论是“exporter 具备低负载采集条件”，不是“cuVSLAM 已形成有效 LC”。下一次若用户选择诊断路线，判定必须结合 metrics event、跨时段新增边 ID、transform/covariance、节点时间跨度和同窗 tracking/后端误差，不能仅凭 pgo_status 或 edge 数增长下结论。
- 在 colcon workspace 内保存带 package `CMakeLists.txt` 的部分备份也可能被识别为同名 package，即使没有完整复制源码树。此类原位备份必须放 `COLCON_IGNORE`，仅在单次构建命令加 `--base-paths src` 不能消除未来默认构建的重复发现风险。

## 2026-08-09 — Phase 40 短闭环证据口径

- 原生 `cuvslam.h` 对 `CUVSLAM_SlamMetrics` 的接口注释明确：`lc_status` 与 `pgo_status` 都是 `0=fail, 1=success`。LC landmark 四个计数非零但 `lc_status` 始终为 0，可作为“候选进入匹配流程但未成功”的证据；计数与 LC 状态均无信号时只能判“未观察到候选”。
- “非相邻回环边”不能只凭总 edge 数增长判断。优先把新增边暂按无向边处理，移除该边后检查两个端点在既有图中的最短路径是否至少跨 2 条边；若拓扑信息不足，`node_id_span > 1` 只能作为辅助，不单独作为通过依据。
- “约束被接受”至少要求同一事件链上出现 `lc_status=1`、可靠的新增非相邻边（`edge_diff_valid=true` 且未截断），并观察到后续 `pgo_status=1`。静止 A/B 已证明单独的 `pgo_status=1` 和顺序边增长在静止初始化时也可能出现，二者不能单独证明回环。
- “全局修正”优先比较 LC/PGO 事件前后完整 graph snapshot 中共同节点的位姿变化，并与一次性 GetAllPoses 同窗结果交叉检查。若有约束但没有可观测的既有节点位姿变化，或后端闭环没有相对 tracking 改善，不得声称后端完成全局修正。
- diagnostics JSONL 的两次事件窗口快照用于覆盖异步图更新；任何 `possibly_truncated=true` 或 `edge_diff_valid=false` 的快照不能用于确认新增回环边。物理走回早期位置只是触发条件和外部参照，不替代上述内部证据。
- 当前宿主未暴露 ByteRover MCP，本机也没有 `brv` 命令，因此本阶段无法执行复杂任务启动时的 L1-3 主动检索；没有把“空检索”伪装成“无相关历史”。
- Phase 40 运动前只读门禁已满足：D455、20W 6CORE、六核/GPU 固定频率、Docker/相关进程为空、GNOME 设置关闭和三份运行文件哈希一致。远端 Git 工作区包含大量既有修改与未跟踪文件，验收不得用 Git 清理、重置或覆盖无关文件。
- 远端 runbook 单文件同步采用先备份、上传 staging、校验 SHA-256、再覆盖目标的顺序；没有修改运行脚本、wrapper、系统配置或其他远端文件。原版可由 `tmp/phase40_runbook_backup_20260809_0240/` 恢复。
- Phase 40 活跃证据目录固定为 `/home/superwfx666/cuvslam_final_acceptance_logs/20260809-024302`。运动前 diagnostics 已有 8 行初始化证据，因此后验分析必须以保存的 baseline line 8 分隔，不能把静止初始化 PGO/顺序边归入路线回环。
- `acceptance/short` 由容器内 root 创建；本轮所有 marker 应从容器内部写 `/logs/acceptance/short/`，避免宿主权限错误。tracking 起点已经成功，禁止因后续 marker 权限错误而重复采样。
- “拓扑非相邻”只是必要条件，不足以证明“新位置连到早期位置”。本轮 85 个节点的末端图中，最终新增边 rank gap 只有 1 和 2；全运动窗最大 rank gap 也只有 7。后续必须同时要求端点分别属于预先标记的早期段与最终回访段。
- 中段 LC 事件的 accepted constraints 确实引发全局图移动：line 100->110 共有 53 个旧节点，48 个移动超过 1cm，中位净 XY 7.61cm。末端回访 line 161->164 虽 `lc_status=1/pgo_status=1`，但 84 个旧节点无一移动超过 1cm，说明最终局部边没有形成可观测的起终点全局拉回。
- 后端同窗 XY `0.520313m` 对比 tracking `0.078694m`，扩大约 6.61 倍；yaw 也由 tracking `4.1599deg` 变为后端 `5.2161deg`。准确诊断是“局部回环约束被接受且优化器工作，但约束集合没有形成正确长程闭环，优化结果恶化”，不能归为单纯的无候选/候选拒绝/后端未运行。
- 证据目录：`/home/superwfx666/cuvslam_final_acceptance_logs/20260809-024302/`；acceptance 文件 SHA-256 清单位于远端 `tmp/phase40_short_control_20260809_024302/acceptance_evidence.sha256`。diagnostics JSONL SHA-256 为 `387ea915...ee32a`。
- 结果版 runbook 远端哈希为 `e343dbbd...c8a802`，已明确写入 Phase 40 fail、长程边定义和“后端修正方向错误”分型；半程/完整路线保持冻结。

## 2026-08-09 — Phase 41 cuVSLAM 外接后端联网调研

- 用户提到的工业 benchmark 可以核实：2026-03-17 提交的 arXiv 预印本 *Industrial cuVSLAM Benchmark & Integration* 比较 RTAB-Map、cuVSLAM、ORB-SLAM3 和 `cuVSLAM stereo front-end + Idealworks in-house SLAM back-end`。在 Xavier、约 1.7 km 单次 VSLAM 路线中，混合方案 mean APE/RMSE 为 `0.91/0.54m`，cuVSLAM 端到端为 `1.57/2.01m`，ORB-SLAM3 为 `1.17/1.65m`，RTAB-Map 完整栈为 `5.89/7.53m`；混合方案 tick-rate `1.50Hz`，RTAB-Map `0.95Hz`。来源：https://arxiv.org/abs/2603.16240 与 https://arxiv.org/html/2603.16240
- 该 benchmark 只能证明“cuVSLAM VO + 某个自研后端”在一个工业数据集上有潜力，不能证明“cuVSLAM + RTAB-Map”必然更好：Idealworks 后端未公开足够实现细节或代码；VSLAM 各配置只跑一次，论文还说明异常运行被剔除；RTAB-Map 对照使用自己的 stereo VO 和后端，不是外部 cuVSLAM odom；LiDAR 定位被当作 ground truth。该文目前是 arXiv v1 预印本，不应作为生产换型的唯一依据。
- RTAB-Map 官方说明其核心链条为：增量 appearance-based BoW 回环检测 -> 假设接受后向图中添加约束 -> 图优化器最小化地图误差，并用内存管理约束大地图实时性。它同时覆盖地点识别、约束生成、图优化和数据库管理，因而可以承担“完整回环后端”，而不是只有数值优化。来源：https://introlab.github.io/rtabmap/
- `rtabmap_ros` 当前 `ros2` 分支 launch 已明确支持外部 odometry：`visual_odometry=false` 可禁止启动 `rgbd_odometry/stereo_odometry`，`odom_topic` 可重映射到 `/visual_slam/tracking/odometry`；`odom_frame_id=''` 时使用 odom topic 而非 TF；SLAM 节点仍可订阅 stereo 或 RGB-D；`publish_tf_map` 控制 map/odom TF，`database_path` 控制地图保存/加载。来源：https://github.com/introlab/rtabmap_ros/blob/ros2/rtabmap_launch/launch/rtabmap.launch.py
- RTAB-Map core 当前提供 `Optimizer/Strategy: 0=TORO, 1=g2o, 2=GTSAM, 3=Ceres`，并为 g2o/GTSAM 提供 Vertigo robust graph optimization；实际默认值和可选项取决于构建时发现的依赖，PoC 必须在目标容器内查询编译能力，不能假定 GTSAM 已启用。来源：https://github.com/introlab/rtabmap/blob/master/corelib/include/rtabmap/core/Parameters.h
- RTAB-Map 的 `rtabmap_msgs/Info` 原生带 `ref_id`、`loop_closure_id`、`proximity_detection_id`、`loop_closure_transform` 和统计字典，可用于区分候选/接受事件；最终仍应保存 `MapData/MapGraph` 或数据库并核对边端点，不能只凭非零 loop ID 宣称起终点长程回环。来源：https://github.com/introlab/rtabmap_msgs/blob/ros2/msg/Info.msg
- Isaac ROS Visual SLAM `release-2.1` 源码确认 `/visual_slam/tracking/odometry` 使用 pure VO 的 `odom -> base_link` pose，而 SLAM rectified pose 单独用于 `map -> base_link` 和 `map -> odom`；`enable_localization_n_mapping=false` 明确表示只运行 Visual Odometry、不产地图。因此该 topic 是外部后端的正确输入，且换型时必须令 cuVSLAM `publish_map_to_odom_tf=false`，避免与 RTAB-Map 双重发布。来源：https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/blob/release-2.1/isaac_ros_visual_slam/src/impl/visual_slam_impl.cpp 与 https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/blob/release-2.1/isaac_ros_visual_slam/include/isaac_ros_visual_slam/visual_slam_node.hpp
- GTSAM 官方定位是 factor graph / smoothing and mapping 数值库；Kimera-RPGO 官方定位是 robust pose graph optimizer，输入接口直接接收 factors/values。二者都不会凭空完成视觉地点识别、关键帧管理、几何验证和 loop factor 生成。来源：https://github.com/borglab/gtsam 与 https://github.com/MIT-SPARK/Kimera-RPGO
- Phase 40 的首要缺口是没有“末端新位置到早期位置”的正确候选/约束，而不是优化器没执行。因此只把 cuVSLAM optimizer 换成 GTSAM/Kimera-RPGO不能解决已观察到的根因；若选自研路线，至少还需实现或集成 BoW/learned place recognition、stereo 几何验证、关键帧/数据库、约束协方差和错误回环拒绝链。
- 首选可证伪 PoC 调整为 `cuVSLAM pure VO + RTAB-Map stereo backend`，优先复用当前单一 RealSense 驱动已经发布的 `/camera/infra1|infra2/image_rect_raw` 与 camera info，不先开启额外 color/depth stream。这样避免第二个 D455 驱动，也避免在尚未测量前引入 RGB-D 对 USB、CPU、内存和时间同步的新负载；若 IR stereo 的外观回环不够，再把 color+aligned depth 作为第二阶段变量。
- TF 唯一所有权应为：cuVSLAM 发布或提供 `odom -> base_link` 的连续局部 VO，RTAB-Map 独占 `map -> odom`；禁用 cuVSLAM `map -> odom` 和任何临时 identity `map -> odom`。RTAB-Map、RealSense 与 cuVSLAM应先放在同一 Humble Docker/DDS 图内，直接订阅原始带硬件时间戳的 topic，不经 Host JPEG/UDP 重打时间戳链。
- RTAB-Map ROS 2 主线当前最低要求 Humble，适合现有 Isaac Humble 容器；Host Foxy 不应承担当前主线后端。来源：https://github.com/introlab/rtabmap_ros/tree/ros2
- 当前开源 cuVSLAM 主线的预构建 Jetson目标为 Orin/Thor，并要求 JetPack 6/7、CUDA 12/13；它不是当前 Xavier NX `release-2.1` 环境的无成本升级路径。本阶段只复用已验证的 release-2.1 VO 输出，不把“换后端”和“升级 cuVSLAM 主线”绑定。来源：https://github.com/nvidia-isaac/cuVSLAM
- 建议的短闭环 Go 门槛：cuVSLAM tracking 全程正常且无新增 frame delta；RTAB-Map 至少形成一条端点分别属于预标记早期段和最终回访段的可靠非相邻约束；约束进入图并触发 `map -> odom`/旧节点全局修正；修正方向朝向起点真值，最终 XY 不劣于纯 VO且达到项目既定约 `<=0.10m`；后端更新率至少 `1Hz`，且不造成 cuVSLAM 掉帧。任一缺失均为 No-Go，禁止解冻半程/完整路线。

## 2026-08-09 — Phase 42 完整遥控路线诊断边界

- 正式 `docs/cuvslam_mapping_runbook_zh.md` 仍保留“短闭环通过后才逐级进入半程/完整路线”的验收门禁；Phase 40 实际失败，因此这次完整路线不能被表述为分级验收已解冻。
- 用户已明确要求遥控完整走一圈并只观察 LC/PGO 与后端优化，同时明确不启动地图保存脚本。因此本次可作为用户授权的隔离诊断采集，使用 `STAGE=full` 区分日志，但不执行 runbook 第 7 节 `save_map`，也不启动 Nav2、bridge、速度仲裁、运动发送器、RViz、rosbag 或在线 recorder。
- 正式判定仍需 tracking 起终点、运动窗口、diagnostics 长程边/LC/PGO/旧节点修正，以及停稳后唯一一次 GetAllPoses 同窗指标。物理回到起点本身不等于回环成功，也不能只凭后端闭环距离判断图优化器内部 cost。
- 当前 ByteRover MCP/CLI 均不可用，本阶段无 L1-3 召回结果。
- 2026-08-09 16:53 只读预检：Jetson SSH、D455 `8086:0b5c`、`MODE_20W_6CORE`、CPU `0-5`、约 `182G` 可用磁盘、Docker 空和相关 ROS/运动进程空均正常；四份 launcher/采样工具/runbook 的本机与远端 SHA-256 完全一致。
- 当前运行门禁未通过：六核 `scaling_min_freq=1190400`、GPU `min/cur=114750000`，未达到已验收的 CPU min=max=cur `1420800` 与 GPU min=max=cur `1109250000`；`gnome-control-center` 也仍在运行。必须锁频并由用户正常关闭设置窗口后再复检，不能直接启动 cuVSLAM。
- root SSH 已验证可用。本地主仓 `scripts/jetson_max_performance.sh` SHA-256 为 `3a06f428529524a81ffc95a18ddf4356238ab636075ed97370c83d95ef785795`；预设的两个远端项目路径未返回该文件，需先只读定位，若不存在则仅部署同哈希临时副本后执行。

## 2026-08-09 — Codex Workspace / Git worktree 开发模式调研

- OpenAI 官方 Codex Worktrees 文档说明：Local checkout 是项目原始仓库，Codex-managed worktree 默认位于 `$CODEX_HOME/worktrees`、通常一任务一棵且 detached HEAD；长期环境应使用 permanent worktree，并可作为独立 project 使用。来源：https://learn.chatgpt.com/docs/environments/git-worktrees
- 同一文档说明 `.worktreeinclude` 只负责把 Git 忽略文件复制到 Codex 创建的 managed worktree，不适用于用户从命令行创建的普通 Git worktree；因此现有 `quadruped-robot-competition-nav2-dwb` 的 PWF 三件套不能依赖 `.worktreeinclude` 自动同步。
- OpenAI 官方 Projects 文档说明：一个 local project 可附加多个本地文件夹并指定 Primary；新任务从 Primary 启动，Git 操作以及 `AGENTS.md`、skills、`config.toml` 自动发现也以 Primary 为准，Secondary 仍可搜索、读取和编辑。来源：https://learn.chatgpt.com/docs/projects
- 本机 `git worktree list --porcelain` 证明 DWB 最新代码目录是独立 worktree `C:/Users/111/Desktop/比赛/quadruped-robot-competition-nav2-dwb`，分支为 `Stonefield/nav2-foxy-dwb-integration`；当前 Codex Workspace Primary 仍是 main worktree，正是启动时先读取旧代码根的原因。
- 主 worktree 当前为 `main`，相对 `origin/main` ahead 22 / behind 37，存在大量未跟踪文件；DWB worktree相对远端同名分支 ahead 15，并有 2 个已跟踪文件未提交。两个目录都不能直接删除、重置或相互覆盖。
- 两个 worktree 都已有本地 PWF 三件套，但主目录约为 `159/560/453 KB`，DWB 约为 `6/11/11 KB`，内容已经分叉。迁移应做一次语义合并，并把唯一活跃三件套放在长期开发所用 worktree 根；不应长期维护两套同时可写的 PWF。
- Jetson 已有 `/home/superwfx666/Desktop/jetson_max_performance.sh`，SHA-256 与本地完全一致；以 root 执行 `--full` 成功，CPU 0-5 的 min/max/cur 均为 `1420800`，GPU min/max/cur 均为 `1109250000`，EMC 当前为 `1866000000`，风扇锁定。
- 锁频后的最终只读复检仍返回 `GNOME_CONTROL_CENTER_RUNNING` / `PREFLIGHT_BLOCKED`；在用户正常关闭 Ubuntu“设置”窗口并确认完整路线物理安全条件前，不得启动 diagnostics 会话。
- 用户确认后再次即时复检仍命中 PID `3894`：`gnome-control-center`，父 PID `2998`，状态 `Sl`，启动时间 `2026-08-09 15:56:50`。这是真实驻留进程而非检索命令假阳性；按 runbook 不自动终止，等待用户关闭或明确授权普通 `SIGTERM`。
- 用户正常关闭设置窗口后，即时复检返回 `GNOME_CONTROL_CENTER_OFF/PREFLIGHT_OK`。本轮冷启动容器为 `cuvslam_accept_full_20260809_170203`，日志目录为 `/home/superwfx666/cuvslam_final_acceptance_logs/20260809-170204`。
- 实际运行配置逐项满足：`640x360x30`、mapping/IMU/planar 与 diagnostics 开启；visualization/landmarks/observations、online recorder、topic/rate probes、RViz、ROS daemon、Nav2、bridge、地图 action 和运动发送链关闭。初始 diagnostics 严格解析 5 行有效。
- 唯一 tracking 起点为 stamp `1786266248.8415666`，`odom -> base_link`，XYZ `(0.0000896, 0.00000562, 0.0000112)`，yaw `-0.001046deg`。运动窗口从 `2026-08-09T17:04:53+0800` 打开，launch/diagnostics 基线行号为 `62/5`。
- 用户完成完整路线后，运动窗口于 `2026-08-09T17:10:40+0800` 关闭，tracking 同窗约 `399.094s`，XY/yaw 漂移 `0.524702m/3.259704deg`；launch line 62..75 没有 tracking lost 或 frame-delta 告警。
- tracking 终点相对起点 `dz=-0.410347m`，提示起终点机身高度/姿态或前端 Z 估计发生显著变化；平面回环结论只使用 XY/yaw，不把 Z 混入主门槛。
- 本会话唯一一次真实 GetAllPoses 成功，`service_calls=1`、`16898` poses；同窗 `11970` poses、XY 路径 `45.320902m`、XY 闭环 `9.753458m`、yaw `159.003463deg`、最大单步 `1.880394m`。该摘要远劣于 tracking，但需与 diagnostics 长程边和 PGO 修正交叉分析后定性。
- 会话通过向核验后的 ROS launch PID 发送 `SIGINT` 正常析构；最终 JSONL 严格解析 `509` 行，事件为 session_start 1、graph_baseline 1、metrics_signal 284、graph_event 221、graph_final 1、session_stop 1，最后事件为 session_stop。Docker 和相关进程为空。
- 全部 27 个证据文件约 `58.6MB` 已复制到本地 `tmp/phase42_full_20260809_170204/`；Jetson 原日志保留不变，未生成或保存地图。

## 2026-08-09 — Workspace 迁移前本地改动审计

- 主 worktree 的 23,594 个 Git 未跟踪文件中，`.cad-deps` 13,722 个、`tmp` 9,508 个，二者合计 23,230 个；不能用总文件数直接等价为 23,594 份有效源码改动。
- 主 worktree 仍有明确的代码/文档资产只存在于该目录，包括 `configs/navigation/ekf_cuvslam_planar.yaml`、两份 Nav2 bridge 文档、`launch/ekf_cuvslam_planar.launch.py`、`scripts/jetson_max_performance.sh`、`scripts/start_official_cuvslam_realsense.sh`、Nav2 overlay 归档等；切换 Primary 前应逐项归档或选择性移植。
- 主 worktree 有 6 个未跟踪脚本路径与 DWB 的已跟踪文件重合：仅 `probe_odom_best_effort.py` 内容一致；其余 5 个不同。DWB 版本的文件时间均更晚，且其中三个差异很大，禁止把主版本批量覆盖到 DWB。
- DWB 本身并非干净：`docs/cuvslam_mapping_runbook_zh.md` 与 `tests/test_cuvslam_slam_diagnostics_contract.py` 有未提交修改；迁移过程中必须原样保留。
- DWB PWF 不是主 PWF 的完整子集：按非空行集合比较，DWB 的 task/progress/findings 分别有 48/63/58 行未出现在主版本。PWF 需要按主题语义合并，不能只复制主三件套覆盖 DWB。
- 推荐稳定状态：Codex local project 以 DWB worktree 为 Primary，主 worktree作为临时 Secondary/归档来源；合并后的唯一活跃 PWF 位于 DWB 根，主 PWF 改为只读归档或迁移完成后改名，避免双写。

## 2026-08-09 — DWB PWF 合并证据协调

- DWB 旧 PWF 的专项 Phase 1–7 已被主 PWF 的 Phase 34–40 及更细日志覆盖；旧 Phase 8 对应主 PWF 的 Phase 40–42，旧 Phase 9 对应主 PWF 的全局校正/替代后端支线。合并后保留主阶段编号，避免产生第二组 Phase 1–9 和第二个 Current Phase。
- DWB 的 125 秒 wrapper-only/librealsense 直连实验保存了独有的 IR/IMU 原始间隔与 frame-number 证据，应补入合并 findings；但其“根因下移到 D455/USB”是当时的中间判断，已被主 PWF 后续更长纯 IMU基线和 `gnome-control-center` 单变量 A/B 修正，不能作为当前最终根因。
- DWB 的轻量观察者三组静止 A/B 精确 CPU 增量、Jetson 非正常重启和启动恢复过程在主 PWF 中没有等价完整记录，应作为历史实测补入；它证明旧探针超过自定负载门槛，但三组 B 未新增数据断档。
- DWB 的静态 `map -> odom`、动态 `global_pose_manager` fail-closed 和 alignment pending 结论已被主 PWF Phase 33/Stage C-G 更完整覆盖，不重复复制；只在合并记录中保留映射说明。
- DWB Phase 40 短闭环结果与主 PWF Phase 40 是同一次实测；以主 PWF 的 diagnostics edge/LC/PGO/GetAllPoses 分层结论为权威版本，不重复导入旧摘要。

## 2026-08-09 — DWB 断帧与轻量探针历史证据补充

- DWB 原跨进程基线 `diag-baseline-20260807-2328` 使用 RealSense 独立节点和独立 cuVSLAM component container；D455 FW `5.17.0.10`，RealSense ROS `4.54.1`，librealsense `2.54.1`。125 秒内 cuVSLAM warning 约每 `30.3-30.5s` 出现，IR 源时间戳最大 gap `150.46ms`，IMU 最大 gap `114.89ms`。
- wrapper-only 显式设置 `enable_sync=false`、`hold_back_imu_for_frames=false`、`unite_imu_method=2`，不加载 cuVSLAM；125 秒仍得到 IR 最大源 gap `150.325ms`、IMU `106.993ms`，IR/IMU 到达停顿约 `131-201ms`。
- Jetson 主机 `pyrealsense2 2.55.1` 直连 125 秒也记录到约 `30.47-30.54s` 周期的 IR 异常，到达停顿 `132-183ms`，最终 infrared frame-number gap `22`，accel/gyro frame-number gap `0`，无 librealsense notification。
- 该证据证明早期 10 秒窗口不足以排除较长周期 IR 异常，但不能单独把当前最终根因定为 D455/USB：主 PWF 后续纯 IMU 100 秒硬件 Frame Number 零缺口，并通过关闭 `gnome-control-center` 的同配置 130 秒单变量 A/B 消除 30.5 秒断档。当前权威结论仍以主 PWF 的 GNOME A/B 和运行期低负载约束为准。
- D455 早期空闲状态为 `power/control=auto`、全局 `/sys/module/usbcore/parameters/autosuspend=2`，推流前可见 runtime suspended；`power/control=on` A/B 因需要交互 sudo 未执行。不能把这一未执行候选解释为已证实根因。
- 轻量观察者的 metadata-only 路径不能证明完整 Image DDS 样本已送达 cuVSLAM，因此其判定必须同时依赖 cuVSLAM frame-delta warning 和 odometry gap；可选 status topic 缺失时只降级辅助信号，不放宽 odometry 门禁。
- 三组 B 静止观察的自身 CPU `11.87-12.04%` 单核、六核整体增量 `3.04-3.57pp`，超过预设负载门槛；但三组均没有新增 IR/IMU/odom gap 或 tracking lost。其证据边界是“负载不合格但未观察到新增断档”，不是“探针无开销”或“探针导致断档”。
- 首轮 A1 后 Jetson 非正常重启只留下 `last` crash、无 OOM 和当前 boot 的重新枚举；因前一 boot journal 未持久化，无法区分掉电、硬复位或内核崩溃，不能把重启归因于观察者。
- DWB 原计划关于静态 `map -> odom`、动态 `global_pose_manager`、alignment pending 和 Phase 40 短闭环的结论已被主 PWF 后续阶段更完整覆盖，不在本节重复；完整原文仍可从备份恢复。

## 2026-08-09 — Phase 42 完整路线回环与后端优化最终判定

- 运动窗 `347.907s`，后端同窗 XY 路径 `45.320902m`；后端 XY 闭环 `9.753458m`、误差率 `21.5209%`，约为 tracking XY 漂移的 `18.59x`，yaw 也从 tracking `3.259704deg` 恶化到 `159.003463deg`。
- LC/PGO 并非未工作：metrics_signal 279 条，`lc_status=1` 73 条、`pgo_status=1` 279 条；四分位 LC 成功数为 `6/36/12/19`，最大 selected/tracked/PNP/good landmarks 为 `1340/246/240/164`。
- 运动中出现 147 个唯一、完整且 edge-diff 有效的拓扑非相邻端点对，最终图中均仍存在；最终图为 285 节点、361 唯一边、单连通分量、cycle rank 77。说明局部/中程回环约束大量存在，不能归因于“后端完全关闭”。
- 目标长程回环仍为 0：按端点首次出现时间的“最早四分之一到最终四分之一”和按最终节点 rank 的“前四分之一到后四分之一”两套独立口径都没有任何边。最大事件 rank gap 为 105，但发生在路线中段，不是最终回访连回起点。
- 最后四分之一有 38 条局部非相邻边，但最大 rank gap 32；最后一条非相邻边在运动开始后 `290.468s`，到运动窗结束尚有约 `57.439s`，其间只新增顺序边。最终四分之一的最大旧节点中位 XY 修正仅 `0.000768m`，没有可观测全局拉回。
- GetAllPoses 优化轨迹在 `80.785s` 出现唯一超过 0.20m 的跳变：XY `1.880393m`，与 diagnostics sequence 89 同时，`pgo_status=1`、`lc_status=0`。轨迹从约 `(3.671,-0.062)` 瞬跳到 `(5.493,-0.529)`，随后最终停在约 `(9.595,-1.745)`。
- 最严重的 graph snapshot 旧节点修正在 `115.726s`：87 个共同节点中 52 个移动超过 1cm，中位/最大 XY 修正 `0.059302/0.235086m`，当时 `lc_status=1,pgo_status=1`。优化器确实修改旧图，但没有建立最终起终点一致性。
- 机械上仍可调用 `save_map`，但质量门槛为 `<0.20m`，实测 `9.753m` 且缺失起终点长程边，因此工程上必须禁止保存。后续不应继续完整路线反复试跑，应转入 Phase 41 的替代地点识别/回环后端 PoC。

## 2026-08-09 — Jetson Git 工作区只读审计

- 期望的职责边界是合理的：Windows/DWB 是源码权威端，完成 commit 并 push；Jetson 是部署端，只接收可追溯 commit，不在部署 worktree 中积累产品源码改动。当前 Jetson 实际状态不符合该模式，直接 `pull` 会被 dirty worktree 阻塞或制造 merge。
- 本机 DWB 当前 `30e50c4`，相对 GitHub `Stonefield/nav2-foxy-dwb-integration@1efbcd6` ahead 15，另有 runbook 与 diagnostics contract 两个未提交修改。GitHub 尚未包含本机最新代码，所以 Jetson 即使工作树干净，也暂时无法从 GitHub 拉到 `30e50c4`。
- Jetson 共定位 9 个 Git 工作区：`main-latest-test`、DWB、stable、vision-change、main、三个 Isaac ROS 仓库和 vision-yolo worktree。`main-latest-test`、`isaac_ros_common`、`isaac_ros_nitros` 干净；其余 6 个中 5 个 dirty，另一个视觉测试 worktree仅 tracked 干净但有未跟踪标定数据。
- Jetson DWB 为旧 `72e3833`，相对 GitHub DWB 落后 18 个 commit；状态共 237 个路径，其中 48 个 tracked 状态项（40 staged、19 unstaged，部分同一路径同时存在两种状态）和 189 个 untracked。对 Windows DWB 按 SHA-256 比较：90 个文件完全一致、16 个两边都已删除、128 个仅 Jetson 存在且全部位于 `tmp/`（约 1.54 MB）、3 个原始哈希不同。
- DWB 三个哈希差异已逐行复核：`package.xml` 只有 CRLF/LF 差异；`tests/test_cuvslam_slam_diagnostics_contract.py` 与 `tools/ros_realsense_frame_probe/src/ros_realsense_frame_probe.cpp` 均是 Windows DWB 版本更新，Jetson 没有额外逻辑。当前未在 DWB 工作区发现必须从 Jetson 反向回收的产品源码；`tmp/` 仍应先归档再清理。
- Jetson main 为 `82512c6`，与 GitHub main 历史分叉（本地侧 20、GitHub 侧 37），但该 commit 仍由 GitHub `backup/old-main` 保存；工作树有 17 个 tracked 差异和 322 个 untracked 文件。它是旧 main、vision 分支、DWB 部署文件、历史导航代码和现场数据混合形成的部署目录，不是可安全更新的 clone。
- main 中可确认的 Jetson 独有资产包括 127 张 gauge dataset 图片约 21.97 MB、2 张 debug capture 约 0.395 MB、导航/WHZ/旧节点源码与测试输出、若干部署脚本和约 6.78 MB 的 depth detector 权重。部分 tracked YOLO 改造与当时 GitHub vision tree 一致，但 `pyproject.toml`、`setup.py`、RealSense camera 改动以及多份未跟踪源码不能仅凭当前两个 Windows worktree重建；清理前必须整体快照并做语义筛选。
- stable 工作区有独有的 `scripts/realsense_gauge_live.py`（10,905 B）、`scripts/gauge_detector.py`（12,371 B）和 `sample_gauge_debug.jpg`（128,555 B）；它们与本机同名候选哈希均不一致或本机不存在。vision-change 工作区有修改后的 `Docker_Yolo_Combine_0720.md`（40,608 B）和未跟踪 `CPU_throttling_and_saturation.md`（21,345 B），本机不存在同名副本。这 5 项属于明确的回收清单。
- vision-yolo worktree 的 9 个未跟踪 calibration CSV/YAML 合计 50,844 B，本机未发现副本，属于明确的设备侧数据回收清单。
- `isaac_ros_visual_slam` 有 5 个 tracked 修改和 3 个未跟踪 diagnostics helper/test 文件；8 个文件均与 Windows 主 worktree `tmp/cuvslam_slam_diagnostics_phase39/isaac_ros_visual_slam/` 的保存副本逐文件 SHA-256 完全一致，因此源码可恢复，但远端仓库仍是 dirty，不能直接更新。
- 视觉测试分支初始为 `f709906`；审计期间外部会话在 17:54:55 把 `origin/feature/vision-change@05ad596` merge 为 `84e7e3c`，又在 17:56:50 把 `origin/feature/vision-change@6cb3fba` merge 为最终快照 `608d93e`。reflog 连续记录 `merge origin/feature/vision-change`；最终 `608d93e` 相对 `6cb3fba` 有 4 个本地历史 commit，但净文件树完全一致，因此这些 local merge/revert commit 不承载独有代码。真正独有的是 9 个未跟踪标定文件；连续两次漂移说明审计对象仍被其他会话并发更新。
- 视觉测试分支出现本地 merge commit 的根因不是“Jetson 必须开发”，而是在无 upstream 的本地测试分支上反复把另一个远端分支 `pull/merge` 进来。部署端应直接 checkout 并跟踪目标远端分支，更新只允许 fast-forward；分叉时停止并重建部署副本，不能继续制造 merge commit。
- 安全治理顺序：先回收 stable/vision 文档源码、9 个 calibration 文件、main 的现场数据/遗留源码和 DWB `tmp`；再把运行日志、标定和设备配置迁到 Git 仓库外的持久目录；最后只保留一个按分支建立的干净部署 clone。常规更新使用 `git pull --ff-only`；若采用精确镜像式 `fetch + reset --hard`，只能在回收清单完成并得到用户单独确认后执行。
- 本轮所有 Jetson/GitHub 操作均为 `status/rev-parse/log/reflog/diff/hash/ls-remote/ps` 及从 Jetson读取三个文件到本机受控临时目录进行比较；未执行 `fetch/pull/add/commit/reset/clean`，未修改或删除远端文件。审计中出现的 fetch/merge 来自外部并发会话，不是本轮命令。

## 2026-08-09 — Phase 46 Jetson DWB 部署前实时复核

- Windows DWB 当前 `HEAD`、本地 tracking ref 和 GitHub DWB ref 均为 `52d30d66883538d46f571eb392b6e84680a21d72`，工作区/index/untracked 全空。
- Jetson 旧 DWB 仍在 `/home/superwfx666/quadruped-robot-competition-nav2-dwb`，`HEAD=72e3833a288aa72d52a4197030419c9dc360c8fd`，分支名虽为 `Stonefield/nav2-foxy-dwb-integration`，upstream 却错误指向 `origin/main`。
- 旧工作区实时计数为 staged `40`、unstaged `19`、untracked `189`；新候选目录 `/home/superwfx666/quadruped-robot-competition-nav2-dwb-deploy` 不存在，磁盘可用 `182G`。
- Jetson 通过专用 GitHub SSH alias 查询目标分支成功，live ref 为 `52d30d6`。
- Jetson 当前有 ROS 2 daemon、`static_transforms.launch.py` 和机械臂节点运行；没有运行中 Docker。为了不干扰现场运行态，不停止进程、不移动/改写旧目录，新部署 clone 使用独立路径。

## 2026-08-09 — Phase 46 Jetson DWB 干净部署完成

- 旧 DWB 原封不动保留在 `/home/superwfx666/quadruped-robot-competition-nav2-dwb`；完成后 `HEAD` 仍为 `72e3833`，237 项 porcelain 状态与操作前快照逐字一致。
- 可恢复快照位于 `/home/superwfx666/dwb-deployment-backups/20260809-192933`，约 `186M`：包含旧 HEAD 完整 history bundle、tracked working tree/index 二进制 patch、完整 porcelain 状态、189 个 untracked 路径及逐文件 SHA-256。快照文件哈希和 bundle verify 均通过。
- 新部署 clone 位于 `/home/superwfx666/quadruped-robot-competition-nav2-dwb-deploy`，约 `524M`；`HEAD=52d30d66883538d46f571eb392b6e84680a21d72`，本地分支 `Stonefield/nav2-foxy-dwb-integration` 直接跟踪同名 `origin` 分支。
- 新 clone 配置 `pull.ff=only`、`fetch.prune=true`；首次 `git pull --ff-only` 返回 `Already up to date`，`git status` 为零项，`git fsck --no-dangling` 通过，且只获取目标分支。
- 未 reset/clean/移动/删除旧目录，未触碰 Jetson main/stable/vision/Isaac ROS 工作区，未启动或停止 ROS/Nav2/Docker/运动链。最终复核时仅剩既有 ROS 2 daemon，Docker 为空；较早看到的静态 TF/机械臂进程已由外部运行态自行结束，本轮未对其发送信号。

## 2026-08-09 — cuVSLAM 30 FPS 与 RTAB-Map 后端边界复核

- 项目所用 Isaac ROS Visual SLAM `release-2.1` 官方 RealSense 示例把 D455 IR 配置为 `640x360x90`；但 NVIDIA 文档的原话是提高相机采集帧率可获得更好的 tracking，并未把 90 FPS 定义为后端正确工作的硬门槛。当前 `release-4.5` 官方 RealSense 示例已改为 `640x360x60`，进一步说明 90 FPS 是版本/示例工作点，不是跨版本不变量。
- 现有 Phase 40/42 实测只能证明 30 FPS 下 cuVSLAM 前端 tracking 可工作，而当前全局后端结果比 pure VO 差；不能证明 30 FPS 是唯一根因。尤其 Phase 42 的直接失败机制是没有形成“路线早期段到最终回访段”的长程回环边，优化器只能在错误或不完整约束上工作。
- `cuVSLAM VO + RTAB-Map` 不是保留 cuVSLAM 紧耦合后端的等价替换，而是有意构成松耦合级联：cuVSLAM 提供局部 `odom -> base_link`，RTAB-Map重新消费 stereo 图像做地点识别、回环约束和位姿图，并独占 `map -> odom`。cuVSLAM 内部特征、IMU 状态、协方差与因子不能通过公开 ROS 接口完整交给 RTAB-Map，因此无法最大化 cuVSLAM 原生紧耦合优势。
- RTAB-Map 不能先验保证更优，只能作为可证伪候选。正确门禁是保留现有 cuVSLAM 为基线，在 RTAB-Map 不接管 Nav2、不发布权威 `map -> odom` 的 shadow/offline 模式下，用相同输入和路线做 A/B；只有独立真值误差、长程回环真阳性、轨迹跳变、资源占用和重复性同时过门槛，才允许接管。
- 若 RTAB-Map 更差，直接判 No-Go 并移除候选链路，不影响现有生产配置。若必须保留 cuVSLAM 原生紧耦合，工程上只能为其提供更接近官方工作点的输入/算力（降低其他负载、拆分计算平台或升级硬件），不能通过外接 ROS 后端同时保留其内部紧耦合信息。

## 2026-08-09 — Phase 47 航点与前后端边界初判

- Phase 42 同路线实测的视觉 tracking 闭环为 `0.524702m/3.259704deg`，同窗后端 GetAllPoses 闭环为 `9.753458m/159.003463deg`；本轮关闭后端优化、保留前端链路具有直接现场证据依据。
- 提交 `33bf86b` 新增的 `configs/navigation/waypoints_reordered_preview.yaml` 明确标记为 preview，未同步 Jetson、不可直接用于真机。
- 提交 `8846a45` 记录了之后的实车交错航点版本：通过避免两个 middle 位姿直接相邻，消除了同点 180 度连续转向；当时 `obstacle_cross_target` 与 `pos1_left_clear` 成功，`pos1_middle` 仍曾因约 `0.270m/0.450rad` 误差超时。因此必须核对当前 HEAD 后续是否已经把最终调整落入生产航点，再启动完整路线。
- Git/PWF 交叉核对后，用户所述“调整航点位置后”的生产路线对应当前 `nav-only-full` 所继承的 2026-07-27 `base_link` 中心/接近点修订：`obstacle_cross_target=(1.05,0.75,pi)`、右侧观察点 `x=2.60m`，抓取/放置使用可达接近点。preview 只改变观察顺序，不是生产坐标来源。
- `scripts/start_competition.sh` 已固定关闭 cuVSLAM 的两条 TF 输出，并通过 tracking odometry UDP + Host `final_bridge.py --camera-world-rebase base_start --planarize-output` 构建前端定位链；本轮还必须额外显式设置 `CUVSLAM_ENABLE_LOCALIZATION_N_MAPPING=false`，否则启动器默认仍启用内部后端。
- 新 deploy clone 最初无 install 产物；限定构建后 route 描述和 11 项相关测试通过。生产路线当前为 9 个逻辑步骤，其中第 2 步将 Nav2 approach 与 yaw-only 接管合并，不能按旧“11 个普通 NavigateToPose 航点”解释。
- 运行前 GPU 原为动态频率；root SSH 成功执行 `jetson_clocks` 后，CPU/GPU/EMC 均锁到当前电源模式上限，消除了本轮算力频率这一变量。
- 运行生成文件提供了纯前端的直接证据：`enable_localization_n_mapping=False` 且两条 cuVSLAM TF 输出为 false；视觉 SLAM diagnostics/visualization 也关闭。仍需单独评估默认 landmarks/observations 输出与当前 frame-delta warning 的关系。

## 2026-08-09 — Phase 47 前端-only 真机路线结论

- 关闭后端没有让当前生产 `nav-only-full` 跑过既有转身瓶颈：第 1 段长直线稳定成功，第 2 段 approach 与接管协议全部正确，但 yaw-only 转身期间纯前端 TF 仍报告 `0.3093m` XY 位移，略超严格 `0.300m` 安全半径。
- 这次不能归因于后端 PGO：实际 launch 已确认 `enable_localization_n_mapping=False`，`map->odom`/`odom->base` cuVSLAM TF 也关闭；Nav2 使用 tracking odometry 经 `final_bridge` 的前端链。
- 接管安全逻辑没有误发平移：yaw-only 的 `linear_x_nonzero_count=0`、`linear_y_nonzero_count=0`；失败来自机器狗转身真实漂移与/或纯前端转动估计漂移的合成，现有证据不能仅凭 TF 将两者分离。
- 不应直接把安全半径从 `0.300m` 放宽到高于 `0.309m` 来追求跑完，因为这会掩盖走廊内真实 footprint 风险。更可证伪的下一次选择是现场复位后，明确重跑生产接管路线，或按用户指代改跑 2026-08-06 的 `full_interleaved` 受控 preview（它用空间顺序分隔相反 yaw，但其 `pos1_middle` 旧坐标曾以 `0.270m/0.450rad` 误差超时）。

## 2026-08-09 — Phase 47 第二次路线身份确认

- 用户实际指代的是 `waypoints_reordered_preview.yaml/routes/full_interleaved`，而不是当前生产内置 `nav-only-full`。完整顺序为 `obstacle_cross_target -> pos1_left_clear -> pos1_middle -> pos2a_upper_right -> pos1_middle_turned -> pos2b_lower_right -> grab_area_approach -> placement_A/B/C/D_approach`。
- 该路线通过在两个相反 yaw 的 middle 位姿之间插入上侧观察点来消除相邻同点 180 度转身，但不会自动修复 `pos1_middle` 自身的旧 PGM 坐标收敛风险；仍必须保留 `--stop-on-failure`。

## 2026-08-09 — `full_interleaved` 第二次真机证据

- 用户指定的交错顺序已被准确执行，但路线仍在交错发生前的第 3 点 `pos1_middle` 阻塞；因此本轮不能评价“先去上侧观察点，再返回反向 middle 点”是否解决后续 180 度转向，因为第 4 点尚未发送。
- 相比 2026-08-06 同入口试跑，`pos1_middle` 终点误差从约 `0.270m/0.450rad` 改善到约 `0.241m/0.322rad`，但仍超过 Nav2 终端容差并在同样 130 秒超时。关闭后端与额外观察负载没有根治该点收敛问题。
- 前两点连续成功再次证明起点、前端 tracking、Nav2、DWB、速度桥和 Lite3 主链可用；当前最小阻塞面是 `pos1_left_clear -> pos1_middle` 的终端目标姿态/坐标与 DWB/Lite3 可达性组合，而不是后端 PGO。
- 下一次不应原样重复完整路线。应先根据本轮稳定终点簇评估把 `pos1_middle` 可达目标调整到约 `(1.26,3.24,yaw≈1.25)`，或把观察任务改为位置容差内到达后单独处理朝向；修改前仍需结合柜体 footprint 净空复核。

## 2026-08-09 — 后端开启的交错路线对照结论

- `CUVSLAM_ENABLE_LOCALIZATION_N_MAPPING=true` 已在实际生成 launch 中验证为 `True`，但 `start_competition.sh` 仍固定关闭 cuVSLAM 的 `map->odom`、`odom->base` TF，并让 Nav2 消费 `/visual_slam/tracking/odometry`。因此该 A/B 只能回答“并行开启后端是否间接影响前端导航”，不能回答“优化轨迹接管 Nav2 后是否更好”。
- 同一路线、同一目标与同一 130 秒超时下，两轮均为前两点成功、第 3 点失败。前端-only 第 3 点终端误差为约 `0.241m/0.322rad`，后端开启为约 `0.233m/0.348rad`；一项略好、一项略差，且均未进入终端容差。
- 现有 A/B 没有证据表明开启 cuVSLAM 后端能解决 `pos1_middle`。三次不同日期/配置的失败终点仍聚集在该目标左下侧并伴随终端 yaw 不收敛，进一步支持优先修正目标坐标/姿态或拆分位置与朝向，而不是继续原样重跑。

## 2026-08-09 — 最近两轮交错路线的 GPU/CPU 配置溯源

- 精确 runtime provenance 推翻了“最近两轮已显式使用 robot + 30 Hz”的假设：`20260809-214628` 前端-only 与 `20260809-220927` 后端-on 均实际使用一键脚本默认的 `bench + planar_60fps + 640x360x60`。
- 两轮的观察输出均已通过环境变量成功关闭；后端-on 的实际生成 launch 为 visualization/landmarks/observations false、localization and mapping true，两条 cuVSLAM TF false。不能把本轮问题归因于这些观察 publisher 未关闭。
- startup topic checks 仍为 true，并在启动阶段产生 CLI 额外负载；后端-on 的 92 条 frame-delta warning 中 80 条发生在路线开始前。路线 190.2 秒内只有 8 条，最大 `50.118ms`，tracking lost 与 DDS/receiver error 均为 0。
- 本轮没有连续 GR3D/CPU/输入速率同步记录，因此既不能证明 GPU 未使用，也不能证明路线失败时 GPU 被 CPU 饿住。能够确认的是配置漂移、启动期输入抖动和监控盲区；不能把 `pos1_middle` 超时直接归因于 CPU/GPU 饥饿。
- 该 backend off/on 还存在时钟策略差异：前端-only 轮锁定 CPU/GPU/EMC 后实跑，backend-on 轮未重新运行 `jetson_clocks`。即使两轮同为 60 Hz，也不能将误差和 frame-delta 差异视为纯后端单变量效应。

## 2026-08-09 — ROS 2 / Nav2 / SLAM 技能生态审计

- skills.sh 总榜没有进入前列的机器人导航或 SLAM 技能；该领域候选总体安装量显著低于通用软件工程技能。`rtab-map` 精确查询没有找到真正针对 RTAB-Map 的技能，结果主要是无关的地图 UI/可视化技能。
- 首选候选 `dbwls99706/ros2-engineering-skills@ros2-engineering-skills`：62 installs、GitHub 145 stars、仓库 2026-08-06 仍有提交；内容明确覆盖 Nav2/SLAM/costmap/行为树、TF、QoS、实时抖动、rosbag2、runtime provenance、系统诊断、部署和安全门禁。Gen Agent Trust Hub/Snyk PASS、Socket WARN；包含 Claude hooks。只读审查显示 hooks 主要做 ROS 文件 lint、危险命令模式拦截和 opt-in session log，Codex 不自动运行 Claude hooks，但安装前仍应单独确认是否接受 hook 文件。
- 次选候选 `arpitg1304/robotics-agent-skills@ros2-development`：348 installs、GitHub 334 stars、三项安全审计 PASS、仓库 2026-07-21 仍活跃；适合 ROS 2 package、QoS、DDS、component、launch、rosbag 和一般部署工程。它对 Nav2/SLAM 只提供通用框架，不包含 cuVSLAM/RTAB-Map 专项诊断，和首选存在明显重叠，不建议同时安装。
- 同源可选 `docker-ros2-development`（98 installs）与 `robot-bringup`（77 installs）对 Jetson 容器、GPU/USB passthrough、DDS、udev、systemd、watchdog 有现实价值；但前者 Snyk WARN、后者 Snyk FAIL，必须先审查完整 skill/脚本，不能直接全局安装。
- 本机已安装 `omer-metin/skills-for-antigravity@ros2-robotics`：244 installs、123 stars、三项安全审计 PASS。实际内容只覆盖通用 node/QoS/TF/launch/lifecycle，缺少 Nav2、SLAM、VIO 和 RTAB-Map；部分断言过度简化，只适合作为普通 ROS 2 编码提示，不应作为本项目后端换型的权威依据。
- `omer-metin/...@sensor-fusion` 与 robot_localization/EKF 方向相关，但只有 31 installs；可在后续明确处理腿部里程计、IMU、视觉 odometry 融合时再单独审计，不是当前 RTAB-Map PoC 的第一优先级。
- `robotics-playground/skills@nav-slam` 内容名称最贴近 Nav2、slam_toolbox、costmap、planner/controller、行为树和狭窄通道调参，但仅 7 installs，GitHub 0 stars；只能当补充材料，不能作为生产决策依据。
- `MIUAV/vibe-coding-ros2@visual-slam/nav2-*` 提供 ORB-SLAM3、VINS-Fusion、视觉里程计和 Nav2 专项条目，但各 5–8 installs、仓库 24 stars；没有 cuVSLAM/RTAB-Map 证据，暂不建议安装。
- `wzyn20051216/ros-robotics-skill@ros-robotics` 为 55 installs、52 stars，且 Gen Agent Trust Hub/Socket FAIL、Snyk WARN；不建议安装。Isaac Sim 官方技能只覆盖仿真侧 bridge/navigation，不解决当前 Jetson 实机 cuVSLAM/RTAB-Map 后端问题。
- 当前最合理的技能策略是二选一安装通用高质量底座：优先 `ros2-engineering-skills`（更贴合当前 Nav2/SLAM/诊断边界，需确认 hooks），或更保守选择 `ros2-development`（审计全 PASS、生态量更高但较泛）；精确的 cuVSLAM 2.1 + D455 30 FPS + RTAB-Map shadow A/B 流程仍需要项目专用 skill，公开生态暂无成熟替代。

## 2026-08-09 — `ros2-engineering-skills` 安装验证

- 已通过 Codex 官方 `skill-installer` 从 `dbwls99706/ros2-engineering-skills` 的 `main` 根目录安装，安装时远端 `main` 为 `2048e1bccf787a79044f140bc6bff4f57ce184f5`；目标为 `C:\Users\111\.codex\skills\ros2-engineering-skills`。
- 安装 manifest 为 `name: ros2-engineering-skills`、`version: 1.3.0`；本地包含 25 份 references、7 个 scripts 和 1 个 `.claude/hooks` 文件。`navigation.md`、`debugging.md`、`realtime.md`、`system-diagnostics.md`、`safety-estop.md` 均存在。
- 手动运行 `skill_validate_hook.py --command 'ros2 topic list'` 只分析命令、不执行命令，返回 `issues_count=0,status=pass`。Claude hooks 在 Codex 中不会自动运行；后续使用该技能时按其 routing 手动读取所需 reference。
- 关键 SHA-256：`SKILL.md=42C1B674...F11CC6A`、`references/navigation.md=B3C40CD2...D3A2A7`、`scripts/skill_validate_hook.py=73C0594D...F442F4`。

## 2026-08-09 — 30 Hz 后端交错路线结论

- `robot + custom + 640x360x30 + backend true` 的实际生成配置已通过 runtime provenance 双重确认；本轮不是再次误用 `bench + 60 Hz`。
- 30 Hz 将路线时间窗内的 cuVSLAM frame-delta 从 60 Hz 后端轮的 `8` 条降为 `0`，且 tracking lost、DDS/receiver error 均为 0；输入连续性问题在本轮已被实证排除。
- 路线时间窗 189 个 tegrastats 样本显示 GR3D P50/P95/max=`4/11/99%`，GPU 确实参与计算但 30 Hz 下多数时间有余量；CPU 六核平均 P95 `70%`、单核最高 `89%`，不存在持续 CPU 满载。低 GPU 利用率是余量而非输入断流，因为同窗 frame-delta 为 0。
- 第 3 点终端误差反而扩大到 `0.331m/0.551rad`，仍在 130 秒取消。结合三轮同一点失败，优先级应从 cuVSLAM CPU/GPU 性能转向 `pos1_middle` 坐标/姿态、goal checker 容差、DWB 末端可达性和柜体 footprint 净空；在不修改目标或控制策略前不应继续原样完整路线重跑。

## 2026-08-10 — `pos1_middle` 末端极限环离线诊断

- 实际 Phase 1 PGM 像素核算显示：当前目标 `(1.50,3.25,1.571)` 的 padded footprint 到最近 occupied cell center 净空约 `0.392m`，大于 `0.30m` inflation radius；目标点本身不是静态足迹碰撞。三次终端位姿净空约 `0.24–0.27m`，处于膨胀带内。
- 30 Hz 后端轮第 3 段的 `cmd_vel.csv` 与 `trace.csv` 对齐后，最后 20 秒 `vx` 响应增益约 `0.969`、方向一致率 `97.9%`；`wz` 响应增益约 `0.993`、方向一致率 `100%`。Lite3/UDP 执行链能准确跟随 DWB 命令，不支持“小速度命令未执行”假设。
- 第 3 段 130 秒内实际走过 `6.978m`，累计顺时针转动 `19.258rad`（`3.07` 圈），离目标最近 `0.1792m`，始终未进入 `0.15m` goal tolerance。最后 20 秒仍走 `1.017m`、顺时针转 `168.5deg`，目标距离在 `0.222–0.390m` 之间循环。
- 直接根因已收敛为 DWB 在 `pos1_middle` 附近形成“前进 + 顺时针最大角速度”的末端极限环；下一次只需录制该段的 global/local plan、DWB evaluation、`/cmd_vel_nav2`、`/cmd_vel`、TF 与 costmap，不应再原样跑完整路线。

## 2026-08-10 — Savitzky-Golay + RPP 控制架构可行性

- Jetson 运行 ROS 2 Foxy，实际安装的 Nav2 为 `0.4.7`。`nav2_regulated_pure_pursuit_controller` 及其插件 `nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController` 已安装，因此 RPP 可通过 controller plugin 配置替换 DWB，不需要先移植控制器。
- 目标机没有 `nav2_smoother` 或 `nav2_constrained_smoother`，Foxy 现有栈不能直接使用新版 Nav2 Smoother Server 的 Savitzky-Golay 流程；若采用 SG，需要自定义 planner wrapper/Path 预处理器，或移植 smoother server。
- SG 本身不感知 costmap，可能把 NavFn 的拐角平滑进柜体或膨胀区。若实现，必须按弧长均匀重采样、保持首尾点/终点 yaw，并对平滑后每个 footprint 做碰撞验证，失败时回退原路径；不能只对 x/y 数组滤波后直接下发。
- Foxy RPP `0.4.7` 的实际源码默认 `desired_linear_vel=0.5`、`rotate_to_heading_angular_vel=1.8`、`regulated_linear_scaling_min_speed=0.25`、`goal_dist_tol=0.25`，均不适合当前 Lite3 的 `0.12m/s`、`0.15rad/s` 限制。尤其 `goal_dist_tol=0.25` 若与现有 `xy_goal_tolerance=0.15` 并存，会在 0.15–0.25m 区间只旋转不平移，导致 goal checker 永远不成功；二者必须一致。
- 当前 local costmap 只有 inflation layer、没有 static/obstacle source。Foxy RPP 的 cost regulation 和 collision projection 读取该 local costmap，且该版本碰撞检查基于机器人中心 cell；在补齐/验证 local costmap 障碍信息及旋转扫掠净空之前，不能把 RPP 自带碰撞预测当作足迹级安全保证。
- 推荐单变量顺序：先保持 NavFn 原始路径，仅做 DWB→RPP A/B；确认末端收敛且路径跟踪稳定后，再评估是否需要 SG。当前 DWB 极限环更直接对应控制器终端行为，SG 是次要路径质量优化，不应与控制器替换捆绑首测。

## 2026-08-10 — `xy_goal_tolerance=0.20m` 实车 A/B 结论

- 在 `robot + custom + 640x360x30 + backend true`、同一无运动恢复 BT、同一前三航点下，两个 live `xy_goal_tolerance` 均为 `0.20m`；三段结果均为 `SUCCEEDED`，第 3 段仅用 `32.824s`，没有重现 130 秒极限环。
- 第 3 段在开始后 `16.983s` 首次进入 `0.198880m`；此时 yaw 误差仍有 `2.571975rad`。进入容差 `0.414s` 后 `vx` 归零并保持为 0，随后 `wz` 最大 `+0.15rad/s`，正方向样本占 `99.8379%`、负方向样本为 0，明确进入最终原地朝向调整。
- 从进入 XY 容差到 action 成功用时 `15.841s`，累计正向调向 `2.260085rad`；最终误差 `0.147335m / 0.281646rad`，同时落在 `0.20m / 0.30rad` 容差内，最小位置误差达到 `0.044169m`。
- 该单变量 A/B 强证实：在本次 `pos1_middle` 条件下，`0.15m` 容差是阻止 stateful goal checker 锁存 XY、进而触发 DWB 极限环的主因；`0.20m` 使控制器按预期切换为零平移终端调向。结论覆盖前三航点，不等同于后续 8 航点已验收。

## 2026-08-10 — `0.20m` 完整 11 航点路线结论

- 同一 `0.20m` 成功版再次使 `obstacle_cross_target`、`pos1_left_clear`、`pos1_middle` 全部成功，随后 `pos2a_upper_right` 也成功；前四点最终 XY 误差分别为 `0.198425/0.185651/0.153572/0.185947m`，均依赖 `0.20m` 容差，第三点未复发极限环。
- 第 5 点 `pos1_middle_turned` 不是初始规划失败：从 `(2.792,4.385,2.872)` 正常运动到 `(2.156,3.877,-2.120)`，共有 `468` 条 cmd_vel、`452` 条非零命令；日志连续出现 `Passing new path to controller`，说明前期规划和控制链均工作。
- 失败发生在周期重规划：NavFn 随后报告 `failed to create plan with tolerance 0.20` 和 `failed to generate a valid path to (1.50, 3.25)`，BT abort 并取消 controller。该失败属于第 4→5 点路径在运行中的全局可规划性问题，不是第 3 点 goal tolerance 极限环，也不是 Lite3/UDP 执行失败。
- 因 `--stop-on-failure`，第 6–11 点没有发送；因此 `0.20m` 是必要且有效的终端容差修复，但当前 `full_interleaved` 仍不能判定全程成功，下一阻塞点已前移到 `pos2a_upper_right -> pos1_middle_turned` 的周期重规划。

## 2026-08-10 — local static layer 后第 4 段提前失败结论

- Phase 56 证明 local `StaticLayer` 确实完成初始化并进入 live plugins，但它本身不足以保证当前 `0.70x0.50m` 矩形足迹不切墙。修复版全路线的前三点成功，第 4 点 `pos1_middle -> pos2a_upper_right` 在运行 `5.55s` 后由 NavFn 周期重规划 abort。
- 失败轨迹从 `(1.453,3.199,1.309)` 到 `(1.755,3.780,0.616)`；`3.681s` 时足迹首次覆盖静态 occupied cell，终点中心净空仅 `0.2331m`，小于 padded footprint 的 `0.27m` 内切半径。随后全局 planner 的当前起点进入不可规划代价区，与 `failed to create plan with tolerance 0.20` 时序一致。
- 根因是 DWB critics 只配置了 `BaseObstacle`。Jetson Foxy 的 `/opt/ros/foxy/share/dwb_critics/default_critics.xml` 明确说明它面向 circular robot；同包已提供 `ObstacleFootprintCritic`，用于在整条候选轨迹上检查真实 footprint，但当前配置未启用。
- 下一修复必须同时处理控制器和路线：在 DWB critics 中加入/替换为 `ObstacleFootprint`，并把 `upper_corner_clear=(2.60,3.25,pi)` 对称用于进入和离开 `pos2a_upper_right`，即 `pos1_middle -> upper_corner_clear -> pos2a_upper_right -> upper_corner_clear -> pos1_middle_turned`。仅保留当前单侧过渡点不能约束第 3→4 段的对角切角。

## 2026-08-10 — Phase 57 实施前契约核对

- `configs/navigation/nav2_params.yaml` 当前 critics 列表和参数命名仍为 `BaseObstacle` / `BaseObstacle.scale: 0.02`；替换时两处必须同步改名，避免 critic 已切换但 scale 留在旧 namespace。
- `upper_corner_clear=(2.60,3.25,pi)` 当前只位于 `pos2a_upper_right` 与 `pos1_middle_turned` 之间；preview、真实模板和 `DEFAULT_INSPECTION_ROUTE` 三个路线来源必须同步插入第二次引用。
- 现有静态扫掠测试已证明 `(2.60,4.50) <-> (2.60,3.25)` 与 `(2.60,3.25) <-> (1.50,3.25)` 两条轴向走廊在全部采样朝向下不压静态 occupied cell，可复用为双向进入/离开回归；需要额外锁定 DWB critic 配置，防止以后退回中心代价检查。
- 修复后聚焦测试 12/12 通过；新的五点上侧子路线四段均在每段 51 个位置、24 个全向姿态采样下无矩形 padded footprint 静态碰撞。该结果为离线 L1 几何回归，不包含 DWB 实际轨迹生成或真机运动。
- Phase 56 失败终点 `(1.755,3.780,0.616)` 已加入碰撞回归并确认会压 occupied cell；`BaseObstacle` 只允许出现在测试的反向断言中，产品配置已无旧 critic/scale namespace。

## 2026-08-10 — Phase 57 软件验证结论

- 最终上侧子路线为 `pos1_middle -> upper_corner_clear -> pos2a_upper_right -> upper_corner_clear -> pos1_middle_turned`；inspection/full 路线分别为 8/13 个 goal，preview、真实模板和默认常量一致。
- 聚焦导航回归 12/12 通过；设置 `PYTHONPATH=src` 并排除既有 `test_lite3_udp_smoke.py` mock 夹具后，扩展回归 102/102 通过。Python 编译、两份 JSON 解析、旧 critic/旧路线扫描和 `git diff --check` 均通过。
- `ros2-engineering-skills` stop validator 返回 `status=pass`、`issues_count=0`；本机未安装 PyYAML，因此通用 Nav2 YAML 扫描被工具跳过，仓库自身的结构契约测试已覆盖本次配置字段。
- 证据等级为 L0/L1：尚未在 Jetson configure-only 验证 `ObstacleFootprintCritic` 实际 pluginlib 加载（L2），也未执行真机路线（L6）。机器狗停在 Phase 56 失败点附近，必须先人工回官方起点，再做最小门禁和 13 点 `--stop-on-failure` 实跑。

## 2026-08-10 — Phase 58 `ObstacleFootprint` 13 航点 L6 尝试

- runtime provenance 完整通过：Foxy controller live critics 含 `ObstacleFootprint`，plugin log 明确为 `dwb_critics::ObstacleFootprintCritic`，scale=`0.02`；local costmap 为 `static_layer + inflation_layer`，两处 XY tolerance=`0.2`，backend=`True`，路线描述为 13 点。
- Segment 1 `obstacle_cross_target` 与 Segment 2 `pos1_left_clear` 均成功；Segment 3 `pos1_middle` 运行 130 秒后由 probe 取消，`--stop-on-failure` 阻止第 4–13 点，因此本轮没有到达新增的第一次 `upper_corner_clear`，不能评价墙角修复的 L6 效果。
- Segment 3 从 `(0.576,2.708,1.420)` 开始，取消后 pose 约 `(1.092,3.191,1.170)`，相对目标最终误差约 `0.412m/0.401rad`。轨迹 129.816 秒内走 `7.647m`、累计绝对转向 `19.042rad`，最近只到 `0.216836m`，始终未进入 `0.20m` XY 容差。
- 最后 20 秒仍走 `1.046m`、转 `2.860rad`，距离在 `0.225–0.398m` 间变化；命令均为前进加顺时针转向，最后 20 秒 `vx` 均值约 `0.013m/s`、`wz` 均值约 `-0.141rad/s`。这是 `pos1_middle` 末端极限环再次出现，不是 NavFn 墙角重规划失败。
- 路线窗口 187 个 tegrastats 样本：GR3D P50/P95/max=`3/8/99%`，六核平均 P50/P95/max=`42.2/58.7/74.3%`，单核 max=`80%`；cuVSLAM frame-delta 仅 1 条、tracking lost=0、路线期 Motion Module failure=0。失败不支持算力饱和或 VIO 丢跟踪解释。
- 运行目录：`/home/superwfx666/competition_logs/nav2_waypoint_sequence/20260810_022746_phase58_footprint_full13/`；`summary.json` SHA-256=`e167ff9a...15a5d`，全文件 manifest SHA-256=`5159caab...6fb3c`。
- 清理后 Nav2/bridge/probe/cuVSLAM/RealSense 相关进程与 Docker 均为空，deploy 三文件恢复原哈希且 Git clean，锁频/风扇状态与运行前一致；机器狗停在约 `(1.092,3.191,1.170)`。

## 2026-08-10 — Phase 59 同配置快速复跑结果

- 未改参数、未重复测试或做详细诊断，直接复用 Phase 58 的 `ObstacleFootprint + 双向 upper_corner_clear + 0.20m` 完整 13 点配置。
- Segment 1 `obstacle_cross_target`、Segment 2 `pos1_left_clear` 成功；Segment 3 `pos1_middle` 再次运行 130 秒后超时取消，结束 pose 约 `(1.193,3.070,1.497)`，`--stop-on-failure` 阻止第 4–13 点。
- 运行目录：`/home/superwfx666/competition_logs/nav2_waypoint_sequence/20260810_024724_phase59_fast_full13/`。本轮按用户要求只确认执行结果，不进行新的根因分析。
- 全栈和 cuVSLAM Docker 已停止，相关进程/Docker 为空；远端三份部署文件恢复原哈希且 Git clean，临时备份目录已删除。

## 2026-08-10 — Phase 60 终点阶段停止重规划修复

- Foxy 0.4.7 的 stock BT 没有“剩余目标距离”condition；`DistanceController` 仅按累计行驶距离触发，不能严格保证终点邻域停止路径更新。为避免新增 C++ BT plugin，采用 action 层两阶段切换。
- 远端阶段继续使用既有 1Hz 无恢复 BT；新鲜 `map -> base_link` TF 进入 `0.35m` 半径后取消该 goal，确认 `/cmd_vel` 连续 `0.20s` 为零，再以相同目标和单次规划 BT 重发。这个一次性重置发生在终点阶段入口，之后不会再清空 goal checker 或 `RotateToGoal` 状态。
- 终点 BT 是 `SequenceStar(ComputePathToPose, FollowPath)`，不包含周期 decorator 或运动恢复；终点阶段失去周期重规划能力是有意的局部 trade-off，范围仅为最后 `0.35m` 的静态场地收敛。
- L0/L1 验证完成：聚焦 16/16、扩展 106/106、Python/XML/diff 检查和 ROS 技能 validator 全通过。尚未完成 Foxy BT XML 运行时加载（L2）或真机终点切换（L6）。

## 2026-08-10 — Phase 61 终点无重规划切换 L6 结论

- Phase 60 的两阶段终点切换已在真机连续 7 个不同航点完成：每段都在距目标约 `0.32–0.35m` 时取消周期重规划 action、确认 `/cmd_vel` 零速，再由 `navigate_terminal_no_replanning.xml` 重发同一目标并最终 `SUCCEEDED`。这把“终点阶段停止 1Hz 重规划”从 L0/L1 提升为 L6 实证。
- 过去反复失败的 `pos1_middle` 本轮仅约 `23.6s` 成功，结束 pose 约 `(1.531,3.252,1.280)`；随后上侧双向过渡及 `pos1_middle_turned` 也全部成功，说明终点状态保留方案有效且没有破坏 `ObstacleFootprint + upper_corner_clear` 路线。
- 全路线的新阻塞点是第 8 段 `pos1_middle_turned -> pos2b_lower_right`：action 在约 `9.60s`、距目标仍约 `1.25m` 时 `ABORTED`，终点 handover 的 `triggered=false`。因此本次失败不能归因于无重规划终点 BT；后续诊断应聚焦第 8 段的周期 NavFn/DWB 路径与静态足迹几何。
- 第 9–13 点未发送，完整 13 点路线仍未验收。机器狗最终停止位姿约 `(1.772,2.934,-0.624)`；远端已恢复干净部署并安全停栈。

## 2026-08-10 — Phase 61 `pos2b_lower_right` ABORTED 的证据边界

- 直接触发是 stock `navigate_w_replanning_time.xml` 的 1Hz 周期阶段：controller 收到第 8 段 goal 后约 `9.16s`，最后一个 TF 样本和 action `ABORTED` 分别落在下一次 `RateController` tick 的前后约 `0.18s`。终点无重规划 handover 尚未触发，不能把这次失败归因于 Phase 60 修复。
- 现有反证排除了三种常见解释：TF 保持新鲜；SimpleProgressChecker 的 `0.10m/15s` 未超限且实际移动 `0.445m`；实际 47 个采样姿态的 padded rectangle 均未压同一 Phase 1 静态占用栅格，最小中心净空约 `0.451m`。
- 仅用静态 PGM 将 occupied+unknown 作为障碍并按 `0.27m` 膨胀时，失败姿态和目标仍连通；因此没有证据支持“机器人已进入静态不可规划区”的旧 Phase 56 根因复发。
- 高置信但非原始错误文本级结论：此次 abort 由周期重规划路径在运行时失败触发，或在同一 tick 内 FollowPath 失败。原始 Nav2 报错无法恢复，因为 `bt_navigator`/`controller_server` 日志在事件前截断且 `planner_server` 文件为空；下一次定因记录必须单独保存这三节点 stdout/stderr、`/plan`、global/local costmap 和 DWB evaluation。

## 2026-08-10 — Phase 62 DWB 候选集耗尽的 L6 证据

- Phase 62 保存的 `nav2_stdout.log` 消除了 Phase 61 的日志缺口：第 8 段 Planner 没有失败，Controller 每秒均收到并接受新 `/plan`，最后一次为 `1786342641.675`；随后 `1786342641.898` DWB 明确报 `No valid trajectories out of 335!`，FollowPath 和 BT 才依次 abort。直接故障层是 DWB Controller，不是 NavFn/Planner、BT handover、TF 或 goal timeout。
- `plan.yaml` 有 128 个路径消息，失败前最后一条从约 `(1.825,2.950)` 连至 `(2.6,2.0)`，初始切线约 `-0.31rad`。第 8 段实际命令始终为 `vx>=0,wz>0`，排除指令符号往返导致的典型 Oscillation 解释。
- 同一 PGM 的切线足迹扫掠显示最后一份全局中心线无碰撞；一份前序重规划路径有 4 个黑栅格碰撞点，但其后的 replan 已改道。因此“全局路径持续要求矩形足迹切墙”不是充分解释；真正让 335 条 DWB rollout 同时无效的 critic 仍不可见。
- 下一次最小、可证伪实验是从当前/安全接管位置只复现第 8 段，临时启用 `FollowPath.debug_trajectory_details=true` 并保存 DWB evaluation、local costmap 与 footprint；不要再次整条 13 点路线来猜 critic。

## 2026-08-10 — Phase 63 `ObstacleFootprint` 原始错误定因

- 在真实机器狗被人工摆到 Phase 62 abort pose `(1.822,2.932,-0.605)` 后，以同一 static map、`ObstacleFootprint`、1Hz replan BT 和目标 `(2.60,2.00,pi)` 冷启动。map TF 在 action 前后均准确为该 pose，DWB debug 参数 live 为 `true`。
- action 被接受但在约 `0.75s` 内 abort，81 条 `/cmd_vel` 全为零，物理机器人未移动。Controller 的原始决策日志为：`No valid trajectories out of 335!`，随后是 `1.00: ObstacleFootprint/Trajectory Hits Obstacle.`。这是 DWB 给出的首个失败 critic，直接排除 Planner/BT/终点切换作为此次 abort 的触发层。
- 同时录到 1 条 `/evaluation`、1 条 `/plan`、180 条 local raw costmap、538 条 local published footprint、71 条 global raw costmap 与 109 条 global footprint；可追溯目录为 `/home/superwfx666/competition_logs/nav2_waypoint_sequence/20260810_143810_phase63_segment8_dwb_critic_debug/`。
- 边界：此结果表明 Phase 62 的停止位姿在当前 local costmap 中已不可作为可行起点；它没有复现机器人如何从先前安全状态进入该碰撞态。修复方向应约束第 8 段的全程矩形净空或在首个 footprint 碰撞前触发安全接管，而不是继续调 BT 终点重规划。

## 2026-08-10 — Phase 64 下侧过渡路线结论

- `lower_corner_clear` 采用 `(2.60,3.25,pi)`：它与 `upper_corner_clear` 共用当前 preview 几何坐标，但保留独立名称和标定项，以便实场测量后分别调整上下路线。
- 第 8 段由 `pos1_middle_turned -> pos2b_lower_right` 对角线改为 `pos1_middle_turned -> lower_corner_clear -> pos2b_lower_right`，先沿 `y=3.25` 横向退出中央观察位，再沿 `x=2.60` 进入下侧观察位，避免控制器对角切入下侧柜体墙角。
- 按 `0.70x0.50m` footprint 加 `0.02m` padding 对两段轴向走廊做全向静态扫掠，未命中 Phase 1 PGM occupied cell；这是 L0/L1 静态几何证据，不代表 Foxy DWB 真机 rollout 已通过。
- 下一次物理验证应只部署路线相关最小文件，从第 8 段之前的安全状态执行 `lower_corner_clear -> pos2b_lower_right`，保留 `ObstacleFootprint` 和 `--stop-on-failure`；单段通过后再运行完整 14 点路线。

## 2026-08-10 — Phase 65 实场边界

- 新增 `lower_corner_clear` 没有在本轮到达：完整 14 点路线在第 3 点 `pos1_middle` 超时停止，说明下侧墙角修复尚未获得 L6 证据。
- 前两点仍成功，证明本轮启动链、初始位姿、bridge 和前段路线可运行；第 3 点再次表现为终端收敛失败，不能把失败归因于 `lower_corner_clear`。
- 后续应从 `pos1_middle` 的终端极限环单独处理或采用已验证的 `0.20m` goal tolerance/终点切换配置，然后再验证第 8、9 点；不要把本轮结果当成下侧过渡航点失败。

## 2026-08-10 — Phase 66 重跑边界

- 即使复用已验证的 `0.20m` 容差和终点 handover，本轮第 3 点仍在约 60 秒时 `ABORTED`，结束位姿距目标约 `0.363m`，且 terminal handover 已经进入但未成功收敛。
- 前两点成功，说明本轮不是启动、TF 初始连接、Lite3 UDP 或路线文件部署失败；新增 `lower_corner_clear` 仍未被执行。
- 后续应单独围绕 `pos1_middle` 的终点 BT/DWB 行为采集最小证据或调整终点切换半径/目标策略，不能通过重复完整路线直接验证第 8 段。

## 2026-08-10 — Phase 67 配置一致性结论

- Phase 67 与 Phase 61/62 的导航控制组合一致：路径远距离阶段使用 Foxy stock `navigate_w_replanning_time.xml`，距目标 `0.35m` 后取消周期 action、确认零速、再以 `navigate_terminal_no_replanning.xml` 单次规划完成终点。
- 当前复跑未能复现 Phase 61/62 的前七点连续成功，而是在第 3 点已 ABORTED；由于第 3 点早于新增 `lower_corner_clear`，该差异不能解释本轮失败。
- 结论边界：配置一致性已由临时部署文件、启动 flags、lifecycle 日志和本轮 summary 的行为树/handover 字段交叉确认；一次 ROS CLI 运行态参数查询因 Foxy 环境脚本与 CLI 超时未完成，但未改变运行或结论。

## 2026-08-10 — Phase 69 `pos1_middle` 历史成功与近期失败根因

- Phase 68 的首个控制错误为 Controller 原始日志 `No valid trajectories out of 335!`，随后才是 FollowPath 与 NavigateToPose abort；不是 TF stale、goal timeout、progress checker、Planner、bridge UDP 或多 `/cmd_vel` publisher。
- 六次运行都在约 `0.33–0.35m` 完成 handover。Phase 61/62 在 handover 后分别进入最小 `0.025m/0.019m`，并很快跨过 `xy_goal_tolerance=0.20m`；Phase 65–68 的最小距离仅为 `0.228/0.227/0.219/0.207m`，全部停在阈值外。成功组跨阈值后命令立即变为 `vx=0,wz=+0.15`；失败组始终保持顺时针 `wz=-0.15` 并间歇前进，累计绕行约 `5–8m`。
- Jetson 安装包为 Foxy Nav2 `0.4.7`。上游同版本源码确认：`DWBLocalPlanner::setPlan()` 会 reset 全部 critics；`RotateToGoalCritic` 只有在当前位置进入自身 XY tolerance 后才锁存 `in_window_`，停车后锁存 `rotating_` 并拒绝所有非零平移轨迹。终点 handover 在 `0.35m` 重发新 plan，因此 critic 从阈值外重新开始；能否再次跨进 `0.20m` 是确定性分岔点。`SimpleGoalChecker` 的 stateful XY 检查是另一套状态，语义与实测一致。
- 失败不是由第 2 段末态单独造成。Phase 66 第 3 段起点与成功的 Phase 62 仅约 `1.4cm/0.027rad` 差异，仍然失败。偏差在第 3 段继续累积：失败组 handover 位姿普遍比成功组更靠目标上方约 `2–9cm`；Phase 68 与 Phase 61 的 trigger 仅差约 `2.4cm` Y，却使最近距离从 `0.177m` 变成 `0.207m`，刚好落在阈值两侧。
- 命令积分与 TF 对照表明运行间存在可观的运动/观测差异。Phase 66–68 在 handover 后 4 秒的 TF 位姿相对理想 `/cmd_vel` 单轮模型约多出 `+0.08–0.10m` Y，实际 yaw 比命令积分少转约 `0.16rad`；但现有产物不能区分真实狗体步态/地面滑移与 cuVSLAM 短时估计偏差，各自贡献不可定论。cuVSLAM 无 tracking lost、TF 新鲜，只能排除明显失锁，不能排除厘米级漂移。
- 静态地图足迹复算解释了最终 abort：Phase 66/67/68 终止足迹边界距下侧 occupied cell 仅约 `3.8/0.5/0.4mm`，且 footprint 内分别已有 `4/7/75` 个 occupied cell；Phase 68 命中约 `(1.312,2.488)` 的横向静态墙。Phase 65 最终仍有约 `0.240m` 净空，所以表现为 130 秒 timeout 而非立即 DWB abort。Phase 68 未开启 critic 明细，故其 335 条候选由 `ObstacleFootprint` 清空属于高置信几何归因，不冒充原始 critic 文本级证明。
- runtime provenance 未发现能解释成败的软件差异：Phase 61/62 与回退后的 Phase 68 使用相同 13 点路线、两个 BT、两处 `0.20m` tolerance、足迹/costmap/critic/速度限制和同一 `robot + custom + 640x360x30 + backend + base_start + cmd_vel_bridge` 启动链；三份启动日志的 Lite3 prepare 均为 `simple=50 complex=48 errors=0`，动作前零速且 `udp_errors=0`。近期失败应归因于现有终点策略对厘米级运行差异缺乏裕量，而不是配置未加载。
- 最小下一次验证不应再跑完整 13/14 点：机器狗人工回官方起点后只跑前 3 点，同时记录 DWB `/evaluation`、local raw costmap/published footprint、`/plan`、cuVSLAM TF/odom、Lite3 IMU/机体反馈和 bridge 实际下发命令。若直接修复，优先评估把两处 XY tolerance 从 `0.20m` 小幅提高到至少覆盖已观测 `0.228m` 的值（例如 `0.23–0.25m`）；代价是观察点位置允许误差增加 `3–5cm`，应先用单段 L6 验证而非继续盲目复跑。

## 2026-08-10 — Phase 70 修改前现状

- 当前分支 `Stonefield/nav2-foxy-dwb-integration` 位于回退提交 `4c65807`，工作树干净；当前 preview/full 路线为 13 点且不含 `lower_corner_clear`。
- `configs/navigation/nav2_params.yaml` 中 `SimpleGoalChecker.xy_goal_tolerance` 与 `FollowPath.xy_goal_tolerance` 均为 `0.20`；本阶段只把这两个终点位置容差改为 `0.30`，不修改 planner tolerance、TF timeout、加速度或其他同值参数。
- preview 中已有 `upper_corner_clear=(2.60,3.25,pi)`；新增下侧航点保持同坐标但使用独立名称和标定项，以便真实场地后续分别调整。
- ByteRover 长期记忆当前不可查询：仓库无 `.brv` 且本机无 `brv` CLI；本阶段使用 PWF 中已有的 Phase 64/69 结论作为历史依据。

## 2026-08-10 — Phase 70 实施结论

- `SimpleGoalChecker.xy_goal_tolerance` 与 `FollowPath.xy_goal_tolerance` 已同步从 `0.20m` 提高到 `0.30m`；NavFn planner 的 `tolerance: 0.20` 和其他同值超时/控制参数未改。
- `lower_corner_clear=(2.60,3.25,pi)` 已作为独立 transit 航点加入 preview；真实模板路线和 `DEFAULT_CALIBRATION_ORDER` 会要求单独采集该名称。它与 `upper_corner_clear` 当前 preview 坐标相同，但标定数据和后续调整互不绑定。
- inspection 路线为 9 点，full 路线为 14 点；下侧顺序固定为 `pos1_middle_turned -> lower_corner_clear -> pos2b_lower_right`。
- 标准静态回归覆盖上侧四段和下侧两段，每段 51 个位置、24 个全向姿态，共 7344 个样本，Phase 1 PGM occupied-cell 碰撞为 0。额外下侧两段高密度预检每段 101 个位置、48 个姿态，共 9696 个样本，碰撞为 0。
- 聚焦回归 11/11、排除既有 `test_lite3_udp_smoke.py` mock 夹具的扩展回归 106/106 通过；两份 JSON 解析、相关 Python 编译、9/14 点路线解析、`git diff --check` 均通过。ROS 技能 stop validator 返回 `status=pass`、0 issues；因当前 Python 无 PyYAML，可选 `nav2_yaml` 子检查被明确跳过，路线 JSON 和 Python 契约已独立覆盖。
- 证据等级仅为 L0/L1；未连接 Jetson、未启动 ROS/Nav2、未发送运动命令。下一步仍应在安全起点和现场监护下先做第 8 段单段 L6，再决定是否运行完整 14 点路线。

## 2026-08-10 — Phase 71 L6 结论

- 独立 `lower_corner_clear` 的设计已获得直接实场支持：`pos1_middle_turned -> lower_corner_clear -> pos2b_lower_right` 两段在同一次完整栈运行中连续 `SUCCEEDED`。这将 Phase 64/70 的静态净空证据提升为该下侧路线的 L6 行为证据，但不证明所有起始偏差、动态障碍或地图漂移条件下都可通过。
- 本轮前 12 点均成功，包含此前反复失败的 `pos1_middle`、上侧双向过渡和下侧新过渡。`0.30m` goal tolerance 与终点 handover 在这些 segment 中均正常工作；单次运行不能把成功完全归因于容差修改，但至少未观察到该修改破坏既有路线。
- 第 13 点失败层明确是 Planner：1Hz 周期重规划时 NavFn/GridBased 无法在 planner `tolerance=0.20m` 下生成到 `(4.25,4.95)` 的路径。这里的 `0.20m` 是 Planner tolerance，与本轮提高到 `0.30m` 的两处 goal/controller XY tolerance 是不同参数，不能用后者解释或修复该错误。
- Segment 13 失败时终点 handover 未触发，Controller 仍在跟随此前路径；Planner action abort 使 BT 取消 FollowPath。后续应优先只读核对失败时 global costmap、目标栅格与膨胀后连通性，并从 `placement_B_approach` 附近做 Segment 13 最小 L6 复现；不应先重复整条 14 点路线。
- 停止链证据为：BT abort 后 Controller 明确记录 `Stopping the robot`，bridge 连续约 `59.48s` 以 `udp_errors=0` 下发零命令，最后约 60 秒 VIO XY 变化小于 `4mm`，随后全栈和容器为空。该证据支持本次运行已停稳，但软件/里程计证据不能替代现场人员对实体姿态和急停链的确认。
- Jetson 已精确恢复到部署前 dirty 基线：11 点路线、两处 `xy_goal_tolerance=0.15`、无终点 XML，Git 状态与备份一致。`colcon --symlink-install` 不会自动删除从 package data 移除的旧符号链接，临时部署回滚时必须同时检查 source/build/install 三层。

## 2026-08-11 — Phase 72 文档基线

- 目标文档当前为 0 字节，所在目录包含 `.obsidian`；应使用 frontmatter、Obsidian callout 和同页标题链接组织流程。
- 手册必须先做版本门禁。Phase 71 结束后 Jetson 已恢复到 11 点/`0.15m` 基线；如果不先同步 Phase 70 的六个运行文件并重建，直接启动不会得到 14 点/`0.30m` 行为。
- 可复用的六个运行文件为 `nav2_params.yaml`、`waypoints_reordered_preview.yaml`、`navigate_terminal_no_replanning.xml`、`nav2_waypoint_sequence_probe.py`、`waypoint_calibration.py` 和 `setup.py`。`waypoints_real.yaml` 尚属于标定路径，不是 Phase 71 preview L6 实跑的输入。
- Phase 71 的路线入口应使用 `--waypoint-file configs/navigation/waypoints_reordered_preview.yaml --waypoint-route full_interleaved --allow-preview-route`，并显式保留 `--goal-timeout 130 --map-tf-timeout 30 --inter-goal-pause 2 --stop-on-failure`、1Hz 周期重规划 BT、`0.35m` 终点无重规划 handover。
- 安全叙述必须区分“流程可完整发起”和“路线已经全通”。当前 L6 证据是前 12 点成功、第 13 点 GridBased Planner abort、第 14 点未发送；文档标题不能被解释为成功保证。

## 2026-08-11 — Phase 72 文档交付结论

- 当前可重复手动流程必须先用行为门禁核验 Jetson，而不能依赖分支名或 `git status`：远端已恢复过旧 11 点/`0.15m` 基线，只有 14 点精确顺序、两处 `0.30m`、独立终点 BT 及安装态一致同时通过后才允许发目标。
- 运行 shell 必须在 source Foxy、Nav2 overlay 和项目环境后重新设置 `PYTHONPATH="$PWD/src:${PYTHONPATH:-}"` 与 `FASTRTPS_DEFAULT_PROFILES_FILE`；`start_competition.sh` 在子 shell 中 source 的环境不会回传到调用终端。
- 路线使用显式 `--output-dir`、前台 probe、`set -o pipefail` 和 `${PIPESTATUS[0]}` 保存真实退出码；成功仍需以 `summary.ok=true`、14 个 segment 全成功、实体停稳和 bridge 末端零速/0 UDP error 联合判定。
- 部署前备份与运行后证据 manifest 都必须排除正在写入的哈希文件本身，否则得到的自引用哈希不可复现。
- 目标 Obsidian vault 的 `学习/` 由所属 Git 仓库 `.git/info/exclude` 本地排除，文档不会被 Git 跟踪；这不影响本地使用，但跨设备同步不能依赖该仓库提交。

## 2026-08-11 — Phase 73 比赛规则与场地事实

- 规则 PDF 第 6–7 页给出的场地总尺寸为 `5000mm × 6000mm`；底部障碍区域在区域划分图中约为 `4000mm × 1500mm`，右侧紧邻出发区域。该障碍区是进入后续巡检/抓取区域的唯一第一阶段通道。
- 障碍区域随机放置 2 个锥形桶，规则标注尺寸为 `67 × 32 × 32cm`；机器人必须全程自主避开并通过，不要求报告锥桶类别、数量或坐标。
- 避障任务本身为 10 分；碰到障碍物或比赛道具每次扣 5 分、最多扣 30 分，连续失控冲撞直接结束比赛。因此第一阶段的优化目标应按“零碰撞和可控停车优先，耗时/最短路径其次”排序。
- 规则明确禁用激光雷达；现有 D455 深度相机是动态障碍几何感知的合规主传感器。锥桶语义识别不是规则要求，不应成为安全避障的前置门禁。
- 以上事实来自仓库内《2026年中国高校智能机器人创意大赛（四足大型组）》PDF 的文本提取与第 6、7、10 页视觉复核；PDF 共 12 页，根目录与 `navi/` 副本 SHA256 相同。

## 2026-08-11 — Phase 73 现有地图、路线与硬件边界

- 硬件上限与仓库目标一致：Lite 系列四足机器人、Jetson Xavier NX 级主机、单台 D455；Jetson 为 Ubuntu 20.04 / ROS 2 Foxy，Isaac ROS cuVSLAM 在 Humble Docker 内运行。D455 被容器占用时，Host 端不能再通过 `pyrealsense2` 直接打开同一设备。
- 第一阶段静态地图已经采用正确语义：`competition_field_phase1.pgm` 将 `4000mm × 1500mm` 障碍区地面设为 FREE，只把固定柜体/抓取/放置区域作为静态墙；`phase2` 才封闭障碍区。`navi/map/README.md` 中仍称 obstacle 为 occupied 的段落已陈旧，与生成器和 `navi_map_data.py` 的现行实现冲突。
- 官方起点约为 map `(4.65, 0.75, pi)`，现有第一目标 `obstacle_cross_target=(1.05,0.75,pi)` 位于障碍区左侧出口附近；任务可建模为在已知狭长通道内，从固定右端到固定左端，绕开两个随机动态占据物。
- 当前 `nav2_params.yaml` 的 local/global costmap 都只有 `StaticLayer + InflationLayer`，没有 `ObstacleLayer` 或 `VoxelLayer`；注释明确写明 D455 动态障碍插入尚未启用。14 航点 L6 因而只验证了静态地图、定位、规划、DWB 和执行链，不包含锥桶避障能力。
- 当前 DWB 已使用矩形 `ObstacleFootprint` critic，足迹 `0.70m × 0.50m` 加 `0.02m` padding，速度上限 `0.12m/s`、角速度 `0.15rad/s`；一旦锥桶进入 costmap，控制器已有拒绝碰撞轨迹的基础，但 local costmap 只有 `3m × 3m`，对 `4m` 长障碍区的前视和全局绕行仍需 global costmap 动态层配合。
- 现有 `depth_relay_docker.py` 只把 Humble `/camera/depth/image_rect_raw` 写成共享 RAW 和宽高/时间戳；现有 Host `depth_publisher.py` 则直接打开 D455，不读取 relay 文件。文档声称二者已串接，但实现并未完成，必须先补一条不重复占用相机的 Humble→Foxy 深度/CameraInfo/PointCloud2 链路。
- 旧 `local_obstacle.py` 只做前方点数阈值和 STOP/SLOW，不能向 Nav2 提供障碍空间位置；其硬编码 pitch `-0.523599` 也与当前已验证 `base_link -> camera_link` 的 `+0.523599` 不一致。它只能参考性改造成失效安全门，不能作为主绕行模块直接复用。

## 2026-08-11 — Phase 73 官方资料核对

- Nav2 官方配置文档说明 `ObstacleLayer` 可用深度或其他传感器做 2D raycasting，观测源 `data_type` 支持 `LaserScan` 或 `PointCloud2`；`marking` 控制写入障碍，`clearing` 控制射线清除，`obstacle_*_range` 与 `raytrace_*_range` 分别约束标记和清除范围，`observation_persistence`/`expected_update_rate` 管理观测缓存与预期频率。来源：https://docs.nav2.org/configuration/packages/costmap-plugins/obstacle.html
- 与 Jetson 安装版本匹配的 Nav2 `0.4.7` 官方 `nav2_params.yaml` 使用 local `VoxelLayer + InflationLayer`、global `StaticLayer + ObstacleLayer + InflationLayer`；两层的观测源都同时启用 `clearing` 和 `marking`。这证明建议不是新版本专属 API。来源：https://github.com/ros-navigation/navigation2/blob/0.4.7/nav2_bringup/bringup/params/nav2_params.yaml
- NVIDIA Isaac ROS Visual SLAM `release-2.1` 官方 RealSense launch 在同一个 `realsense2_camera_node` 中默认 `enable_infra1/2=true`、`enable_color=false`、`enable_depth=false`、emitter=0、`640x360x90`、gyro/accel=200Hz。深度默认关闭是官方 VSLAM 基线，不代表必须由第二个进程打开相机；本项目应在同一 Docker RealSense 节点中按比赛 profile 开启 depth，再从容器中继。来源：https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam/blob/release-2.1/isaac_ros_visual_slam/launch/isaac_ros_visual_slam_realsense.launch.py
- RealSense 当前官方 D455 页面给出 FOV `87° × 58°`、理想范围 `0.6m–6m`、双目基线 `95mm`，4m 误差小于 2%，并明确面向更长距离碰撞规避。障碍区长度约 4m、宽 1.5m，视场与量程足够覆盖，但近于 0.6m 的区域不应依赖 D455 深度继续闭环前进。来源：https://www.realsenseai.com/products/real-sense-depth-camera-d455f/
- RealSense 官方仓库已从 `IntelRealSense` 迁移到 `realsenseai`，旧链接目前重定向；后续技术文档应更新为新组织 URL。来源：https://github.com/realsenseai/librealsense

## 2026-08-11 — Jetson DWB 双仓库身份结论

- 正式运行仓库的精确路径是 `/home/superwfx666/quadruped-robot-competition-nav2-dwb-deploy`，名称结尾是 `deploy` 而非 `deployed`。它是 2026-08-09 从 GitHub `Stonefield/nav2-foxy-dwb-integration@52d30d6` 建立的独立干净 clone。
- `/home/superwfx666/quadruped-robot-competition-nav2-dwb` 是此前主仓库挂出的历史开发 worktree，`HEAD=72e3833` 且长期保留 237 项现场状态；它只用于历史保全，不应再作为部署、构建或启动目录。
- 关键文件哈希相同不能证明仓库身份正确：当前两个目录的 `nav2_params.yaml`、11 点 route、probe、calibration 和 `setup.py` 哈希一致，是因为实跑后都恢复到了旧基线；两个 `install` 树仍分别链接到各自源码目录。
- Phase 71 的 L6 行为结果本身仍是有效实车观测，但其 runtime provenance 必须更正为“从旧脏 worktree 临时部署并启动”，不能归到 clean deploy clone。后续复现实验必须把 deploy 根路径、ROS package prefix 和进程参数路径同时保存为门禁证据。

## 2026-08-11 — Phase 73 推荐架构与数据契约

- 推荐主链为：Docker 内同一个 RealSense 进程开启 depth → RAM-backed 原子深度中继 → Host Foxy 发布原始时间戳的 `Image + CameraInfo` → 降采样 `PointCloud2` → local `VoxelLayer` + global `ObstacleLayer` → `InflationLayer` → NavFn 1Hz 重规划 + DWB `ObstacleFootprint`。锥桶语义识别不进入安全闭环。
- 中继应传递单一原子记录：magic/version、递增 sequence、源 ROS stamp、monotonic timestamp、width/height/step/encoding/endian、depth scale、fx/fy/cx/cy、frame id 和 payload；Host 只发布新的 sequence，绝不能把旧帧改成当前时间重复发布。共享目录应落在 tmpfs/共享内存，不把高频深度写入持久磁盘。
- `CameraInfo` 使用 depth optical frame；Host 必须获得并发布 `camera_link -> camera_depth_optical_frame` 的正确静态 TF，或在生成点云时显式转换到 `base_link`。不能把遵循光学轴约定的深度数据直接标成 `camera_link`，否则地面和锥桶坐标会错误。
- 建议起始数据率为原生 depth `640x360@30`（若设备 profile 不支持则用实测可用 profile），中继/点云 decimate 2 后约 `320x180@10Hz`；有效距离先限 `0.6–3.5m`。发射器先保持当前已验证的 OFF 状态，若锥桶点云孔洞明显，再做 emitter ON/OFF 与 cuVSLAM tracking/frame-delta 的单变量 A/B。
- Foxy 0.4.7 的观测源参数名是 `obstacle_range` / `raytrace_range`，不是新版本文档中的 `obstacle_max_range` / `raytrace_max_range`。初值建议 local costmap `4.0m x 3.0m @ 0.05m`、8Hz，global costmap 2Hz；点云源 `min_obstacle_height=0.07m`、`max_obstacle_height=0.85m`、`obstacle_range=3.0m`、`raytrace_range=3.5m`、`clearing=true`、`marking=true`、`observation_persistence=0.0`、`expected_update_rate=0.20s`。这些是试验初值，不是未经实测即可比赛的最终值。
- 当前 `0.70m x 0.50m + 0.02m padding` 足迹应先用实物测量包含走动/转身摆腿的最大扫掠包络；障碍区只有约 1.5m 宽，锥桶底座约 0.32m，过度增大 footprint 或 inflation 会让可行通道消失。建议 inflation 从 `0.30–0.35m` A/B，而非直接设很大的“安全距离”。

## 2026-08-11 — Phase 73 速度安全链与验收结论

- Foxy 没有当前 Nav2 Collision Monitor；现有唯一速度链应改成 `Nav2/precision -> cmd_vel_arbiter -> cmd_vel_selected -> depth_safety_gate -> /cmd_vel -> bridge -> Lite3`。安全门是 `/cmd_vel` 的唯一发布者；它崩溃时 bridge 依靠现有 command timeout 停车。
- 安全门必须 fail-closed：深度 sequence 超过约 `0.30s` 未更新、TF 不可用/过期、点云异常或中继退出时持续发零速。起始慢区可取前方 `1.2m`，停车区先取 `0.75–0.85m` 并按实际制动距离校准；对危险 twist 应拒绝整条预测扫掠轨迹，而不是声称“识别到锥桶”后才停车。
- 障碍区使用单个 `obstacle_cross_target` 作为出口目标，让全局动态 costmap 决定随机绕行方向；不要写固定“从左绕/从右绕”的中间点。运行 BT 使用 1Hz 重规划且不包含 Spin/BackUp 恢复；无路、感知过期或门禁触发时停车并 abort，避免因恢复动作碰桶。
- 验收按 L0 synthetic/unit → L1 无电机 RViz 点云 → L2 Nav2 configure-only costmap/plan → L3 断开 UDP 的完整命令链 → L4 单锥低速 → L5 双锥典型/S 形/最窄布局 → L6 官方起点多次随机布局推进。比赛配置至少要求随机双锥零碰撞重复通过、遮挡/断流在门限内归零、点云无持续地面墙、TF/帧年龄可审计后再解锁。
- 备选顺序为 PointCloud2 主方案 > 高度切片生成虚拟 LaserScan > YOLO+深度 ROI。虚拟 LaserScan 计算更轻但丢失高度信息；YOLO 可做赛后语义展示或计数，不能承担唯一避障输入；旧 `local_obstacle.py` 的 STOP/SLOW 逻辑只能作为安全门原型，不能独立完成绕行。

## 2026-08-11 — Phase 75 Lite3 无运动边界

- 正式 deploy 的 ROS provenance、定位、Nav2 lifecycle、路线、参数和单一 `/cmd_vel` 链均通过动作门禁；第 1 点 global/controller action 被正常接受并连续生成合理非零命令，故本轮不能归因于串仓、Planner 无路径或 DWB 候选耗尽。
- SimpleProgressChecker 在约 15 秒后准确检测到无位移并触发 `Failed to make progress`。同期 TF 仅变化约 `0.023mm`，而 Nav2 与 bridge 都记录 599 个非零样本，bridge UDP socket 无错误。这把故障边界收敛到 bridge UDP 发送之后：Lite3 当前 basic/gait/motion 状态、控制权、急停/保护状态或机体对命令的接受情况。
- `prepare_lite3_motion_mode.py` 的 `simple=50 complex=48 errors=0` 只证明 UDP `sendto()` 成功，不证明机器狗已接受 auto/motion 模式或允许行走；ping 和 `udp_errors=0` 同样不是机体执行确认。
- 下一次禁止直接重跑 14 点。应先在不发送非零速度的条件下记录 Lite3 RobotState/basic/gait/motion/错误状态，核对遥控器控制权和急停状态；状态满足后只做有现场监护的最小低速直行脉冲，并同时记录机体反馈、bridge 实发值与 TF，确认执行闭环后才重新进入 Nav2。

## 2026-08-11 — Phase 77 14 航点地图标注结论

- `full_interleaved` 的“14 航点”是 14 个路线目标序号，不是 14 个不同 XY：共有 11 个唯一 XY；第 `3/7` 点共用 `(1.50, 3.25)`，第 `4/6/8` 点共用 `(2.60, 3.25)`。
- 地图元数据为 `resolution=0.025`、`origin=[0,0,0]`。世界坐标换算使用 `px=(x-origin_x)/resolution`、`py=height-1-(y-origin_y)/resolution`，再按 5 倍比例绘制，确保 ROS 地图的左下角原点与图像左上角原点正确翻转。
- 为避免把重复路线步骤误画成不同物理位置，共点编号在锚点周围展开，并用引线指回精确坐标；图例保留每一步的标签、XY、yaw 和 action。

## 2026-08-11 - Phase 80 initial launcher facts

- The requested source manual exists at `C:\Users\111\Desktop\比赛\quadruped-robot-competition\学习\可以成功运行全部航点的启动脚本.md` and is 21,442 bytes.
- The repository already owns the operational primitives `scripts/start_competition.sh`, `scripts/stop_all.sh`, `scripts/prepare_lite3_motion_mode.py`, and `scripts/nav2_waypoint_sequence_probe.py`; the new entrypoint should orchestrate these instead of duplicating their implementations.
- This phase is local implementation/static validation only. It must not SSH to Jetson, start ROS/Nav2, prepare Lite3 motion, or send navigation goals during validation.
- The manual fixes the deploy identity at `/home/superwfx666/quadruped-robot-competition-nav2-dwb-deploy`, branch `Stonefield/nav2-foxy-dwb-integration`, commit `94137ea0bbc10b0e46b684fad5f9c123aced6bfc`, route `waypoints_reordered_preview.yaml/full_interleaved`, and 14 goals.
- The proven startup profile is `base_start`, cuVSLAM `robot/custom/640x360x30`, mapping backend enabled, visualization/diagnostics disabled, followed by `start_competition.sh --dog --cmd-vel-bridge --prepare-lite3-motion`.
- A safe launcher must retain a physical-start confirmation before motion, verify five active Nav2 lifecycle nodes, exactly one `/navigate_to_pose` server, runtime tolerances `0.3/0.3/0.2`, start TF near `(4.65,0.75,pi)`, the single arbiter-to-bridge `/cmd_vel` chain, Lite3 prepare completion, and the exact 14-goal route.
- The route command must remain foregrounded with `--stop-on-failure`, preserve its real pipeline exit code, always stop Nav2/bridge/cuVSLAM, and archive the route summary plus startup/runtime evidence. The launcher is not a guarantee that all 14 points will succeed.
- Per the user's follow-up, the launcher must not request an interactive confirmation phrase; invocation proceeds directly through automated checks into startup and route execution.
- Local execution of the route probe is not a valid Windows static check because the module imports `rclpy` before processing `--describe-route`. Local verification should parse the JSON-compatible route file directly, while Jetson validation can run the real describe-only path after sourcing ROS.
- `start_competition.sh` intentionally avoids `set -e` and treats several startup problems as warnings. The wrapper therefore must independently enforce hardware, lifecycle, action, TF, parameter, process-provenance, command-chain, Lite3 prepare, and route gates after it returns.
- `stop_all.sh` zeros both precision and final velocity topics before force-stopping launch, Nav2, arbiter, bridge, SDK, and bridge processes; it deliberately leaves the cuVSLAM container running. The wrapper must additionally capture and stop that container on every exit.
- Local HEAD is `f63d309e016fcf9bbab9e3bf807097262d10c042`, while the proven Jetson deploy gate remains ancestor `94137ea0bbc10b0e46b684fad5f9c123aced6bfc`. The launcher should validate the remote deploy commit, not require the local visualization commit.
- The commits after `94137ea` only add competition-rule evidence and waypoint-map rendering artifacts; they do not modify the runtime startup, route, parameter, bridge, or stop scripts used by the launcher.
- `waypoints_reordered_preview.yaml` is JSON-compatible. Its `full_interleaved` route is exactly 14 entries with `lower_corner_clear` at position 8 and `placement_C_approach` at position 13, so local tests can validate it with the standard-library `json` parser.
- The real `--describe-route` output uses a top-level `steps` list; each entry contains the resolved goal fields plus a 1-based `index`. Jetson validation can therefore assert all 14 labels from this structured output rather than grepping display text.
- `cmd_vel_bridge` diagnostics expose `udp_errors` and `last_send=(vx,vy,wz)`. Before route submission the wrapper can require the latest diagnostic to contain `udp_errors=0` and `last_send=(0.000,0.000,0.000)`.

## 2026-08-11 - Phase 80 launcher delivery

- Implemented `scripts/run_full_navigation.sh` as an external-home deployable wrapper. Its normal path has no prompt: preflight -> cold stop -> full stack startup -> automated runtime gates -> foreground 14-goal route -> unconditional stop/evidence archive -> summary result.
- Added `tests/test_run_full_navigation_launcher.py`; all 7 focused tests passed. Git for Windows Bash accepted the launcher with `bash -n`; Python compilation, LF-only line endings, and explicit trailing-whitespace checks also passed.
- Uploaded the launcher to `/home/superwfx666/run_full_navigation.sh` and set mode `0755`. Local and remote SHA-256 are both `8d8c8b377c3fbffd2a46d2a13c1866a7449525a8cb1aa5d1e43d4b3b6353332f`.
- Per the user's instruction to wait, the Jetson launcher was not executed at all; `--check-only` was also not executed. Upload verification used only `chmod`, `sha256sum`, and `stat`.

## 2026-08-11 - Phase 82 first launcher-run diagnosis

- Run `20260811_151227_oneclick_full14` stopped before route submission and then successfully stopped Nav2/bridge/cuVSLAM. Lifecycle, action server, runtime tolerances, start TF `(4.64995,0.74987,3.14158)`, Lite3 zero output, and final `/cmd_vel` topology had already passed.
- `/cmd_vel_nav2` legitimately reported four publisher endpoints: one from `controller_server` and three from the single `recoveries_server` node, with exactly one subscription from `cmd_vel_arbiter`. Foxy recovery behaviors create multiple publisher endpoints under the same node.
- The launcher defect is the exact `Publisher count: 1` assertion on the Nav2-side input topic. The correct contract is publisher count >= 1, every publisher identity in `{controller_server, recoveries_server}`, controller present, and exactly one subscriber identity `cmd_vel_arbiter`. Final `/cmd_vel` must remain exactly one arbiter publisher and one bridge subscriber.

## 2026-08-11 - Phase 83 doubled-speed deployment inputs

- The local speed change is limited to three runtime files: `nav2_params.yaml`, `cmd_vel_arbiter.py`, and `cmd_vel_bridge.py`; the separate modified speed test is not needed on Jetson.
- The synchronized limits are DWB `max_vel_x/max_speed_xy=0.24`, DWB `max_vel_theta=0.30`, recoveries `max_rotational_vel=0.30`, arbiter `max_vx/max_wz=0.24/0.30`, and bridge `hard_max_vx/hard_max_speed_xy/hard_max_az=0.24/0.24/0.30`. Acceleration, deceleration, lateral, and precision-control limits are unchanged.
- Exact overlay SHA-256 values are params `20b4e157c2d49ad73f7a74709913037676542ee5bcac68cb2c15290fed27df6b`, arbiter `fe1cc4887d86ff636d698f4fffb9f37e37c1779d247fc6c8b84b32315291daa0`, bridge `0a70c468e6d4d5687f2bb5d13e6ab160c4099f6dd3bec08f3eead13427bcfe83`.
- Before deployment, the Jetson formal repo remained clean on the intended branch and no navigation/cuVSLAM container remained after the launcher gate stop. A broad `pgrep` read-only query matched only its own SSH wrapper command, not a navigation process.

## 2026-08-11 - Phase 81 doubled navigation-speed contract

- The production command path has three independent clamps: DWB produces the command, `cmd_vel_arbiter` sanitizes it, and `cmd_vel_bridge` applies the final UDP hard limit. A speed increase must update all three layers or the unchanged downstream clamp remains the effective limit.
- The synchronized main-navigation contract is now `v_max=0.24m/s` and `omega_max=0.30rad/s`; Foxy recovery Spin uses the same `0.30rad/s` angular envelope.
- Acceleration/deceleration and the lower-speed SE(2)/yaw-only precision controllers are separate control properties. They were intentionally not doubled by a request to double `v` and `omega`, preserving terminal-control behavior while increasing ordinary DWB travel/turn ceilings.

## 2026-08-11 - Phase 82/83 final one-click deployment contract

- Foxy can expose multiple publisher endpoints from one `recoveries_server` process on `/cmd_vel_nav2`; endpoint count is not equivalent to node/process count. The observed `controller_server x1 + recoveries_server x3` topology was valid, so the earlier exact-one-publisher check caused the premature stop.
- The user's final launcher contract intentionally contains no startup validation gates. `run_full_navigation.sh` now performs only environment sourcing, full-stack startup, the foreground 14-goal route, cleanup, and log/evidence archiving; startup delay from sequential validation commands is eliminated.
- The next one-click run will use the deployed `0.24m/s` linear and `0.30rad/s` angular ceilings because the three runtime source files were copied to the formal deploy tree, the ROS package was rebuilt, and source/build/install resolution was checked before leaving the Jetson stopped.
- The final launcher artifact is `/home/superwfx666/run_full_navigation.sh`, mode `0755`, SHA-256 `8efbcd98b9b877d6910cb4a0b579f8744264bc026409868feb6c7b370e56c427`. The deployment itself did not start Nav2, cuVSLAM, the route, or robot motion.

## 2026-08-11 - Latest branch commit clarification

- `c070b1ff8cf4f0d578e8b0ee613eec8bfbc46521` is the current local `HEAD` and the GitHub remote head of `Stonefield/nav2-foxy-dwb-integration`; its subject is `清理启动脚本损耗时间的进程`.
- `94137ea0bbc10b0e46b684fad5f9c123aced6bfc` is an ancestor of `c070b1f`, not the latest repository commit. References to `94137ea` describe the earlier Jetson deployment baseline; they must not be described as the current branch head.
- The local remote-tracking ref temporarily displayed `origin/...=ebe84e0` because it had not been fetched, while the read-only `git ls-remote` result authoritatively reported the remote branch at `c070b1f`.

## 2026-08-11 - Direct-upload versus Git deployment provenance

- `c070b1f` was not needed for the simplified launcher to reach Jetson. The launcher was copied as a standalone executable to `/home/superwfx666/run_full_navigation.sh`, outside the deploy repository, so its deployment path was direct SSH file transfer rather than `git pull`.
- Jetson proves the separation: deploy `HEAD=94137ea`, deploy remote-tracking ref=`94137ea`, repository launcher path absent, and only the three speed runtime files appear modified. The external launcher still exists with the expected `8efbcd98...6c427` hash.
- The direct-upload file mtime is `2026-08-11 16:12:18 +0800`; local reflog/commit metadata places creation of `c070b1f` at `17:13:08 +0800`. Thus deployment preceded commit creation by approximately one hour: working-tree artifact upload first, local commit second, GitHub push later.
- GitHub now does contain `c070b1f` according to an authoritative `git ls-remote` query. This does not update Jetson automatically; the Jetson checkout remains at `94137ea` until an explicit fetch/update is performed.

## 2026-08-11 - Jetson functional equivalence to `c070b1f`

- For the current one-click navigation workflow, the dirty Jetson deployment is runtime-equivalent to `c070b1f`: the three modified in-repository runtime files and the external launcher all match the corresponding local `c070b1f` files byte-for-byte by SHA-256.
- No other `94137ea..c070b1f` change participates in navigation execution. The remaining changes are two test files, competition-rule text/images, a waypoint visualization PNG, and the offline waypoint rendering script.
- Functional equivalence is narrower than deployment equivalence. Jetson still reports `HEAD=94137ea` with three modified files, lacks the launcher inside its checkout, and cannot reproduce or update the deployed state using Git alone.

## 2026-08-11 - Phase 87 clean `c070b1f` Jetson deployment

- The formal Jetson deploy checkout is now reproducible and clean at `c070b1f`; its upstream ref is the same commit with ahead/behind `+0/-0`. The earlier functional overlay has been preserved both as a timestamped filesystem backup and as `stash@{0}`.
- ROS deployment provenance confirms the intended package prefix, installed `nav2_params.yaml`, and imported arbiter/bridge Python modules all originate from `/home/superwfx666/quadruped-robot-competition-nav2-dwb-deploy` and match source hashes after the package-limited symlink build.
- The external entrypoint `/home/superwfx666/run_full_navigation.sh` remains byte-identical to the tracked `c070b1f` script and executable with mode `0755`.
- Existing runtime state belonged to the independent vision worktree, not the formal deploy: `cmd_vel_bridge` resolved from `worktrees/quadruped-vision-yolo-refactor`, and `d455_yolo_repro_20260811` remained active. Synchronization did not stop, restart, or modify either process/container and did not execute the one-click launcher.

## 2026-08-11 - Phase 84 remote `src/whz` review (interim)

- Remote `feature/vision-yolo-refactor` resolves to `c6a083312b4e777daa6791b30901bec1fbd961df`; the current local branch and remote branch diverge by 47 local-side commits versus 3 remote-side commits from merge base `bdb0bcf`. The local worktree has no `src/whz` directory and was not switched.
- `src/whz` is a Python orchestration/resource package, not the detector implementation. YOLO detection lives in `src/cv/gauge_detector`; ROS wrappers live under `src/nodes/perception`.
- Confirmed runtime blocker: `InspectionResult` consumes `LetterDetection`/`GaugeDetection` through nonexistent attributes `label` and `conf`; the detector dataclasses expose `letter` and `confidence`. A successful YOLO detection therefore becomes `ok=false` through an `AttributeError` catch.
- Confirmed runtime blocker: `GaugeDetector()` defaults to `InstanceSegmentation/projects/gauge/model/best.pt`, but no such model blob exists in the branch tree. The committed `.pt` files are the depth-detector model and two generic root YOLO weights.
- Confirmed ROS packaging blocker: `setup.py` registers `whz_inspection_node = whz.inspection_node:main`, while `src/whz/inspection_node.py` was deleted and no replacement is registered under that name. The RTSP implementation exists only as an unregistered source script; `whz_standalone` is registered separately.
- Confirmed state-contract bug: inline WHZ results store Chinese `status` values (`正常`/`异常`) into TaskManager, while the abnormal filter excludes only English `normal`; a green normal gauge is consequently classified as abnormal.
- The docs still describe deleted template/depth/ROS-frame-buffer behavior and a 2-of-3 vote. Actual `Inspector` defaults to `min_agree_frames=1`, and the standalone wrapper can reread the same relay JPEG without checking source timestamp freshness.
- No branch tests reference `Inspector`, `GaugeDetector`, or WHZ integration. Syntax compilation succeeds but cannot detect the API/packaging/state-contract faults above.
- Confirmed TaskManager sequencing bug: `_tick_inspect_gauges()` sends a Nav2 goal and then falls through in the same timer tick to `_run_whz_inline()` unless the action is already finished with failure. It therefore captures before arrival and immediately resets the navigation client when advancing the step.
- Confirmed false-success path: missing JPEGs and failed detections call `_advance_step()` rather than retaining/retrying/failing the inspection phase. After four such skips, the empty status set enters the `未发现异常` branch.
- The advertised Docker GPU path is disconnected. `yolo_relay_docker.py` writes `latest_detection.json`, but the only consumer is the unused `DockerDetectionReader` example itself; TaskManager and both ROS wrappers instantiate `GaugeDetector` on the Host. The Docker script also defaults to a separately staged `camera_frames/gauge_best.pt` with no committed staging/startup step.
- Host runtime dependencies are not declared by the ROS/Python package: `package.xml` omits even `std_srvs`, and `pyproject.toml` has no runtime dependency list for OpenCV, Torch, Torchvision, or Ultralytics. The only relevant requirements file targets the training workspace, while the handover describes dependencies installed in a non-reproducible local Docker image.
- The integrated launcher still starts the deleted `whz_inspection_node` entrypoint when `enable_whz=true`. Normal competition startup enables TaskManager but not WHZ by default, so TaskManager later takes its separate inline D455/Host-model path rather than the documented RTSP service path.
- The remote feature branch is 47 commits behind the current Nav2 branch and changes 59 files under the focused perception/decision surface alone. It should not be merged wholesale; any adoption must port a bounded interface and tests onto the current branch.
- Model/data reproduction is incomplete: Git tracks 162 LabelMe JSON files and one dataset YAML, but no corresponding images, trained gauge model, or metric artifact. The YAML hardcodes `C:/Users/tom/.../datasets`, so the reported `mAP50=0.973` cannot be reproduced from the branch alone.
- `scripts/test_whz_detect.py` was not migrated to the new API. It still imports deleted `whz.letter_detector` and `whz.gauge_detector` modules, while the old `src/cv/gauge_detector/test_gauge.py` was deleted and no replacement WHZ tests were added.
- The multi-object association contract is unsafe: `Inspector` independently selects the highest-confidence letter and highest-confidence gauge, records whether the letter is above the gauge, but never requires that relationship or pairs detections geometrically. A frame containing multiple cabinet regions can associate a letter with the wrong gauge state.

## 2026-08-11 - Phase 85 selective WHZ integration assessment (interim)

- The current Nav2 branch already contains a separate, launchable ROS2 `whz` package with `/whz/inspect`, ament-aware resource paths, 12 fixed MP3 files, letter templates, an audio player, and a 3-frame/2-agreement service contract. These assets should be preserved instead of moving the remote `src/whz` package into the main package.
- Current and remote audio-player/model-announcement assets are byte-identical. Porting them would create churn without adding capability.
- The preferred camera source is the Lite3 front RTSP stream, not the D455 RGB/depth relay. This isolates gauge inspection from the already validated D455/cuVSLAM/Nav2 sensor path and matches the camera domain used to train the remote gauge YOLO model.
- The current ROS-image `whz` service waits synchronously for fresh subscription callbacks while running under the default single-threaded `rclpy.spin()`. Because the service callback occupies the executor that must deliver those image callbacks, the implementation can time out even when topics are publishing. A synchronous RTSP reader avoids this executor dependency.
- The target ownership boundary is: the standalone `whz` package owns RTSP capture, YOLO gauge/letter inference, 2-of-3 voting, MP3 mapping/playback, and `/whz/inspect`; TaskManager owns only Nav2 arrival/settle/retry/result handling through an asynchronous Trigger client.
- The current TaskManager must not retain inline image/model code. It currently sends a navigation goal and falls through to inspection before action completion, skips failed detections, and can report no abnormal gauges after all inspections fail.
- The remote RTSP adapter uses an `appsink` with `max-buffers=1 drop=true`, so sequential pulls can consume current frames without accumulating an old queue. It still needs bounded startup/read timeouts and explicit GStreamer bus-error handling before production use.
- Model deployment should use an ament-resolved resource such as `whz/assets/models/gauge_best.pt`, with the exact model tracked or otherwise reproducibly provisioned and verified by SHA-256. The remote source-relative `parents[3]/InstanceSegmentation/...` lookup is not install-safe.
- A read-only Jetson Host audit confirms direct-host feasibility: Python 3.8 has NVIDIA Torch `2.0.0+nv23.05`, Torchvision `0.15.1`, Ultralytics `8.2.103`, OpenCV `4.13.0`, GI, CUDA availability, all required RTSP/GStreamer plugins, and `/usr/bin/mpg123`.
- The trained gauge model exists at both `~/quadruped-robot-competition/InstanceSegmentation/projects/gauge/model/best.pt` and `~/workspaces/isaac_ros-dev/camera_frames/gauge_best.pt`; both have SHA-256 `3ed76de727a87be8d64cc3b259bf2b0ec39daaaa3fac1f3f97af249824abc648`.
- Jetson `~/quadruped-robot-competition/src/cv/gauge_detector/gauge_detector.py` has Git blob `6ca4bd2fa891608b305181e95aa620d215d4693b`, exactly matching the remote refactor source.
- A no-camera, no-ROS, all-zero CUDA smoke successfully loaded the model, reported classes `A/B/C/D/green/red/yellow`, and completed inference with zero boxes. The existing Torchvision image-extension ABI warning did not block Ultralytics inference.
- The measured first dummy inference was `17.75s`, not a steady-state benchmark: it included CUDA/model initialization and occurred while a pre-existing `d455_yolo_repro_20260811` container and `cmd_vel_bridge` processes were active. The probe did not start, stop, or alter those processes, and no further remote load test was run.
- Recommended delivery is staged: first replace only the standalone `whz` service backend with on-demand RTSP + YOLO + existing MP3 playback and validate it without navigation; only after that passes should TaskManager replace inline detection with an asynchronous `/whz/inspect` client gated on successful Nav2 arrival and a settle delay.
- Selective reuse classification: keep the current `whz` package setup, package manifest, ament paths, audio assets/player, and 2-of-3 voting structure; adapt the remote YOLO detector and RTSP camera/node; reject the remote main `setup.py`, launch file, inline TaskManager patch, Docker JSON relay, standalone D455 relay wrapper, and stale WHZ docs/tests.

## Phase 86 kickoff - 2026-08-11

- Target environment evidence is ROS 2 Foxy on Jetson; the local Windows shell has no active `ROS_DISTRO`.
- The current Git branch is `Stonefield/nav2-foxy-dwb-integration` and was clean at kickoff.
- Phase 85 already concluded that WHZ should be selectively ported rather than merging `feature/vision-yolo-refactor` wholesale.
- Phase 86 is limited to the standalone `/whz/inspect` RTSP + YOLO + vote + audio service. TaskManager integration is deliberately deferred until supervised Jetson recognition and playback pass.
- ByteRover is unavailable in this host, so related history comes from the repository PWF and Git objects.
- The remote YOLO data classes expose `LetterDetection.letter`, `LetterDetection.confidence`, and `GaugeDetection.confidence`; the remote Inspector incorrectly reads `letter.label`, `letter.conf`, and `gauge.conf`, reproducing the Phase 84/85 failure.
- The remote detector's independent `best_letter` and `best_gauge` properties can combine detections from different panels. A production result must come from one spatially valid letter/gauge pair and reject tied/ambiguous pairings.
- The current Inspector's 2-of-3 vote and one-shot post-vote audio placement are reusable, but it imports the legacy OpenCV detector and the node rebuilds the Inspector on every request.
- The current node blocks on D455 ROS subscription delivery under a single-threaded executor. Direct synchronous RTSP capture removes that callback dependency and leaves the dedicated service node's blocking request semantics explicit.
- Remote RTSP code uses `appsink max-buffers=1 drop=true`, but `pull-sample` has no bound, startup state/bus errors are not checked, the probe frame is discarded, and frame identity is not verified.
- No trained model is present in the local package or remote branch tree. Phase 85 verified the formal Jetson model SHA-256 as `3ed76de727a87be8d64cc3b259bf2b0ec39daaaa3fac1f3f97af249824abc648`.
- The implementation boundary will be: `YOLODetector.detect()` returns a unique spatially paired area/state candidate; `Inspector` converts colors to stable keys/display fields, votes on `(area,state_key)`, derives `is_abnormal`, and plays once only after a successful vote.
- The formal Jetson model was copied from `/home/superwfx666/quadruped-robot-competition/InstanceSegmentation/projects/gauge/model/best.pt` into `whz/assets/models/gauge_best.pt`; local SHA-256 is the exact required full digest and the size is 6,241,123 bytes.
- `InspectionRunner` now provides a ROS-free camera/detector/player seam so the entire capture-to-vote contract can be unit tested without importing `rclpy` or opening RTSP.
- Focused local L1 evidence: 16 WHZ tests pass, including distinct sample IDs, wrong-gauge rejection, two-panel ambiguity rejection, stable state keys/`is_abnormal`, 2-of-3 voting, no pre-vote audio, one playback attempt, camera errors, one model construction/warmup, launch isolation, and the exact model hash.
- Foxy compatibility evidence: the Jetson `/opt/ros/foxy` Python environment imports `launch_ros.parameter_descriptions.ParameterValue` and all new `rcl_interfaces` parameter descriptor types.
- Repository regression evidence after setting the established `src` PYTHONPATH: 129 tests and 70 subtests passed; the hardware UDP smoke test remained intentionally excluded.
- Jetson L2 evidence from isolated `/home/superwfx666/competition_phase86_whz_ws`: Foxy/Python 3.8 built the `whz` package, installed the model/audio/modules, verified the installed model digest, and completed CPU model warmup with the exact seven expected classes without opening a camera.
- The Jetson still emits the known Torchvision image-extension ABI warning, but Ultralytics model construction and warmup complete successfully. This warning does not establish camera or GPU runtime behavior.
- Jetson hardware validation is currently gated by unrelated live visual/manipulator tests: a D455 YOLO process uses about 200% CPU, and `cmd_vel_bridge`, arm motion, and competition manager processes are active. They are user-owned and were not stopped or modified.
- Final local evidence after enforcing exact camera batch size: 17 focused WHZ tests pass; the full non-hardware suite passes with 130 tests and 70 subtests. The final `inspection.py` was resynchronized and rebuilt successfully in the isolated Jetson workspace.
- Jetson L4 RTSP capture passed in evidence directory `competition_phase86_whz_ws/evidence/20260811_190342`: three `1280x720` frames had different PTS values, different pixel SHA-256 values, and per-frame waits of about 0.003-0.070 seconds.
- Visual and numeric inspection shows the current Lite3 view is an almost uniform close gray surface (BGR means near 128, channel standard deviations near 2), with no cabinet letter or gauge visible.
- GPU execution passed technically: one model construction/warmup completed in about 29.96 seconds and steady single-frame inference completed in about 0.193 seconds. The correct semantic result for the empty scene was `letter_not_detected`.
- A real `/whz/inspect` call with `play_audio=false` consumed three frames in about 2.6 seconds and returned `success=false`, `error=no_valid_frame`, `total_frames=3`, `audio_played=false`; it did not false-positive or play audio.
- Standalone playback of the installed formal `AMN.mp3` completed exactly once in about 4.04 seconds. This proves the player command/resource path, not that automatic audio selection after a live successful vote has passed.
- Live recognition/voting remains blocked by the physical scene. A cabinet target must be placed in the Lite3 front-camera view before the stage-one L4 gate can pass.
- The only historical Jetson color frame contains small distant props but no clear A/B/C/D label; the formal detector also returned no boxes at the production threshold. This is diagnostic evidence only and cannot substitute for a correctly staged live inspection target.

## Phase 86 RTSP decode investigation - 2026-08-11

- The user explicitly confirms the Lite3 front camera's physical field of view is correct. The nearly uniform gray frames must therefore be treated as a receive/decode/caps problem, not as an occluded or incorrectly staged camera.
- A focused public web search found no Lite3-specific official GStreamer pipeline. The exact endpoint `rtsp://192.168.1.120:8554/test` does appear in public robot video-stream configuration and GStreamer examples, supporting the endpoint spelling but not proving a particular decoder/caps chain.
- Public examples for the exact endpoint commonly use `uridecodebin` to negotiate the decoder automatically. On this Jetson, `uridecodebin` selected NVIDIA hardware decode but could not negotiate directly into ordinary `videoconvert` because the NVMM-to-system-memory `nvvidconv` bridge was absent from that generic probe.
- Direct caps inspection establishes the live stream as H.264 High Profile, `1280x720@30`, 8-bit 4:2:0. The explicit software path correctly negotiates `I420/bt709` into tightly packed BGR, ruling out the suspected BGR/BGRx stride interpretation error.
- Decoder/transport cross-validation isolated the failure: `avdec_h264` over default UDP produced low-information concealment frames (gray standard deviation about 4), while `avdec_h264` over RTSP TCP and `nvv4l2decoder` over UDP both produced the same clear D-area/gauge scene (gray standard deviation about 51 and 47 respectively). The production software path was joining the UDP stream before a usable reference frame and returning concealment frames as if valid.
- Visual comparison confirms the TCP software and NVIDIA hardware frames agree on the scene content. The failed UDP software frame retains only faint block-corrupted outlines, so pixel hashes/PTS alone cannot be used as a decoded-image validity gate.
- TCP transport alone does not guarantee a valid first decoded sample: the installed production reader still returned three concealment frames immediately after connection. Setting the documented `avdec_h264 output-corrupt=false` property caused both TCP and UDP software paths to withhold those invalid startup frames; their first delivered frame and the following 20 samples all matched the clear scene with gray standard deviation about 52.
- The production fix therefore combines TCP transport with decoder-level corrupt-frame rejection. It does not use a scene-dependent brightness/contrast heuristic and remains valid if the legitimate camera view itself has low contrast.
- On the corrected live D-area frame, the gauge was easy at all tested sizes but the small letter was resolution-bound: at `imgsz=320` it weakly misclassified as B, at 640 B/D both remained below threshold, and at 960 D reached about 0.389 while green reached about 0.944. With the unchanged production confidence threshold 0.30, `imgsz=960` produced three valid D+green spatial pairs and a 3/3 `middle`, non-abnormal vote.
- Steady 960 inference took about 0.08-0.21 seconds per frame on the Jetson GPU. This is compatible with the on-demand service and materially safer than lowering the confidence threshold, which exposed the B/D ambiguity at smaller inference sizes.
- A later live batch placed D at `0.304/0.302/0.263` confidence while the overlapping B alternative remained only `0.071-0.086`. Raising inference size to 1280 reduced D confidence further. Keeping 960 and lowering the production cutoff narrowly from 0.30 to 0.25 preserves all three correct D detections while retaining at least about 0.17 confidence separation from B.
- Subsequent lighting/view changes exposed that full-frame letter classification was not stable: one 30-frame batch classified the real D as B in all 30 frames at 0.160-0.293 while green remained about 0.93. Lowering the global threshold would therefore create a stable wrong-area result and was rejected.
- Gauge-anchored second-pass YOLO resolves the domain: a crop extending 1.25 gauge widths horizontally, 1.75 gauge heights above, and 0.10 gauge heights below the gauge top converted the same full-frame B error into D. Across two 30-frame batches, this wide crop produced no A/B/C alternative above the model's 0.05 probe floor; D had a 0.145 minimum in the first batch and a 0.251 minimum in the second. A crop-specific 0.15 threshold plus the existing spatial/ambiguity gates preserves 58/60 frames and supports deterministic 2-of-3 voting.
- Tighter gauge-relative crops were empirically worse: the medium crop passed only 7/30 at 0.25 and the tight crop detected no D. The production crop remains gauge-relative rather than using fixed image coordinates, so it can follow multiple panels and camera motion.
- The failed `gst-launch-1.0 ... pngenc snapshot=true ! filesink` probe did not terminate on the live RTSP stream and continuously appended to one invalid PNG path. This was an EOS/sink construction error in the probe, not camera evidence.
- The final installed service with the gauge-anchored letter ROI produced a stable 3/3 vote for `area=D`, `state_key=middle`, `is_abnormal=false`, `color=green`; the user confirmed this mapping is correct for the actual scene.
- Automatic announcement selection is now validated end to end: only after the successful final vote, the service selected `DMN.mp3`, played it once, and returned `audio_played=true`. Ten additional no-audio rounds all returned the same 3/3 result, so stage-one recognition and voting are no longer pending.
- The stationary coexistence launch is isolated from motion/task ownership: it started cuVSLAM plus Nav2 and the command arbiter, while `enable_task_manager=false`, `enable_cmd_vel_bridge=false`, `enable_whz=false`, and no route/goal process is present. The exact new cuVSLAM container is `cuvslam_gui_20260811-201852`, enabling precise cleanup later.
- In the stationary topology, `/cmd_vel` cannot reach the robot because it has zero subscribers. `/cmd_vel_precision` also has no publishers, while `/cmd_vel_nav2` is internally connected only to `cmd_vel_arbiter`; bounded value sampling is still required to prove that no nonzero command appears during WHZ inference.
- The pre-WHZ baseline is healthy: cuVSLAM-to-Foxy `/odom` is effectively 30 Hz and the arbiter emits only exact zero twists while idle. This provides the comparison point for the same sampler during live WHZ inference.
- The pre-WHZ stationary load has ample memory headroom (about 3.85 GiB used of 14.88 GiB) and cuVSLAM consumes about 636 MiB. GPU utilization is naturally variable even before WHZ (`1-46%` over the sampled window), so coexistence should be judged primarily by sustained `/odom` frequency, zero velocity, successful inspection, and absence of resource exhaustion rather than a single GPU percentage.
- The first simultaneous cuVSLAM + Nav2 + WHZ attempt exposed a real resource/runtime defect: the persistent RTSP pipeline consumes roughly one CPU core in `rtpjitterbuffer`, total system CPU can approach saturation, and the otherwise fast inspection request remained outstanding for minutes. Stage-one standalone recognition is correct, but stationary coexistence cannot pass until this behavior is diagnosed or the camera/pipeline lifetime is changed.
- Even during the failed high-load coexistence request, `/odom` stayed at 30.01 Hz and every observed velocity command remained exactly zero. The failure is therefore service latency/resource isolation, not loss of localization frequency or unintended motion.
- The minimal resource fix is to separate model lifetime from camera lifetime: retain the expensive warmed YOLO model for the node lifetime, but open RTSP only when `/whz/inspect` is called and close it immediately after capture. This removes idle decode load and prevents GStreamer from competing with YOLO/cuVSLAM during inference or MP3 playback.
- Jetson evidence validates the first half of that fix: after warmup the request-scoped-camera node uses `0.0%` CPU while idle across an 8-second window, compared with the prior persistent pipeline's roughly two-core load. Model memory remains resident by design.
- The complete standalone on-demand cycle also passes: hardware-decode capture plus 3-frame ROI inference returns the user-confirmed D result in 3.957 seconds, then releases all RTSP threads and returns to 0% CPU. Hardware decode emitted repeated non-fatal `Stream format not found, dropping the frame` lines but still delivered three distinct valid frames and a correct vote.
- A standalone ROS node started beside the formal stack must inherit the same FastDDS no-SHM profile. Without it, two DDS threads busy-spin even though the request-scoped camera is closed. This was a test-launch provenance error, not residual RTSP load; the integrated `competition.launch.py` path already inherits the profile from `start_competition.sh`.
## 2026-08-11 - Phase 88 staged depth-mode architecture decision

- Keep one `competition_field_phase1.yaml` map for the whole mission. Do not introduce a map switch as part of the depth project.
- D455 infrared stereo and IMU remain continuously available to cuVSLAM. The controlled resource is the depth stream and all downstream depth work, not the entire camera device or RealSense owner process.
- The target mission policy is depth `AVOIDANCE` from startup through successful `obstacle_cross_target`, `DISABLED` through inspection, and `MANIPULATION` after successful `pos2b_lower_right` before `grab_area_approach` and placement work.
- Runtime `enable_depth` behavior is an evidence gate, not an assumption. If changing it restarts infrared/IMU or destabilizes cuVSLAM, the production fallback keeps the sensor pipeline stable and deactivates the high-cost relay/PointCloud2/filter/costmap/visualization consumers instead.
- A Docker-side controller must own the Humble RealSense parameter change and acknowledge requests through a versioned shared-memory control/status contract; the Foxy mission layer must not infer success merely because depth messages disappeared.
- Main expected Xavier savings come from stopping depth image transport, point-cloud projection/serialization, filters, Voxel/Obstacle observation callbacks, and RViz cloud rendering. Resource measurements before/after each component are required to identify the actual bottleneck.
- Required depth modes are fail-closed. Re-enabling depth happens only while stopped and requires fresh sequence numbers, source timestamps, CameraInfo, optical TF, point cloud, costmap update, and safety-gate readiness before motion is released.
- A carried object or manipulator may appear in the D455 field of view. Grasp/placement validation must include a self/carry crop mask or separate manipulation-only depth output so Nav2 does not treat the robot's own payload as an obstacle.

## 2026-08-11 - Phase 86 final coexistence finding

- With the production FastDDS no-SHM profile, request-scoped RTSP capture coexists acceptably with stationary cuVSLAM and Nav2: the service returned the user-confirmed `D/middle/false/green` result in `4.135s`, no nonzero velocity was observed, and post-request `/odom` recovered to `30.0138 Hz`.
- The decisive resource property is camera lifetime rather than model lifetime: keeping the warmed YOLO/CUDA context resident is acceptable, while closing GStreamer immediately after acquiring three distinct frames removes the persistent jitterbuffer CPU load and prevents idle decode contention.
- Standalone launch provenance matters. A separately started WHZ node must use the same `RMW_IMPLEMENTATION`, `ROS_DOMAIN_ID`, and `FASTRTPS_DEFAULT_PROFILES_FILE` as the formal launcher; otherwise FastDDS threads can busy-spin and invalidate resource measurements even when the camera is closed.
- Phase 86 acceptance is complete at L1-L4 scope: local regression is green, the isolated Foxy package builds and loads the exact model, live RTSP/GPU voting and automatic MP3 selection pass, and stationary coexistence preserves zero commands plus approximately 30 Hz post-request odometry. No navigation or TaskManager behavior has yet been integrated or field-tested with motion.
## 2026-08-11 - Phase 89 execution baseline

- Local and `origin/Stonefield/nav2-foxy-dwb-integration` both point to clean commit `752c6527c5b243a152444c989ae2e08e0d17c3a2`.
- `eb26351` contains the initial standalone WHZ implementation; `752c652` contains accepted live-scene refinements, expanded WHZ tests/documentation, and the unrelated one-line Lite3 UDP test-fixture repair.
- The formal Jetson deploy checkout `/home/superwfx666/quadruped-robot-competition-nav2-dwb-deploy` is clean at `c070b1ff8cf4f0d578e8b0ee613eec8bfbc46521`, with no source model, installed WHZ prefix, or installed model.
- Phase 1 modified both the `whz` package and the main package launch surface, so formal deployment must rebuild and verify both `whz` and `quadruped_robot_competition` rather than only `whz`.
- TaskManager currently reaches `_run_whz_inline()` without requiring a completed successful navigation result. Navigation goal rejection clears `goal_sent` without producing a terminal result, which would otherwise cause unbounded resubmission.
- The new service returns `state_key=low/middle/high` and `is_abnormal`; the legacy TaskManager expects `status=normal/high/low`. Integration requires an explicit normalizer so `middle` is not classified as abnormal.
- The main package still exposes the legacy `whz_standalone` executable, which owns the same `/whz/inspect` service name as the accepted `whz` package and must be retired to preserve single service ownership.

## 2026-08-11 - Phase 89 post-deployment state

- The authoritative Phase 89 revision is `97ca3efdab01e2e826c3af6212cc79fa8d264918`; both the remote branch and formal Jetson deploy target this commit.
- Phase 89 owns no depth console entrypoints. The two Phase 88 entrypoints in local `setup.py` are intentionally uncommitted and must not be included in Phase 89 deployment or validation.
- Formal Phase 2 deployment and non-motion startup validation are complete. The next evidence gate is a no-Nav2-server bounded-retry smoke, followed by a supervised single observation position only after fresh physical safety confirmation.

## 2026-08-11 - Phase 89 bounded-failure evidence

- On the installed Foxy runtime, an unavailable NavigateToPose server produces exactly four attempts: the initial attempt plus three retries, then terminal `navigation_failed_after_4_attempts` and TaskManager phase `abort`.
- `NavigationClient.navigate_to_pose()` checks `server_is_ready()` before `send_goal_async`; the smoke corroborated this with zero goal-sent log lines and zero action servers. No message appeared on `/cmd_vel` or `/cmd_vel_nav2`.
- The one-position field gate should use `inspection_only:=true`, `inspection_start_index:=3`, and `inspection_count:=1` for the previously validated D-facing `pos2b_lower_right` observation, subject to a fresh physical safety confirmation.
- Foxy logs a shutdown-only `ActionClient.__del__` `InvalidHandle` because destruction occurs after the node handle is gone. This is a cleanup-order defect with no residual process in the smoke; keep it separate from the current functional field-validation gate.
## 2026-08-11 - Phase 88 local implementation findings

- A controller mode ACK alone is insufficient for releasing motion. The mission transition now requires the downstream safety gate to confirm fresh depth, projected cloud, optical TF, and local costmap data; otherwise startup aborts before the first navigation goal.
- `DISABLED` is also an acknowledged transition. The safety gate does not require frames in this mode, but it still rejects motion until the Docker controller reports the same request ID, mode, health, and `depth_enabled=false`.
- Persistent shared files can outlive a process. The Host rejects stale controller-status mtimes, and the mission coordinator ignores unsolicited operational status when booting, preventing a previous run's ACK from satisfying a new mission.
- The original TaskManager route skipped `pos1_left_clear`, both cabinet-corner transits, and used non-approach grasp/placement names. The formal route now derives from the same calibration default as the waypoint probe while retaining task-aware behavior: only actual abnormal placement zones are visited.
- The existing 14-point launcher intentionally remains unchanged and does not enable the staged depth path. This preserves its validated baseline until the Jetson is idle and L2-L6 gates are explicitly run.

## 2026-08-11 - Phase 88 resumed local ROS 2 review

- The Docker relay subscriptions used the default RELIABLE QoS. RealSense image and CameraInfo publishers commonly offer sensor-data BEST_EFFORT QoS, so the relay could match no publisher and receive no depth data. The relay must explicitly request `qos_profile_sensor_data`.
- The shared-file contract carried a monotonic frame timestamp but the Host bridge did not enforce it. Reading an old file after restart could therefore refresh the Host-side receive time and incorrectly satisfy the safety gate. Frame and controller-status ages must be validated from the shared monotonic clock, including rejection of future timestamps.
- A frame sequence alone cannot distinguish a restarted Docker relay whose counter returns to one. Add a per-process stream identifier to controller status and frame metadata, reset Host sequence state only when that identifier changes, and reject frame/status stream mismatches.
- A new depth-required request could inherit recent frame and costmap timestamps from the previous mode. Reset Host frame readiness on every new request, bind safety status to the same request ID, and require at least one new-mode point cloud followed by a costmap publication before motion is released.
- A merely fresh local-costmap topic is not evidence that the current depth generation was consumed. The gate needs a generation latch keyed by request/stream/mode and should confirm a costmap timestamp at or after the current depth source stamp.

## 2026-08-11 - Phase 89 single-position field-gate review

- The deployed `97ca3ef` selection `inspection_only:=true`, `inspection_start_index:=3`, `inspection_count:=1` does isolate `pos2b_lower_right`.
- The three inspection parameters are TaskManager node parameters, not launch arguments in the deployed `competition.launch.py`; the base stack must keep TaskManager disabled and the limited TaskManager must be started separately with `ros2 run ... --ros-args -p ...`.
- Default `max_nav_retries=3` and `max_inspection_retries=3` conflict with a literal fail-on-first-error acceptance rule. A fail-fast field gate must set both to zero, or the SOP must explicitly allow up to four attempts.
- Partial inspection accepts any valid A/B/C/D response. It does not bind index 3 to expected area D, so terminal `finish` alone is insufficient; acceptance must independently require the stored/logged area to be exactly D.
- TaskManager `abort` cancels an active navigation goal and clears its inspection future, but it does not execute `stop_all.sh` or repeatedly own zero velocity. Whole-stack shutdown remains an external supervised action, with the physical emergency stop taking precedence on unexpected motion.
- A preflight that only checks topic/service existence is insufficient. Require fresh/rate-valid `/odom`, stable finite `map -> base_link`, active Nav2 lifecycle nodes, exactly one NavigateToPose server, exactly one `/whz/inspect` server, a planner path from the actual current pose, and observed zero velocity before TaskManager starts.
- The single D-position gate is a valid next step after fresh physical confirmation. Passing it must not automatically release the four-position run: deployed `97ca3ef` still uses the old adjacent `pos1_middle -> pos1_middle_turned` 180-degree turn and omits the validated corner-clear transit route.

## 2026-08-12 - Jetson USB audio routing

- Jetson ALSA detected the newly inserted Jieli Technology `USB Composite Device` as stable card ID `Device` (`card 2, device 0` in this boot). Playback supports stereo `S16_LE` at `48 kHz`; PCM playback was enabled at 30%.
- Direct playback through `mpg123 -o alsa -a plughw:CARD=Device,DEV=0` completed successfully with the installed `DMN.mp3`.
- WHZ currently launches plain `mpg123 -q <file>`. A user-level `/home/superwfx666/.asoundrc` now maps the default PCM/control device to `hw:CARD=Device,DEV=0` through ALSA `plug`, so existing WHZ playback uses the USB device without a source or launch change.
- The exact unmodified WHZ-style command was rerun after configuration. `/proc/asound/card2/pcm0p/sub0/status` reported `state: RUNNING` with the mpg123 owner PID, playback exited `0`, and no mpg123 process remained.
- `.asoundrc` SHA-256 is `0550d91edc64491d7ba24baa29ee9198ba39834d29012be68f4ebf727d9c8838`. The stable card name is intentional because numeric ALSA card indexes may change after reboot.

## 2026-08-12 - Full inspection motion preflight gate

- The operator confirmed the robot was physically returned to the official map start, but has not yet provided the separately required route-clear, emergency-stop-ready, and on-site-supervision confirmation.
- The formal Jetson deploy checkout remains clean at `97ca3ef`. That revision's four-position TaskManager route still places `pos1_middle` directly before `pos1_middle_turned` and does not use the validated cabinet-corner transit route.
- Local/origin `2034df2` contains shared interleaved/transit route semantics, but it also carries the broader Phase 88 staged-depth implementation and has not passed Jetson L2/L3 deployment/runtime gates. It must not be deployed wholesale merely to obtain the route fix.
- The safe requested scope should be defined as navigation from the official start through the validated inspection route, four WHZ observations with one result/audio each, then terminal finish and cleanup; it must not continue into red-bar grasp or placement.
- No ROS launch, cuVSLAM container, Nav2 server, robot mode transition, action goal, or velocity command was started during this preflight.
## 2026-08-12 - Dedicated inspection runner design boundary

- Jetson formal deploy `97ca3ef` contains the WHZ-enabled TaskManager but still uses the old adjacent `pos1_middle -> pos1_middle_turned` same-coordinate 180-degree turn.
- The proven navigation path is `run_full_navigation.sh -> nav2_waypoint_sequence_probe.py -> waypoints_reordered_preview.yaml`; its `inspection_interleaved` route uses `upper_corner_clear` and `lower_corner_clear` transit points and has already reached observation point 9 successfully in supervised field evidence.
- Local `2034df2` shares the safe route with TaskManager through `mission_route.py`, but it also carries 30 Phase 88 depth files and must not be deployed wholesale for this acceptance.
- The dedicated runner should execute WHZ only for waypoint actions prefixed `observe_`, require fresh odometry plus a continuous stop, accept four unique A/B/C/D readings, and abort without retry after any response that already reports `audio_played=true`.
- The implementation can reuse the deployed `97ca3ef` probe without modifying it: subclass `run_segment()`, preserve its NavigateToPose/action/terminal-handover logic, and mark only the combined navigation-plus-inspection segment failed when the post-arrival contract fails.
- The one-click wrapper supports `--single-d`, `--full`, and `--check-only`; motion modes additionally require `--confirm-motion`. Single-D mode still navigates the complete safe 9-step route but invokes WHZ only at `pos2b_lower_right` and requires area `D`.
- Jetson deployment commit `5485086` is a clean three-file child of `97ca3ef` on `codex/inspection-runner-20260812`; rollback branch `codex/pre-inspection-runner-97ca3ef` preserves the prior deployment point.

## 2026-08-12 - First dedicated single-D field attempt

- The fail-closed startup gate worked: action server, WHZ service, fresh odometry, and TaskManager absence passed, but the run terminated `ABORT` before any goal because its main-node `/cmd_vel` callback remained unset for the full stationary timeout.
- This was not evidence of nonzero robot motion. The independent production `cmd_vel_bridge` received about 40 exact-zero `/cmd_vel` samples per second throughout the same window, while odometry linear/angular speeds were near numerical zero.
- Acceptance-critical zero-speed observation should not share the navigation runner's main executor with action/status work. Give `/cmd_vel` a dedicated listener executor, as already done for odometry, while preserving the base probe's original main-node subscription for per-segment command evidence.
- The dedicated-listener correction is validated on the target Foxy runtime: with only the arbiter running and no actuator bridge, it received an exact-zero `/cmd_vel` sample aged about 1 ms even though the inspection runner's main node was intentionally not spun.

## 2026-08-12 - Single-D physical acceptance boundary

- The single-D runner deliberately traverses the full safe 9-waypoint route but invokes WHZ only once at final `pos2b_lower_right`; it is therefore visually indistinguishable from the pure waypoint run until the last stop. Full mode invokes WHZ at all four `observe_*` waypoints.
- Runtime evidence proves the final inspection request occurred from 02:07:40.575 to 02:07:49.260 and returned `D/middle/normal`, 3/3 agreement, one request, and `audio_played=true`.
- `AudioPlayer` defines `audio_played=true` as a successful silent `mpg123` subprocess exit. That is process evidence, not an acoustic sensor or operator-heard guarantee.
- The exact `DMN.mp3` is valid, 15984 bytes, 3 seconds, MPEG 2 Layer III 32 kbps/16 kHz mono, and matches local SHA-256 `7d95da3416f2c8aaf7238bef7125b6e01cbf9ee5cdb789b188eeb42fa45b5d62`.
- Stable ALSA mapping still selects `hw:CARD=Device,DEV=0`, but the USB PCM is only 30% (`-20.16 dB`). Raise volume only in a stationary audio-only test and require the operator to confirm it is audible before full-route acceptance.
- The authorized 70% stationary replay proved the full digital playback path to the USB PCM device: explicit `plughw:CARD=Device,DEV=0`, live card0 PCM `RUNNING` with the mpg123 owner PID, exit code 0, and no residual player. Acoustic acceptance remains a human observation because the system has no microphone feedback loop.
- The operator heard the 70% replay clearly, closing the acoustic acceptance gap. Use 70% as the current field baseline and still require one announcement per observation in full mode.

## 2026-08-12 Phase 91 cone avoidance implementation findings

- The stable `nav2_params.yaml` local costmap is static-only; the existing optional `nav2_depth_obstacles.yaml` uses a Host-generated `PointCloud2`, `VoxelLayer`, and a global dynamic obstacle layer.
- The current shared-file depth path writes raw frames plus JSON with `fsync`; this is the high-bandwidth path being replaced, not extended.
- `start_cuvslam_rviz_gui.sh` already owns the single D455 process and publishes `base_link -> camera_link` in robot mode, so point-cloud transformation must stay inside its Humble graph.
- A LaserScan costmap alone cannot provide fail-closed behavior when UDP disappears because a non-persistent layer can simply clear. The new chain therefore needs an independent health-driven velocity gate after command arbitration.
- Scan hit count is not a valid sensor-health proxy in open space. Depth health must be computed from the decimated depth image and carried alongside the scan as overall and left/center/right valid-pixel coverage.
- The new Nav2 overlay must configure only `local_costmap`; omitting any `global_costmap` block preserves the stable static global configuration.
- Official `realsense-ros` 4.54.1 sources confirm `/camera/depth/color/points`, `/camera/depth/image_rect_raw`, `pointcloud.allow_no_texture_points`, `pointcloud.ordered_pc`, and the `<filter>.<option>` dynamic naming rule. Because librealsense exposes `Filter Magnitude` as an integer option, the correct decimation override is `decimation_filter.filter_magnitude: 4`.
- Official `pointcloud_to_laserscan` 2.0.1 sources confirm the `pointcloud_to_laserscan_node` executable, `target_frame` transform, and `ceil((angle_max-angle_min)/angle_increment)` beam sizing; the configured +/-45 degree field with 0.5 degree increments therefore produces exactly 180 beams.
- Foxy `nonpersistent_voxel_layer` 2.2.1 registers the plugin alias `nav2_costmap_2d/NonPersistentVoxelLayer`, not the C++ type string. Its Foxy example and source require explicit voxel geometry such as `origin_z: 0.0`, and Foxy `ObstacleLayer` uses per-source `obstacle_range`/`raytrace_range` rather than newer min/max range keys.
- A `base_link` LaserScan represents every accepted return at z=0 after Humble-side height filtering. The Foxy observation buffer must therefore use `min_obstacle_height: 0.0`; retaining the camera-side 0.05 m minimum on Host would discard every scan point.

## 2026-08-12 - Full inspection A-letter miss root cause

- The first full four-observation run used the dedicated nine-point route with TaskManager disabled. It navigated successfully through the first five segments, announced one valid C result at `pos1_middle`, then failed closed at `pos2a_upper_right` on `no_valid_frame`; no later goals or announcements occurred.
- The A cabinet was fully visible in the saved 1280x720 frame. Each frame detected the red gauge with roughly 0.85-0.87 confidence, so camera acquisition, framing, and gauge detection were not the failure layer.
- On the exact failed frame, normal full-frame inference detected A at about 0.548 and red at about 0.860. The gauge-anchored 320 crop saw A only at about 0.072, below the dedicated 0.15 letter cutoff.
- `YOLODetector.detect()` replaced `full_letters` unconditionally with gauge-anchored letters whenever a gauge existed. An empty crop result therefore discarded a valid high-confidence full-frame letter and surfaced `letter_not_detected`.
- The narrow production rule is: keep gauge-anchored letters when any are present because they intentionally correct full-frame confusion; only when the anchored list is empty, fall back to the already thresholded full-frame letters. Do not lower the global or crop thresholds for this case.
- After the fallback, the saved failure frame returns `A/high/red`; a new live no-audio batch at the same pose returns the same result with 3/3 agreement. This validates the post-processing fix on the target Jetson/model/camera without changing waypoint geometry or playing a duplicate announcement.

## 2026-08-12 - Dedicated four-observation acceptance result

- The final supervised L6 run completed the validated nine-point interleaved route with 9/9 successful Nav2 segments and terminal `FINISH`; TaskManager was disabled by construction.
- Observation order followed route geometry as C, A, B, D, while the completeness contract correctly normalized the final set to A/B/C/D. Each waypoint had one request, one successful audio-backed result, a 3/3 vote, and a continuous one-second stop gate.
- The A observation that previously failed now passes on the actual route with `letter_confidence=0.3075`, confirming the full-frame fallback under live motion-to-stop conditions rather than only offline replay.
- Cleanup and provenance are part of acceptance: both exit codes were 0, no relevant process/container remained, and the formal Jetson checkout was clean at `40ebb15`.

## 2026-08-12 - One-click inspection entrypoint boundary

- The direct operator command is `bash scripts/start_inspection_one_click.sh` from the formal deploy root. It selects the accepted full four-observation mode and supplies the launcher's motion-confirmation flag automatically.
- “No check” means no separate operator preflight command and no wrapper-side mode selection. It does not remove the underlying runtime safety gates or automatic cleanup that prevent conflicting stacks, stale odometry, nonzero arrival inspection, duplicate announcements, and continued motion after failure.

## 2026-08-12 Phase 93 cone-scan acceptance findings

- The previous `scan_returns_are_healthy()` use conflated a healthy clear scene with a sensor failure. The corrected contract separates depth coverage health from obstacle-return geometry: all-infinite ranges are valid clear space, while any finite returns still require at least three contiguous beams.
- The exporter must apply the short-run filter before setting the source health flag. The Foxy bridge independently repeats the observation-geometry check so malformed direct UDP packets with one or two finite beams fail closed.
- The existing bridge already drains its UDP socket and accepts only the newest datagram per poll; the L3 probe should verify this through the published health sequence and `drained_old` counter rather than adding another receiver implementation.
- A self-contained L3 probe can exercise the installed production bridge and gate entry points safely by overriding every topic into `/cone_l3/*` and using UDP port 19012. No actuator-facing subscriber or production `/cmd_vel` topic is needed.
- The isolated probe must own its DDS boundary rather than depend on a caller's shell state. It now forces `ROS_LOCALHOST_ONLY=1`, rejects production domain 0, and defaults to test domain 93 in addition to loopback UDP 19012 and `/cone_l3/*` topics.
- The standalone scenario sender is also part of the safety boundary: defaults alone are insufficient. It now accepts only numeric IPv4 loopback targets and rejects production port 19002, so an operator cannot redirect synthetic healthy frames into the production bridge.
- `ros2 run` may wrap the actual node process, so cleanup must signal the entire process group and escalate from SIGINT to SIGTERM/SIGKILL. Graceful SIGINT wrapper exits (`-2` or `130`) are recorded as evidence rather than misclassified as crashes; forced or crashed cleanup downgrades the run to failure.
- Runtime evidence must preserve the exact failing step. The probe now appends a failed JSON step before propagating an exception and closes a newly opened log handle if process creation itself fails.
- L2/L3 field acceptance is deliberately split: configure-only proves the Foxy plugin class loads without activation; isolated L3-S proves transport/gate fault behavior; D455 L3-D separately proves graph ownership, real rate/QoS/source age, local-only costmap behavior, gate/mark timing, and stationary resource impact.

## 2026-08-12 Phase 94 Jetson L2 findings

- The formal Jetson deploy remains clean at `b1ae5af` and does not contain Phase 91/93. The exact local acceptance commit `6a69b93` was therefore checked out into a separate worktree `/home/superwfx666/cone-l2-l3-acceptance-6a69b93`; the formal checkout was not switched or modified.
- Jetson system Nav2 is Foxy `0.4.7`; `ros2 pkg list`, dpkg, filesystem, and plugin XML searches found no `nonpersistent_voxel_layer` or `NonPersistentVoxelLayer` registration.
- The existing `$HOME/nav2_foxy_overlay_ws` contains only `nav2_behavior_tree` and `nav2_bt_navigator`. Sourcing its global `setup.bash` also reintroduces the legacy `/home/superwfx666/quadruped-robot-competition-nav2-dwb/install` prefix. L2 must instead start from `/opt/ros/foxy` and source narrowly scoped `local_setup.bash` overlays.
- Upstream `SteveMacenski/nonpersistent_voxel_layer` tag `2.2.1` resolves to commit `0704666393ef1747562a93d934923fa45a3a8d4b`, while `foxy-devel` has advanced. Reproducible acceptance should pin the tag commit, not build a moving branch.
- Jetson L2 configure-only passed with the pinned 2.2.1 plugin overlay and acceptance repo `local_setup.bash` on localhost domain 93. The lifecycle path was exactly `unconfigured -> inactive -> finalized`; no `activate` transition occurred.
- The live local-costmap plugin order was `static_layer`, `cone_obstacle_layer`, `inflation_layer`. The cone layer resolved to `nav2_costmap_2d/NonPersistentVoxelLayer` with `/cone_obstacle/scan`, `LaserScan`, marking enabled, clearing disabled, and Foxy obstacle/raytrace ranges 2.5/3.0 m.
- `/cone_l2/cmd_vel` had one controller publisher and zero subscribers while inactive. Final cleanup left domain 93 empty and no controller/Nav2/Lite3/velocity/actuator process; the unrelated pre-existing D455 container remained untouched with the same ID.
- Formal deploy provenance remained clean at `b1ae5af`; the isolated acceptance worktree remained clean at `6a69b93`. L2 is GO, while L3-S and real D455 L3-D remain unexecuted.

## 2026-08-12 - Lite3 ultrasonic cone-avoidance research

- The official Deep Robotics Lite3 product page describes the built-in perception feature as front/rear stop avoidance, but does not publish angular resolution, field of view, range limits, update rate, or measurement uncertainty. This supports a collision-stop role, not a claim that it can replace a 2-D local obstacle sensor.
- The bundled Lite3 transfer protocol contains two scalar readings in `RobotState.ultrasound[2]`, but the current ROS2 bridge publishes only `ultrasound[1]` as `/us_publisher/ultrasound_distance` (`std_msgs/Float64`). It drops the second reading and supplies no header, sensor frame, field of view, min/max range, covariance, or documented front/rear mapping.
- A single scalar forward distance cannot tell DWB whether a cone is left or right, cannot represent two randomly placed cones, and cannot populate the existing 180-beam +/-45-degree `LaserScan` obstacle geometry. It is therefore unsuitable as the sole source for the current local-costmap avoidance design.
- Nav2 officially provides a Range Sensor Layer for sonar, IR, and other 1-D sensors, but it expects directional range topics and sensor geometry. A usable integration requires publishing `sensor_msgs/Range` with a verified frame, radiation type, field of view, min/max range, timestamps, and freshness handling.
- The practical architecture is D455 depth/LaserScan as the primary DWB obstacle source plus the front ultrasonic reading as an independent short-range slow/stop safety channel. Replacing D455 should be considered only after exposing both ultrasonic channels, experimentally mapping front/rear and blind zones, measuring rate/latency/dropouts on the walking robot, and proving cone detection over lateral offsets and approach angles.
- The user confirmed the applicable rule allows any sensor already on the robot, so the Lite3 built-in ultrasonic sensors are legal for this event. The remaining decision is purely technical: use them as short-range protection unless their directional coverage is experimentally proven sufficient for path planning.
# 2026-08-12 Phase 95 cone avoidance L3-S preparation
- The next cone-only acceptance stage after L2 GO is runbook section 5, L3-S isolated synthetic scanning.
- The accepted probe fixes isolation to localhost ROS domain 93, loopback UDP port 19012, and `/cone_l3/*`; it rejects production domain 0, production UDP port 19002, non-loopback targets, and a missing explicit no-actuator confirmation flag.
- L3-S covers graph isolation, three-frame warmup, healthy clear scan, isolated/short/unhealthy/stale/future/CRC/sequence faults, latest-only backlog, stream restart warmup, and silence deadline.
- Acceptance requires complete JSON evidence, all steps passing, maximum recorded fail-closed latency no greater than 250 ms, graceful child cleanup, and exactly one subscriber on `/cone_l3/cmd_out` (the probe itself).
- ByteRover CLI/MCP is unavailable in this host session, so no L1-3 recall was possible; the decision above comes from the repository PWF, accepted runbook, code, and contract tests.
- Jetson L3-S completed with GO in `/home/superwfx666/competition_logs/cone_l2_l3/20260812_183742_phase95_l3s`: three runs each passed all 13 steps, graph isolation, JSON validation, graceful cleanup, and zero-residual checks.
- Fault injections other than silence closed in about `48.770-49.070 ms`. Silence closed in `249.298/249.254/249.221 ms`, consistently below but very near the `250 ms` acceptance limit; this is a measured timing-risk observation for L3-D, not an L3-S failure under the current contract.
## 2026-08-12 - L3-D reconnect state after renewed physical isolation

- The operator's physical isolation confirmation is current, but it does not establish Jetson runtime state.
- Jetson Tailscale node `100.126.48.49` was offline (`last seen 21m ago`) during the reconnect attempt. The SSH preflight timed out before executing any remote command.
- Therefore the scheduled watchdog result, B2 container state, historical `d455_yolo_repro_20260811` state, D455 ownership, and ROS graph are all unverified current facts.
- Safety consequence: do not resume mode B or ask for cone placement until connectivity returns and the complete restoration/provenance gate passes.

## 2026-08-12 - Historical D455 restoration verification

- The reconnect gate established current physical isolation independently of the earlier operator statement: `eth0` had no carrier/address, Lite3 was unreachable, no actuator UDP listener existed, and `/cmd_vel` was absent.
- The scheduled watchdog had expired without restoring the historical D455 container. Explicit restoration of the existing container was therefore necessary and completed without recreation or configuration changes.
- The original D455 service is operational: color measured roughly 29-30 Hz and depth roughly 60 Hz. A first empty `ros2 topic list` was a transient Fast DDS discovery result, not a camera failure; bounded daemon reset/retry immediately found both topics and their single publishers.
- The derived L3-D cone image remains present with the exact previously validated image ID. No rebuild or package mutation is required for the resumed B run.

## 2026-08-12 - B3 runtime recovery and scene state

- The cone scan path and odometry path have independent DDS discovery timing. A healthy Humble cone scan does not prove the Host odometry bridge survived startup; `/odom` publisher and TF must be checked separately before accepting Nav2/costmap state.
- A container-local dangling or host-absolute symlink can make `docker cp <regular-host-file> container:/same-path` fail because Docker follows the existing destination link. Removing only the invalid container-local temporary link before the copy restored deterministic exporter startup.
- Once odometry recovered, the existing lifecycle manager completed activation without restarting D455 or the Nav2 launch. This preserved single camera ownership while recovering the Host-only path.
- Current scan geometry is dominated by nearby scene objects rather than a clear floor/view: 26 of 119 finite returns are under 0.5 m and the center sector includes multiple approximately 0.31-0.49 m returns. It is unsuitable as the required clear-before acceptance state.
- The local costmap is publishing and currently marked (`lethal_count=259`, `inscribed_count=562`), while the global costmap publishes independently. A fresh clear baseline must be captured only after the operator removes nearby obstacles and the local dynamic marks settle.

## 2026-08-12 - B3 clear-baseline interpretation

- A valid clear acceptance baseline does not require every scan beam to be infinite or every costmap cell to be zero. The stationary setup has repeatable lateral/fixed geometry and map/footprint inflation; the relevant criteria are a clear center placement corridor plus stable repeated local data before introducing the cone.
- The center 20 beams were all infinite after scene clearing, and three local snapshots were exactly identical. This is a stronger baseline for the cone-in delta than comparing raw lethal counts to zero.
- The global costmap baseline is now captured before cone introduction, enabling a strict data-array SHA256 equality check after cone removal.

## 2026-08-12 - D455 mounting TF semantics

- The authoritative running mount TF is `base_link -> camera_link`, translation `(0.080, 0, 0.493) m`, RPY `(0, +0.523599, 0)` and quaternion `(0, 0.258819, 0, 0.965926)`.
- In REP-103 body coordinates (`+X` forward, `+Y` left, `+Z` up), `+30 deg` pitch sends the camera forward direction toward `-Z`; it is therefore the intended downward tilt, not an upward tilt.
- The cone scan target is `base_link`, so the mount extrinsic is applied in the Humble pointcloud-to-laserscan TF lookup. The Host odometry bridge only uses its matching extrinsic for camera-frame odometry; current cuVSLAM output is already base-frame odometry and correctly follows the passthrough branch, preventing double compensation.

## 2026-08-12 - Real cone geometry and local-only marking

- With the cone center axis placed `0.75 m` horizontally from D455, the stable scan profile across the cone body was approximately `0.742-0.822 m` over about `-5 deg` to `+8 deg`. This agrees with the physical placement once surface width, angular sampling, depth noise, and base-frame projection are considered.
- The approximately `0.286-0.303 m` returns at more negative angles belong to the pre-existing near-field/lateral response, not to the cone center. Acceptance comparisons must use the clear-scene delta and the coherent cone beam cluster rather than the absolute minimum of the whole scan window.
- The real cone increased local costmap lethal cells `240 -> 246` and nonzero-known cells `548 -> 716`, while the global costmap data hash stayed exactly `fb91c2e924a3da82df421bfd9938ca0e10643a3368ad7766513302550086b885`. This validates the intended local-only dynamic obstacle ownership for the cone module.

## 2026-08-12 - L3-D final acceptance findings

- Real D455 local clearing is comfortably within contract: center clear scan appeared in `51.256 ms`, and the local data array returned byte-for-byte to the formal clear baseline in `259.780 ms`. The global data array did not change across clear/cone/clear.
- Foxy rosbag2 requires an explicit BEST_EFFORT QoS override for `/cone_obstacle/scan`; topic discovery alone is insufficient because a bag may list the topic while storing zero messages. The checked-in `configs/ros/cone_rosbag_qos.yaml` recorded 55/55 scan and health messages in the recovery proof.
- A generic cleanup helper that publishes zero Twist is unsuitable for a no-command acceptance even when `/cmd_vel` has zero subscribers. L3-D teardown should signal only the known launcher/process tree and exact temporary container, then independently restore and validate the pre-existing D455 owner.
- L3-D passes all stationary gates: coherent `0.75 m` real-cone detection, local-only mark, sub-second clear, stable scan/health, A/B odometry drop below 10%, zero actuator subscribers, no goal or speed publication during the formal B3 sequence, clean teardown, and verified historical D455 restoration.
## 2026-08-13 Phase 97 formal cone deployment smoke
- User-provided starting state: GitHub target `941bed6`; formal Jetson deploy expected at `b1ae5af`; accepted cone image content ID expected as `sha256:3062ea205303487605f71c2c8f9c83fba060ac4ff9c32747dfaacdd8f657a852`; historical D455 container `d455_yolo_repro_20260811` expected running; Lite3 link expected physically disconnected.
- Local checkout is exactly `941bed6503f22d76a7bc9017757876e047f9d03c`.
- Scope is only formal stationary cone-avoidance deployment and restoration. L4 motion, Lite3 reconnection, velocity bridge, TaskManager, auto-advance, and goal publication are excluded.
## 2026-08-13 Phase 98 cone persistence and scan-height implementation findings

- Before Phase 98, `configs/navigation/nav2_cone_obstacles.yaml` was a local-costmap-only overlay with accepted inflation `0.30/3.0` and `cone_scan.observation_persistence: 0.0`; Phase 98 changes only persistence to `1.5` in the formal cone behavior.
- `scripts/start_cuvslam_rviz_gui.sh` currently interpolates scan geometry directly into a generated Python launch. `CONE_SCAN_MIN_HEIGHT` therefore needs strict decimal validation before interpolation, not only an assignment.
- The runtime evidence file `runtime_config.env` already snapshots the other `CONE_SCAN_*` values, so the new minimum height belongs in the same block.
- The accepted local costmap runs at 5 Hz update and 2 Hz publish rates. A clearing contract measured from the final cone-bearing source scan must include the 1.5 s buffer lifetime plus update/publication scheduling; `CONE_OUT` is only an operator marker and cannot be the authoritative start timestamp.
- Global costmap data hashing remains a required invariant. Static local clear-before/clear-after hashing remains meaningful after the observation buffer has fully expired; rolling/moving L4 evidence should use spatial/count metrics instead.
- Candidate inflation and DWB values must be isolated from `configs/navigation/nav2_params.yaml` and the default `nav2_cone_obstacles.yaml`. A separate complete cone overlay can be selected through the existing `cone_params_file` launch argument for controlled experiments.
- A decimal can pass numeric range validation but still be invalid as a generated Python literal if it contains a leading zero such as `00.05`. The shell validator must enforce canonical unsigned decimal syntax before launch generation, in addition to the `[0.0, 1.20)` range check.
- `pointcloud_to_laserscan.min_height` must remain a floating-point ROS parameter. The environment format therefore requires a decimal point (`0.0`, not `0`) so the generated Python launch never changes its parameter type to integer.
- The local host has no standalone PyYAML package, but `invoke.vendor.yaml` is available and parsed both cone overlays successfully. It confirmed floating `observation_persistence=1.5`, local-only structure, and the experiment critic/inflation values.

## 2026-08-13 Phase 99 initial Jetson preflight

- Jetson connectivity is available at `superwfx666@100.126.48.49`; Tailscale used DERP(hkg) at roughly 211-229 ms.
- The physical-isolation runtime indicators pass: `eth0` is DOWN/NO-CARRIER, `/sys/class/net/eth0/carrier=0`, Lite3 `192.168.1.120` is unreachable, UDP 19002 is unused, no relevant navigation/bridge/TaskManager/Lite3 process exists, and `/cmd_vel` is absent.
- `/home/superwfx666/quadruped-robot-competition-nav2-dwb` is a highly dirty linked worktree at `72e3833`, not the formal deployment checkout. The authoritative formal checkout is `/home/superwfx666/quadruped-robot-competition-nav2-dwb-deploy`, branch `codex/formal-cone-941bed6`, at exact `941bed6`; only the latter is eligible for Phase 99.
- Historical container `d455_yolo_repro_20260811` still has exact ID `cadfa809e7b2...`, image `d455-yolo:pick-test-20260811`, restart policy `no`, host network, and OOM=false. Its `17:38:16Z` finish followed by the host boot at approximately `17:41:12Z` corroborates that exit 137 came from the user-reported Jetson reboot, not a Phase 99 command.
- Attempt 1 proved that sourcing only the Nav2 BT overlay through `NAV2_OVERLAY_SETUP` omits the separately pinned costmap plugin: plugin parameters remain undeclared and controller configuration fails even though the launch process and node names exist. A launcher's completion banner is not lifecycle evidence.
- The evidence-local combined setup preserves narrow provenance while satisfying both runtime dependencies. In retry 2, the controller environment contains the pinned plugin, BT overlay, and formal deploy, and the process actually maps the pinned `libnonpersistent_voxel_layer_core.so`; all managed nodes then become active.
- Retry-2 live parameter inspection excludes accidental selection of the experimental overlay: the active controller reports formal `1.5 / 0.30 / 3.0 / 32 / 32 / 0.02`, while the gate remains `3 / 0.20` and generated Humble launch remains `min_height=0.05`.
- A healthy 10 Hz scan alone does not establish a clear baseline. The current stationary scene has repeatable center-sector returns down to approximately `0.285 m`; local/global clear hashes must be captured only after the operator clears the view and repeated local snapshots stabilize.
- With `observation_persistence=1.5 s`, complete local costmap byte-hash restoration can occur one publish interval after the corresponding cone region has already disappeared. Round 1's cone consensus region cleared at `1989.951 ms`, while the full hash returned at `2589.949 ms`; the runbook correctly treats these as separate requirements.
- A strict connected-region comparison needs spatial identity, not only total lethal/nonzero counts. The cone-in consensus was one 156-cell component; at `1989.951 ms` only one edge cell overlapped that footprint and the remaining 20-cell component was in a different near-field area, so the corresponding cone region was absent.
- Docker may reorder the `Mounts` array after restarting an existing container. Restoration comparison must normalize mounts by destination/source before declaring drift; all eight historical D455 mounts and every substantive configuration field were unchanged.

## 2026-08-13 Phase 100 formal startup-chain findings

- The formal launcher sourced its only Nav2 overlay after the D455/cuVSLAM startup and treated it as optional. The pinned costmap plugin was therefore impossible to validate before camera ownership, and the completion banner had no lifecycle dependency.
- A reproducible clean-shell chain must use independent `local_setup.bash` inputs in this order: Foxy, pinned `nonpersistent_voxel_layer`, Nav2 BT overlay, formal deploy. Prefix checks alone are insufficient; the preflight also verifies the plugin XML/`.so`, and the runtime gate verifies the controller's `/proc/<pid>/maps` entry.
- Cone startup success now requires all five Foxy managed nodes active, the expected `/cmd_vel` subscriber count, compatible scan/health QoS endpoints, live official parameters, at least 8 Hz scan, and a continuously `ready` strictly advancing health stream. A log banner alone is no longer success evidence.
- Phase 100 intentionally leaves cone perception, formal/experimental YAML values, and safety-gate defaults unchanged. The new health probe is read-only and publishes no ROS messages.

## 2026-08-13 Phase 101 cold-start findings

- A source checkout can be current while an `ament_python` install is stale. `ros2 pkg executables` plus actual `pkg_resources.load_entry_point` before device access is the relevant entry-point provenance gate; source HEAD alone is insufficient.
- Sourcing an overlay and then assigning a system-only `PYTHONPATH` silently defeats the overlay for Python console scripts even though `ros2 pkg prefix` still reports the expected package. Preserve the environment produced by `local_setup.bash`.
- Foxy `ros2 topic info --verbose` prints reliability as `RMW_QOS_POLICY_RELIABILITY_BEST_EFFORT/RELIABLE`. Runtime contracts that parse CLI text must handle those long names as well as short forms while still requiring every endpoint to match.
- With `colcon build --symlink-install`, the installed plugin `.so` may resolve to the workspace build directory in `/proc/<pid>/maps`. Provenance should compare canonical `readlink -f` file identities, not require the mapped pathname to contain the install prefix.
- The accepted clean-shell launch proved the Phase 100 gate end to end: source chain, entry points, lifecycle, QoS, live parameters, pinned library, 10 Hz scan, continuous health, and zero actuator subscribers all passed without a temporary combined setup.
- A top-level launch/root signal did not reap every Python/Nav2 child in this environment. Exact teardown evidence must enumerate and terminate identity-checked survivors before declaring cleanup complete.
## Phase 102 minimal hardware acceptance - 2026-08-13
- Phase 100/101 evidence is sufficient to skip repeated stationary cone-in/out testing. The next discriminating evidence is one supervised, low-speed, short-goal physical response with the cone in the path.
- Jetson preflight at `2026-08-13T04:08:35+08:00` found formal HEAD `025b3200f89e4be6714157ef1b9ad708e73037c6`, the historical D455 container as sole camera owner, Lite3 physical link down, and no command UDP listener. A single orphan formal `map_server` from 03:57 was precisely identified and removed without broad cleanup.
- The existing full-route and inspection launchers are too broad for the first cone motion check. Use the formal startup with cone avoidance plus the proven Lite3 bridge/motion preparation, then send exactly one goal whose precomputed Nav2 global path is approximately 4-5 m. Do not send a route or second goal automatically.
- The official start prior `(4.65, 0.75)` to existing `pos1_left_clear (0.60, 2.90)` has a 4.59 m Euclidean separation, but the preview waypoint file explicitly forbids treating that chord as a production-clear path. Use it only as a candidate destination; accept it only after the live planner returns a valid approximately 4-5 m path and the operator confirms the entire corresponding physical corridor is clear except for the test cone.
- ROS 2 motion-safety guidance requires fresh on-site confirmation and end-to-end stop capability before reconnecting/enabling the actuator chain. `/cmd_vel` state alone is insufficient proof of a physical stop.
- Phase 102 physically demonstrated the desired fail-safe half of cone avoidance: the robot approached the cone, did not collide, and stopped making forward progress. It did not demonstrate bypass; the operator saw sustained stepping in place before Nav2 ABORTED.
- The abort was controller-generated, not remote cancellation or timeout: `controller_server` reported `No valid trajectories out of 335`, then `bt_navigator` reported `Navigation failed` and ABORTED. The goal still had `3.861 m` position error after only `0.843 m` physical displacement.
- Sensor transport remained healthy during the failure (1188 scans at `9.8936 Hz`, zero unhealthy/error samples). The next investigation should focus on local-costmap footprint/inflation geometry and DWB trajectory feasibility near the cone, especially the forward-only `max_vel_y=0` configuration and the observed close-range heading, rather than repeating startup, QoS, or stationary cone tests.
- Do not claim Phase 102 as L4 bypass GO. The accurate claim is: collision prevention GO, bypass/local trajectory generation NO-GO, single attempt only.
- The operator's footprint/inflation explanation is directionally correct but needs a cost-class distinction. Ordinary inflated cells bias DWB scores and do not by themselves make a trajectory illegal; lethal/inscribed cells intersecting the footprint, or every sampled swept footprint entering those cells, produce the observed all-invalid condition. No synchronized abort-time costmap snapshot was captured, so actual footprint overlap is a high-confidence hypothesis rather than directly proven geometry.
- The configuration creates a predictable local-minimum chain: the global costmap is static-only and therefore replans through the cone every second; local DWB has a 1.5 s horizon (only about 0.36 m at 0.24 m/s), no lateral motion (`max_vel_y=0`), no reverse (`min_vel_x=0`), strong path-following critics, and a low non-collision obstacle score (`ObstacleFootprint.scale=0.02`). It can approach too closely before all forward/turning arcs become illegal.
- The observed stepping has a specific command signature: final samples were `vx=0` with `wz=+/-0.015789 rad/s`. With `max_vel_theta=0.30` and the even `vtheta_samples=20` grid, these are the two samples nearest zero; a true zero angular sample is not on that symmetric even grid. Changing to an odd count can remove this dithering symptom, but cannot by itself create a bypass trajectory.
- Padded footprint half-extents are approximately `0.37 x 0.27 m`; the circumscribed corner radius is about `0.458 m`. Near a cone, turning in place sweeps the corners, so rotation may become illegal before the body visibly touches the cone. The configured `inflation_radius=0.30 m` is only slightly beyond the padded inscribed radius; increasing inflation alone is not a complete fix and may only shift where the local minimum appears.

## Phase 103 cone bypass configuration findings - 2026-08-13
- Adding a `global_costmap` block to the cone YAML alone would not have fixed runtime behavior. `launch/navigation.launch.py` originally split planner_server only by `enable_depth_pipeline`; cone mode followed the base-only planner branch and never loaded `cone_params_file`, even though controller_server did. The planner must have an explicit static/depth/cone three-way split.
- Runtime provenance must cover both costmap owners. `controller_server` owns the local costmap and `planner_server` owns the global costmap, so formal startup now needs both processes to map the canonical pinned `NonPersistentVoxelLayer` library before reporting GO.
- The previous L2/L3 contract that required global costmap data to remain unchanged during cone presence directly conflicts with cone-aware global planning. The replacement contract is: global cone-in data differs from the clear baseline, then global clear-after returns to that baseline after the 1.5 s observation buffer and publication delay.
- The formal cone controller overlay uses `ObstacleFootprint.scale=1.0` and `vtheta_samples=21`, while base/static navigation remains at `0.02/20`. Forward-only/non-holonomic limits remain unchanged (`min_vel_x=0`, `max_vel_y=0`) because reverse and lateral gait behavior have not been validated on Lite3.

## Phase 104 fast Jetson readiness findings - 2026-08-13
- The Phase 103 runtime-loading fix is proven at no-actuator level: planner_server and controller_server both receive `nav2_params.yaml` plus `nav2_cone_obstacles.yaml`, both map the same canonical pinned `NonPersistentVoxelLayer` library, and both costmaps expose the buffered cone layer live.
- A long remote wrapper timeout did not mean startup failed. The launcher was progressing through unusually slow Foxy CLI calls and later emitted its own GO; preserving the live stack and reading the append-only snapshot/log avoided an unnecessary four-minute D455 restart.
- Current command ownership is suitable for the pre-motion boundary: the cone safety gate is the sole `/cmd_vel` publisher, `/cmd_vel` has zero subscribers, and no Lite3 bridge/transfer sender or actuator UDP endpoint is running. Physical Lite3 connectivity alone is not actuator enablement, but it makes starting any bridge a motion-authorizing step requiring fresh operator confirmation.

## Phase 105 cone-aware global-plan retest findings - 2026-08-13

- The Phase 103 global-layer change materially altered behavior: the single goal traversed `4.605 m` straight-line displacement and reached `0.374 m` from `pos1_left_clear`, versus Phase 102 stopping after `0.843 m` with `3.861 m` remaining. Global costmap evidence changed across the run (24 snapshots, 2 unique hashes), so cone-aware global ownership was active rather than merely configured.
- The retest still ended in the same controller failure class, now `No valid trajectories out of 351`. Global cone visibility removed the early structural trap but did not guarantee terminal local feasibility under the unchanged forward-only/no-lateral envelope and footprint geometry.
- The synchronized costmaps close the prior evidence-capture gap for this run: 23 local and 24 global snapshots span the goal and post-abort state. They permit offline footprint/lethal-cell correlation, but physical cone clearance cannot be claimed without the supervising operator's observation.
- Stop evidence is bounded precisely: after abort, about one minute of bridge diagnostics showed fixed motion count, continuous three-axis zero, and `udp_errors=0`; final ROS/OS state has no actuator subscriber or process. The bridge did not log its normal shutdown zero burst because SIGINT to the `ros2 run` wrapper did not reach the child before identity-scoped termination, so graceful shutdown-burst evidence is absent.

## 2026-08-13 Phase 105 后续诊断：锥桶前原地踏步/小角度调头的根因（配置分析，未改动）
用户现象：机器人贴近锥桶后才开始原地踏步式小角度调整偏航，绕行虽成功但极慢；期望在远处就开始预调。

配置证据（nav2_params.yaml + nav2_cone_obstacles.yaml）：
1. 感知进图距离上限 2.5 m：cone_scan `obstacle_range: 2.50`（scan 链路本身 depth max_range_m=3.0 封顶）。起点距锥桶约 4.6 m 时锥桶根本不在代价地图里，全局路径是直线，不可能提前绕。
2. 全局/局部膨胀半径过小：`inflation_radius: 0.30`，`cost_scaling_factor: 3.0`。footprint 0.70x0.50，半宽 0.25 m、角部外接半径约 0.43 m。膨胀 0.30 仅约等于半宽，NavFn 路径贴锥桶走、几乎不提前弯，且角部实际过不去 → DWB ObstacleFootprint 在近处才批量否决前向轨迹。
3. DWB 前瞻只有约 0.36 m：`sim_time 1.5 s x max_vel_x 0.24 m/s`。局部避障只能在锥桶跟前才"看见"碰撞。
4. 路径吸附权重过强：`PathAlign.scale=32 / PathDist.scale=32` vs `ObstacleFootprint.scale=1.0`（正式 overlay），机器人被钉在贴锥直线路径上，不敢提前横向偏出。
5. 转向慢且允许原地旋转：`max_vel_theta=0.30 rad/s`、`min_vel_x=0`。前向被否决时唯一可行解是小角速原地旋转，转一点后 PathDist/GoalDist 又把它拉回前进，再次被否决 → 表现为踏步+反复小角度调头。Oscillation critic 进一步限制来回转向。

结论：这是"感知进图晚(2.5m) + 全局膨胀小(0.30m)路径贴锥 + DWB 前瞻短(0.36m) + 路径吸附强(32)"四因素叠加，避障决策被压缩到锥桶前最后约 0.4 m 内完成，只能靠原地旋转凑可行轨迹。
候选修复（未执行）：A) 正式 overlay 全局/局部 inflation_radius 0.30→0.60~0.75、cost_scaling_factor 3.0→2.0；B) obstacle_range 2.50→3.00（顶到 scan 链路上限；若要 4.5m 起点即见锥需同步提高 depth max_range_m 与 range_max，D455 远距噪声需评估）；C) sim_time 1.5→2.5~3.0；D) PathAlign/PathDist 32→16（实验 overlay 已有此方向：0.45/2.0+16/16，可作参考但幅度可能仍不够）。
Source: nav2_params.yaml / nav2_cone_obstacles.yaml / nav2_cone_obstacles_experimental.yaml / depth_relay_publisher.py 配置阅读 + Phase 105 abort 证据
## 2026-08-13 - Phase 99 real-cone costmap placement visualization

- A corrected stable-frame extraction shows the Phase 99 cone created one 163-cell local-costmap component (bbox `[31,14,48,25]`), matching the formal multi-frame consensus (156 cells, bbox `[31,14,47,25]`).
- The component center is 0.741 m from the rolling-window center; the synchronized base_link LaserScan cone centroid is 0.747 m, a 6 mm radial difference. This strongly supports correct range placement in the local costmap.
- The scan cluster spans -6.5 to +7.5 degrees and 0.720-0.816 m. The 0.286-0.303 m scan returns are pre-existing near-field response and are visualized separately, not classified as the cone.
- Phase 99 did not record `/tf`; therefore the dataset cannot by itself prove scan-to-odom angular placement. It also used a static-only global costmap, so the visualization must not be used to validate the Phase 103+ global cone layer.

## 2026-08-13 - Phase 109 Jetson process/deploy state

- The formal deploy is already synchronized to Phase 106 commit `725c122`; Jetson reflog records the fast-forward at `20:01:23 +08:00`, and the checkout remains clean after the later reboot.
- Jetson boot time is `20:59:31 +08:00`. This explains why the earlier hour-old vision/arm processes disappeared without requiring process termination by this session.
- The dirty vision worktree itself persists at `/home/superwfx666/worktrees/quadruped-vision-yolo-refactor` (`feature/vision-change-jetson-test`, `608d93e`). Its working changes must not be cleaned, reset, or merged into the formal deploy implicitly.
- Current execution-chain state is inert: no `/cmd_vel` graph, no relevant ROS nodes/processes, no containers, and no UDP listeners on Lite3 ports `43893` or `19012`.

## 2026-08-13 - Phase 110 Phase 106 field outcome

- The Phase 106 formal cone profile completed the requested one-shot `obstacle_cross_target=(1.05,0.75,pi)` NavigateToPose action with `SUCCEEDED` in about 20.7 seconds while a cone was intentionally placed on the path.
- The controller still encountered one `No valid trajectories out of 351` episode and invoked one recovery, but unlike the prior aborted run it recovered and completed the action. Final action feedback was within the configured broad goal tolerance (`0.249 m` remaining), not at the exact requested coordinate.
- Software evidence proves the action result, bounded command output, zero UDP errors, and full teardown. Whether the physical clearance/arc around the cone was visually satisfactory still depends on the on-site operator's observation.

## 2026-08-13 - Phase 111 repeatability outcome

- The identical repeated cone-path goal also succeeded, giving two consecutive action-level successes on `725c122`.
- The repeat required five recoveries versus one in Phase 110 and ended at a different tolerated pose (`1.244,0.876` versus `1.186,0.958`). The behavior is action-success repeatable but not trajectory/recovery-count deterministic.

## 2026-08-14 - Phase 112 staged depth shutdown findings

- RealSense ROS `4.54.1` / librealsense `2.54.1` on the competition Jetson accepts dynamic shutdown of `enable_depth`, `pointcloud.enable`, and `decimation_filter.enable` through `/camera/camera/set_parameters`; live readback through `GetParameters` is required before the mission transition is acknowledged.
- Disabling those three parameters stops depth images, pointclouds, and the cone LaserScan chain while preserving Infra1, Infra2, IMU, and cuVSLAM odometry. The measured no-actuation run reduced container CPU from about 367% to 216%; memory remained broadly unchanged.
- Re-enabling the depth pipeline can temporarily disturb visual tracking and produce frame-interval warnings. Any future return to cone avoidance must occur while stopped and must wait for fresh localization/depth health before motion resumes.
- The cone safety gate must not bypass merely because the requested mode is `DISABLED`. It first requires a fresh acknowledged controller status, verified false readback from both Nav2 cone layers, successful local/global costmap clears, and a valid request ID. After that point only scan health is bypassed; stale command input still forces zero velocity.
- The Jetson Foxy `rclpy` does not provide `rclpy.parameter_client.AsyncParameterClient`. The portable contract in this repository is direct asynchronous clients for `rcl_interfaces/srv/SetParameters` and `GetParameters`; therefore `rcl_interfaces` is an explicit runtime dependency of the root package.
- Verification reached L4 with hardware powered and no actuator path. It proves live parameter control, retained localization streams, Nav2 layer/readback/clear behavior, and resource reduction; it does not prove the complete timed cone-to-WHZ mission under motion, which remains an L6 supervised field test.
- A single low-speed odometry sample is insufficient evidence that the robot is stopped. The transition now requires a continuous stationary interval (`depth_transition_settle_duration_sec`, default `1.0 s`); odometry staleness, speed-limit violation, clock regression, or an active navigation goal resets the interval before any resource request is issued.
- The depth shutdown is intentionally mission-scoped rather than permanent. The existing `BEFORE_WAYPOINT grab_area_approach -> MANIPULATION` milestone remains active after inspection transit, so later manipulation can re-enable the depth pipeline while stopped and wait for end-to-end readiness.
- The test-only localization wait and the resource shutdown contract are separate. `--skip-depth-disable-health-check` disables the additional IR/IMU/cuVSLAM/host-odom waiting for a timed run, but it does not skip RealSense false readback, cone-layer false readback, costmap clears, mode acknowledgement, or the command watchdog.
- Final handoff verification is L1 plus the previously captured L4 evidence: `24/24` focused tests and `264/264` total tests pass, along with Python/Bash/XML/diff checks and a zero-issue ROS validator. The only skipped generic check is Nav2 YAML parsing because PyYAML is absent locally; no new dependency was installed.

## 2026-08-14 Phase 113 deployment and startup-gate findings

- Git state must be verified against `git ls-remote`, not inferred from a local push attempt: local `d5f6501` and the tracking ref were one commit ahead while GitHub still exposed `725c122`.
- A verified incremental Git bundle can synchronize a clean Jetson checkout without relying on GitHub availability. The authoritative deploy accepted a strict fast-forward from `725c122` to `d5f6501`, with rollback branch `codex/pre-phase113-725c122` retained locally on Jetson.
- The formal install is a symlink install: runtime provenance for changed Python nodes resolves under `<deploy>/build/quadruped_robot_competition/src/...`, while `ros2 pkg prefix quadruped_robot_competition` resolves under `<deploy>/install/quadruped_robot_competition`; both paths must be checked.
- TaskManager's `auto_advance=false` disables only its debug bypass. In the formal START path, fresh `/odom` for more than one second still advances to `PASS_OBSTACLE`, so an integrated TaskManager startup can create an internal NavigateToPose goal even when no actuator bridge exists. Safety claims must distinguish no-actuation from no-goal.
- A newly launched Humble process running `ros2 topic list` is not reliable readiness evidence for the cone pipeline on this container: it returned no `/cone_obstacle/scan_humble` while the existing exporter process was logging healthy packets at roughly 10 Hz. The cross-domain contract is the UDP datagram, so startup should validate that actual boundary directly.
- The correct pre-bridge readiness probe binds Host loopback `127.0.0.1:19002`, decodes the bounded `CNS1` packet with CRC validation, requires `depth_healthy=true` and wall age within 1 second, then exits so the Foxy bridge can claim the same port.
- Run-owned resource identity must be recorded immediately when it is created, not only after the full startup succeeds. Pre-GO failures otherwise bypass evidence-wrapper cleanup even when the inner launcher has enough identity to clean safely.
- ROS 2 Foxy parameter precedence can invalidate a launch override when a preceding YAML contains an exact node key and the generated launch override uses `/**`. In the observed process, `/tmp/launch_params_cd2747pi` correctly contained `enable_depth_milestones: true`, yet `task_manager_node` loaded `false` from `competition_params.yaml`.
- Parameters selected by launch mode (`auto_advance`, `enable_phase2_map_switch`, `enable_depth_milestones`, `depth_safety_status_topic`, and `verify_host_odom_after_depth_disable`) must have a single owner. Their Python node declarations provide defaults; the base exact-node YAML must not repeat them when launch passes mode-specific values.
- The `89f511d` no-actuation run proves startup provenance, cone UDP/health, Nav2 lifecycle, command isolation, and WHZ preload, but it cannot prove the Cone-to-WHZ transition contract because depth milestones were disabled at runtime. A new run after removing the YAML shadow is required.
- After `fdad03c`, the final run proves the integrated startup contract with depth milestones enabled: TaskManager's mission-start request ID matches `depth_controller_status.json`, and the controller reports acknowledged `AVOIDANCE`, `parameter` strategy, depth enabled, healthy status, and live localization streams.
- No-actuation evidence must identify processes by executable/node identity, not substring-match full launch arguments. The text `enable_cmd_vel_bridge=false` contains `cmd_vel_bridge` but is affirmative evidence that the bridge is disabled; node graph absence, `/cmd_vel` zero subscribers, and empty Lite3 UDP endpoints are the authoritative checks.
- The final startup gate intentionally permits an internal Nav2 goal because TaskManager formally advances after fresh odometry. With no `/cmd_vel` subscriber and no Lite3 command endpoint, this remains no-actuation evidence, not no-goal evidence. The moving mission still requires a fresh physical authorization gate.

## 2026-08-14 Phase 113 route-hardening findings

- The earlier `min_y_velocity_threshold` concern is not a defect in the current configuration. DWB explicitly uses `max_vel_y=0`, `acc_lim_y=0`, and `vy_samples=1`; lateral motion is intentionally disabled and remains outside the validated Lite3 envelope.
- A formal integrated run must not inherit the built-in fallback coordinates. A completed waypoint document plus exact map identity is now a startup prerequisite for `--cone-to-whz-l6`, and the gate runs before cleanup, Docker creation, or ROS launch.
- TaskManager retry count zero means a failed Nav2 goal or WHZ request is not resubmitted by TaskManager. It does not disable recovery behavior internal to a single Nav2 NavigateToPose goal; that behavior must be accepted or changed separately before the one-shot L6 run.
- Odometry freshness and cuVSLAM tracking are different health signals. `/odom` reception now drives odometry readiness only; compatibility field `slam_ok` reports the actual SLAM status rather than being overwritten by odometry callbacks.
- Phase 113 does not use the mechanical arm. The accepted competition path terminates after four WHZ observations; any other path reaching grasp/place without real feedback now aborts unless the bench-only placeholder flag is explicitly enabled.
- Local L1 evidence is `275/275` tests plus static validation. It proves the isolated logic/contracts, not field-route safety; completed waypoint calibration and one supervised L6 run remain mandatory.

## 2026-08-14 Phase 113 route-hardening deployment findings

- The root package uses symlink install. For deployed Python behavior, the expected import provenance is `<deploy>/build/quadruped_robot_competition/src/...`; for package discovery and installed launch/config assets, it is `<deploy>/install/quadruped_robot_competition`.
- `setup.py` installs launch and config assets but intentionally does not install operator scripts. `scripts/start_competition.sh` is executed from the authoritative deploy source tree, so source Git identity plus `bash -n` is the correct provenance check for that script.
- The hardening change does not require rebuilding `whz`: its implementation/model/package data did not change. Rebuilding the main package is sufficient to update TaskManager, NavigationClient, mission-route logic, and the competition launch file.
- The repository's real waypoint template is still fail-closed (`calibration.status=not_calibrated`). A code-only deployment can be complete while the formal `--cone-to-whz-l6` startup remains intentionally unavailable until field calibration and exact `TASK_EXPECTED_MAP_ID` are supplied.

## 2026-08-14 Phase 113 route provenance correction

- The 14-goal `full_interleaved` route was not merely an offline proposal. Phase 71 ran it under supervision against `competition_field_phase1`: the first 12 goals succeeded, `placement_C_approach` aborted, and `placement_D_approach` was not sent.
- The empty `waypoints_real.yaml` represented a later formal-provenance gate, not absence of an established route. Re-capturing every pose would duplicate existing field evidence without changing the accepted coordinates.
- The formal map identity is `competition_field_phase1`, matching the default loaded Nav2 YAML. The pinned artifacts are `competition_field_phase1.yaml` SHA-256 `6993e41e4d057f204fa7d229e25906cf1ccfd4f2cc7c9bee9881851d69ff8ec0` and `competition_field_phase1.pgm` SHA-256 `3540f2abaac8903dd61da70c8ff43ee5c0abf3b33036df1c3576466739692fff`.
- Promoting the route to `calibration.status=complete` means its identity and provenance are accepted for the Phase 113 gate. It does not upgrade the full route to 14/14 success; Phase 113 consumes the 9-goal inspection route and still needs supervised L6 acceptance.

## 2026-08-14 Phase 113 formal-route acceptance findings

- Ordered route length and unique waypoint count are different because `upper_corner_clear` intentionally appears twice. `inspection_interleaved` contains 9 ordered goals but only 8 unique waypoint records; startup evidence must report both rather than calling the unique dictionary size the route count.
- Host/container shared control files use host monotonic timestamps. A `depth_control_request.json` left across a host reboot can appear to be from the future in the next boot and correctly fail the controller's monotonic validation. A fresh formal startup must clear the stale request and controller status only after old processes are stopped; relaxing the runtime time validation would weaken the safety contract.
- Container `/tmp` persists for the lifetime of a reused container. Relay readiness loops that grep `/tmp/dep.log` or `/tmp/cam.log` must clear those logs before starting a new process, otherwise stale lines can satisfy readiness or produce misleading startup output even when the new process is healthy.
- The accepted no-actuation gate at `6dcfc16` proved the formal route and runtime parameters: exact map ID, 9-goal inspection order, zero TaskManager retries, finish after four observations, no placeholder manipulation, healthy acknowledged AVOIDANCE mode, one safety-gate `/cmd_vel` publisher, and zero actuator subscribers. Final `7703e20` adds only readiness-log cleanup and passed 277/277 local and Jetson non-hardware tests.

## 2026-08-14 Phase 113 mission-start depth request race

- The first authorized moving startup exposed a deterministic late-subscriber race rather than a D455, localization, route, or actuator failure. TaskManager published the mission-start AVOIDANCE request at `05:15:57.938`; the `cone_mode_relay` subscription process reported ready at `05:15:59.855`.
- `/depth/mode_request` currently uses default volatile QoS, and `DepthModeClient.begin_transition()` publishes a newly created request exactly once. A subscriber created after that publication receives nothing.
- The downstream evidence matches a lost request: no `depth_control_request.json` was available at teardown, while `depth_controller_status.json` was fresh and healthy but remained `mode=BOOTING`, `ack_request_id=""`, and `message="waiting for mission depth request"`.
- The existing 8-second coordinator timeout behaved correctly and fail-closed. The command bridge recorded zero motion and zero UDP errors, no NavigateToPose goal was sent, and cleanup removed all runtime residue.
- A robust fix must preserve request identity and safety semantics. Acceptable directions are an explicit relay-ready startup gate before TaskManager can publish, or idempotent periodic republishing of the same request ID while the coordinator remains pending. Simply lengthening the timeout does not deliver a message that was already lost.

## 2026-08-14 - Phase 113 startup-race implementation findings

- The request path now uses a latched reliable topic on both endpoints: `QoSProfile(history=KEEP_LAST, depth=1, reliability=RELIABLE, durability=TRANSIENT_LOCAL)`. This addresses both late subscriber discovery and transient transport loss without changing the JSON contract.
- Retries reuse the exact serialized request captured by `DepthModeClient.begin_transition()`. This preserves the controller's request-ID deduplication and makes retries idempotent; a new request is never generated during the wait.
- Retry timing is explicit (`_next_republish_at`) and is driven by the existing TaskManager timer callback. No constructor sleep or modulo-based timing is used, and the request stops being republished once end-to-end status and safety-gate ACKs match.
- Local Windows lacks `rclpy`; the new client tests install minimal test-only ROS stubs when unavailable. The real ROS imports remain unchanged and the ROS 2 skill validator passed with zero issues.

## 2026-08-14 - Jetson deployment verification

- Commit `8268817` fast-forwarded the clean formal Jetson checkout from `7703e20`; rollback branch `codex/pre-phase113-depth-race-7703e20` preserves the previous deploy.
- The Foxy package build and full `282/282` non-hardware tests passed on Jetson. Installed package provenance points to the formal deploy checkout, and no runtime/control endpoints were started by the sync.

## 2026-08-14 - Phase 113 startup-race field-stack acceptance findings

- The original failure mode is resolved in the real formal stack. TaskManager request `6eb9e67f6589484889ee2f69972fe61f` was acknowledged with the same ID before the previous 8-second timeout, and a later accepted run used matching ID `16d6c10abb284eb6bf88de4972639658`.
- Transient Local behavior was directly proven twice: an isolated subscriber created 1.5 seconds after publish received the cached request, and a subscriber created after the accepted formal launcher GO received the active request whose JSON exactly matched the shared control file.
- The first post-fix gate found an independent startup-check issue: after the lifecycle manager logged all nodes active, a single follow-up lifecycle CLI read could fail transiently. Bounded retries preserve fail-closed semantics because success still requires exact `active [3]`; blank/error output never passes.
- Final accepted Jetson commit is `d29fdf3ae3c5f508c1fa29939de62c7d4b6492a2`; no-actuation evidence is `/home/superwfx666/competition_logs/cone_to_whz_l4/20260814_062412_phase113_depth_race_gate_retry_d29fdf3`.

## 2026-08-14 - Phase 114 pre-grasp boundary finding

- The requested pre-grasp endpoint is the tenth ordered `full_interleaved` goal, `grab_area_approach=(3.1,2.0,0)`. The first nine goals are exactly the accepted `inspection_interleaved` cone/WHZ route.
- Existing production settings cannot reach that point safely: `finish_after_inspection=true` stops after goal 9, while `false` plus `allow_placeholder_manipulation=false` aborts immediately after inspection before goal 10.
- The safe boundary is an explicit TaskManager mode that advances into `FIND_RED_BAR` only for its acknowledged pre-waypoint depth transition and NavigateToPose action, then enters `FINISH` immediately on goal success. It must bypass red-bar waiting and must never enter `GRASP_BAR` or `PLACE_TO_ABNORMAL_ZONE`.

### Phase 114 clarification

- The preceding pre-grasp interpretation was superseded by the user's clarification. The actual requested boundary is the existing ninth route goal `pos2b_lower_right`, after all four WHZ observations; `finish_after_inspection=true` then enters `FINISH` without navigating to `grab_area_approach` or executing manipulation.

## 2026-08-14 - Phase 113 two-cone trap findings

- The second L6 attempt proved the startup-race fix and actuator path sufficiently to begin real motion, but failed on the first navigation goal before any resource transition or WHZ inspection.
- Failure order is diagnostic: DWB first returned `No valid trajectories out of 351`; costmap clears followed; spin recovery refused to rotate because of `Collision Ahead`; the planner then repeatedly failed to find any path to `(1.05,0.75)`. This is a geometric costmap/planning trap, not a missing depth request, stale cone scan, or Lite3 UDP failure.
- The production footprint is `0.70 m × 0.50 m`. Both formal cone costmaps use `inflation_radius=0.60 m`, `cost_scaling_factor=2.0`, and `observation_persistence=1.5 s`. When two cones bracket the robot, their inflated regions can eliminate every sampled DWB trajectory and also seal the global path around the current pose.
- Final odometry `(1.744,0.482,-19.4 deg)` is beyond the first goal's x-coordinate. The accepted goal and route geometry should therefore be reviewed together with physical cone spacing and synchronized costmap/scan evidence; tuning only DWB sampling cannot solve a globally closed inflated corridor.
- Fail-closed behavior worked: Nav2 canceled/stopped, TaskManager did not retry, the bridge held zero with no UDP errors, and exact cleanup removed all control state. However, the software stack remained alive and sending zeros until the operator report because the external wrapper did not react to the already-entered ABORT during the launcher's post-start validation. Future field wrappers should monitor terminal TaskManager status concurrently with launcher completion.

## 2026-08-14 - Phase 113 spacing-adjusted rerun findings

- Increasing the physical gap changed the outcome of the first segment: `obstacle_cross_target` completed successfully in about 17 seconds, unlike the prior DWB/collision trap.
- The new limiting failure is distinct from cone inflation at the first passage. While navigating to `pos1_left_clear=(0.60,2.90)`, Nav2 repeatedly reported `Robot is out of bounds of the costmap` and `start position is off the global costmap`, followed by `GridBased` planning failures.
- TaskManager's `120 s` timeout covers the entire `pass_obstacle` phase rather than resetting per waypoint. It expired 98 seconds into the second goal and canceled the still-active Nav2 action, so no WHZ inspection was requested.
- Concurrent wrapper monitoring now reacts to TaskManager terminal state and completed exact cleanup immediately; final container, relevant process, and control UDP evidence is empty.

## 2026-08-14 - Phase 113 third supervised run findings

- The widened physical passage is now repeatably traversable at the action level: `obstacle_cross_target` succeeded again, and this run also completed `pos1_left_clear` before entering goal 3.
- `pass_obstacle_timeout_sec=120` is implemented as one deadline for all three pre-inspection navigation goals. Time spent completing goals 1 and 2 consumes nearly the whole budget; goal 3 was canceled about 18 seconds after dispatch even though its own Nav2 action had not exhausted a per-goal allowance.
- Off-global-costmap warnings persisted during goal 2, but Nav2 recovered and eventually reported success. Near goal 3, DWB again had no valid trajectory and Spin recovery rejected motion because of predicted collision; the phase deadline then became the immediate terminal cause.
- The formal launcher's post-start parameter snapshot can still overlap the active mission. In this run it later failed to read the global inflation `cost_scaling_factor`, but the independent TaskManager terminal monitor already provided the authoritative mission terminal condition and exact cleanup path.
## 2026-08-14 - Phase 115 initial constraints

- The accepted design separates obstacle-source cost generation rather than splitting the PGM map: static/map obstacles retain generic InflationLayer `0.30 / 3.0`, while cone LaserScan observations receive plugin-local inflation `0.60 / 2.0` (experimental `0.75 / 1.5`).
- The implementation must remain compatible with the pinned Foxy/Nav2 2.2.1 runtime and must be verified against installed headers/source rather than newer Nav2 APIs.
- The main `quadruped_robot_competition` package remains pure `ament_python`; the new costmap plugin is a separate `ament_cmake` package built in the existing C++ overlay.
- Runtime disable is not complete when a parameter service merely echoes `enabled=false`. Completion requires the plugin to apply the disabled state during a costmap update, clear its previous cone and halo contribution, and publish acknowledgement for both local and global instances.
- ByteRover lookup was unavailable in this session: no MCP tool, no `brv` executable, and no local `.brv` context tree. Existing PWF history remains the available repository-memory source.
- The repository currently has no `ros2_plugins/` directory. The only tracked C++ packages are unrelated probes and Lite3 packages; the cone layer itself is supplied by an external pinned overlay at `$HOME/cone_l2_plugin_ws_2_2_1`.
- `nav2_cone_obstacles.yaml` and its experimental variant both use plugin order `static_layer`, `cone_obstacle_layer`, `inflation_layer`. Their generic InflationLayer currently carries the cone radius/falloff, so it also expands the static map source.
- `cone_scan_safety_gate.py` currently transitions both costmap parameters, verifies only `cone_obstacle_layer.enabled`, and then calls local/global `ClearEntireCostmap` before reporting ready. It has no plugin-applied acknowledgement channel.
- `start_competition.sh` currently resolves `nonpersistent_voxel_layer`, checks alias `nav2_costmap_2d/NonPersistentVoxelLayer`, locates `libnonpersistent_voxel_layer_core.so`, and confirms both controller/planner processes map that exact library. Phase 115 must update all four provenance assertions to the new package/library while keeping the checks before GO.
- The root package declares `nonpersistent_voxel_layer` only as an execution dependency. Phase 115 should replace that dependency with the new standalone package without converting the root package away from `ament_python`.
- Upstream `nonpersistent_voxel_layer 2.2.1` derives from Foxy `ObstacleLayer`, resets its private voxel and 2-D maps at the start of every `updateBounds()`, marks current observations as lethal, and inherits `ObstacleLayer::updateCosts()` for overwrite/MAX composition. A derived plugin can therefore call the pinned base implementation, inflate only its private source map, and retain the existing observation/voxel behavior.
- Foxy Nav2 `0.4.7` `LayeredCostmap::updateMap()` collects every layer's bounds, resets that master window, then invokes all `updateCosts()` methods in plugin order. Re-submitting the previous cone halo bounds for one cycle is sufficient to clear old cone costs while letting StaticLayer and the generic `0.30 / 3.0` InflationLayer rebuild their own contributions.
- Applied-state acknowledgement must occur after the layer's `updateCosts()` has participated in a full costmap update. Publishing the acknowledgement on the next `updateBounds()` cycle proves the preceding local/global cycle completed, including downstream generic inflation.
- The upstream 2.2.1 package omits `install(DIRECTORY include/ ...)` even though it exports its include directory. The new subclass must be built with the pinned source package available in the same existing overlay; relying only on the installed 2.2.1 prefix is insufficient for its header.
- The source-local inflation kernel can mirror Foxy InflationLayer's formula and `ceil(radius / resolution)` cell radius while using a bounded direct neighborhood expansion. With the current 0.025/0.05 m resolutions and 0.60 m radius, the bounded work is small and avoids copying newer Nav2 internals.

## 2026-08-15 - Phase 115 implementation contract

- `ConeInflatedVoxelLayer` will publish relative `cone_obstacle_layer/applied_status` topics from each costmap node with reliable, transient-local, depth-1 QoS. The resolved topics are `/local_costmap/cone_obstacle_layer/applied_status` and `/global_costmap/cone_obstacle_layer/applied_status`.
- The plugin parameter callback only records a requested enabled state and monotonically increasing revision. The costmap update thread applies the pair in `updateBounds`; `updateCosts` records completion; the next `updateBounds` publishes acknowledgement, proving the prior complete layered-costmap cycle finished.
- Safety Gate must receive an initial retained status from both plugins before setting `enabled`. It snapshots each status sequence and applied revision, then accepts the transition only when both values advance and both requested/applied enabled fields match. This prevents a retained pre-transition status from satisfying a new request.
- The old cone halo world bounds are submitted on every following `updateBounds` cycle. When observations disappear or the layer becomes disabled, LayeredCostmap resets that old window and the static layer plus generic `0.30 / 3.0` inflation rebuild only their own contribution.
- The startup script will rebuild the new package in `$HOME/cone_l2_plugin_ws_2_2_1` before any cleanup, Docker, sensor, or actuator action, while validating the dependency source at pinned commit `0704666393ef1747562a93d934923fa45a3a8d4b`.
- A final source-first check against Nav2 `0.4.7` found that Foxy `Layer::node_` is a `nav2_util::LifecycleNode::SharedPtr`, not a weak pointer. The plugin therefore uses `node_` directly and Foxy's public `Layer::declareParameter/getFullName` helpers; `.lock()` would have failed at compile time.
- The pinned dependency exports `nonpersistent_voxel_layer_core` but does not install its header. Its upstream CMake also defines `PLUGINLIB__DISABLE_BOOST_FUNCTIONS` and exports the costmap plugin XML; the derived package mirrors those pluginlib details while injecting the pinned source include path.

## 2026-08-15 - Phase 115 controller selection contract

- Both cone overlays now declare `controller_plugins: [FollowPath, FollowPathCone]`. `FollowPath` is left entirely in the base YAML; `FollowPathCone` is a full independent DWB block so no plugin parameter falls back through accidental shared namespace state.
- The custom Foxy BT preserves the default replanning/recovery structure and changes only `<FollowPath controller_id="FollowPathCone">`.
- TaskManager enables the waypoint-to-BT mapping only when `enable_cone_controller=true`, validates the installed XML path, and maps only `obstacle_cross_target`. `pos1_left_clear` and every later waypoint submit an empty BT path and therefore use the default tree/controller `FollowPath`.

## 2026-08-15 - Phase 115 L2/L3 continuation constraints

- The repository's L3-S probe is genuinely isolated at ROS domain 93, `ROS_LOCALHOST_ONLY=1`, loopback UDP `19012`, and `/cone_l3/*`; it still deliberately requires the operator assertion `--confirm-isolated-no-actuator`, which the agent cannot infer from software state.
- The runbook's L3-D section starts the production cone stack with a real D455 on domain 0. Under the current verification ladder this crosses into hardware-powered/no-actuation evidence and must remain behind the user's separate L4 authorization.
- Local fallback is unavailable: Windows has neither Docker nor an installed WSL distribution, while the native shell has no Foxy/colcon environment.
- Jetson read-only preflight at `2026-08-15T00:05:36+08:00` found the formal deploy checkout clean at `d29fdf3`; a separate vision worktree had active actuator-capable bridge/manager processes and a D455 container. Running colcon or ROS validation concurrently could interfere with that live task, so no mutation or execution was attempted.
- After explicit user authorization, the complete unrelated runtime was terminated through its own safe-stop path. The Lite3 stop script sends codes `320`, `325`, and `321` repeatedly to the vendor control endpoint before terminating the bridge; the exact D455 container was stopped without deletion and remains recoverable with `docker start d455_yolo_repro_20260811`.
- Post-cleanup process, Docker, and UDP checks were empty, so Jetson CPU/DDS/control-path contention no longer blocks L2 work.
- NonPersistentVoxelLayer 2.2.1's public source header includes PCL headers, but its ament export does not transitively add `${PCL_INCLUDE_DIRS}` to the derived target; its installed include directory is also absent. A derived package must both inject the pinned source include path and declare/link PCL directly.
- The minimal compatible fix mirrors the pinned package's `PCL filters/common` discovery and Qt/VTK library filtering, adds `${PCL_INCLUDE_DIRS}` to the derived target, links `${PCL_LIBRARIES}`, and declares `pcl_conversions` plus `libpcl-all` in `package.xml`.
- Colcon package discovery is command-specific. Building an external package with `--base-paths` does not make a later `colcon test --packages-select` discover that package automatically; test must receive the same base paths or it can return a misleading green summary with zero tests.
- In Foxy Nav2 0.4.7, the `nav2_planner` package's `planner_server` executable logs and advertises the default node name `nav2_planner`. Direct configure-only launch must remap `__node:=planner_server`; otherwise lifecycle commands target a missing node and the YAML block keyed by `planner_server` is not authoritative.
- L2 runtime provenance is now concrete: both costmap-owning processes mapped the same build inode for `libcone_inflated_voxel_layer_core.so`, and the plugin status publishers exposed the intended reliable/transient-local QoS before activation.
- An unprivileged user/network namespace is a stronger repeatable L3-S isolation mechanism on this Jetson: `unshare -Urn` plus loopback activation leaves no route or non-loopback interface, while allowing all bridge/gate/probe processes to communicate internally.
- The synthetic probe's `silence_deadline` consistently consumes almost the full 250 ms budget because it deliberately overrides the production bridge from its 100 Hz default to 20 Hz, adding about 49 ms before the gate's 200 ms health timeout. Four runs passed, but the observed margin was only `0.620-1.326 ms`; retain this as a timing-risk note for L4 rather than weakening the threshold.

## 2026-08-15 - Phase 115 L4 startup findings

- Foxy rejects an explicitly empty launch assignment such as `waypoint_file:=`; an optional launch argument with an empty declared default must be omitted from the CLI entirely. Building a Bash argument array and conditionally appending non-empty values preserves calibrated TaskManager behavior and makes the ordinary no-TaskManager cone startup valid.
- The real D455 L4 startup at `c730f85` proved current runtime provenance, formal parameters, both controller plugins, reliable/transient-local applied-status publishers, scan health, and zero `/cmd_vel` subscribers. It does not yet prove physical cone marking or directional stale-halo cleanup because connectivity failed before cone-in capture.
- The initial production measurements were stable: Foxy scan about `10.0 Hz`, Humble scan converging near `27 Hz`, host `/odom` about `29.9 Hz`, container cuVSLAM odometry about `30.2 Hz`, and startup health probe max source age `39.048 ms`. These are startup/static observations, not the pending A/B resource comparison.
- The connection loss was followed by a Jetson reboot that terminated the stack and bag before any `CONE_IN` marker. Even though the pre-reboot bag is readable and covers every required topic, costmap baselines from that runtime must not be compared with cone snapshots from a post-reboot runtime; the acceptance sequence must remain clear/cone/clear within one continuous runtime.

## 2026-08-15 - Phase 115 L4 final findings

- A fresh continuous no-actuation run at exact `c730f85` completed clear/cone/clear, disable/re-enable acknowledgement, cone-mode resource capture, non-cone resource baseline, bag closure, offline timing, and exact teardown. TaskManager, Lite3 bridge, navigation goals, and nonzero velocity were never enabled; `/cmd_vel` consistently had zero subscribers.
- Source separation is visible in both costmaps. With the physical cone present, local costmap deltas were `+11` lethal, `+164` inscribed, and `+514` nonzero cells; global deltas were `+26`, `+680`, and `+2163`. After removal, both complete costmap hashes exactly matched their clear-before baselines and every delta returned to zero.
- The initial timing analysis was invalid because it followed only the original cone angle. During removal the obstacle moved from beams `91-103` through `167-171`; fixed-angle timing started 590.448 ms too early. Full-scan tracking against 97 clear-before scans found the final physical-removal cluster at beams `167-171`, range `1.803-1.843 m`, followed by 14 clear scans before an unrelated isolated `2.948-2.992 m` range-edge return.
- Corrected cleanup latency is local `2068.409 ms` against `2500 ms` and global `2595.241 ms` against `3500 ms`. The original v1 JSON is preserved as the rejected analysis, and `timing_analysis_v2.json` records the final method and result.
- Layer disable/re-enable was applied by both costmap update loops: disable revision `1` reported `applied_enabled=false`, enable revision `2` reported true, and both costmaps stayed at the clear baseline after the toggle without full-costmap clear services.
- Cone mode B preserved `/odom` at `30.021 Hz` versus baseline A `29.998 Hz` (`-0.0767%` computed drop). B used about `655.4 MiB` container memory versus A `539.4 MiB`; all 59 B tegrastats samples stayed at 1420 MHz, CPU temperature peaked at 36.5 C, swap stayed zero, and the kernel log contained no OOM event.
- The continuous bag is SQLite-clean and contains `34,564` messages over `1048.946 s` on all eight required topics. Final teardown left no relevant process, running container, control UDP endpoint, or deploy change; the historical `d455_yolo_repro_20260811` container remains stopped and was not deleted.
- Final evidence: `/home/superwfx666/competition_logs/cone_l4/20260815_023029_phase115_l4_c730f85_continuous`. L4 is complete; this does not authorize or prove L6 motion behavior.

## 2026-08-15 - Phase 115 L6 preflight findings

- The formal deploy is an independent clean clone at `/home/superwfx666/quadruped-robot-competition-nav2-dwb-deploy`, not the older dirty development checkout with the similar name. L6 provenance checks and startup must use only the `-deploy` path.
- The formal deploy is exact `c730f850ea70e55628a2fee3454fbe4a3ada4635`; its phase-1 map hashes match the calibrated waypoint metadata, and the remote-tracking Phase 115 branch resolves to the same commit.
- A clean process/container/UDP audit found only the idle ROS 2 CLI daemon. `/cmd_vel` was absent from the graph, no relevant control process or running Docker container existed, and ports `43893`, `19001`, `19002`, and `19012` were unused.
- Lite3 was reachable at `192.168.1.120` with 0% loss, but reachability is not motion authorization. The field run remains blocked until the operator confirms continuous supervision and immediate access to the hardware e-stop, and until D455 identity/readiness is proven.
- D455 readiness is now proven independently of librealsense CLI tooling: USB product strings identify D455 serial `310643060408`, V4L2 enumerates all six video nodes, and `/dev/v4l/by-id` resolves stable device links. The host does not install `rs-enumerate-devices`.
- The authorized L6 scope is the repository's full formal `--cone-to-whz-l6` preset, not an ad hoc two-goal subset. Existing production parameters, calibrated route, zero-retry behavior, and depth/cone transition semantics must remain unchanged.
- The operator has now confirmed both continuous supervision and immediate hardware e-stop access. This confirmation authorizes one formal L6 motion attempt; it does not authorize automatic retry after any terminal result or cleanup-triggering fault.
- `stop_all.sh` uses broad process-name matching. A rosbag command line containing `/cmd_vel_arbiter/mode` is indistinguishable from the arbiter process to `pkill -f cmd_vel_arbiter` and is killed during formal startup cleanup. Record the three velocity topics directly but omit the arbiter status topic when the bag starts before `start_competition.sh`.
- An outer supervisor must signal and wait for the exact top-level `start_competition.sh` PID before running secondary teardown. Calling `stop_all.sh` alone does not stop the startup shell or `start_cuvslam_rviz_gui.sh`, so they can continue creating a container after an apparent cleanup.
- With `set -o pipefail`, a positive `lsusb | grep -q` match can still make the pipeline fail because `grep -q` exits early and upstream `lsusb` receives SIGPIPE 141. Hardware-presence gates must capture the finite inventory first and match the captured value, or otherwise avoid a short-circuiting pipeline.
- USB/V4L2 provenance identifies the attached D455 as model ID `8086:0b5c` and USB serial `310643060408`; the librealsense streaming validator independently reports a device serial field `235422300321`. Both refer to the single attached D455, and the latter completed real IR/depth/IMU streaming, so the field difference must not be treated as device absence.
- The formal TaskManager's `pass_obstacle_timeout_sec=120.0` is one aggregate phase budget across `obstacle_cross_target`, `pos1_left_clear`, and `pos1_middle`, not a per-waypoint timeout. In the `48072d9` L6 run, the first two successes consumed roughly 99.2 s of goal execution plus transition time, leaving only about 14.1 s for the third goal before deterministic phase abort.
- Phase 115 L6 motion evidence is a valid terminal failure, not an incomplete startup: nonzero commands reached the Lite3 bridge, waypoints 1-2 returned Nav2 success, waypoint 3 was cancelled by the TaskManager phase timeout, and the resulting 18,256-message bag is SQLite-clean.

## 2026-08-15 - Phase 116 timeout design findings

- The current formal runtime loaded `TASK_PASS_OBSTACLE_TIMEOUT_SEC=120.0`; `TaskManagerNode._phase_enter_time` is initialized once on entry to `PASS_OBSTACLE` and is not reset between its three waypoints.
- In evidence `/home/superwfx666/competition_logs/cone_l6/20260815_043458_phase115_l6_48072d9_formal`, goal 1 succeeded in 85.49 s, the stopped depth transition completed, goal 2 succeeded in 13.69 s, and goal 3 was still receiving valid controller paths and nonzero commands when TaskManager cancelled it 14.10 s after dispatch at aggregate phase time 120.1 s.
- The current formal log contains zero `Robot is out of bounds` and zero `start position is off the global costmap` messages, confirming that the previous boundary-drift failure is not the direct cause of this abort. It contains two `No valid trajectories` events inside goal 1 recovery, but Nav2 recovered and returned success.
- Three timeout-only options were evaluated: raise the aggregate cap only; reset one shared deadline per goal; or combine a per-waypoint deadline with an aggregate cap. The combined design is selected because it prevents earlier goals from consuming goal 3's allowance while retaining a competition-time fail-safe.
- Selected budgets are 120 s per `PASS_OBSTACLE` waypoint and 180 s aggregate for the three-waypoint phase. The formal zero-retry policy and the 300 s inspection timeout remain unchanged.
- ByteRover retrieval is unavailable on this host (`brv` not found and no repository `.brv` directory), so the existing PWF history is the only repository-memory source for this task.
- Historical Phase 78 evidence completed `pos1_middle` in `24.323 s`; under the selected 180 s aggregate cap, replaying the formal Phase 115 timings leaves about 74 s for that waypoint, roughly three times the historical duration while preserving an upper bound on the whole phase.

## 2026-08-15 - Phase 116 Jetson validation findings

- Jetson L2 independently reproduced the local result at exact `44d3962`: native `bash -n`, compileall, `300/300` unittests, and a one-package Foxy colcon build all passed; installed imports resolved to the clean formal deploy source.
- The isolated TaskManager runtime loaded `pass_obstacle_timeout_sec=180.0`, `pass_obstacle_waypoint_timeout_sec=120.0`, and `inspection_timeout_sec=300.0`. With no odometry it stayed in START; `/navigate_to_pose` had one action client and zero servers, its log contained zero goal sends, and the isolated graph contained no `/cmd_vel*` topic.
- The isolated wrapper's initial cleanup defect was test infrastructure only: `ros2 run` spawned an installed Python child after its outer PID exited. Exact-command recovery stopped that child, and the final audit reported zero relevant processes, zero containers, zero control ports, and zero Jetson Git changes.

## 2026-08-15 - Phase 116 L4 and readiness findings

- The exact formal runtime accepts the timeout change without changing the already validated perception/navigation stack: real D455 cone scan remained `9.9991 Hz`, all five Nav2 lifecycle nodes became active, and both controller/planner mapped the pinned cone plugin.
- The no-actuation startup path contained no TaskManager, Lite3 driver, cmd bridge, or motion preparation. `/cmd_vel` had zero subscribers, so the active Nav2 stack had no route to the robot actuator; no NavigateToPose goal was submitted.
- Formal startup persisted `TASK_PASS_OBSTACLE_TIMEOUT_SEC=180.0`, `TASK_PASS_OBSTACLE_WAYPOINT_TIMEOUT_SEC=120.0`, and `TASK_INSPECTION_TIMEOUT_SEC=300.0`. Combined with the isolated TaskManager runtime result, this verifies both launch-chain propagation and node-side parameter loading.
- The timeout-only change has reached the L6 entry gate at commit `44d3962`. This is readiness evidence, not a successful L6 route result; field behavior still requires one newly authorized supervised run with the existing no-retry policy.

## 2026-08-15 - Phase 116 formal L6 terminal findings

- Evidence `/home/superwfx666/competition_logs/cone_l6/20260815_054317_phase116_l6_44d3962_formal` is a valid pre-motion terminal `ABORT`, not a route result. TaskManager emitted no NavigateToPose goal and never left `START`.
- The timeout fix was loaded exactly as designed (`PASS_OBSTACLE` aggregate `180 s`, each waypoint `120 s`, inspection `300 s`, retry counts `0`), but none of those navigation deadlines was exercised.
- The direct abort cause was `depth pipeline readiness timed out at mission_start: waiting for global cone layer applied revision`. In this run TaskManager became ready and requested `AVOIDANCE` about 5.7 s before Nav2 reported all managed nodes active; the global costmap was still waiting for initial `map -> base_link` TF and did not advance the required applied revision before the mission-start deadline.
- The preceding successful-motion `48072d9` run had the opposite startup ordering: Nav2 reported all managed nodes active before TaskManager became ready, then the same mission-start transition completed and goal 1 was sent. This establishes a startup-order timing race rather than a regression in the new pass-obstacle timeout budget.
- Motion evidence is independently zero: bridge diagnostics never advanced `motion`, `/cmd_vel_nav2` and `/cmd_vel_precision` each have zero bag messages, and decoding all 562 recorded `/cmd_vel` Twist messages gives `max_abs=0.0` and `nonzero=0`.
- Cleanup remained complete and auditable: SQLite `ok`, direct Lite3 zero burst had no errors, and relevant process/container/control-port/Git-dirty counts are all zero. The one-run/no-retry rule prevented any second attempt; no out-of-scope startup, costmap, localization, or readiness code was changed.

## 2026-08-15 - Phase 117 initial startup-order finding

- `TaskManagerNode._tick_start()` currently calls `_ensure_depth_mode(AVOIDANCE, "mission_start")` as soon as odometry is fresh. That condition does not prove the Nav2 lifecycle stack, global costmap update loop, `map -> base_link` TF, or `/navigate_to_pose` action server is ready.
- The cone layer only applies and acknowledges a requested revision from active costmap update cycles. Starting its transition timeout before Nav2 activation makes a normal bringup delay indistinguishable from a failed depth transition.
- The repair must gate the first transition on a runtime Nav2 readiness signal while keeping TaskManager fail-closed and preserving all navigation/mission tuning. A mere launch delay would remain machine-load dependent and is not an acceptable deterministic fix.
- `ConeLayerAppliedTracker.baseline_ready()` already proves that both local and global plugins have published an applied status. Because the plugin publishes only after `updateCosts()` completes and the following `updateBounds()` runs, this is stronger than process or lifecycle presence and proves each costmap update loop has actually advanced.
- The selected gate combines `NavigateToPose` action-server readiness with the cone layer's two-source baseline. It applies only when cone mode control is enabled, so the separate non-cone depth pipeline remains compatible. The existing 8 s transition deadline starts only after this startup gate passes.
- Focused local tests passed `52/52` after the first implementation. Review then identified one residual ordering window: an action endpoint can be discoverable before `bt_navigator` is active, so endpoint readiness alone is insufficient for deterministic startup.
- The final gate will additionally poll `/map_server`, `/planner_server`, `/controller_server`, `/recoveries_server`, and `/bt_navigator` `GetState` services asynchronously and require lifecycle state id `3` for all five. This matches the formal startup acceptance set while the cone baseline independently proves both embedded costmaps have executed updates with usable TF.
- The implemented lifecycle polling is round-based and non-blocking: zero-time service discovery, `call_async()`, and future completion checks occur across TaskManager timer ticks. No synchronous wait or nested spin was introduced.
- The strengthened implementation passed Python compilation, `git diff --check`, and `53/53` focused tests. `lifecycle_msgs` is now an explicit runtime dependency rather than an accidental transitive dependency through Nav2.
- Full local regression passed `304/304`. ROS 2 per-file validation and stop audit reported zero issues; launch validation reported zero errors under explicit UTF-8 mode. Its six warnings describe the repository's existing mutually exclusive static/depth/cone node definitions, not concurrently active production nodes.
- Jetson L2 at exact `1881fd9` passed native Bash/Python validation, all `304/304` tests, and a one-package Foxy colcon build. Installed imports resolve to the formal deploy build tree; no runtime process, container, control port, or Git dirt remained.

## 2026-08-15 - Phase 117 final L4 finding

- The deterministic startup gate is implemented and deployed at `1881fd9`: before the initial mission-start depth request, TaskManager now requires lifecycle state `active [3]` for `map_server`, `planner_server`, `controller_server`, `recoveries_server`, and `bt_navigator`; a ready `NavigateToPose` action server; and initial applied-status baselines from both cone costmap layers.
- Lifecycle polling uses zero-time service discovery and asynchronous `GetState.call_async()` futures across timer ticks. The existing depth-transition deadline begins only when `begin_transition()` executes after the prerequisites pass, so normal Nav2 activation time no longer consumes that deadline.
- Formal L4 on the real Jetson/D455 passed without an actuator chain. It proves startup, lifecycle, plugin provenance, sensor rate, and zero-command behavior on hardware; it does not prove the new ordering with TaskManager enabled or any route behavior, which remains an L6 obligation.
- Final L4 evidence reports 20 zero `/cmd_vel` samples, zero TaskManager starts, zero NavigateToPose goals, zero Lite3 driver starts, clean Git, and zero residual process/container/control-port counts. The root startup race is therefore fixed through L4, and the next permitted action is one separately authorized supervised L6 run.

## 2026-08-15 - Phase 118 L6 preflight finding

- The newly authorized formal deploy remains exact and clean at `1881fd9`, with no competing runtime, container, or control-port owner. D455, V4L, audio, Lite3 reachability, disk capacity, and locked six-core CPU state are available for one field attempt.
- The authoritative formal route contains nine goal submissions but eight unique named waypoints because `upper_corner_clear` is intentionally revisited. All entries load from the completed calibration file and resolve to `competition_field_phase1`.
- Software evidence cannot establish the robot's physical start pose, full-route clearance, continuous human supervision, or immediate e-stop access. Those four L6 preconditions require a fresh operator confirmation before the actuator-capable startup command is permitted.
## 2026-08-15 - Phase 118 retry NO_GO root cause

- The Phase 118 retry is valid partial L6 route evidence: five dispatched navigation goals succeeded and one WHZ inspection completed. The `NO_GO` does not mean the first two dashboards were unrecognized and does not invalidate that completed behavior.
- The exact software trigger was an evidence-recorder QoS mismatch. Foxy rosbag defaults to a RELIABLE subscription, while `/cone_obstacle/scan` is intentionally BEST_EFFORT. Because BEST_EFFORT publisher to RELIABLE subscriber is incompatible, the recorder stored zero scan messages and `start_competition.sh` counted a non-BEST_EFFORT endpoint in its all-endpoint scan QoS gate.
- The repository already contains the required correction at `configs/ros/cone_rosbag_qos.yaml`; every formal supervisor must invoke `ros2 bag record --qos-profile-overrides-path "$REPO/configs/ros/cone_rosbag_qos.yaml" ...`.
- A second, independently proven defect is that the formal TaskManager is enabled before the final acceptance gate completes. A correct evidence recorder prevents this particular QoS rejection, but does not close the safety window for any future late gate failure. The formal TaskManager must start with `mission_start_armed=false` and observe no state-machine progress until the launcher sets and verifies it true after every gate passes.
- Compatibility requirement: the node and generic launch default must remain armed (`true`) for existing non-formal workflows. Only `start_competition.sh --cone-to-whz-l6` injects false initially and performs the post-gate transition.

## 2026-08-15 - Phase 119 implementation decision

- A rosbag-only correction would make the next known run pass the QoS endpoint check, but would leave the broader startup defect intact: any later gate could still stop a mission that had already moved. The selected design therefore fixes both the known trigger and the general ordering invariant.
- The arm is a dynamic ROS parameter rather than a fixed launch delay. TaskManager reads it every START tick, so the gate is deterministic and independent of Jetson load or DDS discovery timing. The parameter is deliberately scoped to START; changing it after the mission begins is not presented as an emergency stop.
- All possibly failing acceptance checks run while disarmed. The launcher checks the competition process is still alive, sets the parameter, and re-reads the live value before printing GO. Generic/manual TaskManager launches retain the previous behavior through the default `true` value.
- The formal rosbag wrapper owns the QoS option instead of relying on an operator to remember it. The topic list remains supervisor-owned so evidence scope can evolve without duplicating recorder logic.

## 2026-08-15 - Phase 119 original-evidence confirmation

- The prior summary is now backed by original files rather than inference: the retry supervisor command omitted the QoS override, the launcher emitted the exact scan-QoS `NO-GO`, and the SQLite bag listed the scan topic with count zero despite 590 health messages and 14,447 total messages.
- Task execution had already advanced far beyond startup: five navigation actions returned status 4/succeeded, including arrival at the second observation pose. The supervisor's `NO_GO` therefore describes its startup/evidence acceptance result, not failure of those completed navigation or dashboard steps.
- Fix provenance is unified at `86f589d` across local HEAD, origin, and the clean formal Jetson deploy. Jetson L2 reproduced all 308 tests and installed the same launch content hash.

## 2026-08-15 - Phase 119 final validation finding

- The QoS-correct recorder is proven on the real D455 at L4: `/cone_obstacle/scan` is now retained in rosbag with all four scan endpoints BEST_EFFORT, eliminating the exact Phase 118 supervisor `NO_GO` mechanism.
- The mission arm is proven at isolated L3 with the real TaskManager timer and ROS action client: while false the state remains START; changing the live parameter to true is the event that permits transition to PASS_OBSTACLE. With no action server, `send_goal_async` is never reached and no cmd_vel topic exists.
- Phase 119 is complete through L4 at exact `86f589d`. The next field run is a separate Phase 120 one-shot L6 acceptance, not a continuation of validation authorization.
- The latest physical confirmation covers camera clearance, route clearance, continuous supervision, and hardware e-stop, but does not explicitly establish the robot's formal start pose after the prior run ended near the second observation area. Starting the calibrated nine-goal route without that confirmation would invalidate both safety and route evidence.

## 2026-08-15 - Phase 120 supervisor lifetime finding

- The formal product launcher is a bringup-and-acceptance command: after it arms TaskManager and prints GO, `scripts/start_competition.sh` reaches EOF and exits normally. It is not the lifetime owner of the background `ros2 launch` process.
- The inherited L6 supervisor assumed the opposite and declared `LAUNCHER_EXIT` whenever the top-level launcher PID disappeared. In Phase 120, launcher output ended cleanly at the GO banner, then the supervisor stopped a healthy first navigation goal about 12.8 seconds into nonzero motion.
- Therefore the Phase 120 result is invalid/inconclusive and cannot be used to judge the QoS recorder, mission arming, startup-order gate, full route, inspection sequence, or timeout policy end to end. The recorder itself did retain 3,605 cone scans and passed SQLite integrity, while the arm gate correctly held zero motion until all acceptance checks completed.
- A future formal supervisor must treat successful launcher completion after GO as expected and monitor the actual competition child/ROS graph plus `/task/phase` terminal events. Pre-GO nonzero launcher exit or `NO-GO` remains a failure; post-GO mission monitoring must not depend on launcher PID lifetime.

## 2026-08-15 - Clean manual L6 entrypoint decision

- The operator-selected path intentionally removes both rosbag and the external supervisor. `scripts/start_l6.sh` is therefore only a deterministic parameter/preset wrapper over the already validated formal startup chain; it does not add a second lifecycle owner.
- The clean path reduces DDS subscribers, disk I/O, CPU load, and wrapper failure modes. The trade-off is deliberate: it does not preserve a rosbag or independent terminal audit, and after the bringup command prints GO and returns, stopping is an explicit operator action through the hardware e-stop or `bash scripts/stop_all.sh`.
- Formal safety gates remain inside `start_competition.sh`; removing the external supervisor does not bypass the TaskManager disarm-until-acceptance invariant or the zero-retry mission policy.

## 2026-08-15 - Pure-start L6 decision

- The failed operator attempt was a launcher acceptance false negative, not a runtime-stack failure: `/cmd_vel` had already reported the expected one publisher and one subscriber, all five Nav2 lifecycle nodes reached `active [3]`, and the later one-shot CLI endpoint query alone returned nonzero.
- Retrying or extending the external CLI checks would retain the same unnecessary failure surface. The operator-selected solution is a separate pure path that performs the required bringup and then runs no post-launch acceptance block.
- Skipping acceptance while leaving the formal preset disarmed would create a permanently idle mission. Therefore pure mode passes `mission_start_armed=true` from launch and relies on TaskManager's existing internal lifecycle/action/cone-baseline readiness gate; the default formal path keeps delayed arming unchanged.
- `PURE_L6_START` is selected only by `scripts/start_l6.sh`. After the competition launch PID is created, that path returns before TaskManager polling, node/topic inspection, CPU TOP5, lifecycle/QoS/parameter/plugin/health checks, or acceptance-triggered cleanup.

## 2026-08-15 - Pure-start L6 field result

- The pure-start operator path is no longer only deployment-validated: the operator reports that `bash scripts/start_l6.sh` completed one full L6 run successfully on the robot.
- Treat this as the authoritative practical acceptance result for current project status. It is an operator report rather than an independently reconstructed evidence run, so do not invent per-waypoint timings, inspection counts, telemetry values, or post-run cleanup results without inspecting artifacts.
## 2026-08-15 - Phase 124 evidence boundary

- The current DWB baseline includes the operator-reported successful full L6 execution through `bash scripts/start_l6.sh`; no independent per-waypoint log or rosbag audit is being inferred from that report.
- The integration audit targets the separate dirty Jetson worktree `/home/superwfx666/worktrees/quadruped-vision-yolo-refactor` and must preserve its state exactly while evaluating reusable grasp, placement, AprilTag, YOLO, arm-service, and RGB-D components.
- At `2026-08-15T22:15:04+08:00`, the vision worktree remained on `feature/vision-change-jetson-test` at exact `608d93e6246739ade96658f979af9f1915ea6575`, with no upstream, 34 tracked modifications, and 66 untracked status entries.
- Active camera ownership is the container `d455_yolo_repro_20260811` from image `d455-yolo:pick-test-20260811`; its sole command runs one Humble `realsense2_camera_node` with color `1280x720x30`, depth `640x360x60`, emitter disabled, no aligned depth, and no IMU streams.
- The vision worktree currently has a Foxy `cmd_vel_bridge` process with `init_dog=true` and a CPU `yolo_detect_publisher` reading the relay model path. No `competition_manager`, AprilTag bridge, or arm-motion process appeared in the bounded process snapshot.
- These are observational facts only. The session did not stop, restart, reconfigure, or otherwise touch the active D455, YOLO, command bridge, ROS graph, Docker container, or Lite3 path.
- Current DWB `TaskManagerNode` already owns the mission phases and fail-closed policy. After inspection it enters `FINISH` only for inspection-only/`finish_after_inspection`; otherwise it aborts unless bench-only placeholder manipulation is explicitly enabled. Before `grab_area_approach`, the existing depth policy requests the manipulation depth mode, so the correct integration point is to replace the grasp/place placeholders with explicit execution feedback rather than launch a second competition state machine.
- The DWB relay files are under `scripts/`, not `docker/d455_perception/`: `scripts/camera_relay_docker.py` writes `latest_color.jpg`, while the canonical depth contract declares `latest_depth.raw` plus `latest_depth.json`. Several older standalone utilities still parse `latest_depth_meta.txt`; they are legacy consumers and must not define the new placement interface.
- The remote worktree's 34 tracked diffs total about 1,198 insertions and 294 deletions, but its principal AprilTag/alignment/competition modules and tests are untracked. A direct Git merge would omit the working implementation and also import unrelated Lite3, cmd_vel, navigation, launch, transform, and YOLO changes.
- Integration-relevant untracked modules include AprilTag pose/UDP bridge code, `pick_alignment_core.py`, `placement_alignment_core.py`, `manipulation_segments.py`, a second `competition_manager.py`, calibration YAML, arm/route tests, and printed-tag assets. Captures, calibration CSVs, `tmp/`, alternate Lite3 control scripts, and the parallel competition state machine are not merge candidates.
- `pick_alignment_core.PickOneExecutor` and `placement_alignment_core.PlaceOneExecutor` expose bounded start/tick/cancel/result state machines over small runtime protocols. They are suitable for adapter-based use inside the existing TaskManager. By contrast, the 853-line `competition_manager.py` owns its own NavigationClient, route runner, `/cmd_vel` commands, arm calls, subscriptions, and terminal state, so running it alongside TaskManager would create duplicate mission and velocity ownership.
- `placement_alignment_core.py` hard-codes `latest_depth.raw`, `latest_depth_meta.txt`, and `latest_color.jpg`. The DWB canonical depth metadata is `latest_depth.json` with validated stream/sequence/timestamp/intrinsics fields; placement must be ported to that structured contract and freshness/hash validation rather than retaining the legacy text parser.
- The AprilTag implementation separates Docker detection/PnP from a Foxy UDP bridge and publishes transformed pose data. Its startup default is `tag_size_m=0.100`, while the generated print assets and asset README specify a measured outer black square of `0.150 m`. Deployment must use the physically measured printed black-square size and reject an unconfirmed default.
- `configs/calibration/competition_sites.yaml` is explicitly a draft: `grasp_i0` is `conflict`, A-D dog poses are `provisional`, and the fixed release target is `uncalibrated`. `pick_i2_apriltag.yaml` marks four taught tag poses but gives all four exactly the same `[x,y,yaw]`, so these values cannot be treated as independently calibrated production targets.
- The remote arm node exposes explicit fixed grasp/place services with validation and asynchronous result tracking. This is the appropriate production feedback boundary, but its source package/service definition and tests must be collected deliberately; generated `build/` and `install/` artifacts are not source candidates.
- The proven `start_l6.sh` preset intentionally leaves color and camera relay disabled, enables depth only for cone avoidance, switches to `DISABLED` after `obstacle_cross_target`, and currently finishes after inspection. The existing `MANIPULATION` milestone can re-enable depth before `grab_area_approach`. A new full-route preset must explicitly enable color/its relay from startup and set `finish_after_inspection=false`; the proven inspection preset should remain unchanged.
- The arm service source is tracked at `arm_new/arm_new_interfaces/srv/ExecuteGraspFixed.srv`. It accepts one `geometry_msgs/Point target_arm_base` and returns `success/message`; the same service type is used for fixed grasp and fixed place endpoints in `arm_motion_node`.
- The active TorchScript model reports classes `{0:A,1:B,2:C,3:D,4:green,5:red,6:yellow}`. The source `InstanceSegmentation/projects/gauge/model/best.pt` is present at 6,241,123 bytes. This is the required placement/letter model rather than the container's currently mounted red/green/obstacle model.
- The active D455 container image has 69 layers and size about 17.26 GB; the cone cuVSLAM image has 64 layers and size about 16.90 GB. The container is privileged, host-networked, binds `/dev`, the Isaac workspace, and perception sources, and currently runs only RealSense. A derived unified image can retain the cone stack while adding the five YOLO/AprilTag layers and one RealSense owner.
- The latest discovered place-alignment run (`/tmp/place_align_test_node.log`, 22:02-22:03) is a real motion smoke test but failed: it used the fixed 30-degree pitch fallback because `base_link` TF was unavailable, executed yaw/lateral/distance pulses, and terminated `success=False reason=placement alignment timed out`. It began around 0.78 m and later approached the target distance but did not satisfy all three-axis stability conditions inside 80 s.
- The usage document claims an earlier `success=True` at approximately yaw `0.010`, lateral `0.024 m`, and distance `0.35 m`, while also documenting a reproducible timeout when starting around 0.95 m and recommending start distance at most 0.6 m. Without the original successful log, this is historical documentation evidence, not an independently auditable stable field acceptance.
- Candidate unit tests are meaningful and broad: AprilTag pose ambiguity/history, UDP packet validation/extrinsics, pick tag selection and three-axis alignment, placement RGB-D projection/yaw/bbox/executor behavior, route completion contracts, calibration schema, and arm grasp/place planning. The document reports 47 related tests passed but also says AprilTag tests were failing due to an in-progress core/test mismatch, so AprilTag must be reconciled before adoption.
- A bounded search of `/tmp` and recent competition logs found only the current `success=False` place-alignment log; no original `success=True` log was found. The documentation claim remains useful historical context but is not audit-grade evidence.
- The current local DWB checkout lacks all of the following: the AprilTag Docker/bridge modules, pick/place alignment cores, A-D model, and the entire `arm_new` service package. These should be imported as deliberate new source/assets with their tests, not obtained by merging the dirty branch wholesale.
- Exact image comparison shows a 63-layer common prefix. `isaac_ros_cuvslam_runtime:humble-rs-cone` has one layer after the prefix; `d455-yolo:pick-test-20260811` has six. The unified image should derive from the cone image, install/copy the accepted YOLO/AprilTag requirements and A-D model, then launch one RealSense node plus cuVSLAM/cone/relay/perception processes in that same container.
- The remote `competition_manager` publishes direct `Twist` to `/cmd_vel`, owns its own route services/status, and calls `/arm/execute_grasp_fixed` plus `/arm/execute_place_fixed`. Its alignment executors are reusable, but its ROS manager/wiring must be rewritten as adapters under the existing TaskManager and current cmd_vel arbiter contract.
- The remote parameter set relies on 1.5-second motion pulses, low nonzero speed floors, 80-second timeouts, YOLO detections about every 2 seconds, and a 0.35 m placement distance. These are test-derived tuning values, not validated DWB production defaults; they need isolated segment acceptance before full-route use.
- DWB already provides the required single-writer velocity chain: Nav2 publishes `/cmd_vel_nav2`, precision control publishes `/cmd_vel_precision`, the arbiter grants precision priority with a 0.25 s watchdog and 0.50 s release stop, then the cone safety gate alone publishes `/cmd_vel`. The remote pick/place executors resend their pulse command every manager tick, so a 10 Hz adapter can satisfy the lease after changing the topic from direct `/cmd_vel` to `/cmd_vel_precision`.
- The remote Humble `d455_yolo_3d_node` already subscribes to color, raw depth, and both CameraInfo topics from the sole RealSense node, performs model inference/3D projection, and emits JSON UDP packets. Foxy-side `yolo_udp_bridge.py`/core/tests also exist in the worktree. This supports the target architecture where Docker owns D455 and YOLO inference; host JPEG inference can remain only as a diagnostic fallback.
- Production placement still needs either bbox/depth-plane data sufficient for face-yaw estimation in the YOLO UDP packet, or a dedicated in-container placement-observation packet. Simply swapping the A-D model into the current red/green/obstacle path without validating the packet contract is insufficient.
- The existing YOLO UDP packet includes bbox, center pixel, mask area, depth ratio, and 3D position, but the Foxy bridge hard-codes the class map to red/green/obstacle. Supporting the A-D model requires a versioned class contract or accepted class-name allowlist; the shared raw-depth/JSON relay remains necessary for the current host-side face-yaw estimator.
- Final read-only recheck at `2026-08-15T22:25:54+08:00` confirmed the remote repository state and D455 container were preserved. An external session restarted the host YOLO publisher during the audit, changing only its observed PID; no command from this session initiated that restart.

## 2026-08-15 - Phase 125 dependency and AprilTag semantics

- The minimum production arm closure is package-level: all `arm_new/arm_api/*.py` modules, `arm_new/arm_new_interfaces`, the `arm_new_ros` package metadata plus `arm_motion_node.py` and its launch file, `arm_motion_params.yaml`, and focused tests. The old `arm_grasp_node.py`, examples, interactive scripts, and documentation are optional references and should not enter the formal launch path.
- AprilTag has two incompatible physical conventions in the worktree. The older pickup flow uses four IDs `0..3` attached to fixed block slots and selects red-slot IDs such as `[0,1]`; the newer generated asset set maps ID 0 to pickup and IDs 1..4 to placement A-D. The pick executor/calibration file implements the older per-slot `0..3` model, while placement currently uses YOLO letters rather than tags.
- Tag dimensions are also inconsistent: older handoff text mentions a 72 mm black square yet sets `tag_size_m=0.100`; startup defaults to `0.100`; the newer print set requires a measured 150 mm black square and `tag_size_m=0.150`. No tag asset or default is production-safe until the actual mounted tags are measured and one ID convention is selected.
- The AprilTag coordinate path is intentional: Docker transforms `camera_color_optical_frame -> camera_link` using the RealSense TF, emits UDP in `camera_link`, and the Foxy bridge applies one static `base_link -> camera_link` extrinsic to produce `/apriltag/detections_base`. The DWB merge must preserve this single transform chain and must not copy the vision branch's full static-transform file over the calibrated DWB version.
- The authoritative DWB camera extrinsic is `configs/navigation/cuvslam_camera_extrinsics.yaml`: base_link -> camera_link translation `[0.080, 0.000, 0.493] m` and pitch `0.523599 rad`. AprilTag/Yolo host bridges must load this file or a shared parser for it; the vision branch's temporary transform values are incompatible with the L6-proven DWB mount contract.
- `MANIPULATION` currently inherits `DepthMode.requires_depth`, causing `cone_scan_safety_gate` to enable cone costmap layers and require fresh cone scan health. For pick/place this is the wrong resource policy. The merge must define `cone_resources_enabled = (mode == AVOIDANCE)`: keep raw depth enabled in MANIPULATION, disable pointcloud/decimation and both cone layers, clear stale halo, and allow precision commands without cone scan health once the depth controller and manipulation observation are fresh.
- Formal cone startup currently passes `--no-write-frames` to `depth_relay_docker.py`. The full pick/place preset must omit that flag so MANIPULATION writes canonical `latest_depth.raw` plus `latest_depth.json`; the existing inspection-only L6 preset must retain its current lower-I/O behavior.
- Current TaskManager YOLO parsing is incompatible with the A-D model: it treats class ID 0 as `gauge`, while the accepted A-D model maps ID 0 to `A`, and can misclassify ID 4 `green` as `D`. The merged parser and UDP validator must make `class_name` authoritative, validate a versioned model/class-set identifier, and never reuse class IDs across different models.
- Pick integration should keep existing phases: FIND_RED_BAR performs coarse Nav2 arrival and runs `PickOneExecutor(stop_after_stage='i2')`; GRASP_BAR invokes `/arm/execute_grasp_fixed` and waits for explicit success. PLACE_TO_ABNORMAL_ZONE performs coarse Nav2 arrival, runs `PlaceOneExecutor(stop_after_stage='aligned')` for the current A-D zone, invokes `/arm/execute_place_fixed`, and only then increments the handled count.
- All local alignment Twist commands must publish at the TaskManager tick rate to `/cmd_vel_precision`, never `/cmd_vel`. Phase exit, cancellation, timeout, service failure, and ABORT must continuously publish zero long enough for the arbiter's 0.25 s precision lease and 0.50 s release stop to expire safely.
- UDP ports must be unique: retain `19002` for cone scan, `19003` for AprilTag, and assign `19004` to YOLO. The vision branch's YOLO default `19002` cannot coexist with the L6 cone bridge.

## 2026-08-15 - Phase 125 image and runtime closure

- The active visual image is `d455-yolo:pick-test-20260811` (about 17.3 GB); the L6-proven cone image is `isaac_ros_cuvslam_runtime:humble-rs-cone` (about 16.9 GB). Their histories share 63 layers. The YOLO image adds a 373 MB `bash /install.sh` layer plus small copied-node layers, but `/install.sh` is now a zero-byte file, so the exact original dependency command cannot be recovered from the built image.
- Installed image packages are NVIDIA `torch 1.13.0a0+340c4120.nv22.6`, `torchvision 0.19.1`, `ultralytics 8.2.103`, `opencv-python 5.0.0.93`, and `numpy 1.24.4`. `pip check` proves `torchvision 0.19.1` requires `torch 2.4.1`; importing `d455_yolo_3d_pipeline.install_torchvision_nms_fallback()` fails at `torchvision` import with `ModuleNotFoundError: torch._custom_ops` before the fallback assignment runs.
- The container mounts host site-packages read-only at `/opt/host-python`; metadata there reports `torch 2.0.0+nv23.5` and `torchvision 0.15.1` with an exact `torch==2.0.0` requirement. AprilTag startup explicitly prepends this mount to `PYTHONPATH`, but `run_yolo_3d_node.sh` does not. There is no outer caller that repairs the YOLO environment.
- Therefore the Humble RGB-D YOLO node is a source candidate, not a validated production path. The current live detector remains the Host Foxy CPU `yolo_detect_publisher`; no in-container YOLO, AprilTag, arm-motion, place-align, or second competition manager is running.
- The unified image must derive from the L6-proven cone image and reconstruct a locked JetPack-compatible inference environment rather than replay an unknown layer. Before model use it must pass `pip check` for the inference subset, direct imports, the NMS fallback installation, A-D model load/warmup, and a synthetic UDP packet test. Do not accept an image merely because its build completes.
- Required startup order is: pre-clean and zero precision output; start the one cuVSLAM/RealSense container with color, depth, IR, IMU and the DWB extrinsic; verify cuVSLAM and cone UDP; start camera/depth relays with canonical JSON frame metadata; start in-container AprilTag and optional YOLO exporters; start Foxy UDP bridges on `19003/19004`; start arm service; then start Nav2, arbiter/cone gate, and the single TaskManager while its existing readiness gates remain authoritative.
- Required stop additions are: publish zero to `/cmd_vel_precision` and `/cmd_vel`; cancel active alignment/service work; stop TaskManager/arm/AprilTag/YOLO bridge processes; stop the matching in-container AprilTag/YOLO and relay processes; remove their PID/log/control artifacts; and stop only the cuVSLAM container identity created by the current launcher. The current `stop_all.sh` does not yet include the new bridge, alignment, or arm process names.
- Final remote audit preserved branch `feature/vision-change-jetson-test`, exact HEAD `608d93e6246739ade96658f979af9f1915ea6575`, 34 tracked modifications, 66 untracked entries, and the existing `d455_yolo_repro_20260811` container. The audit left zero added AprilTag/YOLO 3-D/alignment/arm processes and made no remote file, Git, container-lifecycle, camera, ROS, or actuator change.

## 2026-08-15 - Phase 126 Git hygiene and synchronization findings

- Live read-only inspection reconfirmed `/home/superwfx666/worktrees/quadruped-vision-yolo-refactor` at local-only branch `feature/vision-change-jetson-test`, exact HEAD `608d93e6246739ade96658f979af9f1915ea6575`, with no upstream and no same-named GitHub branch.
- GitHub live refs currently include default `main=72e3833a`, `feature/vision-change=3ae72b0`, and `feature/vision-yolo-refactor=c6a0833`. The current worktree cannot become "the same branch as GitHub" without either pushing its local-only branch or selecting one of these existing refs as the canonical target.
- The worktree has 34 unstaged tracked files, no staged files, and a tracked diff of 1,221 insertions and 294 deletions across Lite3 transport, arm control, YOLO/D455, launch/config, navigation, and tests.
- Full `--untracked-files=all` inventory contains 142 files totaling about 38.5 MB. Top-level groups are `captures` 30, `assets` 26, `scripts` 23, `src` 13, `configs` 11, `tests` 11, `calibration_runs` 9, `apriltag_detect` 5, `docs` 5, `docker` 4, `tmp` 4, and `launch` 1.
- The difference between the earlier 66 count and the current 142 count is status presentation: directory-collapsed entries versus individual files, not necessarily a new 76-file change.
- `git clean -nd` proves a normal untracked cleanup would remove the AprilTag implementation, pick/place alignment cores, route/manager code, tests, calibration material, print assets, and captured frames. It is not safe before recovery.
- `git clean -ndX` additionally exposes ignored generated directories and two valuable local artifacts: `InstanceSegmentation/projects/gauge/model/best.pt` and `configs/test/arm_pick_hardware_test.local.yaml`. Therefore `git clean -fdx` is explicitly unsafe for this checkout.
- Because this path is a linked worktree sharing `/home/superwfx666/quadruped-robot-competition/.git`, fetches and remote-tracking ref updates affect the common repository shared by all six listed worktrees even though they do not modify working files.
- The safest synchronization design is a new clean sibling worktree tracking the selected GitHub ref while preserving this dirty worktree as a source snapshot. An in-place cleanup requires, in order, a binary tracked patch, an untracked archive, an ignored-value archive/manifest, checksum verification, runtime ownership recheck, target-ref selection, fetch, hard reset, and selective cleanup.
- A later liveness check at `2026-08-15 22:57 +08:00` found the peer briefly advertised through relay `hkg` but simultaneously marked offline; Tailscale ping, TCP 22, Tailscale SSH, and ordinary SSH all failed. This is a host-connectivity failure rather than an authentication failure and does not alter the earlier audit findings.

## 2026-08-15 - Phase 127 current-DWB completion audit

- The authoritative local DWB checkout is clean on `Stonefield/nav2-foxy-dwb-integration` at exact `998a4322c517c466317e5cbeb200a463731fff51`; the operator-reported successful `bash scripts/start_l6.sh` run remains the practical route baseline.
- Current `TaskManagerNode` already contains `FIND_RED_BAR`, `GRASP_BAR`, and `PLACE_TO_ABNORMAL_ZONE`. The first detects a red bar after coarse navigation, while grasp/place abort unless the bench-only placeholder flag is enabled. These are the exact production replacement points for the bounded alignment executors and explicit arm-service futures.
- Current `MissionDepthPolicy` transitions to `MANIPULATION` before `grab_area_approach`. Current cone resource logic incorrectly derives costmap-layer enablement and scan-health requirements from `DepthMode.requires_depth`, so MANIPULATION would retain cone resources. The port must instead use `mode == AVOIDANCE` for cone resources while retaining raw depth for MANIPULATION.
- The canonical depth snapshot reader already validates stream ID, sequence, timestamps, dimensions, step, depth scale, byte count, CRC32, mode, and CameraInfo. Placement must consume this contract rather than the legacy `latest_depth_meta.txt` format.
- Current TaskManager accepts class IDs as fallbacks against `configs/yolo/classes.yaml`, while the A-D model has a different numeric schema. The merged protocol must require a model/schema identity and make `class_name` authoritative.
- Current velocity ownership is suitable without redesign: `/cmd_vel_nav2` and `/cmd_vel_precision` feed one arbiter with a 0.25 s precision timeout and 0.50 s release stop, then the safety gate publishes the only `/cmd_vel`. Alignment adapters must use `/cmd_vel_precision` exclusively.
- The current launcher selects `isaac_ros_cuvslam_runtime:humble-rs-cone` for cone mode and starts one RealSense process in that container. The full preset can enable color/depth and run AprilTag/YOLO via `docker exec`; no second camera container is necessary.
- Completion verdict: every requested design question is answered by current DWB source plus the same-day authenticated remote audit. Implementation and physical calibration were outside the user's requested read-only scope and remain separate future work.
## 2026-08-16 - Phase 128 selective-port feasibility recheck

- Current DWB remains at `998a4322c517c466317e5cbeb200a463731fff51` on `Stonefield/nav2-foxy-dwb-integration`; the named AprilTag/alignment/arm/YOLO source files are not present in the current tree.
- `origin/vision-change` contains committed AprilTag Docker/bridge files, `pick_alignment_core.py`, the full `arm_new` package, YOLO 3-D/bridge files, the 6,241,123-byte A-D model, and focused tests. It does not contain `placement_alignment_core.py`.
- Raw-byte verification confirms `origin/vision-change:InstanceSegmentation/projects/gauge/model/best.pt` and current `whz/assets/models/gauge_best.pt` both have SHA-256 `3ed76de727a87be8d64cc3b259bf2b0ec39daaaa3fac1f3f97af249824abc648`; the model can be imported without waiting for Jetson recovery.
- Whole-branch merge evidence shows conflicts or incompatible edits in `.gitignore`, README, Nav2 parameters, `competition.launch.py`, `task_manager.py`, `stop_all.sh`, setup metadata, and control/navigation modules. Commit `a88b157` changes 126 files and includes explicitly excluded competition manager, Lite3, launch, transform, and navigation content, so it is not a safe cherry-pick unit.
- The committed AprilTag bridge defaults to `configs/transforms/static_extrinsics.yaml`, not the L6-proven `configs/navigation/cuvslam_camera_extrinsics.yaml`.
- The committed YOLO UDP validator fixes `CLASS_NAMES={0:red,1:green,2:obstacle}` and accepts no `model_id` or `class_schema`; it cannot safely consume the A-D model without a protocol revision.
- The committed pick core differs between `origin/visionchange` and `origin/vision-change` in pulse timing (`0.5 s` versus `1.5 s` plus settle), confirming that the source version must be selected from the audited Jetson snapshot rather than guessed from a branch name.
- The arm service package exposes `/arm/execute_grasp_fixed` with `ExecuteGraspFixed` and `/arm/execute_place_fixed` with `Trigger`; both return explicit `success` and `message`, which is sufficient for fail-closed TaskManager futures after selective import.
- At recheck time, Tailscale reported Jetson `100.126.48.49` offline and ping received no reply. No further polling or remote mutation was performed.
- A first OpenSSL hash computed through a PowerShell binary pipeline was discarded because PowerShell transformed the stream. Raw subprocess bytes produced the authoritative matching hash above.
## 2026-08-16 - Phase 129 isolated worktree bootstrap

- The pick/place integration workspace is `C:\Users\111\Desktop\比赛\quadruped-robot-competition-pick-place`, branch `codex/pick-place-selective-port`, based exactly on the proven DWB commit `998a4322c517c466317e5cbeb200a463731fff51`.
- The original DWB worktree remains independently checked out on `Stonefield/nav2-foxy-dwb-integration` at the same commit.
- The repository-level `.git/info/exclude` is shared across linked worktrees, so `task_plan.md`, `progress.md`, and `findings.md` remain ignored in the new worktree after manual copying.
- The repository has no `.brv` directory, so ByteRover worktree registration is not applicable to this worktree creation.

## 2026-08-16 - Phase 130 source recovery

- Jetson `100.126.48.49` is reachable again. Read-only SSH confirmed the preserved worktree remains on local branch `feature/vision-change-jetson-test` at `608d93e6246739ade96658f979af9f1915ea6575`.
- The missing untracked `src/nodes/decision/placement_alignment_core.py`, its focused test, the audited pick-alignment core, untracked AprilTag modules, and modified arm/YOLO sources are present in the preserved worktree.
- Approved source directories were copied to local staging path `C:\Users\111\AppData\Local\Temp\codex-pick-place-source-20260816-001`; the remote checkout was not modified.
- The staged A-D model SHA-256 is exactly `3ed76de727a87be8d64cc3b259bf2b0ec39daaaa3fac1f3f97af249824abc648`.
- Both alignment cores import only the shared `Point3`/`SegmentResult` data contracts from the early `manipulation_segments.py`. The selective port must provide those contracts without importing the excluded early `PlaceOneExecutor` implementation.
- The staged launch directory contains generated `__pycache__` files; these and all other generated artifacts remain excluded from the repository import.
- Standard-library inspection of the model checkpoint (without unpickling/executing it) found the embedded names `A`, `B`, `C`, `D`, `green`, and `red`. This confirms that the legacy root `configs/yolo/classes.yaml` numeric mapping does not describe this model and must not be used for manipulation packets.
- The recovered AprilTag tests exposed a real source mismatch: the core used single-result `solvePnP`, while the tests require IPPE multi-solution selection with prior-rotation continuity. The port now retains bounded per-tag pose history and expires it after missed frames.

## 2026-08-16 - Phase 130 startup and packaging integration findings

- `arm_new/arm_new_ros/setup.py` referenced an unapproved and absent `frame_transforms.yaml`, while `arm_motion.launch.py` resolved the excluded legacy static-transform launch at import time. The selective port must remove both dependencies and let the existing DWB TF tree remain authoritative.
- In cone mode the Host launch intentionally omits its existing `base_link -> camera_link` publisher because the inspection route does not consume camera-frame detections. The pick/place route needs that same calibrated Host TF for the YOLO UDP bridge, so the publisher must be enabled only when manipulation is enabled, preserving the current L6 behavior.
- The imported arm parameter file marks the camera/arm transform and grasp reference as calibrated even though the accepted merge assessment still lists grasp/release calibration as a hard gate. Repository defaults must be fail-closed and the full-route preset must require an explicit calibrated override before touching runtime.
- The current cone-mode depth relay always adds `--no-write-frames`; placement alignment requires canonical `latest_depth.raw` and `latest_depth.json`. Only the new pick/place branch should omit that flag, while the existing L6 branch keeps it unchanged.
- The accepted YOLO checkpoint is present but ignored by the repository-wide `InstanceSegmentation/**/*.pt` rule. The exact approved model path needs a narrow `.gitignore` exception and a repeated SHA-256 gate.

## 2026-08-16 - Phase 130 merge-preparation findings

- The selective-port implementation is locally complete and reviewable, but it is not yet field-ready. The correct handoff point is the current uncommitted integration branch, before any commit, merge, Jetson deployment, or robot runtime action.
- Existing inspection behavior is isolated from the new route: `scripts/start_l6.sh` is unchanged, while `scripts/start_l6_pick_place.sh` owns the fail-closed manipulation preset and requires explicit calibrated configuration.
- The production motion boundary is preserved: alignment publishes only `/cmd_vel_precision`; the existing arbiter and cone gate remain the sole route to `/cmd_vel`; cancellation, timeout, service failure, ABORT, and phase exit release the precision lease with zero commands.
- Placement consumes the canonical `latest_depth.raw + latest_depth.json` contract and validates sequence, timestamps, dimensions, step, byte count, CRC32, depth scale, endianness, mode, and CameraInfo before using a frame.
- YOLO packets now carry `model_id` and `class_schema`; `class_name` is authoritative and numeric IDs are not interpreted across model schemas.
- Repository defaults intentionally reject motion until calibrated overrides are supplied. This is required because the AprilTag ID/size convention conflicts, the four historical I2 values are duplicates, release/place targets remain unaccepted, and the latest observed place-alignment run timed out at 80 seconds.
- Local test evidence is strong for software integration (`404` tests and `244` subtests passed), but it does not replace Jetson package/image compatibility checks or physical segment acceptance.

## 2026-08-16 - Phase 131 review findings

- A fresh pick/place start enabled raw depth but not the color relay, while placement observation required `latest_color.jpg` for the color-frame geometry. The full-route preset now starts that relay inside the existing cuVSLAM container; it remains a subscriber rather than a second RealSense owner.
- UDP bridge freshness checks protect packets only while they are being received. TaskManager previously retained the last valid AprilTag and YOLO packet indefinitely, and placement could retain the last canonical depth snapshot. Consumer-side monotonic timeouts now prevent stale cached observations from generating alignment pulses.
- The Jetson image verifier must test behavior rather than package import alone. It now executes the CUDA-safe torchvision NMS fallback on synthetic boxes, warms the exact model on a zero image, and round-trips a synthetic source UDP packet through the same Host validation contract.
- The complete reviewed software suite now passes `406` tests plus `244` subtests. Python AST, Shell syntax, package XML, setup metadata, Git whitespace, model hash, and the preserved `start_l6.sh` hash all pass.

## 2026-08-16 - Phase 132 Jetson build-environment findings

- Jetson `superwfx666-desktop` is reachable at `100.126.48.49`, runs `aarch64` kernel `5.10.216-tegra`, and has Host ROS 2 Foxy only under `/opt/ros/foxy`; no active ROS distro was sourced in the login shell.
- `colcon` is available at `/usr/bin/colcon` with Python `3.8.10`. The root filesystem has about 177 GB free of 234 GB, sufficient for an isolated source build and later image build.
- The pushed remote ref `codex/pick-place-selective-port` resolves to exact commit `80bf2549947b44b7470b31e787da6eb2a505214e`, but that object is not yet present in the Jetson's shared local Git repository.
- Proposed isolated worktree `/home/superwfx666/worktrees/quadruped-pick-place-selective-port` does not exist. Existing worktrees include the preserved dirty vision worktree; none needs to be reset, cleaned, or reused.
- No Docker container and no matching RealSense, relay, cuVSLAM, Nav2, TaskManager, AprilTag, YOLO, or arm process was active at the point-in-time preflight. This is runtime-inactivity evidence only, not a hardware disconnect guarantee.
- Repository-local ByteRover memory is unavailable (`.brv` absent and `brv` CLI missing); Phase 124-131 PWF evidence remains the applicable project history.
- Plain `colcon list` from the repository root finds only the root package because package discovery stops descending once the root itself is identified as a package. Explicit base paths correctly discover `quadruped_robot_competition`, `arm_new_interfaces`, and `arm_new_ros`.
- An isolated Foxy build of those three packages passed in 56.6 seconds and installed all expected ROS package indexes and console scripts under `install/phase132`.
- `competition.launch.py` directly resolves the separate `whz` package, but root `package.xml` does not declare it. The formal install therefore needs both an explicit `whz` build path and a manifest dependency to avoid accidental resolution from an old overlay.
- The cone plugin depends on a pinned NonPersistentVoxelLayer source absent from `/opt/ros/foxy`; the expected source exists at `/home/superwfx666/cone_l2_plugin_ws_2_2_1/src/nonpersistent_voxel_layer` and is intentionally handled by the separate cone overlay build path in `start_competition.sh`.
- Image audit found a deterministic packaging failure: downloaded wheels are renamed to `/tmp/torch.whl` and `/tmp/torchvision.whl`, which pip rejects as invalid PEP 427 wheel filenames. The build layer also runs a CUDA-required verifier even though only the post-build `docker run` explicitly requests NVIDIA runtime.
- No trusted values for `TORCH_WHEEL_URL`, `TORCH_WHEEL_SHA256`, `TORCHVISION_WHEEL_URL`, or `TORCHVISION_WHEEL_SHA256` exist in the repository, Git history, PWF, or current local environment.
- Direct main-agent inspection confirmed the Dockerfile installs the generic `/tmp/torch.whl` paths and invokes the default CUDA verifier in its final `RUN`; `verify_runtime.py` also uses prefix version comparisons and validates only an empty detection list.
- The producer already exposes `MODEL_ID`, `CLASS_SCHEMA`, and `MODEL_CLASS_NAMES`, and each `Detection3D` has a complete `packet_dict()`. The verifier can import these producer constants, build one representative non-empty detection, JSON round-trip it, and validate it through the Host consumer contract without opening the D455.
- The root Python distribution intentionally installs `nodes.*` packages, so install smoke must import actual entry-point targets such as `nodes.decision.task_manager`; the distribution name itself is not a Python module.
- Exact commit `4e103bfe379e349336b0a7ce0b464fdfc929ff27` passed a fresh Jetson Foxy four-package build in 54.2 seconds using explicit `--paths` and standard isolated `build/install/log`. All four package prefixes resolved under that new install, expected root/arm/WHZ executables were indexed, actual target modules imported, and `competition.launch.py --show-args` parsed without launching nodes.

## 2026-08-16 - Phase 133 trusted wheel provenance findings

- Jetson local artifact `/home/superwfx666/jetson_wheels/torch-2.0.0+nv23.05-cp38-cp38-linux_aarch64.whl` is 171,768,083 bytes with SHA-256 `39eeb9894ef8c7b84249ab917f212a91703f30255d591b956ab12cc10e836532`.
- Direct ZIP metadata inspection reports `Name: torch`, `Version: 2.0.0+nv23.5`, `Requires-Python: >=3.8.0`, and wheel tag `cp38-cp38-linux_aarch64`.
- NVIDIA's official Jetson PyTorch installation page names `https://developer.download.nvidia.cn/compute/redist/jp/v511/pytorch/torch-2.0.0+nv23.05-cp38-cp38-linux_aarch64.whl`. A live HEAD response returned HTTP 200 and the same 171,768,083-byte content length. A full independent download and byte comparison is still running at this checkpoint.
- Jetson's installed Torch metadata is `2.0.0+nv23.5`, tag `cp38-cp38-linux_aarch64`; installed Torchvision metadata is `0.15.1`, tag `cp38-cp38-manylinux2014_aarch64`, with `Requires-Dist: torch (==2.0.0)`. Neither distribution contains `direct_url.json`.
- PyPI's official `torchvision 0.15.1` release JSON lists an unyanked `torchvision-0.15.1-cp38-cp38-manylinux2014_aarch64.whl`, uploaded 2023-03-22, size 17,477,632 bytes, SHA-256 `7fe9b0cd3311b0db9e6d45ffab594ced06418fa4e2aa15eb2e60d55e5c51135c`, at the content-addressed `files.pythonhosted.org` URL returned by PyPI.
- The official Torchvision filename/tag exactly matches the Jetson installed distribution's wheel tag. The artifact must still be independently downloaded, hash-checked, inspected, and exercised against NVIDIA Torch before image build acceptance.
- A second download from NVIDIA's documented Torch URL produced SHA-256 `39eeb9894ef8c7b84249ab917f212a91703f30255d591b956ab12cc10e836532`; `cmp` proved it is byte-for-byte identical to the preserved Jetson artifact. The subagent independently repeated this result and additionally verified all ZIP CRCs, all 9,682 RECORD hashes, and that all 15 ELF objects are AArch64.
- The PyPI Torchvision wheel downloaded to Jetson at the exact published size and SHA-256. Its metadata is `torchvision 0.15.1`, tag `cp38-cp38-manylinux2014_aarch64`, generator `bdist_wheel 0.37.1`, and dependency `torch ==2.0.0`.
- Comparing the official PyPI wheel directly against `/home/superwfx666/.local/lib/python3.8/site-packages` found 191 comparable files, zero missing files, and zero content mismatches. This establishes that the current compatible Jetson installation came from the exact official PyPI artifact despite the absent `direct_url.json`.
- PEP 440 evaluation confirms NVIDIA Torch `2.0.0+nv23.5` satisfies Torchvision's `torch ==2.0.0` requirement. With the repository fallback installed, both CPU and CUDA `torchvision.ops.nms` returned `[0, 2]`; CUDA was available and no camera or ROS process was opened.
- The official Torch wheel stores normalized metadata `2.0.0+nv23.5`, but its imported module reports raw `torch.__version__ == 2.0.0+nv23.05`. The image verifier's former raw-string comparison would reject the correct artifact, so the verifier now checks exact installed distribution metadata and retains fail-closed mismatches for all three locked packages.
- The PyPI Torchvision image extension still emits its known ABI warning on import, but the accepted runtime does not use `torchvision.io`; the required NMS fallback works on CPU and CUDA. Final acceptance still requires the isolated unified-image `pip check`, model warmup, and synthetic protocol test.
- This is L2 source/build evidence only. No ROS graph, Docker runtime, D455, navigation, arm service, or actuator path was started.

## 2026-08-16 - Phase 133 unified-image build failure

- The exact clean Jetson worktree at `fabbc9a7c85d21696c8227d7dd6fc8397e4cf2af` passed both pre-build gates and entered the Docker build.
- `Dockerfile.cuvslam-pick-place` runs `apt-get update` before wheel handling. The inherited stable cone image exposes three APT trust failures: expired ROS 2 testing signing key `F42ED6FBAB17C654`, missing Kitware key `65ADECD7A7039392`, and missing Isaac ROS key `58F4DA023E691207`.
- BuildKit stopped at layer 2/8 with exit code 100. No Torch/Torchvision download, SHA verification, pip uninstall/install, model warmup, protocol check, camera access, ROS graph, navigation, arm service, or actuator action occurred.
- The correction must remain within the derived pick/place Dockerfile/build path and must not mutate the stable cone image or `scripts/start_l6.sh`.
- The stable cone image stores the Isaac ROS and NVIDIA Jetson common repositories directly in `/etc/apt/sources.list`, so disabling only `/etc/apt/sources.list.d` is insufficient. The derived build can avoid all failing vendor repositories by generating a temporary list from the ten `ports.ubuntu.com/ubuntu-ports` entries and pointing APT exclusively at that file.
- Commit `fa9111fda677ce2df3e6322ea13bb5c38dcd9249` proves the APT correction: the formal build accessed only Ubuntu Ports, upgraded the three prerequisite packages, downloaded both accepted wheels, verified both SHA-256 values, and installed Torch `2.0.0+nv23.5` plus Torchvision `0.15.1`.
- The next blocker is dependency closure, not APT or wheel provenance. `requirements.lock` is installed with `--no-deps` but does not pin all dependencies required by Requests, Pandas, and Matplotlib; the stable base also reports missing `rospkg` for `rosinstall-generator` and `testresources` for `launchpadlib`. The existing OpenCV exception remains intentional because the image supplies system OpenCV rather than the `opencv-python` wheel.

## 2026-08-16 - Phase 133 dependency closure audit

- The accepted NVIDIA Torch wheel metadata requires only `filelock`, `jinja2`, `networkx`, `sympy`, and `typing-extensions`; it does not require the PyPI CUDA split packages or `fsspec`. Torchvision `0.15.1` requires `numpy`, `requests`, `torch==2.0.0`, and `pillow`.
- Native Jetson base-image inspection confirmed Python `3.8.10`, pip `20.0.2`, system OpenCV `4.2.0`, `catkin-pkg==1.0.0`, and `setuptools==65.7.0`. Base `pip check` additionally reports missing `rospkg` for `rosinstall-generator` and `testresources` for `launchpadlib`.
- A Python 3.8/aarch64 manylinux resolution using the exact top-level pins plus the accepted NVIDIA Torch URL, Torchvision `0.15.1`, `rospkg==1.5.1`, and `testresources==2.0.1` produced a 46-package closure. The generated closure excludes `opencv-python` by design and retains the base-compatible `catkin-pkg`, `distro`, `docutils`, `packaging`, `pyparsing`, `setuptools`, and `typing-extensions` pins.
- The lock correction must remain an explicit `--no-deps` install. The Dockerfile's existing `pip check` filter must continue allowing only the `ultralytics requires opencv-python ... which is not installed` line; every other dependency mismatch remains fatal.

## 2026-08-16 - Phase 133 first-stage rebuild finding

- Commit `4c86ebf018a96cd8c0cb5ab6772405a131b7bf8b` proves the dependency closure is correct in the real Jetson build environment: all locked packages installed from compatible Python 3.8/aarch64 wheels under `--no-deps`, and the strict `pip check` gate passed.
- `YOLO_DEVICE=cpu` is not sufficient to make the NVIDIA Torch wheel importable during ordinary `docker build`. Torch loads its global CUDA dependencies at import time and failed because `libcurand.so.10` and `libcublas.so` are supplied through the NVIDIA container runtime rather than the build environment.
- The build-stage verifier must therefore avoid importing Torch, Torchvision, Ultralytics, or the model. Full distribution-version, CUDA NMS, GPU warmup, model-class, and synthetic UDP verification must remain in the existing post-build `docker run --runtime nvidia --network none` stage.
- No target image was exported after the failure. This remains a packaging-stage issue and provides no camera, ROS, navigation, manipulation, or hardware acceptance evidence.

## 2026-08-16 - Phase 133 first-stage build success

- The correct verifier boundary is now proven at exact commit `78a120f4d61fd8daa31b9338bb7ef2abf0a72bc6`: ordinary Docker build validates pip closure, exact distribution metadata, system OpenCV `aruco`, and model SHA without importing the NVIDIA inference runtime.
- The default verifier remains the only path that imports Torch/Torchvision/Ultralytics and performs CUDA availability, NMS fallback, model warmup, model-class, and synthetic UDP checks. Both production call sites still invoke that default path through `docker run --runtime nvidia --network none`.
- The unified image successfully exported as `sha256:21d4dbf36112d29ac814a1396520ff3dbb177f2d07ade2f6bcda9a67d4bde06a`. This is build evidence only; the NVIDIA-runtime acceptance remains unexecuted.

## 2026-08-16 - Phase 133 NVIDIA-runtime import failure

- The exact full acceptance command with `--runtime nvidia --network none` reached the verifier but failed at its first Torch import because `libcurand.so.10` and `libcublas.so` were not visible inside the container.
- This disproves the assumption that selecting the registered NVIDIA Docker runtime alone is sufficient to inject the JetPack CUDA user-space libraries into this derived image on the current Jetson configuration.
- The failure occurred before CUDA availability, NMS, model warmup, model-class, or synthetic UDP checks. It does not provide inference acceptance evidence and did not access the D455, ROS graph, navigation, arm service, or actuators.
- NVIDIA runtime inspection shows that Jetson `l4t.csv` mounts driver-facing libraries such as `libcuda.so`, but contains no cuRAND/cuFFT/cuSPARSE/cuSOLVER/cuBLAS entries. CUDA toolkit libraries must therefore already exist in the image.
- Both the stable cone base and derived pick/place image contain CUDA runtime `11.4.298`, cuBLAS `11.6.6.84`, and cuDNN `8.6.0.166`, but omit five libraries required by the accepted Torch wheel: `libcurand.so.10`, `libcufft.so.10`, `libcusparse.so.11`, `libcusolver.so.11`, and `libnvToolsExt.so.1`.
- A complete `ldd` scan over all Torch/Torchvision native objects found no additional missing CUDA toolkit libraries beyond those five; standalone Torchvision objects also report Torch libraries that are resolved through the normal Python import path.
- Jetson's official NVIDIA APT metadata pins the required ARM64 packages and SHA-256 values: `libcurand-11-4=10.2.5.297-1` (`d4e00251...f692`), `libcufft-11-4=10.6.0.202-1` (`87f2161d...219f`), `libcusparse-11-4=11.6.0.299-1` (`b1fedfac...a04a`), `libcusolver-11-4=11.2.0.297-1` (`f2e39c71...5c6e`), and `cuda-nvtx-11-4=11.4.300-1` (`921de34d...5812`).
- The independent verifier safety audit confirmed that the default verifier does not open the D455, initialize ROS, contact navigation or arm services, command actuators, or send UDP. It uses only local package/model checks, GPU tensors, zero-image warmup, and in-memory synthetic packet validation.
- Installing the five locked CUDA packages into a disposable container is sufficient for both Torch and Torchvision imports. The next observed failure is independent: `verify_runtime.py` imported the ROS node only to read constants, causing `ModuleNotFoundError: rclpy` when invoked directly without sourcing Humble.
- Producer protocol constants are pure data and belong in a ROS-independent module. Sharing that module between the ROS node and verifier preserves producer/consumer identity checks while ensuring the no-camera verifier neither initializes nor depends on ROS.
- Explicit `YOLO_DEVICE=0` on both full verifier call sites closes the possibility that an inherited image environment could silently select CPU and bypass the intended CUDA acceptance.
- Direct Ultralytics loading of the exact SHA-locked model reports the authoritative mapping `{0: 'A', 1: 'B', 2: 'C', 3: 'D', 4: 'green', 5: 'red', 6: 'yellow'}`. Earlier standard-library checkpoint scanning missed `yellow`; executable runtime metadata is the decisive evidence.
- `yellow` is a legitimate model output and is already part of the repository's inspection status vocabulary. The Host bridge must accept it to preserve packet integrity, but TaskManager manipulation consumers intentionally ignore it; only A-D/red/green affect placement or red-bar workflows.
- After locking the complete mapping and schema, the disposable integrated verifier passed CUDA availability, NMS fallback, zero-image model warmup, class mapping, and synthetic producer-to-Host packet validation under `--runtime nvidia --network none`.

## 2026-08-16 - Phase 133 accepted unified image

- Accepted source commit: `af34b9f3c371f7ad551c6a30edf4126bcdc9ba6a`.
- Accepted image: `isaac_ros_cuvslam_runtime:humble-rs-cone-pick-place`, ID `sha256:f7384634ab69256558415a074d4ad53774f2399390ddcdc7135f2c33415fb5a0`, ARM64 size `18,707,536,476` bytes.
- The exact no-network NVIDIA-runtime verifier passed without host mounts. It established package closure, CUDA inference availability, NMS behavior, model load/warmup, exact model mapping, and producer-to-Host protocol compatibility.
- The emitted `torchvision.io.image` undefined-symbol warning is non-blocking for this accepted path: `torchvision.io` is unused, while the required `torchvision.ops.nms` fallback and Ultralytics warmup both passed. Any future use of `torchvision.io` requires a separate ABI-compatible wheel decision.
- This acceptance is intentionally below camera/ROS/robot evidence levels. It does not establish D455 ownership, live frame timing, ROS launch health, navigation, grasp/place calibration, arm services, or actuator safety.
## 2026-08-16 - Phase 134 initial boundary
- The exact unified image and no-camera NVIDIA-runtime verifier are already accepted at L2/L3-equivalent container scope, but they do not establish robot hardware or field readiness.
- Phase 134 must preserve the existing fail-closed manipulation defaults and distinguish recoverable deployment evidence from calibration values that require authentic operator acceptance.
- The repository has no available ByteRover store/CLI for this task, so L1-3 lookup cannot contribute historical evidence; PWF and Jetson-preserved artifacts are the available sources.

## 2026-08-16 - ROS build and launch audit requirements
- Source-tree correctness is insufficient: the Jetson audit must identify `AMENT_PREFIX_PATH`, the resolved package prefixes, and whether installed launch/config files exactly match the intended commit.
- `colcon` install spaces can retain deleted or stale artifacts, so a successful earlier build does not prove the current runtime will load the current source.
- Launch readiness must cover declared/default arguments, conditional branches, included launch files, event-driven sequencing, and shutdown behavior; node presence alone is not health evidence.

## 2026-08-16 - ROS deployment and bringup audit requirements
- The formal image tag must be resolved to the accepted immutable image ID before every verifier or runtime probe; image-name equality alone is not provenance.
- Embedded runtime checks require explicit environment sourcing, bounded startup/shutdown timeouts, and a cleanup/residue audit. A process or node appearing is not sufficient; health evidence must cover intended data flow and configuration.
- Device identity, permissions, time synchronization, DDS discovery settings, and actual process ownership are L4 preconditions. These can be audited without enabling motion, but cannot be inferred from a successful container-only verifier.
- The combined reference read truncated `system-bringup.md`; it must be reread separately before deriving the final checklist.

## 2026-08-16 - ROS runtime provenance requirements
- For any live no-actuation probe, capture process `cmdline`, `cwd`, `AMENT_PREFIX_PATH`, `PYTHONPATH`, `ROS_DISTRO`, `ROS_DOMAIN_ID`, and RMW settings from the real process namespace rather than inferring them from the shell.
- Diff source launch/config/module artifacts against the resolved install prefix; also check for orphaned installed files that no longer exist in source.
- Validate actual live parameters, `/cmd_vel`-family publisher counts, `/tf` and `/tf_static` endpoints, TF freshness, and OS process ownership. ROS node names or cached daemon output alone are insufficient.
- Configure-only validation is at most L2 and may still open hardware; a vendor node's configure path must be proven no-motion and outputs physically/logically isolated before it can be attempted on powered hardware.
- The combined reference read truncated `testing.md`; it must be reread separately before selecting a runtime smoke procedure.

## 2026-08-16 - ROS safety and manipulation boundaries
- Software stop or a zero Twist is not a verified hardware stop. The stop chain requires command ownership, driver translation, transport submission/device acceptance, and measured hardware response; the final link is L5 and is outside Phase 134.
- Any L4 observation must retain the single-arbiter invariant and verify no independent `/cmd_vel` or vendor-control bypass is active. Reset/enable state must remain fail-closed.
- Pick/place readiness requires accepted robot-specific transforms, grasp/place coordinates, reachability, collision assumptions, limits, and supervised execution evidence. Repository defaults cannot substitute for these measurements.
- The combined reference read truncated `safety-estop.md`; it must be reread separately before approving any hardware-powered probe.

## 2026-08-16 - Full-route entrypoint is not a no-actuation probe
- `scripts/start_l6_pick_place.sh` always passes `--dog --cmd-vel-bridge --prepare-lite3-motion` and enables the complete pick/place route.
- `--pick-place-l6` enables camera/depth relays, AprilTag, YOLO, arm service, manipulation, cone avoidance, TaskManager, and active Nav2 lifecycle nodes.
- Before ROS launch, the script may call `prepare_lite3_motion_mode.py`, which changes the dog into heartbeat/auto/navigation/motion mode even though it does not toggle stand/lie state.
- After startup acceptance, `start_competition.sh` sets `/task_manager_node mission_start_armed` to `true`. This can begin the real route; the entrypoint therefore cannot be used during Phase 134.
- A Phase 134 runtime check needs a separate fail-closed/preflight-only path or must remain read-only. Reusing the full route with an informal interruption point is not sufficiently reviewable.

## 2026-08-16 - Independent static audit gaps
- The final startup acceptance can currently print `GO` after cuVSLAM tracking wait, final odometry bridge wait, or dog-network checks only warned and continued. For the formal pick/place route these must be hard NO-GO conditions before TaskManager is armed.
- The startup snapshot records calibration paths and the parsed gate result but not the exact SHA-256 of both selected calibration YAML files. This weakens incident reconstruction and runtime provenance.
- `stop_all.sh` is not an arm emergency stop: it publishes base zero commands and kills the arm node, but already-issued servo motion has no proven cancel/hold path. This is a mandatory supervised L5 blocker, not an offline patch target without vendor stop semantics.
- The calibration gate catches missing, non-finite, duplicate, and internally inconsistent values, but it has no accepted physical envelope for tag size, I2 targets, or place distance. Bounds cannot be invented; they require a real site/arm calibration authority.
- `arm_motion_params.yaml` names a nonexistent `configs/calibration/competition_sites.yaml` as the future system source of truth, and no loader exists. The current actual authority is the explicitly selected override YAML plus external acceptance, so documentation/provenance must state that accurately until a site-calibration schema is designed.

## 2026-08-16 - Phase 134 verifier evidence
- The accepted image remains reproducibly valid under the required isolated GPU runtime: `--runtime nvidia --network none`, explicit `YOLO_DEVICE=0`, no host mounts, and the full verifier all passed on the Jetson.
- The successful checks are container/GPU inference evidence only. They do not raise the readiness level for D455 ownership, live ROS data flow, navigation, grasp/place calibration, arm services, or actuator safety.
- A uniquely named verifier container plus an unconditional exact cleanup trap provides auditable timeout/interruption cleanup; the run and post-run audit both showed no residue.
## 2026-08-16 - Phase 134 Jetson deployment and calibration audit

- Read-only Jetson audit found formal deploy `/home/superwfx666/quadruped-robot-competition-nav2-dwb-deploy` clean at `998a4322c517c466317e5cbeb200a463731fff51`, but it lacks `start_l6_pick_place.sh`, the arm packages, manipulation configuration, and the pick/place Dockerfile.
- The clean ROS build worktree at `4e103bfe379e349336b0a7ce0b464fdfc929ff27` resolves all four packages and expected bridge/arm entry points, but its Host producer contract is `competition-ad-red-green-v1`. The accepted image and source worktree at `af34b9f3c371f7ad551c6a30edf4126bcdc9ba6a` use `competition-ad-yellow-red-green-v1`; reusing the old overlay would create a deterministic schema mismatch.
- The accepted image remains `sha256:f7384634ab69256558415a074d4ad53774f2399390ddcdc7135f2c33415fb5a0`, ARM64, 18,707,536,476 bytes. The image itself has no embedded Git-revision attestation, so formal source commit and immutable image ID must be recorded as separate evidence.
- No accepted field evidence was found for measured AprilTag size/identity, four independent I2 targets, complete grasp coordinates, place coordinates, or `place_target_distance_m`. Historical I2 values were duplicated; current grasp/place flags remain false and place distance remains `0.0`.
- The Jetson had no running Docker container, relevant ROS/camera/Nav2/arm/Lite3 process, UDP listener on 19002/19003/19004, or related active systemd service. Exited historical containers use restart policy `no`.
- L6 remains NO-GO. Safe next work is limited to an exact reviewed formal deploy, clean four-package rebuild, seven-class schema verification, and no-action preflight. Authentic calibration and a supervised, independently proven arm stop chain are required before L5/L6.

## 2026-08-16 - Phase 134 formal Host schema gate

- A clean source checkout plus package-prefix checks do not prove that the installed Python modules were rebuilt from that checkout. The audited `4e103bf` overlay demonstrates this risk: it resolves the expected packages but carries the obsolete six-class schema.
- Formal preflight now imports the actually resolved `nodes.perception.yolo_udp_bridge_core`, verifies model ID `gauge-ad-3ed76de7-v1` and schema `competition-ad-yellow-red-green-v1`, and requires its source bytes to match the approved checkout.
- This gate complements, rather than replaces, the immutable image ID and full container verifier: the image proves producer/GPU behavior, while the Host import proves the deployed Foxy consumer contract.

## 2026-08-16 - Formal deploy resume checkpoint
- The authoritative deploy candidate is now exact commit `f31993c7e3dab77ef63a0e6861e3698264d5969a`, and the local checkout is clean with a matching upstream ref.
- The next admissible Jetson action is a bounded read-only repository/worktree inventory. No formal worktree may be created until its parent Git repository, current worktrees, free disk, and inactive runtime state are identified.
- The Jetson currently answers over a direct Tailscale path, so the inventory can use authenticated `tailscale ssh` with Base64-preserved LF-only script transport.
- Repository topology is split: prior pick/place build/image worktrees share `/home/superwfx666/quadruped-robot-competition/.git`, whose primary worktree is dirty; the existing formal deploy is a separate clean repository at `/home/superwfx666/quadruped-robot-competition-nav2-dwb-deploy` and currently manages `/home/superwfx666/cone-l2-l3-acceptance-6a69b93` as an additional worktree.
- A new formal worktree should be attached to the clean formal repository if that repository can resolve exact `f31993c`; this preserves the older formal deploy and keeps deployment provenance separate from the dirty development clone.
- The current Jetson runtime baseline is inactive: no container, relevant process, or audited UDP/control listener is present, and 173 GB is free.
- Neither Jetson repository currently contains commit `f31993c`. The formal repository's configured fetch refspec only tracks `Stonefield/nav2-foxy-dwb-integration`, so deployment must use an explicit narrow refspec for `codex/pick-place-selective-port` rather than changing the repository's persistent fetch configuration.
- The chosen immutable formal path is `/home/superwfx666/worktrees/quadruped-pick-place-formal-f31993c`, attached to the clean formal repository and checked out detached at the exact approved commit. This leaves the existing `998a432` formal deployment untouched as rollback evidence.
- The formal worktree now exists exactly as designed: detached `f31993c`, clean, sharing `/home/superwfx666/quadruped-robot-competition-nav2-dwb-deploy/.git`. It is approved for build/preflight evidence only and is not an authorization to launch L6.
- Formal source discovery must explicitly include four package roots: repository root, `whz`, `arm_new/arm_new_interfaces`, and `arm_new/arm_new_ros`; relying on root recursive discovery previously omitted nested packages.
- `scripts/preflight_l6_pick_place.sh` intentionally refuses to proceed unless both calibration approval flags are true and authentic paths/AprilTag values are supplied. Therefore a pre-calibration invocation cannot be promoted to a passing formal preflight; it can only demonstrate the fail-closed gate and absence of residue.
- The exact `f31993c` Jetson build proves the four-package Foxy overlay is fresh and internally discoverable. Prefix evidence now resolves `quadruped_robot_competition`, `whz`, `arm_new_interfaces`, and `arm_new_ros` exclusively under the new formal install, eliminating the previously audited stale six-class overlay from this worktree.
- The accepted seven-class identity is model `gauge-ad-3ed76de7-v1`, schema `competition-ad-yellow-red-green-v1`, and producer map `0:A, 1:B, 2:C, 3:D, 4:green, 5:red, 6:yellow`. Host validation intentionally treats `class_name` as semantic authority while requiring `class_id` to be a nonnegative integer.
- The next safe evidence step is limited to importing the installed pure Host protocol module, byte-comparing it to exact source, validating seven synthetic packets plus malformed rejections, comparing installed launch/config/interface artifacts, and parsing `competition.launch.py --show-args` without launching nodes.
- That safe evidence step passed on the Jetson. The formal Host module loads from the exact worktree source, the five installed launch/config/interface artifacts match byte-for-byte, all seven accepted class names validate, malformed model/schema/name/id/key variants reject, and launch argument parsing starts no runtime.
- The pre-calibration wrapper behavior is independently proven fail-closed: rc `2` occurs at the approval flag before `start_competition.sh`, with no log mutation or runtime residue. A complete preflight PASS cannot be obtained until authentic calibration is supplied and approved.

## 2026-08-16 - Remaining stop-chain evidence model
- A software zero command or process kill is not a verified arm stop. Evidence must separately cover command ownership, the exact vendor stop/idle/cancel translation, local submission versus remote device acceptance, and measured joint/current/physical response.
- Protocol acknowledgement may be absent; if so, the final report must state that device acceptance was not directly verified rather than relabeling downstream hardware response as an acknowledgement.
- Configure-only or import-only tests are not automatically no-motion because vendor code may touch hardware during initialization. Any live arm-node probe remains prohibited until source review proves the initialization path is passive and the actuator is physically isolated.

## 2026-08-16 - Independent field-calibration and arm-stop audits
- The current calibration contract is internally inconsistent: the runbook assigns pickup/place roles across AprilTag IDs, while the gate requires an I2 target for every global ID. The formal schema must carry explicit tag roles and require I2 only for pickup IDs.
- The calibration gate currently requires `enable_motion=true`, which conflates accepted calibration with permission to actuate. Offline/formal preflight must validate calibration while motion remains disabled; L5 motion authorization is a separate temporary decision.
- `transform_calibrated` is only a boolean. The accepted bundle must contain the numeric `base_link -> arm_base_link` transform and the runtime path must verify or publish that exact transform.
- Placement still depends on fixed D455 mounting values and nominal intrinsics/depth-to-color/box-width defaults. These values must be supplied by an accepted calibration file and injected into the placement path before field acceptance.
- A calibration evidence manifest must bind the exact source commit, immutable image ID, both YAML hashes, device identities, tag-role map, segmented measurement metadata, operator/supervisor identities, timestamps, and approval record. It provides traceability and tamper detection, not cryptographic identity authentication.
- The arm stack exposes no cancel/stop/hold service or protocol primitive. `future.cancel()` only cancels the client-side ROS future, the serial path only writes position frames, and process/serial shutdown cannot be claimed as a hardware stop.
- No vendor stop command may be implemented until the exact controller/servo models, firmware, power topology, and matching official protocol are identified. The admissible current L5 path is supervised proof of a physical actuator-power disconnect.

## 2026-08-16 - Competition-oriented manipulation policy correction
- The uncommitted approval-bundle design is disproportionate to the competition objective and will be removed before publication.
- The minimum hard contract is a named fixed arm preset with validated grasp/place numeric parameters, gripper pulses, and a conservative maximum sequence duration. Source/image provenance remains a deployment concern, not part of calibration approval.
- `transform_calibrated` and exact `base_link -> arm_base_link` matching are optional diagnostics for the fixed-motion path and must not block motion when the preset does not use runtime coordinate transforms.
- I2 pickup alignment and J1 visual placement alignment are optional enhancements. Disabled or failed alignment falls back to the coarse J0/fixed preset path.
- A successful ROS service response proves only that the host-side sequence completed without an exception; it does not prove object retention. Grasp/place failure or missing true grasp feedback is recorded as uncertain and the competition flow continues.
- Once an arm request is dispatched, the base must remain stationary until the configured maximum sequence duration has elapsed, even if the client future errors or times out, because cancelling the future does not cancel servo motion.

## 2026-08-16 - Fixed-preset implementation review findings
- The conservative arm guard must cover the successful response path as well as timeout/error paths. The current arm service is synchronous today, but the competition contract deliberately uses dispatch time plus `max_arm_sequence_sec` so a future server change or early response cannot release the base prematurely.
- Preset validation and motion authorization are distinct contracts. A valid `competition_v1` YAML must keep `enable_motion=false`; offline/no-action preflight may accept that preset, while actual grasp/place services require a separate launch-time authorization override.
- No-request failures and post-dispatch uncertainty have different timing requirements. A missing/unready service before `call_async` can be recorded immediately as uncertain; any result after dispatch must wait for the guard because client future state does not prove servo state.
- Optional perception must be conditional end to end: container process, Host bridge, fresh-topic probe, installed entry-point check, and final liveness check all follow the I2/J1 enable flags. Disabling an enhancement also requires clearing stale optional container processes before the route starts.
- `abnormal_attempted` is the zone index and completion driver. The existing `abnormal_handled` value now means software-confirmed place sequence completion only, not physical object placement; the detailed `manipulation_outcomes` field preserves the explicit `sequence_completed` versus `uncertain` result.

## 2026-08-16 - Final fixed-preset safety boundary
- `call_async()` raising locally does not prove that no request reached the service or downstream controller. The conservative competition policy therefore treats this path as post-dispatch uncertainty and applies the same `max_arm_sequence_sec` precision-zero guard before allowing base departure.
- The current evidence is local L0/L1 only: static validation and automated tests support the intended software contract, but do not establish Jetson deployment correctness, live ROS behavior, physical grasp/place success, a measured arm stop chain, or L5/L6 readiness.
- A new exact commit and fresh Jetson formal worktree are required because the existing formal `f31993c` worktree predates this uncommitted policy correction and cannot be reused as evidence for the changed behavior.

## 2026-08-16 - Goal resume evidence
- The existing active goal matches the user's current `/goal` text, so continuation does not require replacing or broadening the goal.
- The only local product diff is the previously recorded 15-file competition-oriented implementation based on `f31993c`; it must be reviewed as one coherent change and published as one commit after all targeted and full local tests pass.
- The accepted GPU inference image remains outside the current diff and must not be rebuilt unless later review finds a genuine image-content dependency change.

## 2026-08-16 - Final-review behavioral gaps
- `_tick_inspect_gauges()` currently assigns every non-normal A/B/C/D result to `_abnormal_zones` and enters `FINISH` when none are detected. This violates the fixed two-distinct-task contract for 0, 1, 3, and 4 detections and means the task queue is not normalized before freezing.
- `_tick_find_red_bar()` and `_tick_place_to_abnormal_zone()` both call the shared retry-or-ABORT helper after the last Nav2 retry. For manipulation approaches, the required policy is to record an uncertain skipped attempt and continue to the next frozen task; localization/odometry/startup/control conflicts remain separate hard ABORT paths.
- `PickOneExecutor` already supports `excluded_tag_ids` and returns `target_tag_id`, but TaskManager neither passes prior selections into `PickConfig` nor records a successful selected tag for the next round.
- The current calibration path permits an arbitrary number of pickup IDs and rejects duplicated I2 targets. The competition contract instead needs exactly two simple pickup IDs and must not treat independent multi-tag calibration evidence as a merge blocker.

## 2026-08-16 - Competition behavior closure
- A frozen tuple is the task queue boundary. Successful inspection readings contribute `agree_frames / total_frames` confidence; missing/invalid perception remains confidence `0` and is handled by the configured A/B/C/D fallback order.
- `PickOneExecutor` already had the correct visibility and exclusion semantics. TaskManager now records `target_tag_id` as soon as a round locks it and passes all used IDs as `excluded_tag_ids` to the next round.
- Manipulation navigation exhaustion and optional depth/I2/J1 failures are now local degradation paths. Route/inspection navigation, runtime localization/odometry, transition collision, startup provenance, and command ownership remain hard-failure domains.
- Offline preflight and no-motion ROS bringup are distinct: preflight exits before runtime mutation; `start_l6_pick_place_no_motion.sh` starts the graph with no Lite3/cmd_vel bridge, `ARM_MOTION_AUTHORIZED=false`, and `mission_start_armed=false` so installed nodes/services/parameters can be inspected without issuing motion.

## 2026-08-16 - Final publication review boundary
- The broad product diff confirms that the new work remains inside the original TaskManager architecture and exposes a separate no-motion wrapper, but the combined diff output is too large to serve as publishable review evidence by itself.
- Targeted review must prove two high-risk paths before commit: the exact two-round state/index transitions after a skipped grab or placement navigation, and whether starting `arm_motion_node` with `ARM_MOTION_AUTHORIZED=false` can expose preflight/services without issuing any serial motion command.
- The accepted GPU image contents are still unchanged by the host-side TaskManager, launch, configuration, and arm-service edits; no Docker rebuild is justified at this checkpoint.
- Targeted TaskManager review confirms that exhausted grab navigation and exhausted placement navigation each funnel through `_complete_place_attempt()` exactly once, increment the frozen-task index, record an uncertain outcome, and continue to the next frozen zone or `FINISH` rather than invoking the global ABORT path.
- The arm timing contract distinguishes pre-dispatch unavailability from post-dispatch uncertainty: service-not-ready paths may degrade immediately because no request was sent, while `call_async()` success, exception, timeout, rejection, and response failure all retain the conservative `arm_max_sequence_sec` zero-motion guard.
- Remaining code-review checks are the per-phase reset performed by `_enter_phase()` and the no-motion arm-node preflight path's interaction with the serial driver.
- `_enter_phase()` resets the per-round pick/place executors, futures, arrival/alignment flags, request clocks, uncertain state, and motion guard. This closes the cross-round leakage risk while preserving `_used_pick_tag_ids` across rounds so the second pick excludes the first selected Tag.
- Constructing `arm_motion_node` does not open the serial device or dispatch servo steps. The no-motion startup's `/arm/preflight` call does open `BusLinkerExecutor` and invokes `require_servos_online()`; final classification therefore depends on confirming that method performs identity/online queries only and never writes target positions.
- `require_servos_online()` calls `scan_ids()`, which uses the read-position protocol for online discovery. The only target-position command is `move_to_position()` inside `execute_steps(dry_run=false)`, and grasp/place execution is blocked while launch passes `enable_motion=false`; the no-motion preflight therefore performs serial queries but no arm motion command.
- `start_l6_pick_place_no_motion.sh` passes no dog, cmd_vel bridge, or Lite3 motion-preparation flag. The downstream option parser preserves those defaults as false, forces TaskManager unarmed and arm motion unauthorized, and still loads `waypoints_real.yaml/full_interleaved` for graph/parameter/waypoint inspection.
- The ROS-independent selector validates an A/B/C/D fallback permutation and returns an immutable two-element tuple: zero/one abnormal result is completed from configured order, exactly two are preserved, and three/four are ranked by abnormal confidence with configured-order tie breaking.
- Unit and integration contracts cover uncertain inspection continuation, frozen-task observability, exclusion of the first selected pickup Tag in round two, manipulation-navigation skip semantics, hard runtime localization/odometry ABORT, forced `full_interleaved`, no-motion flags, and post-dispatch arm timing guards. The configuration gate's exact numeric and optional-alignment conditions still require direct review plus execution.
- Direct gate review confirms that `pick_red_tag_ids` is always exactly two unique non-negative IDs. I2-disabled presets require no active I2 targets or Tag size; I2-enabled presets require one target per configured ID but do not require independent target values. J1-disabled presets do not require positive placement distance or camera geometry; those become required only when visual alignment is enabled.
- The fixed arm gate requires matching `competition_v1` presets, configured grasp/place coordinates, distinct open/close pulses, positive action timings, `enable_motion: false` in the YAML, and `arm_service_timeout_sec >= max_arm_sequence_sec`. It does not require numeric base-to-arm TF, approval manifests, device identity bundles, or a product-level stop-chain certificate.
- Final local evidence is L0/L1 only but complete for publication: focused `80/80`, repository `tests/` `429/429`, arm planner/service `9/9`, Python compilation, four Shell syntax checks, `git diff --check`, and the ROS 2 file/stop validators all passed with no skipped checks.
- The Jetson formal repository is clean and resolves the pushed branch to exact `26a2c28a52ccec9c1b54eeead6aff0e215e28b03`. Before deployment it had zero running containers, relevant ROS/camera/Nav2/arm/Lite3 processes, or listeners on UDP 19002/19003/19004, with 172 GB free.
- Fresh detached worktree `/home/superwfx666/worktrees/quadruped-pick-place-formal-26a2c28` now shares only the clean formal repository common Git directory, resolves exact `26a2c28`, and has zero status lines. The older `f31993c` evidence worktree remains untouched.
- Fresh Jetson discovery returned exactly four packages, and `colcon build --symlink-install` completed all four in 51.2 seconds. Every package prefix and expected executable resolves under the new worktree install; evidence is `/home/superwfx666/competition_logs/deployment/20260815T233417Z_formal_pick_place_26a2c28`.
- The post-build worktree remains exact and clean, with zero running containers, relevant processes, or audited UDP listeners. No camera, ROS graph, navigation goal, arm service call, serial motion, or actuator command occurred during deployment/build.
- A bounded Jetson search found no YAML selecting `competition_v1` and no startup-log reference to such a file. The new checkout correctly remains `manipulation_preset: unconfigured`, `pick_red_tag_ids: []`, and `arm_preset: unconfigured`.
- Repository/history search found only a prior grasp XY baseline and gripper pulse comments; the fixed place reference remains zero/unconfigured and the only complete preset values are test fixtures. Test fixtures and historical defaults are not authentic field parameters and cannot be used to pass the no-motion startup gate.
- `full_interleaved` contains 14 ordered route entries but 13 unique labels because `upper_corner_clear` intentionally appears twice. Verification must check the 14-entry resolved sequence and independently assert the five required grab/place labels in the loaded mapping; treating mapping length as route length is incorrect.
- Jetson installed/source byte comparison, Python module provenance, all five grab/place waypoints, the 14-entry ordered route, launch `--show-args` (169 lines), four Shell entrypoints, and the repository-default fail-closed gate all passed. Evidence is `/home/superwfx666/competition_logs/deployment/20260815T234335Z_static_pick_place_26a2c28`.
- The accepted Docker image is still exact `sha256:f7384634ab69256558415a074d4ad53774f2399390ddcdc7135f2c33415fb5a0`; no rebuild occurred. Invoking the no-motion wrapper with repository defaults stopped before runtime with `task and arm presets must both be competition_v1`, and the post-check residue remained zero.
- Local HEAD, upstream tracking ref, GitHub remote ref, and the Jetson detached formal worktree all resolve exact `26a2c28a52ccec9c1b54eeead6aff0e215e28b03`. The only remaining prerequisite for a successful no-motion graph bringup is authentic site YAML input, not another code change or image build.
- The Jetson wrapper's default overlay paths all exist and resolve correctly: Cone plugin under `/home/superwfx666/cone_l2_plugin_ws_2_2_1`, Nav2 BT under `/home/superwfx666/nav2_foxy_overlay_ws`, and the formal competition package under the new `26a2c28` install. Sourcing them starts no runtime and left zero residue.

## 2026-08-16 - Authentic preset history audit
- Commit `66256a5` introduced the arm service with explicit calibration instructions but kept `place_target_arm: [0,0,0]` and `place_target_configured: false`; it is implementation provenance, not evidence of a tested placement pose.
- Commit `80bf254` still kept the fixed placement reference zero/unconfigured. Values such as pickup IDs `[0,1]`, grasp `[0.42,0,0.20]`, placement `[0,0.42,0.20]`, and distance `0.45` occur in unit-test fixtures and cannot be promoted to authentic robot settings.
- Commit `746e64e` added `configs/calibration/competition_sites.yaml` and `configs/ros/grasp_place_params.yaml`; these files require direct inspection because they are the only historical candidates that might bind values to a named site rather than a test.
- Direct inspection shows `competition_sites.yaml` is explicitly `competition-sites-2026-08-09-draft`: navigation entries are `provisional`/`uncalibrated`/`conflict`, `fixed_release.target_m` is `null` with status `uncalibrated`, and only grasp XY `[0.45, 0.00]` is labeled a `confirmed_reference` from a standalone mounted-arm face-approach grasp. `grasp_place_params.yaml` is an independent/manual test configuration and says alignment signs still require first low-speed confirmation. These files cannot authenticate two pickup Tag IDs or a tested fixed placement preset.
- The same historical arm README says ArmPi `(0.00, 0.45, 0.06)` is the mounted-arm grasp baseline that was actually verified. Its direct-place example `(0.00, 0.42, 0.06)` is still framed as a dry-run candidate that must be checked before low-speed execution, so it is not tested placement evidence. Planner defaults `open_gripper=75` and `close_gripper=450` exist in code, but the README explicitly requires pulse verification before real execution; source defaults alone do not satisfy the requested tested preset.
- Commit `a88b157` is internally inconsistent as field evidence. `pick_i2_apriltag.yaml` contains `pick_red_tag_ids: [0,1]` and marks IDs 0-3 taught at one identical pose, while the handoff calls `[0,1]` a default/example and still warns that initial entries are untaught; the generated asset map assigns ID 0 to pickup and ID 1 to placement A. Its arm configuration labels `(0.00,0.42,0.15)` as pending real service validation and retains `place_target_configured: false`. The commit also introduced grasp-preopen pulse `0` while retaining release/open `75` and close `450`, but does not establish a completed fixed-place hardware run.
- Remote tip `origin/visionchange` (`73ce9d6`) changes only AprilTag alignment pulse timing relative to `a88b157`; its pickup YAML and arm YAML are unchanged. It therefore adds no later evidence for actual pickup IDs, fixed placement, or validated arm motion.
- The Jetson retains ignored local override `/home/superwfx666/worktrees/quadruped-vision-yolo-refactor/configs/test/arm_pick_hardware_test.local.yaml` (mtime 2026-08-12 21:05:29, SHA-256 `281ae53d...`). It enables motion and supplies `place_reference_grasp_arm: [0.0,0.42,0.15]`, 20 mm descent, 1200/800 ms segments, and duration scale 2.0, but explicitly labels the release point temporary and unsuitable for a full competition route. The old worktree arm YAML says gripper pulses 400 open / 256 close are calibrated on the current gripper. These are strong candidate values, but the override and comments alone do not prove a successful grasp/place service execution.
- Jetson shell history supplies the missing execution provenance: the arm node was repeatedly launched with that ignored override, preflight was called, the grasp target was iterated from `(0.45,0,0.06)` through intermediate poses to `(0.42,0,0.15)`, and many later sessions issued paired `/arm/execute_grasp_fixed` and `/arm/execute_place_fixed` calls at the final pose. No command output was retained, so this proves repeated supervised command execution rather than object-level success, but it is sufficient to identify the final historical fixed-motion candidate. The current two Tag IDs remain only `[0,1]` configuration evidence and require a quick field identity check.
- The finalized calibration gate permits both optional alignments to remain disabled: with I2 off, `pick_i2_targets_json` must be empty and no tag size is required; with J1 off, no RGB-D geometry or positive target distance is required. A Jetson-external `competition_v1` preset can therefore use the historical fixed grasp/place sequence for no-motion graph inspection while keeping YAML `enable_motion: false`, with only the physical identity of pickup Tags `[0,1]` left for onsite confirmation.
- Jetson external presets now exist at `/home/superwfx666/competition_configs/pick_place_competition_v1.yaml` (SHA-256 `f5a0bc2d...`) and `/home/superwfx666/competition_configs/arm_motion_competition_v1.yaml` (SHA-256 `c0e48bcf...`). The fixed-preset gate passed with Tags `[0,1]`, both optional alignments disabled, grasp `[0.42,0,0.15]`, and 20 s maximum sequence protection; the formal worktree remains exact `26a2c28` and tracked-clean.
- The exact-config Jetson no-action preflight passed at `/home/superwfx666/competition_logs/deployment/20260816T000726Z_competition_v1_preflight_26a2c28`: accepted image runtime verification, seven-class contract, `full_interleaved` 14-goal/13-unique waypoint gate, and formal overlay checks all passed. Post-preflight containers, related processes, and UDP 19002-19004 listeners were all zero.
- The first exact-config no-motion start reached a complete visible graph (`task_manager`, `arm_motion`, whz, Nav2 lifecycle nodes, arbiter, Cone safety/relay, odometry bridge) with DOG/cmd_vel bridge/motion-mode all disabled, but the external 240 s wrapper expired just as the product entered its own up-to-90 s lifecycle acceptance. Evidence `/home/superwfx666/competition_logs/deployment/20260816T001111Z_competition_v1_no_motion_graph_26a2c28` ended with `stop_all.sh` rc 0 and zero containers/processes/ports/tracked changes. This is a test-harness budget issue, not a product-start failure.
- The 420 s attempt independently confirmed the same graph and advanced much further: every Nav2 lifecycle node was active, `/cmd_vel` had the expected zero subscribers, Cone scan/health QoS matched, and live costmap/controller parameters were being appended until five seconds before the wrapper expired. Evidence `/home/superwfx666/competition_logs/deployment/20260816T001821Z_competition_v1_no_motion_graph_final_26a2c28` again cleaned to zero. The product's sequential verifier, sensor startup, lifecycle and many bounded ROS CLI checks require a wrapper budget derived from their aggregate upper bound, not 240/420 s guesses.
- With a sufficient wrapper budget, the exact product start reached `/arm/preflight` and exposed two concrete issues: it plans the arithmetic midpoint of the configured z range (`0.20`) rather than the fixed TaskManager request (`0.15`), and it always requires IDs 1-6 online even when `enable_motion=false`. The current planner rejects the midpoint while the historical fixed request is `0.15`; the no-motion identity requirement also conflicts with the competition scope. Correct behavior is a fixed z preset plus plan-only preflight when motion is unauthorized, while full motion startup still requires online servos.
## 2026-08-16 - No-motion arm preflight pause boundary
- The final Jetson no-motion bringup failure is narrower than the competition runtime logic: the graph reached `/arm/preflight`, but the node both planned an untested z-range midpoint (`0.20`) and required servo discovery while arm motion authorization was false.
- The local three-file correction separates offline graph/preflight validation from physical actuator availability. With `enable_motion=false`, preflight remains plan-and-duration-only and never opens the serial bus for servo scanning; with `enable_motion=true`, `require_servos_online()` remains mandatory.
- The external Jetson arm preset still needs its configured grasp z range constrained to the historically exercised fixed z `0.15` before the next exact no-motion run; this external configuration change has not yet been made in the paused session.
- Current verification is intentionally incomplete: arm tests, the expanded integration contract, and whitespace validation passed, but configuration-gate and full repository regression must be rerun after restoring PyYAML in an isolated temporary dependency directory.
- Publication and deployment provenance remain at `26a2c28a52ccec9c1b54eeead6aff0e215e28b03`. The three-file correction is uncommitted, so that SHA is no longer the candidate final delivery commit and must not be reported as L6-test-ready.
- No navigation goal, arm service, nonzero velocity, camera-ownership change, container start, Jetson deployment, or actuator command occurred after resuming; this is a clean handoff checkpoint before any further validation or remote action.
- The resumed source audit confirms the three-file correction does not weaken the motion-authorized preflight: `enable_motion=true` still opens `BusLinkerExecutor` and requires the configured servos online, while `enable_motion=false` performs only configuration, IK plan, duration, and optional TF checks. The tested fixed z remains a site-preset responsibility and must be represented as `grasp_z_min_m == grasp_z_max_m == 0.15` in the external Jetson YAML for the final no-motion acceptance.
- The corrected local publication baseline is now current at L0/L1: focused competition/arm tests `90/90`, repository tests `430/430`, arm tests `9/9`, compilation/Shell/diff checks, and ROS 2 validators all pass without skips. No additional product defect was found before amend/publication.
- Exact final source provenance is now `0e401f8c87509820e62cb4a683dadf31254ca130` on local HEAD, GitHub, and the new clean Jetson worktree. The four required packages built successfully and the immutable inference image remained `sha256:f7384634ab69256558415a074d4ad53774f2399390ddcdc7135f2c33415fb5a0`; no image rebuild was performed.
- The Jetson external arm preset now fixes both `grasp_z_min_m` and `grasp_z_max_m` to the historically exercised `0.15`, so no-motion preflight plans the same z as TaskManager instead of an untested arithmetic midpoint. The original `0.25` max file remains as `/home/superwfx666/competition_configs/arm_motion_competition_v1.before-0e401f8.yaml`.
- The exact no-action preflight passed at final SHA with zero residue. The subsequent no-motion ROS start visibly reached the required graph, but connection loss occurred before the complete acceptance output and cleanup evidence were retrieved; this remains an evidence gap, not yet a product failure or success.

## 2026-08-16 - Final no-motion interruption correction
- The operator identified the interruption as external power loss to the Jetson. The prior boot/recovery observations are consistent with power loss but must not be presented as evidence of a software, thermal, memory, or kernel failure.
- The pre-power-loss graph observations remain useful diagnostics, but the run cannot satisfy final acceptance because it did not produce the terminal `GO` and verified cleanup evidence.
- With power restored, the correct action is to rerun the unchanged no-motion entrypoint under an independent bounded watchdog and complete the residue audit; no product patch or image rebuild is implied by the interruption.

## 2026-08-16 - Startup parameter read false-negative
- The power-restored no-motion run constructed `/cone_scan_safety_gate`, whose own live log reported `timeout=0.200s required_frames=3`; the source declares `health_timeout_sec=0.20` and immediately consumes it during node initialization.
- Startup successfully read every preceding costmap/controller parameter and `required_consecutive_frames`, then one `ros2 param get` for `health_timeout_sec` returned nonzero inside the 8-second bound. This is a transient CLI/DDS observability failure, not evidence that the parameter is absent or wrong.
- A startup acceptance check should remain fail closed but tolerate a small number of read-only ROS CLI failures while the Jetson is heavily loaded. The scoped correction retries only parameter reads three times, checks that the competition launch remains alive between attempts, records the last error, and still produces NO-GO if all attempts fail.
- The failed run left no runtime residue and did not issue a navigation goal, arm motion service, Lite3 initialization, cmd_vel bridge, or actuator command.
- The retry implementation passed the full local L0/L1 publication gate. The ROS 2 validator does not inspect `.sh`, so Shell correctness is independently covered by Git Bash `bash -n`; the Python contract test verifies bounded retries, process-liveness gating, last-error recording, and the absence of fabricated fallback values.

## 2026-08-16 - Final no-motion acceptance and delivery boundary
- Exact final provenance is `16ad08c6fc4b2368535919b88eed08af2e2f7590` across local HEAD, upstream, GitHub, and the clean Jetson worktree. The four required installed package prefixes all resolve inside that worktree.
- The final product no-motion entrypoint itself passed (`START_RC=0`) and produced the terminal GO. The supervisor's four failures were checker defects, not runtime defects: damaged UTF-8 pattern transport, a false match on `enable_cmd_vel_bridge:=false`, and two checks for Unix executable bits outside the documented explicit-Bash invocation contract.
- Runtime evidence confirms no `/cmd_vel_bridge` node or positive process match, zero `/cmd_vel` subscribers, TaskManager unarmed, arm `enable_motion=false`, I2/J1 disabled, both arm services available, all required Nav2 lifecycle nodes active, and `waypoints_real.yaml/full_interleaved` with 14 route goals and all five grab/place approach labels.
- Cleanup evidence and an independent post-check agree on zero running containers, zero related processes, zero target UDP listeners, and zero Jetson worktree changes. The no-motion run is L4 evidence only; it does not prove physical grasp, placement, navigation, or failover behavior under motion.
- Jetson external presets are `/home/superwfx666/competition_configs/pick_place_competition_v1.yaml` (SHA-256 `f5a0bc2d...`) and `/home/superwfx666/competition_configs/arm_motion_competition_v1.yaml` (SHA-256 `05e82f79...`). Candidate pickup IDs remain `[0,1]` pending physical identity confirmation. The fixed historical arm values are grasp `[0.42,0.0,0.15]`, place `[0.0,0.42,0.15]`, open/close pulses `400/256`, descent `0.02 m`, pose/descent durations `1200/800 ms`, and `max_arm_sequence_sec=20`.
- The accepted Docker image remains exact `sha256:f7384634ab69256558415a074d4ad53774f2399390ddcdc7135f2c33415fb5a0`; host-side code changes did not require or trigger an image rebuild.

## 2026-08-16 - Minimal L6 launcher initial boundary
- The exact formal source baseline is `16ad08c6fc4b2368535919b88eed08af2e2f7590`, with the accepted image ID `sha256:f7384634ab69256558415a074d4ad53774f2399390ddcdc7135f2c33415fb5a0` and Jetson worktree `/home/superwfx666/worktrees/quadruped-pick-place-formal-16ad08c`.
- The operator wants no separate monitoring process and no redundant outer status inspection. This does not authorize removal of fail-closed checks already owned by the product launcher, nor any weakening of the arm-motion authorization or stop path.
- Candidate pickup IDs `[0, 1]` remain an unresolved physical identity fact. A clean launcher can require an explicit operator acknowledgement, but cannot turn that candidate into validated L6 evidence.
- No robot-side command is in scope for implementation verification. The new entrypoint must be proven only by static/source contracts and local tests before onsite supervised use.
- `scripts/start_l6_pick_place.sh` is already the narrow supported motion entrypoint and launches no monitoring sidecar. Its final command is `exec bash scripts/start_competition.sh --pick-place-l6 --dog --cmd-vel-bridge --prepare-lite3-motion`, so signals and exit status stay attached to the operator terminal.
- The remaining inconvenience is environment setup, not process architecture: the operator currently has to export two external YAML paths, the exact source SHA, image tag, immutable image ID, and arm authorization before invoking the wrapper.
- A minimal site-specific wrapper should set those fixed formal values and `exec` `start_l6_pick_place.sh`. It should not fork, background, poll, run `ros2`/Docker status commands, or duplicate readiness checks.
- `full_interleaved` names the route/config contract, while TaskManager owns the competition sequence and dynamically executes two pickup/place rounds. A new wrapper must not replace that state machine with a shell waypoint loop.
- `start_competition.sh` is a startup coordinator, not a monitor daemon. It background-starts the actual stack, verifies the exact runtime contract, arms TaskManager only after acceptance, prints the log/snapshot/stop command, and exits.
- The product launcher currently traps `INT`/`TERM` during startup and invokes its established cleanup on failure after runtime state has been touched. Once startup returns GO, `stop_all.sh` is the explicit operator stop/recovery path.
- The ROS 2 safety reference explicitly separates optional health monitoring from the command/safety path. Removing a monitor is acceptable; removing authorization, arbitration, fail-closed readiness gates, or the physical e-stop requirement is not.
- A repository commit cannot safely hardcode its own future Git SHA. To preserve the already accepted exact baseline without weakening provenance, the new helper must be explicitly scoped to the existing `/home/superwfx666/worktrees/quadruped-pick-place-formal-16ad08c` deployment and pin `PICK_PLACE_SOURCE_COMMIT=16ad08c6fc4b2368535919b88eed08af2e2f7590`.
- The implemented wrapper preserves the accepted source/image/config tuple exactly and performs no dynamic `git rev-parse HEAD` substitution. This avoids turning any arbitrary clean checkout into an implicitly approved deployment.
- Invoking the wrapper is intentionally the explicit operator motion authorization. It must not be run until the two external-YAML pickup IDs have been physically confirmed and the supervised L6 area/stop conditions are in place.
- Static proof now rejects `nohup`, background jobs, loops, sleeps, timeouts, ROS/Docker/pgrep probes, and waits in the wrapper, while requiring a single `exec env` handoff to `start_l6_pick_place.sh`.
- The formal `start_competition.sh` already has an intentionally clean `PURE_L6_START=true` mode. For the L6/pick-place flags it sets `TASK_MISSION_START_ARMED=true`, starts the stack, prints the pure-start banner, and exits before the later task-manager waits and `[6/6]` graph/QoS/parameter/health acceptance. Existing `test_formal_startup_chain.py` contracts both the absence of recorder/supervisor in the clean entrypoint and this early-return behavior.
- The final helper directly invokes `start_competition.sh` rather than wrapping a newly changed `start_l6_pick_place.sh`. This is necessary because the requested Jetson target is a frozen clean worktree at `16ad08c`; adding a new wrapper must not require it to run an unbuilt newer source revision.
- The helper retains the launcher's pre-stack fail-closed gates (external YAML validation, exact source/image provenance, formal overlay/runtime preparation, command path setup) but intentionally declines the post-stack acceptance checks. Its authorization decision is explicit in `ARM_MOTION_AUTHORIZED=true` and `PURE_L6_START=true`; it must only be used under the onsite supervisory conditions supplied by the user.
- Final evidence is L0/L1 only: static wrapper contract plus full local regression. No factual claim is made about navigation, physical grasp/place, arm stop response, localization, or the two-round field outcome.
## 2026-08-16 - Grab approach relocation geometry
- The operator-approved new `grab_area_approach` is ROS map pose `(x=4.25, y=3.05, yaw=-pi/2)`, centered above the estimated grab platform and facing toward it.
- The equivalent legacy field-coordinate record is `(x_mm=4250, y_mm=2950, yaw_deg=+90)` because field Y points downward and `_deg_to_quat()` negates field yaw.
- Direct parsing of `competition_field_phase1.pgm` places the grab lethal core up to approximately `map y=2.35`; the configured static inflation radius extends the cost envelope to approximately `map y=2.65`.
- With the configured footprint plus padding, yaw `-pi/2` produces a `0.37 m` half-extent along map Y. At center `y=3.05`, the footprint nearest the platform reaches `y=2.68`, leaving about `0.03 m` beyond the inflation envelope. Candidate `y=2.80` clears lethal cells but lets the footprint enter inflation costs.
- The existing formal route marks calibration complete based on the prior `(3.10, 2.00, 0)` field run. Changing only the grab waypoint invalidates that blanket completion claim; the route must become `in_progress` until supervised field acceptance.

## 2026-08-16 - Grab approach relocation implementation result
- All four code/config sources now agree on `grab_area_approach=(4.25, 3.05, -pi/2)`: formal route, preview route, NavigationClient fallback, and standalone Nav2 probe.
- The equivalent field-coordinate fallback is `(4250 mm, 2950 mm, +90 deg)`, which converts back to the same ROS map pose.
- Offline implementation and consistency checks are complete, but the formal route intentionally remains fail-closed with `calibration.status: in_progress` until the new pose is accepted during supervised field operation.
- No dedicated safety test was added or executed, per the operator's explicit instruction.

## 2026-08-16 - GitHub-to-Jetson waypoint deployment result
- GitHub and the new Jetson candidate worktree now share exact source SHA `676ef89c64f7f27a21de710bfd6bb9f8b332d893`.
- The deployed candidate path is `/home/superwfx666/worktrees/quadruped-pick-place-waypoint-676ef89`; the accepted historical `16ad08c` formal worktree remains intact and clean.
- Synchronization updates source/config only. The new route remains intentionally non-runnable through the formal calibration gate until supervised field acceptance changes `calibration.status` from `in_progress` to `complete`.

## 2026-08-16 - Latest-worktree one-click L6 result
- The historical wrapper filename no longer determines deployment provenance. Its own current clean worktree determines the source SHA and waypoint file, so updating that worktree from GitHub updates the one-click route without stale path redirection.
- The current released route resolves the grab waypoint to `(4.25,3.05,-pi/2)` and passes the same `load_calibrated_waypoints()` gate used by startup.
- `calibration.status: complete` now records operator release authorization for supervised L6, while `grab_area_approach_field_result: pending` explicitly preserves the lack of real-field outcome evidence for the relocated pose.
- Exact deploy provenance is GitHub/local/Jetson SHA `19b07e51f00f517f77a9a68dc0ccce327c636a18` in the existing Jetson formal worktree.

## 2026-08-16 - Restored taught I2 deployment result
- AprilTag camera-to-base conversion now defaults to the original project `configs/transforms/static_extrinsics.yaml`, using `base_link -> camera_link` translation `[0.231724440,0.077561412,0.503275873]` and quaternion `[0.000900958,0.240529563,-0.013474058,0.970547870]`; it no longer defaults to the navigation extrinsic.
- The Jetson external competition preset enables I2 for pickup IDs 0/1 with the shared original target `[0.806210719,0.018127014,3.109325721]` and `0.100 m` Tag size. J1 remains disabled because no positive placement target distance was authorized.
- The existing one-click wrapper already loads `/home/superwfx666/competition_configs/pick_place_competition_v1.yaml`, so its next invocation will consume these new I2 values without another script change.
- Exact runtime source provenance is `73718f99d4b3a2ce768ef1fda24f0129032383a8` on GitHub and the clean existing Jetson formal worktree. The affected package build and offline calibration gate passed, but no live AprilTag alignment or hardware motion was executed.

## 2026-08-16 - Temporary J1 distance override
- The Jetson external competition preset now enables placement vision alignment with operator-selected temporary `place_target_distance_m=0.2` so the full L6 flow enters J1.
- This value is configuration authorization only, not field calibration evidence. Replace it after measuring the successful real placement standoff.
- The previous J1-disabled preset is recoverable at `/home/superwfx666/competition_configs/pick_place_competition_v1.before-j1-0p2.yaml`.
- The offline gate and one-click external-config linkage pass; no live placement alignment or robot motion has validated the temporary distance.

## 2026-08-16 - Docker AprilTag readiness failure initial boundary
- This is a startup acceptance failure in the manipulation-perception reset/readiness stage, not a Nav2 waypoint gate, cuVSLAM tracking, camera relay, or depth relay startup failure: each of those earlier stages explicitly passed in the supplied transcript.
- The transcript alone does not distinguish whether the Docker AprilTag process crashed, remained alive under a different node name/domain, or waited for image/camera-info input. The repository launch command, readiness predicate, and captured container log must be correlated before assigning root cause.
- The launcher's cleanup behavior is correct for the current evidence: I2 is enabled, so accepting the run without the required AprilTag pose source would violate the configured manipulation contract.
- `scripts/start_competition.sh` launches `/opt/quadruped/perception/bin/run_apriltag_pose_node.sh` detached and waits at most 20 seconds for two simultaneous conditions: a process matching `[d]455_apriltag_pose_node.py` and the literal text `AprilTag IDs` in `/tmp/apriltag_pose.log`.
- The failure precedes the later Foxy-side fresh-packet check on `/apriltag/detections_base`. It therefore cannot yet be attributed to the UDP bridge, TaskManager subscription, or absence of a visible physical Tag; the Docker node did not satisfy its own initialization-ready marker.
- `d455_apriltag_pose_node.py` prints the required ready marker synchronously at the end of `D455AprilTagPoseNode.__init__()`, before receiving any image, CameraInfo, TF, or physical Tag detection. Missing/occluded Tags cannot explain this particular readiness timeout.
- Any process failure before that marker is concentrated in imports and constructor setup: ROS/CvBridge/TF imports, JSON/float parsing of `APRILTAG_TAG_IDS` and `APRILTAG_TAG_SIZE_M`, `AprilTagPoseDetector` construction, OpenCV `cv2.aruco`/`ArucoDetector` availability, socket/CvBridge/TF setup, or ROS subscription/timer creation.
- The unified-image verifier checks only `hasattr(cv2, "aruco")`, while `AprilTagPoseDetector.__init__()` requires both `cv2.aruco.DetectorParameters()` and `cv2.aruco.ArucoDetector(...)`. This leaves a concrete verification gap: an older system OpenCV can pass preflight because `aruco` exists, then crash the live node because `ArucoDetector` is absent.
- The requirements lock intentionally omits PyPI OpenCV and relies on the base image's system `python3-opencv`, making the exact system OpenCV API version a high-priority field check. The startup transcript's runtime-verifier success does not rule out this mismatch.
- Existing accepted-image history records the native base as Python 3.8.10 with system OpenCV `4.2.0`. The detector uses the newer object-oriented ArUco API (`DetectorParameters()` and `ArucoDetector`) rather than the older OpenCV 4.2 factory/function API, making an API-level crash the leading source-backed hypothesis.
- Failure cleanup calls `stop_all.sh`, which deletes `/tmp/apriltag_pose.log` before the cuVSLAM container is stopped. `startup_no_go()` prints the host snapshot path but does not copy the Docker AprilTag traceback into it, so the current failure path destroys the most direct diagnostic artifact.

## 2026-08-16 - Docker AprilTag readiness diagnosis result
- A read-only Jetson audit confirmed the failed run's exact source, image, I2/J1 switches, Tag IDs `[0,1]`, Tag size `0.1`, temporary placement distance `0.2`, cuVSLAM tracking, cone UDP health, camera relay, and depth relay. The configuration gate was valid; no current competition container remained after cleanup.
- The host startup log contains no inner traceback because the detached node writes only to container `/tmp/apriltag_pose.log`, and cleanup removes that file. The snapshot stops before `apriltag_udp_port=19003`, consistent with failure before Docker-node readiness.
- The most likely root cause is an OpenCV API mismatch: accepted image history records system OpenCV `4.2.0`; the verifier checks only that `cv2.aruco` exists; the live detector requires the newer object API and would raise before logging `AprilTag IDs`. This exactly explains why preflight passed and the first I2-enabled live launch failed.
- The `torchvision.io.image` undefined-symbol warning is non-fatal in this run: the same verifier continued through CUDA warmup, NMS, class-map, and synthetic UDP checks. It is unrelated to the AprilTag constructor path.
- Lowest-risk product fix is compatibility with the existing system OpenCV rather than installing a second OpenCV wheel into the ROS/CvBridge image: use the newer `ArucoDetector` path when available and fall back to `DetectorParameters_create()` plus `cv2.aruco.detectMarkers()` on OpenCV 4.2.
- Runtime verification should instantiate `AprilTagPoseDetector(0.1, [0,1])` or explicitly exercise the exact ArUco API used by production. Startup failure handling should print or copy `/tmp/apriltag_pose.log` before `stop_all.sh` deletes it.

## 2026-08-16 - Phase 142 release requirements
- Completion requires stronger evidence than local compatibility code: the exact new Git commit must be present in the Jetson formal worktree, the rebuilt image must have a new immutable ID, and that image must prove the AprilTag detector/node can initialize without camera or actuator access.
- The existing test gap has three parts: no OpenCV 4.2 API double, verifier does not construct the detector, and startup contracts allow cleanup to delete the only Docker traceback before surfacing it.
- The lowest-risk compatibility design keeps the system OpenCV exception and selects modern `ArucoDetector` when present, otherwise the OpenCV 4.2 `DetectorParameters_create()` plus module-level `detectMarkers()` path.
- The exact accepted image probe proves the fallback API is available on the target: OpenCV `4.2.0` exposes the AprilTag 36h11 dictionary, legacy parameter factory, and module-level detector function. No OpenCV package change is required.

## 2026-08-16 - Phase 142 final release state
- Production code now supports both OpenCV 4.2 legacy ArUco and newer object APIs without installing a second OpenCV distribution into the ROS/CvBridge image.
- Image verification now constructs the exact AprilTag detector used by production, closing the false-positive preflight gap. Startup NO-GO handling preserves and tails perception logs before `stop_all.sh` removes container temporary files.
- The rebuilt image passed the exact constructor path and the full Python ROS node initialization path. Physical Tag visibility is intentionally not required for readiness and remains part of the next L6 field test.
- All launch/preflight defaults now lock image `aafbc91a...`; source provenance is final commit `d16f245...`. The final preflight is the authoritative boundary: software is ready for the next supervised L6 startup, but no L6 outcome is claimed.

## 2026-08-16 - Phase 143 initial cuVSLAM timeout boundary
- The new failure is independent of the fixed AprilTag constructor path: startup never reaches camera/depth relay or manipulation-perception reset.
- `scripts/start_competition.sh` launches `start_cuvslam_rviz_gui.sh` in the background, then checks only for a running container name containing `cuvslam` for up to 180 seconds. If the wrapper exits immediately, the loop still waits the entire timeout and reports only the generic message.
- The failed `20260816_130248` snapshot has no `runtime_cuvslam_container` entry, and the post-cleanup Docker inventory has no container from that timestamp. The precise error must therefore be read from `/tmp/cuvslam_start.log` before changing timeout values.
- A running `d455_yolo_repro_20260811` container is present during diagnosis. It is a concrete camera/device-ownership conflict candidate, but not yet the proven cause.
- `/tmp/cuvslam_start.log` proves the conflict: D455 enumeration succeeded, but IR/depth setup failed with `VIDIOC_S_FMT errno=16 Device or resource busy`; the cuVSLAM preset then failed with an I/O error. Docker never became the relevant failure layer.
- `docker inspect` showed `d455_yolo_repro_20260811` bind-mounted `/dev:/dev` and ran `realsense2_camera_node` with the same D455 serial. Its restart policy was `no`, so stopping it is stable until manually restarted.
- After stopping only that stale test container, the exact repository D455 validator passed IR1/IR2/depth, accelerometer/gyro, and `RealsenseCamera.for_cuvslam`; the camera conflict is resolved without a full competition launch.
- The product correction should retain the original operator entrypoint and startup checks, but make the outer launcher observe early wrapper exit and preserve `/tmp/cuvslam_start.log`; increasing or merely reducing the timeout would not fix the diagnostic defect.
- Final deployment uses commit `51a0c22855b76eff5645f02c1ed3087c71877d71`. The operator wrapper filename and absolute path are unchanged; only its downstream startup script gained immediate background-exit detection and start-log preservation.

## 2026-08-16 - Phase 144 initial-pose runtime stall
- The dog remained stationary because the command path behaved fail-safe: `cmd_vel_bridge` received only `(0,0,0)` while TaskManager waited for Nav2 lifecycle activation. `AUTO_ADVANCE=false` was not the blocking condition.
- The first fatal runtime event was `initial_pose_publisher` importing `navi_map_data` through a source-tree path derived from `__file__`. In the installed package that path resolves under `install/.../lib/python3.8/`, where `navi/map/navi_map_data.py` does not exist.
- Without the node, `map -> odom` was absent. `planner_server` could not transform `base_link` to `map`, stayed inactive, and TaskManager correctly withheld the first navigation goal.
- The existing installed `cuvslam_start_prior.yaml` is a stable single-purpose runtime source and contains the same transform produced from `ROBOT_START_POSE`: x `4.65`, y `0.75`, yaw `pi`.
- The correction adds `nodes.navigation.start_prior`, which is automatically included by the existing `find_packages(where="src")`, and resolves the YAML artifact through `ament_index_python.get_package_share_directory`. No map data duplication or source-tree path injection remains in the runtime node.
- The loader rejects a non-`map` frame and non-finite transform values before publishing TF. The accepted artifact loads as exactly `(4.65, 0.75, pi)`.
- Installed-runtime evidence closes the original failure: the console entry point now stays alive, resolves the package-share prior, and publishes the exact accepted static transform. The next supervised launch no longer depends on a source-tree-only Python module.

## 2026-08-17 - Phase 146 post-obstacle odometry abort
- The stop is not a Nav2 active-goal stall. `obstacle_cross_target` returned `SUCCEEDED`, then TaskManager aborted before it could send the next route goal.
- The trigger is deterministic in the captured timeline: `DISABLED` was requested at epoch `1786930945.233`; RealSense stopped and closed the complete `Depth Module` at `1786930945.309-1786930946.367`; TaskManager aborted at `1786930946.430`; IR1/IR2 reopened only at `1786930946.893`; cuVSLAM reported tracking loss at `1786930947.016` and later recovered.
- On this RealSense driver/hardware combination, changing `enable_depth` restarts the shared stereo module. Therefore the prior assumption that the runtime parameter disables only the Depth stream while leaving IR stereo uninterrupted is false at the physical driver boundary, even though RGB and IMU are separate resources.
- The code has two conflicting time domains: `_runtime_base_safety_ok()` always enforces `odom_timeout_sec=1.0` before the phase-specific tick, while `_host_odom_ready_after_depth_transition()` intends to allow `host_odom_disable_timeout_sec=2.0` for fresh odometry after `DISABLED`. The generic check wins first and makes the recovery-specific timeout unreachable.
- Current recovery evidence is strong: the cuVSLAM UDP exporter continued beyond the incident, final_bridge reports normal ~20-30 ms latency, and its comparison CSV added 61 rows over 2.20 seconds during the read-only audit. This is a transient mode-switch outage followed by a latched TaskManager abort, not a persistent localization or UDP failure.
- The current `depth_controller_status.json` confirms the recovered steady state: `mode=DISABLED`, `depth_enabled=false`, `healthy=true`, `localization_ready=true`, with IR1/IR2/IMU/cuVSLAM ages all below 0.031 seconds.
- A future fix must explicitly coordinate runtime localization safety with the pending `DISABLED` transition. Merely increasing all odometry timeouts would weaken unrelated runtime fault detection; changing the RealSense resource strategy to avoid restarting the stereo module is a separate design option requiring field/resource validation.

## 2026-08-17 - Phase 147 initial stable-commit comparison
- Current `HEAD` and the locally cached `origin/codex/pick-place-selective-port` both resolve to `b5ef00dbe8abfc5a5678c1c50ef9205ba1d5349d`; a fresh GitHub query was unavailable because the configured local proxy could not connect.
- The immediately preceding field commit is `0a49132baddd2fa72c5db69a16242113b96525bd`. The Phase 145 field record shows that version crossed the obstacle and completed four inspections before stalling at the later premature `MANIPULATION` transition.
- `0a49132..b5ef00d` does not modify `scripts/depth_relay_docker.py`, `scripts/start_competition.sh`, the `obstacle_cross_target -> DISABLED` milestone, `_runtime_base_safety_ok()`, or the one-second `odom_timeout_sec` behavior.
- The latest commit changes the later pickup/placement policy: it keeps Depth disabled for `grab_area_approach`, enables `MANIPULATION` only after a placement approach succeeds, resets that timing per round, and adjusts no-op cone-layer acknowledgement. Those changes occur after the four inspections and cannot directly explain the immediate post-obstacle interruption.
- The `obstacle_cross_target -> DISABLED` milestone and optional RealSense `enable_depth` parameter strategy were introduced in `2034df247600a9cf15e9372ab24b7d029ed144fd` on 2026-08-11. Commit `d5f6501c021ad4113a6e5af616a6915b4cba62de` on 2026-08-14 hardened that strategy with live readback plus IR1/IR2/IMU/cuVSLAM verification; `80bf254` later refactored it for selective pick/place resources.
- Current evidence distinguishes resources: IMU is a separate RealSense Motion Module and was fresh after recovery; the observed outage was the shared stereo/Depth Module restart that temporarily removed IR1/IR2 and therefore cuVSLAM visual odometry.
- The prior `0a49132` field success is compatible with the same latent hazard: the transition can pass when IR/cuVSLAM recover before the generic one-second odometry guard expires. The current run's approximately 1.58-second IR reopen exceeded that guard, so a timing-dependent driver restart became a deterministic mission abort.

## 2026-08-17 - Phase 148 reused-container startup failure
- The failed formal restart began at `2026-08-17 10:08:58` and reused `cuvslam_gui_20260817-093922`, which had remained alive after the prior TaskManager abort.
- Startup phase zero deleted stale depth-mode request/status files but did not change the live RealSense parameters. The reused camera therefore remained physically in the prior mission's `DISABLED` state with `/camera/camera enable_depth=false`.
- The container still published cuVSLAM tracking from IR stereo, so the odometry readiness gate passed. `cone_scan_udp_exporter.py` was also still running, but it subscribed to `/camera/depth/image_rect_raw`; with Depth disabled it could not emit a fresh healthy cone packet to host port `19002`.
- The timestamped startup snapshot ends at `cuvslam_tracking_ready=true` and contains no `cone_udp_startup_probe`, precisely locating the failure at the next cone UDP gate. The operator terminal confirms `{"error": "no datagram received", "passed": false}`.
- The reuse branch checks exact image/tag/ID and tracking only. It lacks an AVOIDANCE resource reconciliation step before cone acceptance, so a valid but mission-disabled container is incorrectly treated as startup-ready.
- The cleanup message is expected fail-closed behavior: after phase zero, `STARTUP_RUNTIME_TOUCHED=true`; any later `startup_no_go()` calls `stop_all.sh`. Because the cuVSLAM container predated this attempt, `RUNTIME_STARTED_CUVSLAM=false`, so the Host formal stack was removed while the old container remained running.

## 2026-08-17 - Phase 151 Depth consumer subscription audit
- `scripts/depth_relay_docker.py` creates its `/camera/depth/image_rect_raw` subscription once when `--write-frames` is enabled. In `DISABLED`, `_on_depth()` returns before serialization, but the ROS subscription and message delivery remain active.
- `scripts/cone_scan_udp_exporter.py` always creates a raw Depth subscription in `main()`. Its callback rate-limits processing to 10 Hz, but still receives DDS image samples and processes accepted frames; it has no mission-mode control or unsubscribe path.
- `docker/d455_perception/d455_yolo_3d_node.py` always creates RGB, Depth, and CameraInfo subscriptions and continuously queues Depth frames. Its timer performs inference at `max_fps` regardless of TaskManager depth mode; there is no `DISABLED`/`MANIPULATION` gate.
- `scripts/start_competition.sh` starts the Docker depth relay for every pick/place run, starts the cone exporter inside the cuVSLAM launch when cone avoidance is enabled, and starts YOLO 3-D for the manipulation bridge. The current `DISABLED` mode therefore gates output consumers logically but does not reduce all upstream Depth CPU/DDS load.
- This explains the live resource profile (cone exporter ~80% CPU, depth relay ~76%, YOLO ~30%, RealSense ~50%) and cuVSLAM frame gaps without contradicting the repaired `enable_depth=true` physical-stream policy. A complete performance fix requires consumer lifecycle/mode gating, not another RealSense `enable_depth` transition.

## 2026-08-17 - Phase 153 latest rerun mid-mission stop
- The latest run reached `obstacle_cross_target` at epoch `1786937522.202`, then TaskManager aborted at `1786937530.183`, only about 8 seconds later. This was the first navigation goal; it did not cross the obstacle and did not issue a `DISABLED` request.
- The direct terminal predicate is again `runtime odometry became unavailable or stale` with the existing 1.0-second `odom_timeout_sec`. Nav2 received a cancellation from TaskManager and stopped normally; it did not report an autonomous navigation failure.
- The run was actively driving before the abort: the bridge observed motion commands up to `(0.240, 0.000, -0.150)` and no UDP send errors. Thus the robot stop is the expected downstream result of the TaskManager abort.
- No `Visual tracking is lost` event occurred around the abort. The latest cuVSLAM bridge sample at `1786937528.020` had 103.34 ms latency, 157 drained-old packets, and 211 stale drops. cuVSLAM repeatedly logged 66/100/133 ms image gaps against its 40 ms threshold, including immediately before the abort.
- Because there was no mode transition in the incident window, this independently reproduces an odometry freshness failure under sustained visual/DDS load. The prior `enable_depth=false` module-restart cause is not involved in this newest stop.

## 2026-08-17 - Phase 153 bridge/QoS and load boundary
- `final_bridge.py` publishes `/odom` with BEST_EFFORT depth 10; `task_manager.py` subscribes with the same BEST_EFFORT depth 10 profile. The source does not show a QoS reliability mismatch that would explain the isolated stale sample.
- `final_bridge` accepted odometry after the abort and its Docker exporter continued at roughly 30 Hz, so the failure is between continuous source traffic and the TaskManager callback's one-second freshness observation, not a permanent cuVSLAM/exporter exit.
- The latest run's Nav2 controller repeatedly missed its 10 Hz loop while the first goal was active. `cone_scan_protocol.depth_coverage_from_image()` performs a nested Python loop over every pixel and three zones for each accepted raw Depth frame; this is a concrete CPU path concurrent with cuVSLAM and other Depth consumers.
- The evidence supports a host/DDS scheduling backlog or callback starvation under sustained Depth workload, but the preserved logs do not identify the exact dropped `/odom` packet or prove whether the delay occurred inside DDS delivery versus TaskManager process scheduling.

## 2026-08-17 - Phase 153 final chronology and exclusion set
- Fresh formal startup `20260817_112753` created container `38cd4706...` from the locked image and passed cuVSLAM tracking plus cone UDP health; it did not reuse stale runtime state.
- `obstacle_cross_target` began at `1786937522.202`. During this first goal, Nav2 controller loop misses were logged at least 19 times, cone UDP rejected a stale-source packet at `1786937529.823`, TaskManager aborted on stale `/odom` at `1786937530.183`, and Nav2 then logged an expected client cancellation.
- The Depth and camera relay logs show only normal readiness followed by the later explicit cleanup's `ExternalShutdownException`; neither failed during the incident. No `DISABLED` transition, RealSense module stop/restart, or cuVSLAM tracking-loss log occurs near the abort.
- The repair target is therefore runtime load shedding and odometry observability: consumer lifecycle/mode gating must stop cone raw-Depth health processing outside `AVOIDANCE` and stop YOLO 3-D except `MANIPULATION`, while keeping physical `enable_depth=true`. Add a bridge-to-TaskManager inter-arrival diagnostic so a future run records the exact gap location before changing safety timeouts.

## 2026-08-17 - Phase 155 formal source-dirty NO-GO
- Formal startup at `20260817_120301` failed before a mission was launched because `scripts/start_competition.sh` rejects a nonempty `git status --porcelain --untracked-files=no` result for pick/place runs.
- The transferred L1 PWF files are untracked and are explicitly excluded by that predicate. They are not the cause of `formal source worktree has tracked modifications`.
- Remote tracked diffs span 18 paths: `README.md`, `src/nodes/decision/task_manager.py`, `configs/manipulation/pick_place.yaml`, `scripts/pick_place_calibration_gate.py`, L6 runbook, and multiple `arm_new` API/ROS/config/test files. These are unrelated pre-existing source modifications from the perspective of the PWF transfer.
- No safe automatic action exists: the formal launcher requires a clean tracked tree, while discarding or committing these changes would alter user work. Do not remove them without an explicit preservation/disposition decision.
