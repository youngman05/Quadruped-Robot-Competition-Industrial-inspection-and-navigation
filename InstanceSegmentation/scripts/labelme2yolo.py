#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
labelme JSON 标注 → YOLOv8 实例分割格式 转换脚本

用法:
    # 把 labelme 标注好的图片和 JSON 放到 datasets/raw/ 下，然后：
    python scripts/labelme2yolo.py --src datasets/raw --split train

    # 手动指定类别映射
    python scripts/labelme2yolo.py --src datasets/raw --split val --classes "dog,cat,car"
"""

import argparse
import json
import shutil
from pathlib import Path
from typing import Dict, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="labelme JSON → YOLOv8 seg 格式")
    parser.add_argument("--src", type=str, required=True,
                        help="labelme JSON 和图片所在的源目录")
    parser.add_argument("--split", type=str, default="train",
                        choices=["train", "val", "test"],
                        help="数据集划分（默认: train）")
    parser.add_argument("--classes", type=str, default=None,
                        help="逗号分隔的类别名列表，不传则自动从 JSON 里收集")
    return parser.parse_args()


def load_labelme_json(json_path: Path) -> dict:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def polygon_to_yolo(points: List[List[float]], img_w: int, img_h: int) -> List[float]:
    """将 labelme 的多边形坐标转为 YOLO 归一化坐标（0~1）。"""
    yolo_coords = []
    for x, y in points:
        yolo_coords.append(x / img_w)
        yolo_coords.append(y / img_h)
    return yolo_coords


def validate_polygon(points: List[List[float]]) -> bool:
    """检查多边形至少 3 个点。"""
    return len(points) >= 3


def main() -> None:
    args = parse_args()

    src_dir = Path(args.src).resolve()
    if not src_dir.exists():
        raise FileNotFoundError(f"源目录不存在: {src_dir}")

    # 输出目录
    root = Path(__file__).resolve().parents[1]
    img_out = root / "datasets" / "images" / args.split
    lbl_out = root / "datasets" / "labels" / args.split
    img_out.mkdir(parents=True, exist_ok=True)
    lbl_out.mkdir(parents=True, exist_ok=True)

    # 收集所有 JSON 文件
    json_files = sorted(src_dir.glob("*.json"))
    if not json_files:
        raise FileNotFoundError(f"{src_dir} 下没有找到 .json 文件")

    # 类别名 → id 映射
    if args.classes:
        class_names = [c.strip() for c in args.classes.split(",") if c.strip()]
        class_map = {name: i for i, name in enumerate(class_names)}
    else:
        # 自动收集所有 labelme 里的类别
        all_labels: set = set()
        for jf in json_files:
            data = load_labelme_json(jf)
            for shape in data.get("shapes", []):
                all_labels.add(shape["label"])
        class_names = sorted(all_labels)
        class_map = {name: i for i, name in enumerate(class_names)}
        print(f"[自动发现 {len(class_names)} 个类别]: {', '.join(class_names)}")

    converted = 0
    skipped = 0

    for json_path in json_files:
        data = load_labelme_json(json_path)
        img_w = int(data.get("imageWidth", 0))
        img_h = int(data.get("imageHeight", 0))

        if img_w <= 0 or img_h <= 0:
            print(f"[跳过] {json_path.name}: 缺少 imageWidth/imageHeight")
            skipped += 1
            continue

        # 找到对应的图片文件
        img_name = data.get("imagePath", "")
        img_path = src_dir / img_name
        if not img_path.exists():
            # 尝试同名不同后缀
            for ext in [".jpg", ".jpeg", ".png", ".bmp"]:
                candidate = src_dir / (json_path.stem + ext)
                if candidate.exists():
                    img_path = candidate
                    img_name = candidate.name
                    break
        if not img_path.exists():
            print(f"[跳过] {json_path.name}: 找不到图片 {img_name}")
            skipped += 1
            continue

        # 转换所有 shape
        yolo_lines: List[str] = []
        for shape in data.get("shapes", []):
            label = shape["label"]
            if label not in class_map:
                print(f"[警告] {json_path.name}: 未知类别 '{label}'，跳过")
                continue

            points = shape["points"]
            if not validate_polygon(points):
                print(f"[警告] {json_path.name}: {label} 多边形点数不足 3，跳过")
                continue

            cls_id = class_map[label]
            coords = polygon_to_yolo(points, img_w, img_h)
            yolo_lines.append(f"{cls_id} " + " ".join(f"{c:.6f}" for c in coords))

        if not yolo_lines:
            print(f"[跳过] {json_path.name}: 没有有效的标注")
            skipped += 1
            continue

        # 写 YOLO 标签文件
        lbl_path = lbl_out / (json_path.stem + ".txt")
        with open(lbl_path, "w", encoding="utf-8") as f:
            f.write("\n".join(yolo_lines) + "\n")

        # 复制图片（源和目标相同则跳过）
        dest_img = img_out / img_name
        if img_path.resolve() != dest_img.resolve():
            shutil.copy2(img_path, dest_img)

        converted += 1
        if converted % 10 == 0:
            print(f"  已转换 {converted} / {len(json_files)} ...")

    print(f"\n完成！转换 {converted} 个，跳过 {skipped} 个")
    print(f"  图片: {img_out}")
    print(f"  标签: {lbl_out}")
    print(f"  类别 ({len(class_names)}): {class_map}")


if __name__ == "__main__":
    main()
