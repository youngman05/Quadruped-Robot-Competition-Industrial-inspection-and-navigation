# 三合一实例分割模型

同时识别 **red / green / obstacle** 三类物体。

## 模型

| 项目 | 值 |
|------|-----|
| 模型 | `model/best.pt` |
| 架构 | YOLOv8n-seg (Nano, 3.2M 参数) |
| 类别 | 0: red, 1: green, 2: obstacle |
| 训练集 | 163 张 (train) |
| Mask mAP50 | **0.964** |
| 来源数据 | red_green (97) + obstacle (41) + comp_dataset (25) |

## 运行

```bash
# 项目根目录下：
python InstanceSegmentation/scripts/camera_detect.py \
    --d455 \
    --model InstanceSegmentation/projects/combined/model/best.pt
```

按 `Q` 退出。

## 仅 CPU

```bash
python InstanceSegmentation/scripts/camera_detect.py \
    --model InstanceSegmentation/projects/combined/model/best.pt \
    --device cpu
```

## 导出 TensorRT（Jetson 部署）

```bash
python -c "from ultralytics import YOLO; \
    YOLO('InstanceSegmentation/projects/combined/model/best.pt').export(format='engine')"
```
