# cuVSLAM CPU 饱和、帧率测量与诊断负载说明

## 1. 文档目的

本文档记录 Jetson Xavier NX 上 cuVSLAM 测试 A/B 的纠错结论，说明：

- 单独开启 D455 RGB 是否会导致 cuVSLAM 降频；
- 为什么初次测试曾观察到约 `52.5 Hz`；
- 哪些诊断程序会造成 CPU 爆满和测量污染；
- 部署时如何关闭非必要诊断；
- 测试阶段如何控制变量，得到可重复、可解释的数据。

本文中的“降频”必须区分三种含义：

1. cuVSLAM 实际发布频率下降；
2. 订阅探针来不及处理，观察到的接收频率下降；
3. CPU/GPU 因功耗或温度限制发生硬件时钟降频。

本轮实验确认发生的是第 2 种，并伴随诊断程序造成的 CPU 饱和；没有证据表明 cuVSLAM 实际发布降频，也没有发生热降频。

## 2. 最终结论

干净对照结果：

| 测试 | RGB | IR1 | cuVSLAM Odom |
|---|---|---:|---:|
| A | 关闭 | 约 60 Hz | 约 59.8 Hz |
| B，低分辨率 | `640x360x30` | 59.86 Hz | 59.84 Hz |
| B，高分辨率干净对照 | `1280x720x30` | 59.85 Hz | 59.85 Hz |

高分辨率 RGB 对照中：

```text
Odom Host接收频率: 59.92 Hz
Odom源时间戳频率: 59.85 Hz
Visual tracking lost: 0
USB/bandwidth error: 0
CPU/GPU温度: 约30-33摄氏度
```

结论：

> 单独开启 D455 RGB 没有降低 cuVSLAM 实际发布频率。初次看到的约 `52.5 Hz` 是组合探针漏收消息和启动诊断占满 CPU 造成的观察者效应。

正式 RGB profile 仍采用 `640x360x30`，理由是满足 YOLO 输入需求并为 Depth、Alignment 和 YOLO 留资源余量，而不是为了修复 cuVSLAM 降频。

## 3. USB 带宽核对

Jetson 实测 D455 USB 链路：

```text
USB device speed: 5000 Mbit/s
理论带宽: 625 MB/s
```

`1280x720x30 RGB8` 原始流量：

```text
1280 x 720 x 3 x 30 = 82.9 MB/s
```

双路 `640x360x60 Y8` IR 原始流量：

```text
640 x 360 x 1 x 60 x 2 = 27.6 MB/s
```

合计：

```text
约110.5 MB/s，不含USB协议开销
```

即使考虑协议开销，也明显低于 USB 3.x 有效带宽。日志中没有出现：

- `bandwidth`；
- `No space left`；
- UVC profile 启动失败；
- RealSense stream 启动失败。

因此 USB 带宽不是初次测试中约 `52.5 Hz` 的原因。

## 4. 初次测量为什么错误

### 4.1 测量口径不同

测试 A 的约 `59.8 Hz` 来自：

```bash
ros2 topic hz /visual_slam/tracking/odometry
```

当时只订阅 Odom 一个 topic。

初次测试 B 的约 `52.5 Hz` 来自一个 Python 组合探针，该探针在单线程执行器中同时订阅：

```text
RGB
IR1
IR2
Odom
```

Python 需要依次反序列化多路大图像，来不及处理所有 Odom 消息，因此订阅端发生丢样。

该 `52.5 Hz` 表示探针处理能力，不代表 cuVSLAM publisher 频率。

### 4.2 测量时机不同

测试 A 的 Odom 频率检测位于启动诊断序列较前的位置。

初次测试 B 的组合探针运行时，启动器还在对 Path、PointCloud 和 Pose Graph 执行频率检测，并且 loop recorder 同时运行。因此 A/B 不是相同负载下的对照实验。

### 4.3 消息源时间与Host计数的区别

每个ROS消息包含源时间戳：

```text
msg.header.stamp
```

需要同时报告：

```text
Host rate   = Host实际执行回调数量 / Host时间
Source rate = 收到的消息数量 / 源时间戳跨度
```

如果Host处理不过来，两者都会受到漏收影响，但Host rate通常下降更明显。判断cuVSLAM是否真实降频，至少要满足：

