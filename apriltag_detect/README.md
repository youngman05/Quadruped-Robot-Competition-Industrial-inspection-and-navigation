# AprilTag 36h11 识别脚本

一个零依赖第三方库（只依赖 OpenCV + NumPy）的 AprilTag 检测工具：识别 tag36h11 标记，输出每个 tag 的 ID、距离、位姿，并能在画面上实时标注边框、坐标轴和距离文字。

支持四种输入模式：

| 模式 | 命令 | 适用场景 |
|------|------|---------|
| 静态图 | `python apriltag_detect.py 图片.jpg` | 离线识别一张照片 |
| 自测 | `python apriltag_detect.py --selftest` | 合成 tag 图验证环境可用（无需相机） |
| 实时窗口 | `python apriltag_detect.py --live` | 直连 Intel RealSense 相机（D435i / D455 均可）实时标注 |
| 文件轮询 | `python apriltag_detect.py --relay <目录>` | 轮询目录下不断更新的 `latest_color.jpg` |

## 环境要求

## Production Pose Local Checker

`d455_apriltag_pose_local.py` reuses the production Docker detector, including
the `tag36h11` ID filter (`0,1,2,3`), CameraInfo distortion, 3 px reprojection
gate, and tag-axis conversion. Its default black-square size is 100 mm.

```bash
python d455_apriltag_pose_local.py --live
python d455_apriltag_pose_local.py image.jpg --fx 617 --fy 617 --cx 320 --cy 240 --dist-coeffs 0,0,0,0,0
```

For an offline image or relay, pass the D455 CameraInfo `K` and `D` values to
match the Docker result. The reported translation is in the color optical frame;
the script deliberately does not apply the robot TF transforms.

- Python **3.8 及以上**
- 无特殊硬件要求；`--live` 模式需要 Intel RealSense 相机（D435i / D455 等）

## 安装

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 验证环境可用（无需相机）
python apriltag_detect.py --selftest
```

看到类似输出即说明环境正常：

```
selftest: synthetic tag_id=7 on 800x600 canvas
found 1 tag(s):
  tag_id=7  dist=0.391m  err=0.14px  center=(399.5, 299.5)  tvec=[0.050, 0.037, 0.386]
```

## 快速开始

### 1. 没有相机？先测离线识别

```bash
# 用随包附带的示例 tag 图
python apriltag_detect.py example/tag7_example.jpg --save-out result.jpg

# 或者打印一张 tag 贴在墙上拍照测试
python apriltag_detect.py 你的照片.jpg
```

### 2. 有 RealSense 相机？实时标注

```bash
python apriltag_detect.py --live
```

- **Q** 退出，**S** 保存当前帧（标注图 + JSON 检测数据到 `./captures/apriltag/`）
- 窗口左上角状态行：`tags:1 fps:29.8`（检测到 tag 为绿色，否则为红色）
- 每帧检测结果打印在终端：`tag_id=1  dist=0.62m  err=0.42px ...`

### 3. 机器人竞赛场景（ROS 无相机权限时）

当相机被其他进程（如 SLAM）占用时，把相机画面落盘为 `latest_color.jpg`，然后：

```bash
python apriltag_detect.py --relay /path/to/camera_frames --interval 0.2
```

## 常用参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--tag-size` | `0.10` | tag 黑色方块边长（米），**按你打印的尺寸改** |
| `--expected-ids` | 全接受 | 只接受指定 ID，逗号分隔，如 `--expected-ids 0,1,2,3` |
| `--max-reproj-error` | `5.0` | 位姿重投影误差门限（像素），误检多可调小 |
| `--save-out` | 不保存 | 保存标注图路径 |
| `--fx --fy --cx --cy` | D455 内参 | 覆盖相机内参（`--live` 模式自动从相机读取，无需设置） |
| `--fps` / `--width` / `--height` | 30 / 640 / 480 | `--live` 模式视频流参数 |
| `--serial` | 自动 | `--live` 模式指定相机序列号（多相机时用） |
| `--capture-dir` | `./captures/apriltag` | S 键保存目录 |

## 输出说明

终端每帧输出：

```
tag_id=0  dist=0.371m  err=4.48px  center=(341.7, 291.5)  tvec=[0.013, 0.029, 0.370]
```

- `dist`：相机到 tag 中心的直线距离（米）
- `err`：重投影误差（像素），越小越可靠，超过 `--max-reproj-error` 的位姿会被丢弃
- `tvec`：tag 在相机坐标系下的平移向量 `[x, y, z]`（米，x 右 y 下 z 前）

S 键保存的 JSON 结构：

```json
{
  "detections": [
    {
      "tag_id": 0,
      "center_px": [341.7, 291.5],
      "translation_m": [0.013, 0.029, 0.370],
      "distance_m": 0.371,
      "rotation_matrix": [...],
      "reprojection_error_px": 4.48
    }
  ]
}
```

## 常见问题

**Q: 报 `OpenCV was installed without the aruco module`？**
安装的 OpenCV 版本低于 4.7 且不是 contrib 版本。`pip install -U opencv-python` 升级，或改装 `opencv-contrib-python`。

**Q: 检测不到 tag？**
1. 确认打印的 tag 是 **36h11 家族**（用 [此网站](https://chev.me/arlucodraw/) 生成时选 AprilTag 36h11）
2. 确认 `--tag-size` 与打印尺寸一致（量黑色方块边长，不含白边）
3. 距离过近（<0.2m）或过远（>3m）都会降低检出率；倾斜角过大也会失败

**Q: `--live` 报 `failed to start camera`？**
相机被其他程序占用（如 SLAM、RealSense Viewer）。关掉占用程序，或用 `--relay` 模式读取落盘画面。

**Q: D435i 和 D455 的区别？**
对 tag 识别无区别。`--live` 模式自动读取相机内参，无需手动设置。

## 检测算法说明

- 标记词典：`DICT_APRILTAG_36h11`（OpenCV aruco 内置）
- 位姿估计：`cv2.solvePnP`（SOLVEPNP_IPPE_SQUARE，4 角点平面解算），距离单位米
- 可靠性：重投影误差门限 + 位姿有限值/正深度校验，误检结果会被丢弃
- 兼容性：自动适配 OpenCV 4.7+（`ArucoDetector`）与旧版（`detectMarkers`）API
