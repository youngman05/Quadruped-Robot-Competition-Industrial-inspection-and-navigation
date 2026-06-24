#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
D455 双模型实时实例分割 — 同时检测红绿色块和路障。

用法:
    python scripts/camera_multi_detect.py

按 Q 退出。
"""

import sys
import time
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def draw_all(annotated, results_list, colors_list, alpha=0.45):
    """在帧上绘制多个模型的分割结果。"""

    for results, colors in zip(results_list, colors_list):
        if results[0].masks is None:
            continue

        masks = results[0].masks.data.cpu().numpy().astype(bool)
        boxes = results[0].boxes
        names = results[0].names

        overlay = annotated.copy()

        for i, mask in enumerate(masks):
            cls_id = int(boxes.cls[i])
            conf = float(boxes.conf[i])
            label = names.get(cls_id, f"cls{cls_id}")
            color = colors[cls_id % len(colors)]
            area_px = int(mask.sum())

            # 半透明 mask
            overlay[mask] = color
            # 轮廓
            contours, _ = cv2.findContours(
                mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            cv2.drawContours(annotated, contours, -1, color, 2)

        cv2.addWeighted(overlay, alpha, annotated, 1 - alpha, 0, annotated)

        # Box + 标签
        for i, mask in enumerate(masks):
            cls_id = int(boxes.cls[i])
            conf = float(boxes.conf[i])
            label = names.get(cls_id, f"cls{cls_id}")
            color = colors[cls_id % len(colors)]
            xyxy = boxes.xyxy[i].cpu().numpy()
            x1, y1, x2, y2 = map(int, xyxy)

            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            text = f"{label} {conf:.2f}"
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
            cv2.rectangle(annotated, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
            cv2.putText(annotated, text, (x1 + 2, y1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

    return annotated


def main():
    from cv.realsense_camera import RealsenseCamera

    # 模型配置
    models_cfg = [
        {
            "path": "projects/red_green/model/best.pt",
            "colors": [(0, 0, 255), (0, 255, 0)],  # 红(red)用蓝色框, 绿(green)用绿色框
            "name": "色块",
        },
        {
            "path": "projects/obstacle/model/best.pt",
            "colors": [(0, 165, 255), (0, 140, 255)],  # 路障用橙色
            "name": "路障",
        },
    ]

    # 加载模型
    models = []
    all_colors = []
    for cfg in models_cfg:
        mpath = ROOT / "InstanceSegmentation" / cfg["path"]
        print(f"[加载] {cfg['name']}: {mpath}")
        models.append(YOLO(str(mpath)))
        all_colors.append(cfg["colors"])

    # 启动 D455
    cam = RealsenseCamera(width=640, height=480, enable_depth=False)
    cam.start()
    print(f"[相机] {cam.device_name} ({cam.serial})")
    print("[运行] 按 Q 退出\n")

    prev_time = time.perf_counter()
    frame_count = 0

    try:
        while True:
            frame = cam.get_color_image()
            if frame is None:
                continue

            frame_count += 1

            # 两个模型分别推理
            all_results = []
            for model in models:
                res = model(frame, conf=0.5, imgsz=640, device=0, verbose=False)
                all_results.append(res)

            # 绘制
            annotated = draw_all(frame, all_results, all_colors)

            # FPS + 实例数
            curr_time = time.perf_counter()
            elapsed = curr_time - prev_time
            fps = frame_count / elapsed if elapsed >= 1.0 else 1.0 / elapsed if elapsed > 0 else 0
            if elapsed >= 1.0:
                prev_time = curr_time
                frame_count = 0

            total_instances = sum(
                len(r[0].boxes) if r[0].boxes is not None else 0
                for r in all_results
            )
            cv2.putText(annotated, f"FPS: {fps:.1f}  Instances: {total_instances}",
                        (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(annotated, "Red/Green + Obstacle",
                        (10, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

            cv2.imshow("D455 双模型 [Q 退出]", annotated)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    except KeyboardInterrupt:
        print("\n[退出]")
    finally:
        cam.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
