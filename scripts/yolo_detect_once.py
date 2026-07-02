#!/usr/bin/env python3
"""
One-shot YOLO cone detection — capture 1 frame, find obstacles, return positions.

Usage: python3 scripts/yolo_detect_once.py [--relay-dir PATH]
Output: JSON with list of cones: [{distance_m, angle_deg, center_px}, ...]
"""
import sys, json, time, math, argparse
from pathlib import Path

import cv2
import numpy as np
import torch
import torchvision.ops

# NMS patch (must be BEFORE ultralytics import)
def _pure_nms(boxes, scores, iou_thres):
    if len(boxes) == 0:
        return torch.zeros(0, dtype=torch.int64)
    boxes_np = boxes.cpu().numpy(); scores_np = scores.cpu().numpy()
    x1, y1 = boxes_np[:, 0], boxes_np[:, 1]
    x2, y2 = boxes_np[:, 2], boxes_np[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores_np.argsort()[::-1]; keep = []
    while order.size > 0:
        i = order[0]; keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1); h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[np.where(iou <= iou_thres)[0] + 1]
    return torch.tensor(keep, dtype=torch.int64)

torchvision.ops.nms = _pure_nms

from ultralytics import YOLO

# D455 RGB intrinsics (640x480)
FX, FY = 617.0, 617.0
CX, CY = 320.0, 240.0


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--relay-dir', default=str(Path.home() / 'workspaces/isaac_ros-dev/camera_frames'))
    p.add_argument('--model', default='src/cv/yolo_detector/projects/combined/model/best.pt')
    p.add_argument('--conf', type=float, default=0.5)
    args = p.parse_args()

    jpg = Path(args.relay_dir) / 'latest_color.jpg'
    if not jpg.exists():
        print(json.dumps({"error": "no relay JPEG"}))
        sys.exit(1)

    # Wait for a fresh frame
    color = None
    for _ in range(20):
        color = cv2.imread(str(jpg), cv2.IMREAD_COLOR)
        if color is not None and color.shape[0] > 0:
            break
        time.sleep(0.1)

    if color is None:
        print(json.dumps({"error": "imread failed"}))
        sys.exit(1)

    # Resize to 640 width for model
    h, w = color.shape[:2]
    if w != 640:
        color = cv2.resize(color, (640, int(h * 640 / w)))

    # Load model + detect
    model = YOLO(args.model)
    results = model(color, conf=args.conf, imgsz=640, device='0', verbose=False)
    r = results[0]

    # Read depth image for distance estimation
    depth_raw = Path(args.relay_dir) / 'latest_depth.raw'
    depth_meta = Path(args.relay_dir) / 'latest_depth_meta.txt'
    depth_img = None
    dw, dh = 640, 360
    if depth_raw.exists():
        if depth_meta.exists():
            parts = depth_meta.read_text().strip().split()
            if len(parts) >= 2:
                dw, dh = int(parts[0]), int(parts[1])
        raw_data = depth_raw.read_bytes()
        if len(raw_data) == dw * dh * 2:
            depth_img = np.frombuffer(raw_data, dtype=np.uint16).reshape(dh, dw)

    cones = []
    if r.boxes is not None:
        for i in range(len(r.boxes)):
            cls_id = int(r.boxes.cls[i])
            if cls_id != 2:  # obstacle only
                continue
            conf = float(r.boxes.conf[i])
            xyxy = r.boxes.xyxy[i].cpu().numpy()
            x1, y1, x2, y2 = map(int, xyxy)
            cx = (x1 + x2) / 2.0
            cy = (y1 + y2) / 2.0

            # Get distance from depth image (scale to color resolution)
            if depth_img is not None:
                dcx = int(cx * dw / w)
                dcy = int(cy * dh / h)
                if 0 <= dcy < dh and 0 <= dcx < dw:
                    d_mm = depth_img[dcy, dcx]
                    if d_mm > 0:
                        dist_m = d_mm / 1000.0
                    else:
                        dist_m = None
                else:
                    dist_m = None
            else:
                dist_m = None

            # Fallback: estimate from bbox width (cone ~670mm wide)
            if dist_m is None or dist_m <= 0:
                bbox_w_px = x2 - x1
                if bbox_w_px > 0:
                    dist_m = (670.0 / bbox_w_px) * (FX / 1000.0)
                else:
                    dist_m = None

            # Pixel offset → angle from camera center
            angle_x = math.degrees(math.atan2(cx - CX, FX))
            angle_y = math.degrees(math.atan2(cy - CY, FY))

            if dist_m is None or dist_m <= 0:
                print(json.dumps({"error": f"cone {i}: no distance available from depth or bbox"}))
                sys.exit(1)

            cones.append({
                "center_px": [int(cx), int(cy)],
                "angle_h_deg": round(angle_x, 1),
                "angle_v_deg": round(angle_y, 1),
                "distance_m": round(dist_m, 2),
                "confidence": round(conf, 3),
            })

    print(json.dumps({"cones": cones, "count": len(cones)}))


if __name__ == '__main__':
    main()
