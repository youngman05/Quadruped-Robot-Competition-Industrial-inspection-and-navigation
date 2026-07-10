#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
YOLO 视频文件实例分割
使用 YOLOv8-seg 模型对视频进行实例分割，输出带 mask 的标注视频。
"""

import argparse
from ultralytics import YOLO


def parse_args():
    parser = argparse.ArgumentParser(description="YOLOv8 视频实例分割")
    parser.add_argument("--model", type=str, default="yolov8n-seg.pt",
                        help="模型路径（默认: yolov8n-seg.pt）")
    parser.add_argument("--source", type=str, required=True,
                        help="视频文件路径")
    parser.add_argument("--conf", type=float, default=0.5,
                        help="置信度阈值（默认: 0.5）")
    parser.add_argument("--imgsz", type=int, default=640,
                        help="推理图像尺寸（默认: 640）")
    parser.add_argument("--device", type=str, default="0",
                        help="推理设备: 0=GPU, cpu=CPU（默认: 0）")
    parser.add_argument("--output", type=str, default="outputs",
                        help="输出目录（默认: outputs）")
    parser.add_argument("--show", action="store_true",
                        help="是否实时显示推理过程")
    return parser.parse_args()


def main():
    args = parse_args()

    print(f"[信息] 加载模型: {args.model}")
    model = YOLO(args.model)

    print(f"[信息] 视频来源: {args.source}")
    results = model(
        source=args.source,
        conf=args.conf,
        imgsz=args.imgsz,
        device=args.device,
        save=True,
        project=args.output,
        name="video_detect",
        exist_ok=True,
        show=args.show,
    )

    print(f"[信息] 检测完成！结果已保存到: {args.output}/video_detect")


if __name__ == "__main__":
    main()
