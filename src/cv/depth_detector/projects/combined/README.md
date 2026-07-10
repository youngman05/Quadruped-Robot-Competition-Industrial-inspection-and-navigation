# Combined YOLOv8 Segmentation Model

This project keeps the runtime model for the competition detector.

| Item | Value |
| --- | --- |
| Model | `model/best.pt` |
| Architecture | YOLOv8n-seg |
| Classes | `0: red`, `1: green`, `2: obstacle` |

Run from the repository root:

```bash
python src/cv/depth_detector/scripts/camera_detect.py \
  --d455 \
  --model src/cv/depth_detector/projects/combined/model/best.pt
```

TensorRT export on Jetson:

```bash
python -c "from ultralytics import YOLO; YOLO('src/cv/depth_detector/projects/combined/model/best.pt').export(format='engine')"
```
