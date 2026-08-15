#!/usr/bin/env python3
"""Validate the locked Jetson inference runtime without opening the D455."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


EXPECTED_MODEL_SHA256 = (
    "3ed76de727a87be8d64cc3b259bf2b0ec39daaaa3fac1f3f97af249824abc648"
)
EXPECTED_CLASSES = {"A", "B", "C", "D", "green", "red"}
EXPECTED_TORCH_VERSION = "2.0.0+nv23.5"
EXPECTED_TORCHVISION_VERSION = "0.15.1"
EXPECTED_ULTRALYTICS_VERSION = "8.2.103"
MODEL_PATH = Path("/opt/quadruped/perception/models/gauge_ad_best.pt")


def _check_pip_dependencies() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return
    unexpected = []
    for line in result.stdout.splitlines():
        allowed_opencv_gap = (
            line.startswith("ultralytics ")
            and " requires opencv-python" in line
            and line.endswith("which is not installed.")
        )
        if line and not allowed_opencv_gap:
            unexpected.append(line)
    if unexpected or not result.stdout.strip():
        details = "\n".join(unexpected) or "pip check failed without output"
        raise RuntimeError(f"pip dependency check failed:\n{details}")


def main() -> None:
    import cv2
    import torch
    import torchvision
    import ultralytics

    _check_pip_dependencies()
    if str(torch.__version__) != EXPECTED_TORCH_VERSION:
        raise RuntimeError(f"unexpected torch version: {torch.__version__}")
    if str(torchvision.__version__) != EXPECTED_TORCHVISION_VERSION:
        raise RuntimeError(f"unexpected torchvision version: {torchvision.__version__}")
    if str(ultralytics.__version__) != EXPECTED_ULTRALYTICS_VERSION:
        raise RuntimeError(f"unexpected ultralytics version: {ultralytics.__version__}")
    if not hasattr(cv2, "aruco"):
        raise RuntimeError("OpenCV aruco module is unavailable")

    actual_hash = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
    if actual_hash != EXPECTED_MODEL_SHA256:
        raise RuntimeError(f"model SHA-256 mismatch: {actual_hash}")

    from d455_yolo_3d_pipeline import (
        Yolo3DConfig,
        Yolo3DPipeline,
        install_torchvision_nms_fallback,
    )
    from d455_yolo_3d_node import (
        CLASS_SCHEMA as PRODUCER_CLASS_SCHEMA,
        MODEL_CLASS_NAMES as PRODUCER_CLASS_NAMES,
        MODEL_ID as PRODUCER_MODEL_ID,
    )
    from yolo_udp_bridge_core import CLASS_SCHEMA, MODEL_ID, validate_source_packet

    if PRODUCER_MODEL_ID != MODEL_ID or PRODUCER_CLASS_SCHEMA != CLASS_SCHEMA:
        raise RuntimeError("YOLO producer and Host validator protocol identities differ")
    if set(PRODUCER_CLASS_NAMES) != EXPECTED_CLASSES:
        raise RuntimeError("YOLO producer class set differs from the accepted model")

    device = os.environ.get("YOLO_DEVICE", "0")
    if device != "cpu" and not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable for the required Jetson warmup")
    install_torchvision_nms_fallback()
    tensor_device = torch.device("cpu" if device == "cpu" else "cuda:0")
    boxes = torch.tensor(
        [[0.0, 0.0, 10.0, 10.0], [1.0, 1.0, 9.0, 9.0], [20.0, 20.0, 30.0, 30.0]],
        device=tensor_device,
    )
    scores = torch.tensor([0.9, 0.8, 0.7], device=tensor_device)
    keep = torchvision.ops.nms(boxes, scores, 0.5)
    if keep.device != boxes.device or keep.tolist() != [0, 2]:
        raise RuntimeError(f"NMS fallback failed: device={keep.device} keep={keep.tolist()}")
    pipeline = Yolo3DPipeline(str(MODEL_PATH), Yolo3DConfig(device=device))
    pipeline.warmup((360, 640, 3))
    class_names = set(pipeline.class_names.values())
    if class_names != EXPECTED_CLASSES:
        raise RuntimeError(f"unexpected model classes: {sorted(class_names)}")

    synthetic_packet = {
        "schema_version": 1,
        "model_id": PRODUCER_MODEL_ID,
        "class_schema": PRODUCER_CLASS_SCHEMA,
        "sequence": 1,
        "stamp": {"sec": 1, "nanosec": 0},
        "frame_id": "camera_link",
        "inference_ms": 1.25,
        "detections": [
            {
                "class_id": 0,
                "class_name": "A",
                "confidence": 0.9,
                "bbox": [10, 20, 30, 40],
                "center_px": [20, 30],
                "mask_area_px": 200,
                "depth_m": 1.25,
                "depth_valid_ratio": 0.95,
                "position_valid": True,
                "position_m": [0.1, 0.2, 1.25],
            }
        ],
    }
    validate_source_packet(json.loads(json.dumps(synthetic_packet)))
    print(
        "pick-place runtime verified: "
        f"torch={torch.__version__} torchvision={torchvision.__version__} "
        f"ultralytics={ultralytics.__version__} classes={sorted(class_names)} "
        "pip=ok nms=ok warmup=ok synthetic_udp=ok"
    )


if __name__ == "__main__":
    main()
