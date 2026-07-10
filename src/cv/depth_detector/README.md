# YOLO Detector

This folder contains the runtime YOLOv8 instance-segmentation code used by the competition perception stack.

## Runtime Model

- Combined model: `projects/combined/model/best.pt`
- Classes: `red`, `green`, `obstacle`
- Training checkpoints, datasets, notebooks, and per-class debug projects are intentionally not kept here.

## Run

From the repository root:

```bash
python src/cv/depth_detector/scripts/camera_detect.py --d455 --model src/cv/depth_detector/projects/combined/model/best.pt
```

CPU fallback:

```bash
python src/cv/depth_detector/scripts/camera_detect.py --model src/cv/depth_detector/projects/combined/model/best.pt --device cpu
```

The helper scripts under `scripts/` are kept for future labeling or retraining, but new datasets should stay outside Git unless they are deliberately added.