- 一次只订阅一个topic；
- 订阅端能够接近满量接收；
- Host rate和Source rate接近；
- 同时检查publisher日志和tracking状态。

高分辨率干净对照中：

```text
Odom Host rate:   59.92 Hz
Odom Source rate: 59.85 Hz
```

这证明cuVSLAM没有实际降频。

## 5. 重型诊断程序

### 5.1 `loop_metrics_recorder`

文件：

```text
scripts/cuvslam_loop_metrics_recorder.py
```

用途：

- 订阅 odometry；
- 订阅 VO path 和 SLAM path；
- 计算轨迹长度和闭合误差；
- 调用 GetAllPoses 相关接口；
- 周期性写 CSV、JSON 和文本摘要。

主要输出：

```text
loop_metrics_latest.txt
loop_metrics_latest.json
odometry_samples.csv
slam_path_latest.csv
vo_path_latest.csv
```

它不参与cuVSLAM定位，也不向Nav2提供数据，只用于离线评估。

现场观测负载：

```text
约83%单个CPU核心
```

Path和pose数组随运行时间增长，Python解析、统计和文件写入会持续消耗CPU。

### 5.2 多个 `ros2 topic hz`

启动器会对多个topic依次执行：

```bash
timeout 12 ros2 topic hz <topic>
```

`ros2 topic hz`不是读取publisher内部计数，而是创建真实订阅者：

```text
DDS接收
-> 消息反序列化
-> Python回调
-> 时间统计
-> 输出平均频率
```

消息越大，测量本身越重。

### 5.3 Landmarks Cloud频率检测

topic：

```text
/visual_slam/vis/landmarks_cloud
```

内容是cuVSLAM地图视觉特征点云，主要供RViz显示。Nav2不依赖该topic。

对该topic执行`ros2 topic hz`时，需要接收并反序列化完整PointCloud2，CPU和内存分配成本明显高于Odom。

### 5.4 Observations Cloud频率检测

topic：

```text
/visual_slam/vis/observations_cloud
```

内容是当前帧或局部窗口中的视觉观测点，用于调试tracking和RViz显示。Nav2不依赖该topic。

现场观测：

```text
ros2 topic hz observations_cloud约占329% CPU
```

即大约占用3.29个CPU核心，是本次CPU爆满的主要直接来源之一。

### 5.5 Path频率检测

相关topic：

```text
/visual_slam/tracking/slam_path
/visual_slam/tracking/vo_path
```

`nav_msgs/Path`包含Pose数组。路径越长，单条消息越大。完整反序列化整条Path会产生明显CPU和内存开销。

Nav2正常定位只需要Odom和TF，不依赖这些可视化Path。

### 5.6 Pose Graph频率检测

相关topic：

```text
/visual_slam/vis/pose_graph_nodes
/visual_slam/vis/pose_graph_edges
/visual_slam/vis/pose_graph_edges2
```

内容是SLAM内部关键帧节点、帧间约束和回环约束，主要供RViz和算法调试。节点和边数量可能随运行时间增长。

当前启动器对`pose_graph_nodes`执行频率检测，并对其余可视化topic执行存在性检查。

## 6. 测试 A 是否也启动了这些诊断

是。

测试 A 和测试 B 都使用相同启动器，默认配置为：

```text
ENABLE_SLAM_VISUALIZATION=true
ENABLE_LANDMARKS_VIEW=true
ENABLE_OBSERVATIONS_VIEW=true
```

两组测试都会：

- 发布landmarks、observations、path和pose graph可视化topic；
- 启动`loop_metrics_recorder`；
- 依次执行多个`ros2 topic hz`。

所以不能说“这些诊断只让测试B降频”。正确结论是：

> 它们污染了A/B测试环境，而初次A/B又采用不同测量时机和不同订阅负载，导致结果不可直接比较。

诊断本身降低系统余量；B中的组合探针又额外反序列化RGB，因此B探针更容易漏消息。但cuVSLAM publisher本身仍保持约60 Hz。

## 7. CPU爆满的真实原因

测试过程中曾观测六个CPU核心接近100%。进程负载包括：

