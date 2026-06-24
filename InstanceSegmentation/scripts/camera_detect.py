#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
实时实例分割
使用 YOLOv8-seg 模型进行实时实例分割，显示 mask + box + FPS。

相机支持：
  - 默认：cv2.VideoCapture（普通 USB 摄像头）
  - --d455：使用 Intel RealSense D455

按 Q 键退出。
"""

import argparse
import time
import sys
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO


def parse_args():
    parser = argparse.ArgumentParser(description="YOLOv8 实时实例分割")
    parser.add_argument("--model", type=str, default="yolov8n-seg.pt",
                        help="模型路径（默认: yolov8n-seg.pt，首次运行自动下载）")
    parser.add_argument("--camera", type=int, default=0,
                        help="摄像头设备 ID，--d455 时忽略（默认: 0）")
    parser.add_argument("--conf", type=float, default=0.5,
                        help="置信度阈值（默认: 0.5）")
    parser.add_argument("--imgsz", type=int, default=640,
                        help="推理图像尺寸（默认: 640）")
    parser.add_argument("--device", type=str, default="0",
                        help="推理设备: 0=GPU, cpu=CPU（默认: 0）")
    parser.add_argument("--d455", action="store_true",
                        help="使用 RealSense D455 相机（需 pyrealsense2）")
    parser.add_argument("--alpha", type=float, default=0.45,
                        help="mask 透明度（默认: 0.45）")
    return parser.parse_args()


def draw_segmentation(frame, results, depth_img=None, alpha=0.45):
    """在帧上绘制实例分割结果：彩色半透明 mask + 轮廓 + box + 标签 + 距离。

    Args:
        frame: 原始 BGR 图像 (H, W, 3)
        results: YOLO 推理结果
        depth_img: 对齐后的深度图 (H, W) uint16 mm，None 则不显示距离
        alpha: mask 透明度

    Returns:
        标注后的图像
    """
    annotated = frame.copy()

    if results[0].masks is None:
        return results[0].plot()

    rng = np.random.default_rng(42)
    colors = rng.integers(0, 255, (80, 3), dtype=np.uint8)

    overlay = annotated.copy()
    masks = results[0].masks.data.cpu().numpy().astype(np.bool_)
    boxes = results[0].boxes

    for i, mask in enumerate(masks):
        cls_id = int(boxes.cls[i]) if boxes.cls is not None else 0
        color = colors[cls_id % 80].tolist()
        overlay[mask] = color
        contours, _ = cv2.findContours(
            mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        cv2.drawContours(annotated, contours, -1, color, 2)

    cv2.addWeighted(overlay, alpha, annotated, 1 - alpha, 0, annotated)

    for i, mask in enumerate(masks):
        cls_id = int(boxes.cls[i]) if boxes.cls is not None else 0
        conf = float(boxes.conf[i]) if boxes.conf is not None else 0.0
        label = results[0].names.get(cls_id, f"cls{cls_id}")

        color = colors[cls_id % 80].tolist()
        xyxy = boxes.xyxy[i].cpu().numpy()
        x1, y1, x2, y2 = map(int, xyxy)

        # 计算 mask 中心 → 查深度
        ys, xs = np.where(mask)
        if len(xs) > 0:
            cx, cy = int(xs.mean()), int(ys.mean())
        else:
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

        # 画中心点
        cv2.circle(annotated, (cx, cy), 4, (255, 255, 255), -1)
        cv2.circle(annotated, (cx, cy), 6, color, 2)

        # 标签文字
        text_parts = [f"{label} {conf:.2f}"]
        if depth_img is not None and 0 <= cy < depth_img.shape[0] and 0 <= cx < depth_img.shape[1]:
            d_mm = depth_img[cy, cx]
            if d_mm > 0:
                text_parts.append(f"| {d_mm/1000:.2f}m")
        text = " ".join(text_parts)

        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        cv2.rectangle(annotated, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
        cv2.putText(annotated, text, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

    return annotated


def open_d455():
    """打开 D455 相机，返回 (RealsenseCamera instance, width, height)."""
    try:
        ROOT = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(ROOT / "src"))
        from cv.realsense_camera import RealsenseCamera
    except ImportError:
        print("[错误] 无法导入 cv.realsense_camera，请先执行:")
        print("       python setup.py develop")
        return None, 0, 0

    cam = RealsenseCamera(width=640, height=480, enable_depth=True, align_depth=True)
    cam.start()
    print(f"[信息] D455 已启动: {cam.device_name} (serial={cam.serial})")
    return cam, cam.width, cam.height


def main():
    args = parse_args()

    # 加载模型
    print(f"[信息] 加载模型: {args.model}")
    model = YOLO(args.model)

    # 打开相机
    if args.d455:
        d455_cam, cam_w, cam_h = open_d455()
        if d455_cam is None:
            return
        use_d455 = True
    else:
        cap = cv2.VideoCapture(args.camera)
        if not cap.isOpened():
            print(f"[错误] 无法打开摄像头 (ID={args.camera})")
            return
        cam_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        cam_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        use_d455 = False

    print(f"[信息] 相机分辨率: {cam_w}x{cam_h}")
    print("[信息] 开始实时实例分割，按 Q 键退出...")

    prev_time = time.perf_counter()
    frame_count = 0

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
                ret, frame = cap.read()
                if not ret:
                    print("[警告] 读取摄像头帧失败")
                    break

            frame_count += 1

            # 推理
            results = model(frame, conf=args.conf, imgsz=args.imgsz,
                           device=args.device, verbose=False)

            # 绘制分割结果
            annotated = draw_segmentation(frame, results, depth_img=depth_img, alpha=args.alpha)

            # FPS
            curr_time = time.perf_counter()
            elapsed = curr_time - prev_time
            if elapsed >= 1.0:
                fps = frame_count / elapsed
                prev_time = curr_time
                frame_count = 0
            else:
                fps = 1.0 / elapsed if elapsed > 0 else 0

            cv2.putText(annotated, f"FPS: {fps:.1f}", (10, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

            # 实例计数
            n_instances = len(results[0].boxes) if results[0].boxes is not None else 0
            cv2.putText(annotated, f"Instances: {n_instances}", (10, 56),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            cv2.imshow("YOLO 实例分割 [Q 退出]", annotated)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                print("[信息] 用户退出")
                break
    except KeyboardInterrupt:
        print("\n[信息] Ctrl+C 退出")
    finally:
        if use_d455:
            d455_cam.stop()
        else:
            cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
