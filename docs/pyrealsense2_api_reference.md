# pyrealsense2 API 参考手册

> 来源：Intel 官方文档 + librealsense GitHub + 社区实践  
> 整理日期：2026-06-22  
> 适用于：Intel RealSense D455 + Jetson Xavier NX + Python 3.8

---

## 1. 安装

```bash
python3 -m pip install --no-cache-dir pyrealsense2==2.55.1.6486
```

---

## 2. 基础流程

```python
import pyrealsense2 as rs
import numpy as np

# 1. 枚举设备
ctx = rs.context()
devices = ctx.query_devices()
for dev in devices:
    print(dev.get_info(rs.camera_info.name))          # 设备名称
    print(dev.get_info(rs.camera_info.serial_number)) # 序列号

# 2. 创建 pipeline + 配置流
pipeline = rs.pipeline()
config = rs.config()
config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)   # RGB
config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)    # 深度

# 3. 启动
profile = pipeline.start(config)

# 4. 取帧
frames = pipeline.wait_for_frames(timeout_ms=5000)

# 5. 分离帧
color_frame = frames.get_color_frame()
depth_frame = frames.get_depth_frame()

# 6. 转 numpy
color_image = np.asanyarray(color_frame.get_data())   # (H, W, 3) uint8 BGR
depth_image = np.asanyarray(depth_frame.get_data())   # (H, W) uint16 mm

# 7. 停止
pipeline.stop()
```

---

## 3. 深度帧 (depth_frame)

### 3.1 像素深度查询

```python
# 单位：米
distance = depth_frame.get_distance(x, y)   # x=列, y=行

# 单位：毫米 (raw)
raw_value = depth_image[y, x]               # numpy: 先行后列!
```

### 3.2 常用方法

| 方法 | 说明 |
|------|------|
| `get_distance(x, y)` | 返回该像素深度（米），无效返回 0 |
| `get_data()` | 返回原始 uint16 数组 |
| `get_width()` / `get_height()` | 宽高（像素） |
| `get_stride_in_bytes()` | 每行字节数 |
| `get_bits_per_pixel()` | 每像素位数 |
| `get_frame_number()` | 帧序号 |
| `get_timestamp()` | 时间戳 |

---

## 4. 内参 (Intrinsics)

### 4.1 获取

```python
# 从深度帧获取
depth_intrinsics = depth_frame.profile.as_video_stream_profile().intrinsics

# 从彩色帧获取
color_intrinsics = color_frame.profile.as_video_stream_profile().intrinsics

# 从 profile 获取（启动时）
stream_profile = profile.get_stream(rs.stream.color)
color_intrinsics = stream_profile.as_video_stream_profile().intrinsics
```

### 4.2 内参字段

```python
intrinsics.width    # 图像宽度
intrinsics.height   # 图像高度
intrinsics.fx       # 焦距 x (像素)
intrinsics.fy       # 焦距 y (像素)
intrinsics.ppx      # 主点 x (像素)
intrinsics.ppy      # 主点 y (像素)
intrinsics.model    # 畸变模型: rs.distortion.brown_conrady / inverse_brown_conrady
intrinsics.coeffs   # 畸变系数: [k1, k2, p1, p2, k3]
```

### 4.3 手动构造内参

```python
intrinsics = rs.intrinsics()
intrinsics.width = 640
intrinsics.height = 480
intrinsics.fx = 600.0
intrinsics.fy = 600.0
intrinsics.ppx = 320.0
intrinsics.ppy = 240.0
intrinsics.model = rs.distortion.brown_conrady
intrinsics.coeffs = [0, 0, 0, 0, 0]
```

---

## 5. 深度对齐到彩色 (Alignment)

### 5.1 基础用法

```python
# 创建对齐对象：把深度对齐到彩色
align = rs.align(rs.stream.color)

frames = pipeline.wait_for_frames()
aligned_frames = align.process(frames)

aligned_depth_frame = aligned_frames.get_depth_frame()
color_frame = aligned_frames.get_color_frame()

depth_image = np.asanyarray(aligned_depth_frame.get_data())
color_image = np.asanyarray(color_frame.get_data())
```

### 5.2 要点

- `rs.align(rs.stream.color)` → 深度图被重投影/缩放到彩色分辨率
- `rs.align(rs.stream.depth)` → 彩色被重投影到深度分辨率
- **对齐后必须用对齐目标的 intrinsics**（如对齐到 color，就用 color intrinsics 反投影）