```text
ros2 topic hz observations_cloud: 约329% CPU
loop_metrics_recorder:             约83% CPU
cuVSLAM component container:       约50% CPU
RealSense node:                    约44%-60% CPU
ROS2 daemon和其他探针:             额外负载
```

因此CPU爆满的主要原因是：

1. 对大型PointCloud/Path执行Python频率测量；
2. loop recorder持续解析路径并写文件；
3. 多个诊断订阅和自定义组合探针同时运行；
4. RealSense和cuVSLAM核心进程仍需正常CPU时间。

这不是USB饱和，也不是D455单独开启RGB造成的。

## 8. 是否发生硬件热降频

稳态测试中：

```text
CPU/GPU温度: 约30-33摄氏度
GPU负载: 约6%-35%
RAM: 约3.4/14.9 GB
```

没有观察到温度过高或持续时钟下降，因此本轮没有发生热降频。

后续加入YOLO和Depth后，仍需使用`tegrastats`持续检查：

```bash
timeout 60 tegrastats --interval 1000
```

## 9. 日后部署时如何关闭重型诊断

### 9.1 关闭cuVSLAM可视化输出

当前启动器已经支持：

```bash
ENABLE_SLAM_VISUALIZATION=false
ENABLE_LANDMARKS_VIEW=false
ENABLE_OBSERVATIONS_VIEW=false
```

比赛模式建议：

```bash
ENABLE_SLAM_VISUALIZATION=false \
ENABLE_LANDMARKS_VIEW=false \
ENABLE_OBSERVATIONS_VIEW=false \
bash scripts/start_cuvslam_rviz_gui.sh --no-rviz --skip-input-test
```

这些开关只关闭调试可视化输出，不修改cuVSLAM tracking算法、IR输入、IMU融合和odometry。

### 9.2 关闭 `loop_metrics_recorder`

当前`start_cuvslam_rviz_gui.sh`仍会无条件调用：

```text
start_loop_metrics_recorder
```

`start_competition.sh`启动后会尝试杀掉recorder，但这不是最终可靠方案。启动器仍会先创建额外进程和负载。

正式修改应增加：

```text
ENABLE_LOOP_METRICS=0
```

并将启动逻辑改为：

```bash
if [[ "$ENABLE_LOOP_METRICS" == "1" ]]; then
  start_loop_metrics_recorder
fi
```

在该开关实现前，临时关闭方式为：

```bash
CN=$(docker ps --format '{{.Names}}' | grep cuvslam | head -1)
docker exec "$CN" pkill -INT -f '[c]uvslam_loop_metrics_recorder.py'
```

### 9.3 关闭自动 `ros2 topic hz`

当前启动器会无条件执行多个12秒频率探针。正式修改应增加：

```text
ENABLE_STARTUP_RATE_PROBES=0
```

或统一为：

```text
SKIP_RUNTIME_DIAGNOSTICS=1
```

当该开关为1时应跳过：

- status echo采样；
- 多topic存在性检查中的重型订阅；
- 所有自动`ros2 topic hz`；
- loop metrics recorder；
- RViz和重型可视化输出。

注意：该统一开关目前尚未实现，属于进入测试C和正式部署前的必做修改。

### 9.4 正式部署推荐命令

统一开关实现后，正式运行目标为：

```bash
SKIP_RUNTIME_DIAGNOSTICS=1 \
ENABLE_LOOP_METRICS=0 \
ENABLE_STARTUP_RATE_PROBES=0 \
ENABLE_SLAM_VISUALIZATION=false \
ENABLE_LANDMARKS_VIEW=false \
ENABLE_OBSERVATIONS_VIEW=false \
ENABLE_COLOR=1 \
ENABLE_DEPTH=1 \
ENABLE_ALIGN_DEPTH=1 \
bash scripts/start_cuvslam_rviz_gui.sh --no-rviz --skip-input-test
```

实际变量在代码实现后再作为正式接口使用。

### 9.5 正式运行应保留的接口

定位和导航核心保留：

```text
D455 IR1/IR2
D455 IMU
/visual_slam/status
/visual_slam/tracking/odometry 或正式选择的odometry源
/odom
TF
Depth障碍数据
```

按需启用：

```text
RGB
YOLO三维结果
perception status
```

