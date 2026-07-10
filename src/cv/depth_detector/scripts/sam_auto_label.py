#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SAM 自动标注工具 — 用 Segment Anything 自动生成 labelme JSON。

用法:
    python src/cv/depth_detector/scripts/sam_auto_label.py --src datasets/raw --label obstacle

流程:
    1. SAM 自动检测图片里所有物体
    2. 每个物体生成多边形 mask → 写入 labelme JSON
    3. 再用 labelme2yolo.py 转 YOLO 格式
"""

import argparse
import json
import os
from pathlib import Path

import cv2
import numpy as np
from segment_anything import sam_model_registry, SamAutomaticMaskGenerator


MODEL_PATH = os.path.expanduser("~/.labelme/models/sam_vit_b_01ec64.pth")


def parse_args():
    parser = argparse.ArgumentParser(description="SAM 自动标注 → labelme JSON")
    parser.add_argument("--src", type=str, required=True,
                        help="图片目录")
    parser.add_argument("--label", type=str, default="obstacle",
                        help="类别名（所有检测到的物体都用这个标签）")
    parser.add_argument("--min-area", type=int, default=500,
                        help="最小 mask 面积 (px)，过滤小噪点")
    parser.add_argument("--device", type=str, default="0",
                        help="0=GPU, cpu=CPU")
    return parser.parse_args()


def mask_to_polygon(mask: np.ndarray, simplify_eps: float = 2.0) -> list:
    """二值 mask → 多边形点列表（简化后）"""
    contours, _ = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    all_points = []
    for cnt in contours:
        if len(cnt) < 3:
            continue
        # 简化轮廓
        epsilon = simplify_eps * cv2.arcLength(cnt, True) / 1000
        approx = cv2.approxPolyDP(cnt, epsilon, True)
        pts = approx.squeeze(1)  # (N, 2)
        if pts.ndim == 1:
            pts = pts.reshape(-1, 2)
        if len(pts) >= 3:
            all_points.append(pts.tolist())
    return all_points


def main():
    args = parse_args()

    src_dir = Path(args.src).resolve()
    if not src_dir.exists():
        raise FileNotFoundError(f"目录不存在: {src_dir}")

    image_paths = []
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.bmp"):
        image_paths.extend(sorted(src_dir.glob(ext)))
    if not image_paths:
        raise FileNotFoundError(f"{src_dir} 下没有图片")

    print(f"[找到 {len(image_paths)} 张图片]")

    # 加载 SAM
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(
            f"SAM 模型未找到: {MODEL_PATH}\n"
            f"手动下载: https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth\n"
            f"放到: {MODEL_PATH}"
        )

    print(f"加载 SAM 模型 ({'GPU' if args.device != 'cpu' else 'CPU'})...")
    sam = sam_model_registry["vit_b"](checkpoint=MODEL_PATH)
    sam.to(f"cuda:{args.device}" if args.device != "cpu" else "cpu")
    mask_generator = SamAutomaticMaskGenerator(
        model=sam,
        min_mask_region_area=args.min_area,
    )
    print("SAM 加载完成\n")

    auto_labeled = 0
    for img_path in image_paths:
        print(f"  {img_path.name} ...", end=" ")

        img = cv2.imdecode(np.fromfile(str(img_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            print("读取失败")
            continue
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w = img_rgb.shape[:2]

        # SAM 自动生成所有 mask
        masks = mask_generator.generate(img_rgb)

        # 过滤太小或太碎的区域
        shapes = []
        for m in masks:
            if m["area"] < args.min_area:
                continue
            polygons = mask_to_polygon(m["segmentation"])
            for poly in polygons:
                shapes.append({
                    "label": args.label,
                    "points": poly,
                    "shape_type": "polygon",
                    "group_id": None,
                })

        print(f"{len(shapes)} 个实例")

        # 写 labelme JSON
        labelme_data = {
            "version": "5.1.1",
            "flags": {},
            "shapes": shapes,
            "imagePath": img_path.name,
            "imageData": None,
            "imageHeight": h,
            "imageWidth": w,
        }

        json_path = src_dir / (img_path.stem + ".json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(labelme_data, f, ensure_ascii=False, indent=2)

        if len(shapes) > 0:
            auto_labeled += 1

    print(f"\n完成！{auto_labeled}/{len(image_paths)} 张图有检测结果")
    print(f"JSON 已写入: {src_dir}")
    print(f"\n下一步:")
    print(f"  python scripts/labelme2yolo.py --src {args.src} --split train --classes \"{args.label}\"")


if __name__ == "__main__":
    main()
