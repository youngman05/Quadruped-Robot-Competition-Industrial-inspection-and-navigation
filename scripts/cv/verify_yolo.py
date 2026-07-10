#!/usr/bin/env python3
"""Quick verification of YOLO + torch installation on Jetson."""

from pathlib import Path

import ultralytics
import torch

print("ultralytics:", ultralytics.__version__)
print("torch:", torch.__version__)
print("CUDA available:", torch.cuda.is_available())

from ultralytics import YOLO

# 使用项目相对路径，避免硬编码用户目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = PROJECT_ROOT / "src/cv/yolo_detector/projects/combined/model/best.pt"

if not MODEL_PATH.exists():
    print(f"[WARN] 模型文件不存在: {MODEL_PATH}")
    print("请确认模型已放置到正确位置，或修改 MODEL_PATH")
    exit(1)

m = YOLO(str(MODEL_PATH))
print(f"Model loaded OK: {MODEL_PATH}")
print("Classes:", m.names)

# Quick test inference
import numpy as np

dummy = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
results = m(dummy, verbose=False)
print("Inference OK")
print(f"  Speed: {results[0].speed}")
print("Installation verified!")
