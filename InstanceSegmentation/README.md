# YOLOv8 实例分割工作空间

基于 [Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics) 的**实例分割**工作空间，支持模型训练、图片/视频推理和实时摄像头检测。

实例分割 = 目标检测 (bounding box) + 像素级 mask，可以精确分割出每个物体的轮廓。

## 环境要求

- Python >= 3.8
- NVIDIA GPU + CUDA（可选，CPU 也可运行）

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 验证 GPU（可选）

```bash
python -c "import torch; print('CUDA 可用' if torch.cuda.is_available() else 'CUDA 不可用，将使用 CPU')"
```

### 3. 实时摄像头实例分割

```bash
# 普通 USB 摄像头
python scripts/camera_detect.py --model yolov8n-seg.pt

# Intel RealSense D455 相机
python scripts/camera_detect.py --d455 --model yolov8n-seg.pt

# CPU 模式
python scripts/camera_detect.py --model yolov8n-seg.pt --device cpu
```

首次运行会自动下载 `yolov8n-seg.pt` 模型。按 `Q` 退出。

输出动画包含：
- 半透明彩色 mask（像素级分割区域）
- mask 轮廓线
- bounding box + 类别名 + 置信度
- 每个实例的 mask 面积 (px)
- 实时 FPS

### 4. 图片实例分割

```bash
# 单张图片
python scripts/image_detect.py --model yolov8n-seg.pt --source path/to/image.jpg

# 整个目录
python scripts/image_detect.py --model yolov8n-seg.pt --source path/to/dir/
```

输出 mask 面积和置信度。

### 5. 视频实例分割

```bash
python scripts/video_detect.py --model yolov8n-seg.pt --source path/to/video.mp4
```

### 6. 启动 Jupyter Notebook

```bash
jupyter notebook notebooks/quickstart.ipynb
```

## 目录结构

```
识别/
├── datasets/              # 标注数据存放
│   ├── images/            # 图片 (train/val/test 子目录)
│   └── labels/            # YOLO 格式标签 (train/val/test 子目录)
├── models/                # 训练好的模型权重 (.pt 文件)
├── outputs/               # 推理输出结果
├── configs/               # 配置文件
│   └── dataset.yaml       # 数据集配置模板
├── scripts/               # 脚本
│   ├── camera_detect.py   # 实时摄像头实例分割（支持 D455）
│   ├── image_detect.py    # 图片实例分割
│   ├── video_detect.py    # 视频实例分割
│   └── train.py           # 模型训练
├── notebooks/             # Jupyter Notebooks
│   └── quickstart.ipynb   # 快速入门
├── requirements.txt       # Python 依赖
└── README.md              # 本文件
```

## 训练自定义模型

### 1. 准备数据集

使用 [LabelImg](https://github.com/HumanSignal/labelImg) 标注数据：

```bash
labelImg
```

标注完成后，将图片和标签分别放入 `datasets/images/` 和 `datasets/labels/` 下对应的 `train`/`val` 目录。

### 2. 修改配置文件

编辑 `configs/dataset.yaml`，设置正确的类别数和类别名称。

### 3. 开始训练

```bash
# 基本训练
python scripts/train.py --data configs/dataset.yaml

# 自定义参数
python scripts/train.py \
    --data configs/dataset.yaml \
    --model yolov8s.pt \
    --epochs 200 \
    --batch 16 \
    --imgsz 640
```

可选预训练模型（检测版 vs 分割版）：

| 检测模型 | 分割模型 | 尺寸 | 速度 | 说明 |
|----------|----------|------|------|------|
| `yolov8n.pt` | `yolov8n-seg.pt` | Nano | 最快 | 实时首选 |
| `yolov8s.pt` | `yolov8s-seg.pt` | Small | 快 | |
| `yolov8m.pt` | `yolov8m-seg.pt` | Medium | 中 | |
| `yolov8l.pt` | `yolov8l-seg.pt` | Large | 慢 | |
| `yolov8x.pt` | `yolov8x-seg.pt` | XLarge | 最慢 | 最高精度 |

> 分割模型（`-seg.pt`）输出像素级 mask，检测模型只有 bounding box。

## 常用命令速查

```bash
# D455 实时实例分割（自定义训练模型）
python scripts/camera_detect.py --d455 --model models/best.pt --conf 0.6

# 普通摄像头实时分割
python scripts/camera_detect.py --model yolov8n-seg.pt --conf 0.6

# 批量图片推理
python scripts/image_detect.py --model models/best.pt --source datasets/images/test/

# 视频推理并显示
python scripts/video_detect.py --model models/best.pt --source test.mp4 --show

# CPU 推理（无 GPU 时）
python scripts/image_detect.py --model yolov8n-seg.pt --source img.jpg --device cpu

# 标注工具
labelImg
```

## 模型导出

```bash
# ONNX
python -c "from ultralytics import YOLO; YOLO('models/best.pt').export(format='onnx')"

# TensorRT (NVIDIA 加速)
python -c "from ultralytics import YOLO; YOLO('models/best.pt').export(format='engine')"
```

## 参考资源

- [Ultralytics 中文文档](https://docs.ultralytics.com/zh/)
- [YOLO 官方 GitHub](https://github.com/ultralytics/ultralytics)
- [LabelImg 标注工具](https://github.com/HumanSignal/labelImg)
