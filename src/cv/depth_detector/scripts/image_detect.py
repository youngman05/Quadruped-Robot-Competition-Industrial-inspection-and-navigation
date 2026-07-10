#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
YOLO 图片实例分割
使用 YOLOv8-seg 模型对图片进行实例分割，输出 mask + box + 标签。
"""

import argparse
import os
from pathlib import Path
from ultralytics import YOLO


def parse_args():
    parser = argparse.ArgumentParser(description="YOLOv8 图片实例分割")
    parser.add_argument("--model", type=str, default="yolov8n-seg.pt",
                        help="模型路径（默认: yolov8n-seg.pt）")
    parser.add_argument("--source", type=str, required=True,
                        help="图片路径或目录")
    parser.add_argument("--conf", type=float, default=0.5,
                        help="置信度阈值（默认: 0.5）")
    parser.add_argument("--imgsz", type=int, default=640,
                        help="推理图像尺寸（默认: 640）")
    parser.add_argument("--device", type=str, default="0",
                        help="推理设备: 0=GPU, cpu=CPU（默认: 0）")
    parser.add_argument("--output", type=str, default="outputs",
                        help="输出目录（默认: outputs）")
    parser.add_argument("--show", action="store_true",
                        help="是否显示结果图片")
    return parser.parse_args()


def main():
    args = parse_args()

    print(f"[信息] 加载模型: {args.model}")
    model = YOLO(args.model)

    print(f"[信息] 推理来源: {args.source}")
    results = model(
        source=args.source,
        conf=args.conf,
        imgsz=args.imgsz,
        device=args.device,
        save=True,
        project=args.output,
        name="image_detect",
        exist_ok=True,
        show=args.show,
    )

    output_dir = os.path.join(args.output, "image_detect")
    print(f"[信息] 结果已保存到: {output_dir}")

    # 打印检测摘要
    for r in results:
        if r.boxes is not None:
            n = len(r.boxes)
            n_masks = len(r.masks) if r.masks is not None else 0
            fname = Path(r.path).name
            print(f"  {fname}: {n} 个目标, {n_masks} 个 mask")
            for i in range(n):
                cls_id = int(r.boxes.cls[i])
                conf = float(r.boxes.conf[i])
                label = r.names.get(cls_id, f"cls{cls_id}")
                mask_area = int(r.masks.data[i].sum()) if r.masks is not None else 0
                print(f"    [{i}] {label} conf={conf:.3f} mask_area={mask_area}px")


if __name__ == "__main__":
    main()