---

## 6. 2D → 3D 反投影

### 6.1 基础

```python
pixel = [x, y]    # x=列, y=行
depth = depth_frame.get_distance(x, y)   # 米

# 反投影到相机 3D 坐标系 (米)
point_3d = rs.rs2_deproject_pixel_to_point(intrinsics, pixel, depth)
# 返回: [X, Y, Z]   X=右, Y=下, Z=前（右手系）
```

### 6.2 手动计算（验证用）

```python
fx, fy = intrinsics.fx, intrinsics.fy
ppx, ppy = intrinsics.ppx, intrinsics.ppy

X = (x - ppx) / fx * depth  # 右为正
Y = (y - ppy) / fy * depth  # 下为正
Z = depth                     # 前为正
```

### 6.3 计算空间两点距离

```python
import math

def pixel_distance(depth_frame, intrinsics, x1, y1, x2, y2):
    d1 = depth_frame.get_distance(x1, y1)
    d2 = depth_frame.get_distance(x2, y2)

    p1 = rs.rs2_deproject_pixel_to_point(intrinsics, [x1, y1], d1)
    p2 = rs.rs2_deproject_pixel_to_point(intrinsics, [x2, y2], d2)

    return math.sqrt(
        (p1[0] - p2[0])**2 + (p1[1] - p2[1])**2 + (p1[2] - p2[2])**2
    )
```

---

## 7. 坐标系变换 (Extrinsics)

### 7.1 深度→彩色坐标变换

```python
depth_intrin = depth_frame.profile.as_video_stream_profile().intrinsics
color_intrin = color_frame.profile.as_video_stream_profile().intrinsics
depth_to_color_extrinsics = depth_frame.profile.get_extrinsics_to(color_frame.profile)

# 先在深度系反投影
depth_point = rs.rs2_deproject_pixel_to_point(depth_intrin, [x, y], depth)

# 变换到彩色系
color_point = rs.rs2_transform_point_to_point(depth_to_color_extrinsics, depth_point)
```

### 7.2 Extrinsics 字段

```python
extrinsics.rotation    # [r00, r01, r02, r10, r11, r12, r20, r21, r22] 行优先 3x3
extrinsics.translation # [tx, ty, tz]  米
```

---

## 8. 后处理滤波器

### 8.1 推荐处理顺序

```
原始深度 → Decimation → Depth2Disparity → Spatial → Temporal
         → Disparity2Depth → Hole Filling → Threshold → 输出
```

### 8.2 完整示例

```python
# 创建滤波器
decimation = rs.decimation_filter()
decimation.set_option(rs.option.filter_magnitude, 1)  # 1=不降采样

spatial = rs.spatial_filter()
spatial.set_option(rs.option.filter_magnitude, 5)
spatial.set_option(rs.option.filter_smooth_alpha, 0.75)
spatial.set_option(rs.option.filter_smooth_delta, 35)
spatial.set_option(rs.option.holes_fill, 3)

temporal = rs.temporal_filter()
temporal.set_option(rs.option.filter_smooth_alpha, 0.35)
temporal.set_option(rs.option.filter_smooth_delta, 45)

hole_filling = rs.hole_filling_filter()
hole_filling.set_option(rs.option.holes_fill, 1)  # 1=基本, 2=激进

threshold = rs.threshold_filter(min_dist=0.15, max_dist=7.0)

# 视差变换（改善远距离滤波质量）
depth_to_disparity = rs.disparity_transform(True)
disparity_to_depth = rs.disparity_transform(False)

# 处理循环
while True:
    frames = pipeline.wait_for_frames()
    depth_frame = frames.get_depth_frame()
    if not depth_frame:
        continue

    depth_frame = decimation.process(depth_frame)
    depth_frame = depth_to_disparity.process(depth_frame)
    depth_frame = spatial.process(depth_frame)
    depth_frame = temporal.process(depth_frame)
    depth_frame = disparity_to_depth.process(depth_frame)
    depth_frame = hole_filling.process(depth_frame)

    depth_image = np.asanyarray(depth_frame.get_data())
```

### 8.3 各滤波器参数

