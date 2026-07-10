"""
将 LabelMe JSON 标注转换为 YOLO 格式，建立训练/验证集。

用法:
    cd InstanceSegmentation
    python scripts/setup_gauge_dataset.py

输出:
    projects/gauge/
    ├── datasets/
    │   ├── images/train/   ← 训练图
    │   ├── images/val/     ← 验证图
    │   ├── labels/train/   ← YOLO txt 标注
    │   └── labels/val/
    └── configs/
        └── dataset.yaml
"""

import json
import random
import shutil
from pathlib import Path

# ── 配置 ──
BASE = Path(__file__).resolve().parent.parent  # InstanceSegmentation/
SRC = BASE / "gauge_dataset"
PROJ = BASE / "projects" / "gauge"
DATASETS = PROJ / "datasets"
VAL_RATIO = 0.2   # 20% 验证集
SEED = 42

# 类别映射: LabelMe label → class_id
CLASS_NAMES = ["A", "B", "C", "D", "green", "red", "yellow"]
CLASS_MAP = {name.lower(): i for i, name in enumerate(CLASS_NAMES)}

# 创建目录结构
for split in ("train", "val"):
    for sub in ("images", "labels"):
        (DATASETS / sub / split).mkdir(parents=True, exist_ok=True)

# 收集所有标注，按类别分层拆分
json_files = sorted(SRC.glob("*.json"))
random.seed(SEED)

# 统计每张图的标签
file_labels = {}
for jf in json_files:
    d = json.load(open(jf))
    file_labels[jf] = [s["label"].strip().lower() for s in d["shapes"]]

# 确保稀有类别 (A, C, red 等) 至少 1 张进验证集
val_files = []
train_files = list(json_files)
# 为每个稀有类别选至少 1 张进验证集
rare_classes = {"a", "c", "red"}
for cls in rare_classes:
    candidates = [jf for jf in train_files if cls in file_labels[jf]]
    if candidates and len(val_files) < len(json_files) * VAL_RATIO + len(rare_classes):
        chosen = random.choice(candidates)
        train_files.remove(chosen)
        val_files.append(chosen)

# 剩余验证集随机补足
needed = max(1, int(len(json_files) * VAL_RATIO)) - len(val_files)
if needed > 0:
    random.shuffle(train_files)
    val_files.extend(train_files[:needed])
    train_files = train_files[needed:]

print(f"总图片: {len(json_files)}  (train={len(train_files)}, val={len(val_files)})")
print(f"类别: {CLASS_NAMES}\n")


def convert_one(json_path, split):
    """转换单个 LabelMe JSON → 复制图片 + 写 YOLO label txt"""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    img_name = data["imagePath"]
    img_src = SRC / img_name
    if not img_src.exists():
        print(f"  [WARN] 图片不存在: {img_name}")
        return

    h_img, w_img = data["imageHeight"], data["imageWidth"]

    # 复制图片
    shutil.copy2(str(img_src), str(DATASETS / "images" / split / img_name))

    # 写 YOLO 标注
    label_name = img_src.stem + ".txt"
    label_path = DATASETS / "labels" / split / label_name

    lines = []
    for shape in data["shapes"]:
        label = shape["label"].strip()
        # 统一大小写
        label_lower = label.lower()
        if label_lower not in CLASS_MAP:
            print(f"  [WARN] 未知标签: '{label}' in {json_path.name}")
            continue
        cls_id = CLASS_MAP[label_lower]

        (x1, y1), (x2, y2) = shape["points"]
        # LabelMe 矩形: 左上 + 右下 → YOLO 归一化中心宽高
        x_center = ((x1 + x2) / 2) / w_img
        y_center = ((y1 + y2) / 2) / h_img
        width = abs(x2 - x1) / w_img
        height = abs(y2 - y1) / h_img

        lines.append(f"{cls_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}")

    with open(label_path, "w") as f:
        f.write("\n".join(lines))


# 转换
for split, file_list in [("train", train_files), ("val", val_files)]:
    print(f"[{split}] {len(file_list)} 张...")
    for jf in file_list:
        convert_one(jf, split)

# 写 dataset.yaml
yaml_path = PROJ / "configs" / "dataset.yaml"
yaml_path.parent.mkdir(parents=True, exist_ok=True)
yaml_content = f"""# 仪表柜面字母+颜色检测 — YOLO 数据集配置
# 类别: A(0), B(1), C(2), D(3), green(4), red(5), yellow(6)

path: {DATASETS.resolve().as_posix()}

train: images/train
val: images/val

nc: {len(CLASS_NAMES)}

names:
"""
for i, name in enumerate(CLASS_NAMES):
    yaml_content += f"  {i}: {name}\n"

with open(yaml_path, "w") as f:
    f.write(yaml_content)

print(f"\n[DONE] 数据集: {DATASETS}")
print(f"   配置文件: {yaml_path}")
print(f"\n训练命令:")
print(f"   python ../src/cv/yolo_detector/scripts/train.py \\")
print(f"       --data {yaml_path} \\")
print(f"       --model yolov8n.pt --epochs 100 --batch 16 --imgsz 640")


if __name__ == "__main__":
    # 显示类别统计
    from collections import Counter
    stats = Counter()
    for jf in json_files:
        d = json.load(open(jf))
        for s in d["shapes"]:
            stats[s["label"].strip().lower()] += 1
    print("类别分布:", dict(stats))
    print()
