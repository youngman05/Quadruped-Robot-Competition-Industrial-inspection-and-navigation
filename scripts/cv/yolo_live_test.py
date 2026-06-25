#!/usr/bin/env python3
"""
YOLO 实时检测可视化 — 使用 combined 模型，D455 相机。
按 Q 退出，按 S 截图保存。

用法:
    python3 scripts/yolo_live_test.py
    python3 scripts/yolo_live_test.py --conf 0.3  # 降低阈值看更多检测
    python3 scripts/yolo_live_test.py --cpu         # CPU 模式
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

# ── 修复 torchvision NMS 与 NVIDIA torch 的 ABI 不兼容 ──
import torch
import torchvision.ops

def _pure_nms(boxes, scores, iou_thres):
    """纯 NumPy NMS，替代 torchvision 的 C++ 版本。"""
    if len(boxes) == 0:
        return torch.zeros(0, dtype=torch.int64)
    boxes_np = boxes.cpu().numpy()
    scores_np = scores.cpu().numpy()
    x1, y1 = boxes_np[:, 0], boxes_np[:, 1]
    x2, y2 = boxes_np[:, 2], boxes_np[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores_np.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[np.where(iou <= iou_thres)[0] + 1]
    return torch.tensor(keep, dtype=torch.int64)

torchvision.ops.nms = _pure_nms
# ─────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(SCRIPTS))

MODEL_PATH = (
    ROOT / "src/cv/yolo_detector/projects/combined/model/best.pt"
)

# 每个类的显示颜色 (BGR) 和中文名
CLASS_INFO = {
    0: {"name": "red", "label": "红色条", "color": (0, 0, 255)},       # 红框
    1: {"name": "green", "label": "绿色条", "color": (0, 255, 0)},     # 绿框
    2: {"name": "obstacle", "label": "障碍物", "color": (0, 165, 255)}, # 橙框
}


def parse_args():
    p = argparse.ArgumentParser(description="YOLO 实时检测可视化")
    p.add_argument("--model", type=str, default=str(MODEL_PATH), help="模型路径")
    p.add_argument("--conf", type=float, default=0.5, help="置信度阈值")
    p.add_argument("--imgsz", type=int, default=640, help="推理图像尺寸")
    p.add_argument("--cpu", action="store_true", help="使用 CPU 推理")
    p.add_argument("--no-depth", action="store_true", help="不显示深度/距离")
    p.add_argument("--save-dir", type=str, default="", help="截图保存目录（留空不保存）")
    return p.parse_args()


def open_camera():
    """优先 D455，回退 USB 摄像头。"""
    try:
        from cv.realsense_camera import RealsenseCamera
        cam = RealsenseCamera(width=640, height=480, enable_depth=True, align_depth=True)
        cam.start()
        print(f"[相机] D455: {cam.device_name} (serial={cam.serial})")
        return cam, None, True
    except Exception as e:
        print(f"[相机] D455 失败 ({e})，回退 USB 摄像头")
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            raise RuntimeError("无法打开任何摄像头")
        print(f"[相机] USB 摄像头: {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
        return None, cap, False


def draw_results(frame, results, depth_img=None, show_depth=True):
    """在帧上绘制分割 mask + bbox + 标签 + 中心点 + 距离。"""
    annotated = frame.copy()
    r = results[0]

    if r.masks is None or r.boxes is None or len(r.boxes) == 0:
        cv2.putText(annotated, "No detections", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        return annotated, []

    masks = r.masks.data.cpu().numpy().astype(bool)
    boxes = r.boxes

    # 半透明 mask
    overlay = annotated.copy()
    for i, mask in enumerate(masks):
        cls_id = int(boxes.cls[i])
        color = CLASS_INFO.get(cls_id, {}).get("color", (255, 255, 255))
        overlay[mask] = color
        contours, _ = cv2.findContours(
            mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        cv2.drawContours(annotated, contours, -1, color, 2)
    cv2.addWeighted(overlay, 0.4, annotated, 0.6, 0, annotated)

    detections = []
    for i, mask in enumerate(masks):
        cls_id = int(boxes.cls[i])
        conf = float(boxes.conf[i])
        info = CLASS_INFO.get(cls_id, {"name": f"cls{cls_id}", "label": f"cls{cls_id}", "color": (255, 255, 255)})
        color = info["color"]
        xyxy = boxes.xyxy[i].cpu().numpy()
        x1, y1, x2, y2 = map(int, xyxy)

        # 中心点
        ys, xs = np.where(mask)
        if len(xs) > 0:
            cx, cy = int(xs.mean()), int(ys.mean())
        else:
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        cv2.circle(annotated, (cx, cy), 4, (255, 255, 255), -1)
        cv2.circle(annotated, (cx, cy), 6, color, 2)

        # 标签 + 距离
        text_parts = [f"{info['label']} {conf:.2f}"]
        distance_m = None
        if show_depth and depth_img is not None:
            if 0 <= cy < depth_img.shape[0] and 0 <= cx < depth_img.shape[1]:
                d_mm = depth_img[cy, cx]
                if d_mm > 0:
                    distance_m = d_mm / 1000.0
                    text_parts.append(f"{distance_m:.2f}m")

        text = " | ".join(text_parts)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
        cv2.rectangle(annotated, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
        cv2.putText(annotated, text, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

        detections.append({
            "class": info["name"],
            "confidence": conf,
            "center": (cx, cy),
            "distance_m": distance_m,
        })

    return annotated, detections


def main():
    args = parse_args()

    # 加载模型
    print(f"[模型] 加载: {args.model}")
    from ultralytics import YOLO
    model = YOLO(args.model)
    device = "cpu" if args.cpu else "0"
    print(f"[模型] 类别: {model.names}  | 设备: {'CPU' if args.cpu else 'GPU'}")

    # 打开相机
    d455_cam, usb_cap, use_d455 = open_camera()

    # 截图目录
    save_dir = None
    if args.save_dir:
        save_dir = Path(args.save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

    print("[运行] 按 Q 退出 | 按 S 截图")
    print(f"{'类别':<8} {'置信度':<8} {'中心':<14} {'距离'}")
    print("-" * 45)

    fps_smooth = 0
    frame_count = 0
    prev_time = time.perf_counter()
    screenshot_count = 0

    try:
        while True:
            # 取帧
            depth_img = None
            if use_d455:
                color_img, depth_img = d455_cam.get_frames()
                if color_img is None:
                    continue
                frame = color_img
            else:
                ret, frame = usb_cap.read()
                if not ret:
                    break

            frame_count += 1

            # 推理
            t0 = time.perf_counter()
            results = model(frame, conf=args.conf, imgsz=args.imgsz, device=device, verbose=False)
            t1 = time.perf_counter()
            infer_ms = (t1 - t0) * 1000

            # 绘制
            annotated, detections = draw_results(frame, results, depth_img, show_depth=not args.no_depth)

            # FPS 平滑
            fps_smooth = fps_smooth * 0.9 + (1000 / infer_ms) * 0.1 if infer_ms > 0 else fps_smooth

            # 顶部信息栏
            total = len(detections)
            counts = {}
            for d in detections:
                counts[d["class"]] = counts.get(d["class"], 0) + 1
            count_str = " | ".join(f"{c}:{n}" for c, n in counts.items()) if counts else "none"

            cv2.putText(annotated, f"FPS: {fps_smooth:.1f}  |  {count_str}",
                        (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.rectangle(annotated, (0, 0), (annotated.shape[1], 36), (0, 0, 0), -2)

            # 打印终端输出
            if detections:
                for d in detections:
                    dist_str = f"{d['distance_m']:.2f}m" if d["distance_m"] else "-"
                    print(f"\r{d['class']:<8} {d['confidence']:.3f}   ({d['center'][0]:>4},{d['center'][1]:<4})  {dist_str}")

            # 显示
            cv2.imshow("YOLO Live Detection [Q=退出 S=截图]", annotated)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                print("\n[退出]")
                break
            elif key == ord("s"):
                screenshot_count += 1
                if save_dir:
                    path = save_dir / f"yolo_screenshot_{screenshot_count:04d}.jpg"
                else:
                    path = Path(f"yolo_screenshot_{screenshot_count:04d}.jpg")
                cv2.imwrite(str(path), annotated)
                print(f"\n[截图] 已保存: {path}")

    except KeyboardInterrupt:
        print("\n[退出]")
    finally:
        if d455_cam:
            d455_cam.stop()
        if usb_cap:
            usb_cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
