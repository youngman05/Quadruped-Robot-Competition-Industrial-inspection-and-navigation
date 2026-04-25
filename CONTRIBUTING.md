# Contributing Workflow

本文件规定四足机器人比赛项目的协作流程。目标是保证主分支稳定、Jetson 环境干净、实机测试可复现。

## 角色分工

- CV: D455 图像采集、YOLO 检测、仪表盘状态识别、目标深度定位。
- SLAM/VIO: 视觉惯性定位、地图或局部位姿估计。
- Navigation: move_base 或等价导航模块、路径执行、到点逻辑。
- Task Manager: 比赛任务状态机，串联巡检、播报、抓取、放置。
- Speech: 中文终端输出和语音播报。
- Arm Control: 机械臂或夹爪抓取、放置接口。

## 核心规则

1. `main` 必须保持可部署。
2. 不直接在 `main` 上开发。
3. 一个分支只做一个明确任务。
4. Jetson 是部署和测试设备，不是主要开发设备。
5. 改代码时同步更新相关文档、配置和测试说明。
6. 不提交大文件，包括模型权重、数据集、视频、rosbag、日志。

## 标准流程

### 1. 开始工作前

```bash
git checkout main
git pull --ff-only
git status
```

确认当前主分支干净，再创建分支：

```bash
git checkout -b feature/cv-gauge-detector
```

分支命名建议：

```text
feature/cv-xxx
feature/slam-xxx
feature/navigation-xxx
feature/task-xxx
fix/cv-xxx
docs/xxx
```

### 2. 开发前调研

写代码前先确认：

- 相关模块在哪里。
- 输入输出接口是什么。
- 依赖是否能在 Jetson Xavier NX 上安装。
- 是否需要 ROS topic、相机、机械臂或机器人本体。
- 是否会影响主运行链路。

### 3. 本机开发

在 Windows/开发机上完成代码修改和静态检查。

如果涉及 Jetson 依赖，先写清楚部署命令，不要在 Jetson 上临时手改后忘记同步。

### 4. 提交代码

```bash
git status
git add .
git commit -m "Add D455 smoke test"
```

commit 信息要说明改了什么，不要写 `update`、`fix bug` 这类无信息量描述。

### 5. 部署到 Jetson

在 Jetson 上：

```bash
git checkout main
git pull --ff-only
bash scripts/check_jetson_env.sh
```

如果测试某个功能分支：

```bash
git fetch origin
git checkout feature/cv-gauge-detector
git pull --ff-only
```

### 6. 实机测试

测试前：

- 确认机器人可以急停或遥控接管。
- 确认 D455、机器人本体、机械臂、扬声器连接正常。
- 确认电量和场地安全。

测试中：

- 记录任务阶段。
- 观察识别、导航、抓取失败点。
- 必要时录制视频和日志。

测试后：

- 记录问题现象。
- 保存关键日志。
- 判断问题属于参数、代码 bug、环境问题还是架构问题。

### 7. 合并

合并前应满足：

- 代码能在 Jetson 上运行。
- 相关测试通过。
- 文档已更新。
- 主分支不会被破坏。

推荐通过 GitHub Pull Request 合并，不建议直接 push 到 `main`。

