# RealSense Camera

Intel RealSense D455 RGB-D 相机封装模块。

支持：RGB、深度、红外立体视觉、BMI055 IMU (Accel + Gyro)。

---

## 三个工厂预设

```python
from cv.realsense_camera import RealsenseCamera

# cuVSLAM：红外双目 + IMU，投影仪关闭
cam = RealsenseCamera.for_cuvslam(accel_rate=200, gyro_rate=200)

# 仪表检测：彩色图即可
cam = RealsenseCamera.for_gauge()

# 全能模式：所有传感器全开
cam = RealsenseCamera(color=True, depth=True, infrared=True, imu=True)
```

---

## cuVSLAM 用法

```python
from cv.realsense_camera import RealsenseCamera

with RealsenseCamera.for_cuvslam() as cam:
    print(f"cuVSLAM ready: {cam.device_name}, projector={cam.projector_on}")
    print(f"IR intrinsics: {cam.cuvslam_intrinsics()}")

    while True:
        # 1. 红外立体图像 → cuVSLAM 视觉跟踪
        left_ir, right_ir = cam.get_infrared_frames()
        # left_ir:  (480, 640) uint8 灰度
        # right_ir: (480, 640) uint8 灰度

        # 2. IMU 数据 → cuVSLAM 惯性融合
        imu = cam.get_imu_data()
        # imu.accel → (x, y, z) m/s²
        # imu.gyro  → (x, y, z) rad/s

        # 3. 喂给 cuVSLAM：
        # - 发布 left/image_raw, right/image_raw, camera_info topics
        # - 发布 imu topic
        # - ros2 launch isaac_ros_visual_slam isaac_ros_visual_slam_realsense.launch.py
```

### 批量读取 IMU

```python
# 读 200 个采样 (1 秒 @ 200Hz)
samples = cam.get_imu_samples(200)
accel_z = [s.accel_z for s in samples]

# 按时间读取
batch = cam.get_imu_batch(duration_sec=1.0)
```

---

## 仪表检测用法

```python
from cv.realsense_camera import RealsenseCamera

with RealsenseCamera.for_gauge() as cam:
    color = cam.get_color_image()
    # 送进 gauge_detector...
```

---

## 手动控制各传感器

```python
cam = RealsenseCamera(
    enable_color=True,       # RGB 彩色图
    enable_depth=True,       # 深度图
    enable_infrared=True,    # 红外双目 (infra1 + infra2)
    enable_imu=True,         # BMI055 Accel + Gyro
    imu_accel_rate=200,      # 加速度计频率: 100/200/400 Hz
    imu_gyro_rate=400,       # 陀螺仪频率: 200/400 Hz
    align_depth=True,        # 深度对齐到彩色
    projector_on=True,       # 红外投影仪开关
)
```

---

## 投影仪控制

cuVSLAM 要求红外投影仪关闭，否则散斑图案会干扰立体匹配。

```python
cam.projector_on = False     # 关投影仪 (cuVSLAM 模式)
cam.projector_on = True      # 开投影仪 (深度模式)
cam.set_projector(False)     # 等价方法
```

---

## 完整 API 表

### 构造函数参数

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `width` | int | 640 | 图像宽度 |
| `height` | int | 480 | 图像高度 |
| `fps` | int | 30 | 帧率 |
| `enable_color` | bool | True | 启用 RGB 彩色流 |
| `enable_depth` | bool | True | 启用深度流 |
| `enable_infrared` | bool | False | 启用红外双目 (infra1/2) |
| `enable_imu` | bool | False | 启用 BMI055 IMU |
| `imu_accel_rate` | int | 200 | 加速度计频率 (100/200/400 Hz) |
| `imu_gyro_rate` | int | 200 | 陀螺仪频率 (200/400 Hz) |
| `align_depth` | bool | True | 深度对齐到彩色 |
| `projector_on` | bool | True | 红外投影仪开关 |

### 方法

| 方法 | 返回 | 说明 |
|------|------|------|
| `for_cuvslam()` | RealsenseCamera | 工厂方法：cuVSLAM 配置 |
| `for_gauge()` | RealsenseCamera | 工厂方法：仪表检测配置 |
| `start(warmup_frames=30)` | None | 启动相机 |
| `stop()` | None | 停止相机 |
| `get_frames()` | `(ndarray, ndarray\|None)` | 彩色 + 深度图 |
| `get_color_image()` | `ndarray` | 仅彩色图 |
| `get_depth_image()` | `ndarray\|None` | 仅深度图 |
| `get_infrared_frames()` | `(ndarray, ndarray)` | 红外左目 + 右目 |
| `get_imu_data()` | `IMUSample` | 单次 IMU 采样 |
| `get_imu_samples(count)` | `list[IMUSample]` | 批量 IMU 采样 |
| `get_imu_batch(duration_sec)` | `list[IMUSample]` | 按时间采样 |
| `get_distance(x, y)` | `float` | 像素深度 (米) |
| `deproject(x, y)` | `(float,float,float)` | 2D → 3D |
| `deproject_points(pixels)` | `ndarray` | 批量 2D → 3D |
| `set_projector(on)` | None | 开关红外投影仪 |
| `cuvslam_intrinsics()` | `dict` | cuVSLAM 所需红外内参 + 基线 |
| `intrinsics_dict()` | `dict` | 彩色内参字典 |

### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `device_name` | str | 设备名称 |
| `serial` | str | 序列号 |
| `width` / `height` | int | 分辨率 |
| `is_running` | bool | 是否已启动 |
| `has_imu` | bool | IMU 是否启用 |
| `has_infrared` | bool | 红外是否启用 |
| `projector_on` | bool | 投影仪状态 (可读写) |
| `color_intrinsics` | rs.intrinsics | 彩色内参 |
| `depth_intrinsics` | rs.intrinsics | 深度内参 |
| `infrared_intrinsics` | rs.intrinsics | 红外左目内参 |

### `IMUSample`

| 字段 | 类型 | 说明 |
|------|------|------|
| `accel_x/y/z` | float | 加速度 m/s² |
| `gyro_x/y/z` | float | 角速度 rad/s |
| `timestamp_ms` | float | 时间戳 ms |
| `accel` | tuple | `(x, y, z)` 快捷属性 |
| `gyro` | tuple | `(x, y, z)` 快捷属性 |

---

## 注意事项

- 深度有效距离 ~0.3m ~ 7m。0 = 无效像素。
- `get_distance(x, y)` 中 x=列, y=行（OpenCV 约定）。
- cuVSLAM 模式下投影仪必须关闭，否则红外散斑干扰立体匹配。
- D455 IMU 支持 Accel 100/200/400 Hz，Gyro 200/400 Hz。
- 红外内参和彩色内参不同，cuVSLAM 用 `cuvslam_intrinsics()` 获取红外参数。
- Jetson Xavier NX 上用 `pyrealsense2==2.55.1.6486`。
- 多流全开时注意 USB 3.x 带宽限制。