| 滤波器 | 参数 | 典型值 | 说明 |
|--------|------|--------|------|
| **Decimation** | `filter_magnitude` | 1-8 | 降采样倍数，值越大分辨率越低 |
| **Spatial** | `filter_magnitude` | 2-5 | 平滑强度 |
| **Spatial** | `filter_smooth_alpha` | 0.25-0.75 | 边缘保留（越小越锐利） |
| **Spatial** | `filter_smooth_delta` | 20-50 | 边缘检测的深度差阈值 |
| **Spatial** | `holes_fill` | 0-4 | 内部孔洞填充 |
| **Temporal** | `filter_smooth_alpha` | 0.1-0.5 | 时域平滑（越小越平滑） |
| **Temporal** | `filter_smooth_delta` | 20-100 | 帧间最大深度变化阈值 |
| **Hole Filling** | `holes_fill` | 1-2 | 1=最近邻, 2=外推填充 |

### 8.4 对齐 vs 滤波的顺序

Intel 建议：**先滤波，后对齐**。在 frameset 上操作：

```python
align = rs.align(rs.stream.color)

while True:
    frames = pipeline.wait_for_frames()

    # 在 frameset 上滤波
    filtered = decimation.process(frames).as_frameset()
    filtered = spatial.process(filtered).as_frameset()

    # 最后对齐
    aligned = align.process(filtered)
    depth_frame = aligned.get_depth_frame()
```

---

## 9. 可视化

### 9.1 深度图伪彩色

```python
import cv2

depth_image = np.asanyarray(depth_frame.get_data())

# OpenCV 伪彩色映射
depth_colormap = cv2.applyColorMap(
    cv2.convertScaleAbs(depth_image, alpha=0.03),   # alpha 调节亮度
    cv2.COLORMAP_JET
)

# 并排显示
images = np.hstack((color_image, depth_colormap))
cv2.imshow('RGB + Depth', images)
cv2.waitKey(1)
```

### 9.2 深度叠加

```python
# 深度图转 alpha 叠加
depth_colormap_dim = depth_colormap.shape
color_colormap_dim = color_image.shape

# 如果对齐后分辨率不同，resize
if depth_colormap_dim != color_colormap_dim:
    color_image = cv2.resize(color_image, dsize=(depth_colormap_dim[1], depth_colormap_dim[0]))

# 半透明叠加
blended = cv2.addWeighted(color_image, 0.6, depth_colormap, 0.4, 0)
```

---

## 10. Advanced Mode（预设加载）

```python
import json

device = profile.get_device()
advanced_mode = rs.rs400_advanced_mode(device)

# 加载从 RealSense Viewer 导出的 JSON 预设
with open("HighAccuracyPreset.json", "r") as f:
    preset_json = json.load(f)

advanced_mode.load_json(json.dumps(preset_json))
```

---

## 11. 常见坑

| 问题 | 原因/解决 |
|------|-----------|
| `get_distance()` 返回 0 | 该像素深度置信度低（边缘、暗面、反光）。用孔洞填充或检查邻近像素 |
| numpy 索引反了 | `get_distance(x,y)` 是 (列,行)，numpy `arr[y,x]` 是 (行,列) |
| 对齐后 intrinsics 选错 | 对齐到 color → 用 color intrinsics 反投影；对齐到 depth → 用 depth intrinsics |
| 单位混淆 | `get_distance()` 返回**米**，`get_data()` 是**毫米** (uint16) |
| 单位混淆 | `rs2_deproject_pixel_to_point` 输出 `[X,Y,Z]` 单位**米** |
| 时间滤波需要连续帧 | 单帧无效，必须在循环里跑 |
| `wait_for_frames` 阻塞 | 超时用 `wait_for_frames(timeout_ms=5000)` |

---

## 12. IMU (BMI055 Accel + Gyro)

D455 内置 Bosch BMI055 六轴 IMU（三轴加速度计 + 三轴陀螺仪）。

### 12.1 查询传感器

```python
sensors = device.query_sensors()
for s in sensors:
    print(s.get_info(rs.camera_info.name))
# Output:
#   Stereo Module
#   RGB Camera
#   Motion Module          ← IMU 在这里
```

### 12.2 支持的速率

```python
# 查询 Motion Module 支持的所有 profile
motion = device.query_sensors()[2]  # Motion Module
for p in motion.get_stream_profiles():
    print(p.stream_name(), p.fps())
# Accel: 100, 200, 400 Hz
# Gyro:  200, 400 Hz
```

### 12.3 启用 IMU 流