默认关闭：

```text
landmarks cloud
observations cloud
pose graph visualization
完整Path记录
loop metrics recorder
自动topic hz
RViz
标注图持续发布
```

## 10. 测试阶段如何控制变量

### 10.1 一次只改变一个变量

推荐测试矩阵：

```text
A: IR + IMU + cuVSLAM
B: A + RGB
C1: B + Depth
C2: C1 + Alignment
D: C2 + YOLO 5 FPS
E: D + YOLO 10 FPS
F: E + Nav2 + Host Bridge
```

不要一次同时打开RGB、Depth、Alignment和YOLO，否则无法确定性能变化来源。

### 10.2 固定所有环境条件

每组测试保持一致：

- Jetson `nvpmodel`模式；
- 是否运行`jetson_clocks`；
- 电源和散热条件；
- D455 USB端口和线缆；
- IR/RGB/Depth profile；
- cuVSLAM参数；
- 可视化和诊断开关；
- 机器人静止或运动路线；
- 场景光照和纹理；
- 预热时间；
- 采样时长；
- 测量脚本及订阅QoS。

### 10.3 分开做功能测试和性能测试

功能测试可以检查：

- topic是否存在；
- 图像内容是否正确；
- TF是否连通；
- RViz是否显示；
- recorder是否生成报告。

性能测试必须关闭：

- recorder；
- RViz；
- cloud/path频率探针；
- 多路组合Python探针；
- 非必要可视化publisher。

不能在同一次运行中既开启所有诊断，又把CPU和帧率当作比赛性能。

### 10.4 完成预热后再测量

本机cuVSLAM GPU预热约需54秒。建议：

```text
启动
-> 等待cuVSLAM开始发布
-> 再等待30秒进入稳态
-> 开始60秒以上采样
```

启动阶段的频率和CPU不能作为稳态结果。

### 10.5 一次只订阅一个高带宽topic

错误做法：

```text
一个Python单线程节点同时订阅RGB、Depth、IR1、IR2、Odom和PointCloud
```

正确做法：

```text
先单独测Odom
停止探针
再单独测IR
停止探针
再单独测RGB
停止探针
最后测Depth
```

避免测量程序自身成为瓶颈。

### 10.6 使用正确QoS

相机和cuVSLAM常使用BEST_EFFORT/SensorData QoS。测试订阅者应显式匹配：

```python
from rclpy.qos import qos_profile_sensor_data
```

QoS不匹配可能表现为无数据或低频，不能误判为publisher降频。

### 10.7 同时报告Host rate和Source rate

建议每个探针输出：

```text
count
elapsed_host
host_rate
source_timestamp_span
source_rate
first_stamp
last_stamp
frame_id
```

如果Host rate明显小于Source rate，优先检查探针处理能力和DDS，而不是修改cuVSLAM。

### 10.8 记录资源与错误

每组测试记录：

```text
IR FPS
Odom Host/Source FPS
RGB/Depth FPS
tracking lost次数
frame delta warning/min
CPU各核心占用
GPU占用
RAM/SWAP
温度
实际camera profile
USB speed
启动错误
```

资源采样：

```bash
timeout 60 tegrastats --interval 1000
```

错误检查：

```bash
grep -Ei \
  'tracking is lost|bandwidth|No space left|uvc.*error|failed to start|exception' \
  <launch.log>
```

### 10.9 使用相同统计窗口

A/B/C必须使用相同：

```text
预热时间
采样时长
运动状态
探针顺序
诊断开关
```

不能用A启动后第2分钟的Odom单topic结果，对比B启动后第5分钟的多topic组合探针。

## 11. 推荐的科学测试流程

每一组配置按以下步骤执行：

1. 清理旧容器和Host订阅者；
2. 确认没有其他进程打开D455；
3. 设置唯一测试变量；
4. 启动cuVSLAM，关闭运行时重型诊断；
5. 等待GPU预热和30秒稳态；
6. 用单topic BEST_EFFORT探针测Odom 60秒；
7. 停止探针；
8. 测IR 60秒；
9. 停止探针；
10. 按需测RGB或Depth；
11. 同时后台运行`tegrastats`，但不运行点云/path频率探针；
12. 统计tracking lost和frame delta warning/min；
13. 正常停止容器；
14. 保存配置、日志和结论；
15. 下一组只改变一个变量。

