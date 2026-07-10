#!/usr/bin/env python3
"""D455 live instance segmentation using the single combined YOLO model."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

MODEL_PATH = ROOT / "src/cv/depth_detector/projects/combined/model/best.pt"
CLASS_COLORS = {
    0: (0, 0, 255),
    1: (0, 255, 0),
    2: (0, 165, 255),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run combined YOLOv8-seg on D455.")
    parser.add_argument("--model", default=str(MODEL_PATH), help="YOLO model path.")
    parser.add_argument("--conf", type=float, default=0.5, help="Confidence threshold.")
    parser.add_argument("--imgsz", type=int, default=640, help="Inference image size.")
    parser.add_argument("--device", default="0", help="Inference device, e.g. 0 or cpu.")
    return parser.parse_args()


def draw_results(frame: np.ndarray, results, alpha: float = 0.4) -> np.ndarray:
    annotated = frame.copy()
    result = results[0]
    if result.masks is None or result.boxes is None:
        return annotated

    masks = result.masks.data.cpu().numpy().astype(bool)
    boxes = result.boxes
    overlay = annotated.copy()

    for i, mask in enumerate(masks):
        cls_id = int(boxes.cls[i])
        color = CLASS_COLORS.get(cls_id, (255, 255, 255))
        overlay[mask] = color
        contours, _ = cv2.findContours(
            mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        cv2.drawContours(annotated, contours, -1, color, 2)

    cv2.addWeighted(overlay, alpha, annotated, 1 - alpha, 0, annotated)

    for i, mask in enumerate(masks):
        cls_id = int(boxes.cls[i])
        conf = float(boxes.conf[i])
        label = result.names.get(cls_id, f"cls{cls_id}")
        color = CLASS_COLORS.get(cls_id, (255, 255, 255))
        x1, y1, x2, y2 = map(int, boxes.xyxy[i].cpu().numpy())
        area_px = int(mask.sum())
        text = f"{label} {conf:.2f} area={area_px}"
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
        cv2.rectangle(annotated, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
        cv2.putText(
            annotated,
            text,
            (x1 + 2, y1 - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            2,
        )

    return annotated


def main() -> None:
    args = parse_args()

    from cv.realsense_camera import RealsenseCamera

    model = YOLO(args.model)
    cam = RealsenseCamera(width=640, height=480, enable_depth=False)
    cam.start()
    print(f"Camera: {cam.device_name} ({cam.serial})")
    print(f"Model: {args.model}")
    print("Press Q to quit.")

    prev_time = time.perf_counter()
    fps = 0.0

    try:
        while True:
            frame = cam.get_color_image()
            if frame is None:
                continue

            t0 = time.perf_counter()
            results = model(frame, conf=args.conf, imgsz=args.imgsz, device=args.device, verbose=False)
            infer_ms = max((time.perf_counter() - t0) * 1000.0, 1e-6)
            fps = 0.9 * fps + 0.1 * (1000.0 / infer_ms)

            annotated = draw_results(frame, results)
            elapsed = time.perf_counter() - prev_time
            if elapsed > 0.2:
                prev_time = time.perf_counter()
            cv2.putText(
                annotated,
                f"FPS: {fps:.1f}",
                (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
            )
            cv2.imshow("YOLO combined D455 [Q quit]", annotated)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cam.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
