#!/usr/bin/env python3
"""
Runs inside Docker: subscribes to /camera/color/image_raw, runs YOLO
detection on GPU, writes results as JSON to shared directory.

Output: /workspaces/isaac_ros-dev/camera_frames/latest_detection.json

JSON format:
{
  "ts": "20260710_143025.123",
  "letters": [{"label": "C", "conf": 0.95, "bbox": [x1,y1,x2,y2]}, ...],
  "gauges":  [{"color": "green", "conf": 0.88, "bbox": [x1,y1,x2,y2]}, ...]
}
"""

import json
import os
import time
from pathlib import Path

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from sensor_msgs.msg import Image

# ── Shared output ──
OUT_DIR = Path(os.environ.get("CAMERA_FRAMES_DIR", "/workspaces/isaac_ros-dev/camera_frames"))
OUT_DIR.mkdir(parents=True, exist_ok=True)
DETECTION_JSON = OUT_DIR / "latest_detection.json"
DETECTION_TMP = OUT_DIR / "latest_detection_tmp.json"

# ── YOLO model path (mounted from host) ──
MODEL_PATH = Path(os.environ.get(
    "YOLO_MODEL_PATH",
    "/workspaces/isaac_ros-dev/camera_frames/gauge_best.pt",
))

# ── torchvision NMS fix for Jetson ──
import torch
import torchvision

def _py_nms(boxes, scores, iou_threshold):
    if boxes.numel() == 0:
        return torch.empty((0,), dtype=torch.int64, device=boxes.device)
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    _, order = scores.sort(descending=True)
    keep = []
    while order.numel() > 0:
        i = order[0].item(); keep.append(i)
        if order.numel() == 1: break
        xx1 = torch.max(x1[i], x1[order[1:]]); yy1 = torch.max(y1[i], y1[order[1:]])
        xx2 = torch.min(x2[i], x2[order[1:]]); yy2 = torch.min(y2[i], y2[order[1:]])
        w = (xx2 - xx1).clamp(min=0); h = (yy2 - yy1).clamp(min=0)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter)
        order = order[(iou <= iou_threshold).nonzero(as_tuple=False).squeeze(1) + 1]
    return torch.tensor(keep, dtype=torch.int64, device=boxes.device)

torchvision.ops.nms = _py_nms

from ultralytics import YOLO

# ── Global state ──
bridge = CvBridge()
model: YOLO = None
class_names: list = []
frame_count = 0
skip_frames = int(os.environ.get("YOLO_SKIP_FRAMES", "2"))  # run every Nth frame


def load_model():
    global model, class_names
    print(f"[yolo_relay] Loading model: {MODEL_PATH}", flush=True)
    model = YOLO(str(MODEL_PATH))
    class_names = list(model.names.values())
    # Warmup
    dummy = np.zeros((320, 320, 3), dtype=np.uint8)
    model(dummy, verbose=False, imgsz=320)
    print(f"[yolo_relay] Model ready. Classes: {class_names}", flush=True)


def callback(msg: Image):
    global frame_count
    frame_count += 1
    if model is None:
        return

    # Skip frames to stay real-time
    if frame_count % (skip_frames + 1) != 0:
        return

    try:
        t0 = time.time()
        cv_image = bridge.imgmsg_to_cv2(msg, "bgr8")
        results = model(cv_image, verbose=False, imgsz=320, conf=0.3, iou=0.5)[0]

        letters = []
        gauges = []
        gauge_colors = {"green", "red", "yellow"}

        for box in results.boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            name = class_names[cls_id]
            x1, y1, x2, y2 = map(int, box.xyxy[0])

            item = {"conf": round(conf, 4), "bbox": [x1, y1, x2, y2]}
            if name in gauge_colors:
                item["color"] = name
                gauges.append(item)
            else:
                item["label"] = name
                letters.append(item)

        ms = (time.time() - t0) * 1000

        # Atomic write via tmp + rename
        ts = time.strftime("%Y%m%d_%H%M%S")
        data = {
            "ts": ts,
            "inference_ms": round(ms, 1),
            "letters": letters,
            "gauges": gauges,
        }
        with open(DETECTION_TMP, "w") as f:
            json.dump(data, f)
        os.replace(DETECTION_TMP, DETECTION_JSON)

        if frame_count % 30 == 1:
            print(f"[yolo_relay] frame={frame_count} {ms:.0f}ms "
                  f"letters={len(letters)} gauges={len(gauges)}", flush=True)

    except Exception as exc:
        print(f"[yolo_relay] ERROR: {exc}", flush=True)


def main():
    load_model()

    rclpy.init()
    node = rclpy.create_node("yolo_relay")
    node.create_subscription(Image, "/camera/color/image_raw", callback, 10)
    node.get_logger().info(f"[yolo_relay] Subscribed /camera/color/image_raw -> {DETECTION_JSON}")

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
