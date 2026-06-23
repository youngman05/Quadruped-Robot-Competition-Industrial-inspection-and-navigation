# YOLOv8 实例分割工作空间

基于 [Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics) 的**实例分割**工作空间。

实例分割 = 目标检测 (bounding box) + 像素级 mask，可以精确分割出每个物体的轮廓。

---

## 环境要求

- Python >= 3.8
- NVIDIA GPU + CUDA（可选，CPU 也可运行）
- D455 相机需要 `pyrealsense2`，并执行 `python setup.py develop`（项目根目录）

## 安装

```bash
pip install -r requirements.txt
```

---

## 完整工作流

```
标注数据                    训练                      部署
───────                    ────                      ────
labelme 多边形标注          yolov8n-seg.pt            camera_detect.py --d455
       ↓                         ↓                         ↓
   JSON 文件               100 epoch 训练              实时 mask 叠加
       ↓                         ↓                         ↓
labelme2yolo.py             best.pt                   按 Q 退出
       ↓
YOLO seg .txt 格式
```

### 1. 标注数据

使用 [labelme](https://github.com/wkentaro/labelme) 画多边形标注实例 mask：

```bash
labelme
```

- 图片放在 `datasets/images/<split>/` 下
- 标注后 JSON 和图片放同一目录
- 每个物体画一个多边形 shape

### 2. 转换格式

```bash
python scripts/labelme2yolo.py --src datasets/images/train --split train --classes "red,green"
python scripts/labelme2yolo.py --src datasets/images/val   --split val   --classes "red,green"
```

把 labelme 的 `.json` 转成 YOLO 分割用的 `.txt`，自动写入 `datasets/labels/<split>/`。

### 3. 配置数据集

编辑 `configs/dataset.yaml`：

```yaml
path: C:/Users/tom/Desktop/quadruped-robot-competition-main/InstanceSegmentation/datasets
train: images/train
val: images/val

nc: 2
names:
  0: red
  1: green
```

### 4. 训练

```bash
# 基础训练
python scripts/train.py --data configs/dataset.yaml

# 自定义参数
python scripts/train.py \
    --data configs/dataset.yaml \
    --model yolov8n-seg.pt \
    --epochs 100 \
    --batch 4 \
    --imgsz 640
```

### 5. 实时实例分割

```bash
# D455 相机 + 训练好的模型
python scripts/camera_detect.py --d455 --model runs/segment/train-4/weights/best.pt

# 普通摄像头
python scripts/camera_detect.py --model runs/segment/train-4/weights/best.pt

# CPU 模式
python scripts/camera_detect.py --model yolov8n-seg.pt --device cpu
```

按 `Q` 退出。

---

## 当前训练模型

| 项目 | 值 |
|------|-----|
| 训练数据 | 97 张 train, 7 张 val |
| 类别 | red, green |
| 模型 | `yolov8n-seg.pt` (Nano) |
| Epochs | 100 |
| **Mask mAP50** | **0.975** |
| **Box mAP50** | **0.959** |
| GPU | RTX 4070 Laptop (8GB) |
| 模型路径 | `runs/segment/train-4/weights/best.pt` |

---

## 目录结构

```
InstanceSegmentation/
├── datasets/                 # 数据集
│   ├── images/
│   │   ├── train/            # 训练图片 + labelme JSON
│   │   ├── val/              # 验证图片 + labelme JSON
│   │   └── test/             # 测试图片
│   └── labels/
│       ├── train/            # YOLO 分割 .txt 标签
│       ├── val/
│       └── test/
├── configs/
│   └── dataset.yaml          # 数据集配置
├── scripts/
│   ├── camera_detect.py      # 实时摄像头实例分割（支持 D455）
│   ├── image_detect.py       # 图片实例分割
│   ├── video_detect.py       # 视频实例分割
│   ├── train.py              # 模型训练
│   └── labelme2yolo.py       # labelme JSON → YOLO 分割格式
├── notebooks/
│   └── quickstart.ipynb      # Jupyter 快速入门
├── runs/                     # 训练输出（模型权重 + 指标图表）
├── outputs/                  # 推理输出
├── requirements.txt
└── README.md
```

---

## 推理命令速查

```bash
# D455 实时 + 训练模型
python scripts/camera_detect.py --d455 --model runs/segment/train-4/weights/best.pt

# 单张图片
python scripts/image_detect.py --model runs/segment/train-4/weights/best.pt --source bus.jpg

# 视频文件
python scripts/video_detect.py --model runs/segment/train-4/weights/best.pt --source test.mp4 --show

# 提高置信度过滤
python scripts/camera_detect.py --d455 --model runs/segment/train-4/weights/best.pt --conf 0.7
```

---

## 模型导出

```bash
# ONNX
python -c "from ultralytics import YOLO; YOLO('runs/segment/train-4/weights/best.pt').export(format='onnx')"

# TensorRT（Jetson 部署）
python -c "from ultralytics import YOLO; YOLO('runs/segment/train-4/weights/best.pt').export(format='engine')"
```

## 参考

- [Ultralytics 文档](https://docs.ultralytics.com/zh/)
- [YOLOv8 实例分割](https://docs.ultralytics.com/tasks/segment/)
- [labelme 标注工具](https://github.com/wkentaro/labelme)