## 12. 通过标准建议

以测试A约60 Hz为基线：

| 指标 | 建议标准 |
|---|---|
| cuVSLAM Odom源频率 | 接近60 Hz，长期无持续下降 |
| IR源频率 | 接近配置的60 Hz |
| tracking lost | 固定测试路线内为0或符合既有基线 |
| frame delta warning | 按每分钟统计，不显著高于A |
| CPU | 不持续全部核心100% |
| 温度 | 无持续热降频 |
| RAM/SWAP | 无持续增长或换页 |
| 数据延迟 | 不随运行时间持续增加 |

判断“降频”前必须同时满足：

- 单topic探针；
- 相同测试条件；
- 诊断负载一致或全部关闭；
- Host和Source频率均下降；
- 日志或资源数据支持该判断。

## 13. 后续必须完成的代码改动

在测试C和正式部署前，需要修改`start_cuvslam_rviz_gui.sh`：

1. 新增`SKIP_RUNTIME_DIAGNOSTICS`；
2. 新增`ENABLE_LOOP_METRICS`；
3. 新增`ENABLE_STARTUP_RATE_PROBES`；
4. 比赛模式默认关闭三者；
5. 将重型可视化publisher默认关闭或由比赛启动器显式关闭；
6. 保留独立的诊断模式，供SLAM精度专项测试使用；
7. 不修改`visual_slam_node` tracking算法和传感器参数。

同时建议把启动模式明确分成：

```text
diagnostic: RViz + recorder +可视化topic，专门测SLAM质量
benchmark: 无重型诊断，单变量性能对照
competition: 无重型诊断，只保留比赛必需接口
```

## 14. 最终原则

- 不能把订阅端漏收当作publisher降频；
- 不能在CPU被诊断程序占满时评价RGB或YOLO性能；
- A/B都启动相同诊断时，诊断本身不能解释真实A/B差异；
- 大型PointCloud和Path的`ros2 topic hz`是主动高负载订阅，不是零成本观察；
- `loop_metrics_recorder`只在SLAM质量专项测试中启用；
- 正式比赛关闭RViz、recorder、自动频率探针和重型可视化；
- 每次只改变一个变量，并使用相同、轻量、可重复的测量方法。

## 15. 2026-07-23 测试 C：连续 Alignment 的单核饱和

### 15.1 测试方法修正

本轮关闭了以下全部运行期诊断：

```text
SKIP_RUNTIME_DIAGNOSTICS=1
RViz关闭
loop_metrics_recorder关闭
自动topic list/hz关闭
landmarks/observations/pose graph等可视化publisher关闭
```

启动脚本为了等待topic会短暂创建ROS 2 CLI daemon。C1同时记录了daemon停止
前后两次Odom结果，停止后结果没有恢复，因此不能把C1差异归因于daemon；C2
正式采样前执行 `ros2 daemon stop`并确认进程消失。每次只运行一个
BEST_EFFORT订阅者。

完整 `sensor_msgs/Image` 的Python订阅者仍不是零开销。C1中直接订阅RGB和IR
时新增大量cuVSLAM frame-delta，因此这组频率作废。后续原始相机流改订阅
`camera_info`：它与图像具有相同帧头和发布节奏，但消息很小，显著降低测量
程序的反序列化和内存复制压力。

必须分别记录三种事实：

1. 驱动日志中的硬件profile，例如 `Depth Z16 640x360 @ 60`；
2. 轻量订阅者实际收到的Host和Source timestamp rate；
3. 探针窗口是否新增frame-delta，判断测量是否扰动被测系统。

不能把“驱动配置60 FPS”等价成“消费者必然收到60 FPS”，也不能把有明显
frame-delta的完整图像探针结果当成publisher真实频率。

### 15.2 C1：原始 Depth 的资源情况

配置为IR 60、Depth 60、RGB 30，Alignment关闭。30秒无订阅稳态窗口内：

