#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
YOLO 模型训练脚本
封装 Ultralytics 训练接口，支持自定义数据集和参数。
"""

import argparse
from ultralytics import YOLO


def parse_args():
    parser = argparse.ArgumentParser(description="YOLO 模型训练")
    parser.add_argument("--data", type=str, required=True,
                        help="数据集配置文件路径（如 configs/dataset.yaml）")
    parser.add_argument("--model", type=str, default="yolov8n.pt",
                        help="预训练模型（默认: yolov8n.pt）")
    parser.add_argument("--epochs", type=int, default=100,
                        help="训练轮数（默认: 100）")
    parser.add_argument("--batch", type=int, default=16,
                        help="批次大小（默认: 16，显存不足可调小）")
    parser.add_argument("--imgsz", type=int, default=640,
                        help="输入图像尺寸（默认: 640）")
    parser.add_argument("--device", type=str, default="0",
                        help="训练设备: 0=GPU, cpu=CPU（默认: 0）")
    parser.add_argument("--workers", type=int, default=8,
                        help="数据加载线程数（默认: 8）")
    parser.add_argument("--patience", type=int, default=50,
                        help="早停轮数（默认: 50，设为 0 禁用）")
    parser.add_argument("--lr0", type=float, default=0.01,
                        help="初始学习率（默认: 0.01）")
    parser.add_argument("--name", type=str, default=None,
                        help="训练任务名称（默认: 自动生成）")
    return parser.parse_args()


def main():
    args = parse_args()

    print(f"[信息] 加载预训练模型: {args.model}")
    model = YOLO(args.model)

    print(f"[信息] 数据集配置: {args.data}")
    print(f"[信息] 训练参数: epochs={args.epochs}, batch={args.batch}, imgsz={args.imgsz}")

    # 开始训练
    results = model.train(
        data=args.data,
        epochs=args.epochs,
        batch=args.batch,
        imgsz=args.imgsz,
        device=args.device,
        workers=args.workers,
        patience=args.patience,
        lr0=args.lr0,
        name=args.name,
    )

    print("[信息] 训练完成！")
    print(f"[信息] 最佳模型保存在: {results.save_dir}")


if __name__ == "__main__":
    main()