```python
pipeline = rs.pipeline()
config = rs.config()
config.enable_stream(rs.stream.accel, rs.format.motion_xyz32f, 200)  # Hz
config.enable_stream(rs.stream.gyro,  rs.format.motion_xyz32f, 400)  # Hz

# 可以和视频流混合
config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)

pipeline.start(config)
```

### 12.4 读取 IMU 数据

```python
frames = pipeline.wait_for_frames()

accel_frame = frames.first_or_default(rs.stream.accel)
gyro_frame  = frames.first_or_default(rs.stream.gyro)

a = accel_frame.as_motion_frame().get_motion_data()
g = gyro_frame.as_motion_frame().get_motion_data()

print(f"Accel (m/s2): x={a.x:.3f} y={a.y:.3f} z={a.z:.3f}")
print(f"Gyro (rad/s): x={g.x:.3f} y={g.y:.3f} z={g.z:.3f}")
print(f"Timestamp: {accel_frame.get_timestamp()} ms")
```

### 12.5 数据含义

| 传感器 | 单位 | 说明 |
|--------|------|------|
| `accel.x/y/z` | m/s² | 三轴加速度，含重力。静止平放时 y≈+9.8 |
| `gyro.x/y/z` | rad/s | 三轴角速度。静止时接近 0 |

---

## 13. 红外双目 (Infrared Stereo)

D455 有两个红外摄像头（infra1 左目, infra2 右目），基线 95mm。

### 13.1 启用红外流

```python
config.enable_stream(rs.stream.infrared, 1, 640, 480, rs.format.y8, 30)  # 左目
config.enable_stream(rs.stream.infrared, 2, 640, 480, rs.format.y8, 30)  # 右目
```

### 13.2 读取红外帧

```python
frames = pipeline.wait_for_frames()

left_frame  = frames.get_infrared_frame(1)  # 左目 (infra1)
right_frame = frames.get_infrared_frame(2)  # 右目 (infra2)

left_img  = np.asanyarray(left_frame.get_data())   # (480, 640) uint8
right_img = np.asanyarray(right_frame.get_data())  # (480, 640) uint8
```

### 13.3 cuVSLAM 需要的红外立体配置

cuVSLAM 用红外双目做立体视觉跟踪。需要：

- `infra1/image_raw` → 映射为 `stereo_camera/left/image_raw`
- `infra2/image_raw` → 映射为 `stereo_camera/right/image_raw`
- 红外投影仪**必须关闭**（见第 14 节）
- 发布 `camera_info` topic 包含红外内参和基线 (95mm)

---

## 14. 投影仪控制

D455 默认往场景投射红外散斑辅助深度计算。cuVSLAM 需要红外图像干净无散斑，所以必须关闭投影仪。

```python
device = profile.get_device()
sensor = device.first_depth_sensor()

# 关闭投影仪
sensor.set_option(rs.option.emitter_enabled, 0)

# 开启投影仪
sensor.set_option(rs.option.emitter_enabled, 1)
```

**注意**：深度图在投影仪关闭时质量会下降，但 cuVSLAM 不用深度图。

---

## 15. D455 在你们项目里的配置

```yaml
# configs/camera/d455.yaml
color:     640×480, BGR8, 30fps
depth:     640×480, Z16,  30fps
infrared:  640×480, Y8,   30fps   # 红外双目 (cuVSLAM)
imu:
  accel: 200 Hz                   # BMI055 加速度计
  gyro:  200 Hz                   # BMI055 陀螺仪
  baseline: 95 mm                 # 红外立体基线
projector: off                     # cuVSLAM 模式设为 off
```

当前项目中的实际用法参考：
- `scripts/realsense_smoke_test.py` — 最干净的示例
- `scripts/realsense_gauge_live.py` — 非 ROS 的实时仪表识别
- `scripts/gauge_status_node.py` — ROS2 节点的 D455 采集
- `src/cv/realsense_camera/` — **封装后的相机 API**（含 cuVSLAM 预设）

---

## 16. 官方资源

- **GitHub**: https://github.com/IntelRealSense/librealsense
- **Python 示例**: https://github.com/IntelRealSense/librealsense/tree/master/wrappers/python/examples
- **ROS 封装**: https://github.com/IntelRealSense/realsense-ros
- **D400 预设**: https://github.com/IntelRealSense/librealsense/wiki/D400-Series-Visual-Presets
- **API 文档**: https://dev.intelrealsense.com/docs/python2