```text
各核心CPU: 约10%-39%，没有核心持续100%
RealSense节点: 约52% CPU
cuVSLAM节点: 约40%-48% CPU
GPU: 0%-8%
RAM: 约2.9/14.9 GB
SWAP: 0
温度: CPU约34.5-35摄氏度
新增frame delta: 0
tracking lost: 0
USB/启动错误: 0
```

Depth轻量实收为59.38 Hz；RGB为28.56 Hz。Odom两次15秒实收结果分别为
58.24 Hz和56.12 Hz source timestamp rate，IR轻量实收为55.09 Hz。与无Depth
的测试B约59.8 Hz相比，C1余量变小，但无订阅空载窗口本身稳定。

### 15.3 C2：Alignment 的真实瓶颈

只把 `ENABLE_ALIGN_DEPTH` 从0改为1，profile保持：

```text
IR1/IR2: 640x360 @ 60
Depth:   640x360 @ 60
RGB:     640x360 @ 30
```

空载时RealSense节点约占122% CPU，容器约占137%-144% CPU；`tegrastats`
连续30秒显示同一个CPU核心保持100%。同时GPU只有0%-1%，RAM约2.86/14.9 GB，
SWAP为0，温度约34.5摄氏度。

因此这是RealSense ROS软件对齐路径的CPU单核瓶颈，不是：

- USB 5 Gbit/s带宽不足；
- GPU不足；
- 内存或Swap不足；
- 温度导致的热降频；
- loop recorder、点云或多topic `hz`造成的诊断饱和。

功能结果也证明主链已经不可用：aligned Depth只有约3.58 Hz，raw Depth约
4.59 Hz，RGB约2.87 Hz，IR为0 Hz，cuVSLAM Odom为0 Hz。日志中没有tracking
lost并不代表正常，因为cuVSLAM没有持续收到IR帧，已经没有跟踪输出可供判断。

把RGB从30 FPS降到15 FPS后，RealSense节点仍约122% CPU，IR和Odom仍为0 Hz，
所以RGB帧率不是该瓶颈的决定因素。

### 15.4 部署处理

在当前组合上禁止正式部署以下配置：

```text
ENABLE_DEPTH=1
ENABLE_ALIGN_DEPTH=1
```

推荐的下一轮控制变量测试是：

```text
IR和cuVSLAM保持原样
ENABLE_DEPTH=1
ENABLE_ALIGN_DEPTH=0
YOLO只取最新RGB和raw Depth
对齐/投影频率限制为YOLO的5 FPS
```

优先采用检测区域的稀疏Depth-to-color投影，或在YOLO工作线程内按5 FPS处理
整帧对齐；不要让RealSense驱动在60 FPS连续生成整幅aligned Depth。下一轮仍需
分别验证无消费者空载、低频对齐消费者和YOLO推理三种负载，不能一次全部开启。

## 16. Alignment根因补充：frame pool耗尽

脱离cuVSLAM单独运行与测试C相同的RealSense配置后，故障仍能复现：RealSense
节点约占122% CPU，并出现librealsense原生错误：

```text
Exception was thrown during callback: Out of frame resources!
```

所以Odom失败的因果链是：

```text
启用align_depth filter
-> RealSense ROS把Depth/Color/IR送入asynchronous_syncer
-> 单一frameset回调串行执行像素重投影和多路ROS发布
-> 60 FPS双路IR和Depth持续进入，处理速度跟不上
-> synthetic frame未及时释放，frame pool耗尽
-> IR停止/严重漏发
-> cuVSLAM没有双目输入
-> Odom归零
```

`enable_sync=false`不能绕开该路径，因为RealSense ROS 4.54.1在任意filter启用
时仍调用 `_asyncer.invoke(frame)`。关闭IMU后仍复现，排除IMU和cuVSLAM算法；
去掉IR后frame资源错误消失，确认多路视频与Alignment共享回调是关键触发条件。

以后错误检查必须同时匹配ROS日志和librealsense裸日志：

```bash
grep -Ei \
  'tracking is lost|out of frame resources|synthetic-stream|bandwidth|uvc.*error|exception' \
  <launch.log>
```

部署解决原则是关闭驱动内连续Alignment，保留raw Depth和RGB，在YOLO 5 FPS
线程内做稀疏Depth-to-color投影，或者对节流到5 FPS的图像运行独立注册节点。
