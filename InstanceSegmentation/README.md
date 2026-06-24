# YOLOv8 实例分割工作空间

基于 [Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics) 的实例分割工作空间。
检测 = box + 像素级 mask。

---

## 项目

| 项目 | 路径 | 类别 | Mask mAP50 | 训练集 |
|------|------|------|:---:|:---:|
| 红绿色块 | `projects/red_green/` | red, green | 0.975 | 97 |
| 路障 | `projects/obstacle/` | obstacle | 0.995 | 41 |
| **三合一** | `projects/combined/` | red, green, obstacle | **0.964** | 163 |

每个项目包含独立的 `datasets/`、`configs/`、`model/`，脚本共用。

---

## 快速运行

```bash
# 三合一模型（推荐）
python scripts/camera_detect.py --d455 --model projects/combined/model/best.pt

# 双模型同时检测（两个模型各跑各的）
python scripts/camera_multi_detect.py

# 普通摄像头
python scripts/camera_detect.py --model projects/combined/model/best.pt
```

---

## 目录结构

```
InstanceSegmentation/
├── projects/
│   ├── red_green/
│   │   ├── model/best.pt        ← Mask mAP 0.975
│   │   ├── configs/dataset.yaml
│   │   └── datasets/            # images + labels (train/val/test)
│   ├── obstacle/
│   │   ├── model/best.pt        ← Mask mAP 0.995
│   │   ├── configs/dataset.yaml
│   │   └── datasets/
│   └── combined/
│       ├── model/best.pt        ← Mask mAP 0.964 (三合一)
│       ├── configs/dataset.yaml  (nc=3: red, green, obstacle)
│       └── datasets/
├── scripts/
│   ├── camera_detect.py         # 单模型实时检测（支持 D455）
│   ├── camera_multi_detect.py   # 双模型同时检测
│   ├── image_detect.py          # 图片推理
│   ├── video_detect.py          # 视频推理
│   ├── train.py                 # 模型训练
│   ├── labelme2yolo.py          # labelme JSON → YOLO seg
│   └── sam_click_label.py       # SAM 辅助标注（点一下 AI 画 mask）
├── notebooks/quickstart.ipynb
└── requirements.txt
```

---

## 完整工作流

### 1. 标注

**SAM 辅助标注**（推荐）：
```bash
python scripts/sam_click_label.py projects/obstacle/datasets/images/train obstacle
```
鼠标点击物体 → SAM 自动生成 mask → 回车确认 → S 保存为 labelme JSON → D 下一张。

**手动标注**：
```bash
labelme
```
画多边形标注，JSON 和图片放同一目录。

### 2. 转换格式

```bash
python scripts/labelme2yolo.py --src projects/<project>/datasets/images/train --split train --classes "class1,class2"
```

### 3. 训练

```bash
python scripts/train.py --data projects/<project>/configs/dataset.yaml --epochs 100 --batch 4
```

### 4. 实时检测

```bash
python scripts/camera_detect.py --d455 --model projects/<project>/model/best.pt
```

---

## 新增数据到已有项目

如果后续补标了新数据（如 `comp_dataset/`）：

```bash
# 1. 转格式
python scripts/labelme2yolo.py --src comp_dataset --split train --classes "red,green,obstacle"

# 2. 手动拷到 projects/combined/datasets/ 对应位置

# 3. 重新训练
python scripts/train.py --data projects/combined/configs/dataset.yaml --epochs 100 --batch 4
```

---

## 模型导出

```bash
# ONNX
python -c "from ultralytics import YOLO; YOLO('projects/combined/model/best.pt').export(format='onnx')"

# TensorRT（Jetson 部署）
python -c "from ultralytics import YOLO; YOLO('projects/combined/model/best.pt').export(format='engine')"
```

## 参考

- [Ultralytics 文档](https://docs.ultralytics.com/zh/)
- [YOLOv8 实例分割](https://docs.ultralytics.com/tasks/segment/)
- [labelme](https://github.com/wkentaro/labelme)
- [SAM](https://github.com/facebookresearch/segment-anything)
