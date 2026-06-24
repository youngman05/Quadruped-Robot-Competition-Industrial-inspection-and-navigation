#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SAM 辅助标注 — 点一下，AI 帮你画 mask

操作:
  鼠标左键点击  →  SAM 自动生成该物体的 mask
  鼠标右键      →  删除上一个 mask
  按 S          →  保存为 labelme JSON
  按 D / A      →  上一张 / 下一张图片
  按 Q          →  退出
"""

import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

MODEL_PATH = os.path.expanduser("~/.labelme/models/sam_vit_b_01ec64.pth")

# Global state
state = {
    "img": None,           # BGR image
    "img_rgb": None,       # RGB for SAM
    "display": None,       # annotated display
    "masks": [],           # [(mask, label_name)]
    "current_mask": None,  # temp mask being previewed
    "img_path": None,
    "img_name": "",
    "label_name": "obstacle",
    "image_list": [],
    "image_idx": 0,
    "sam_predictor": None,
    "h": 0, "w": 0,
}


def load_image(img_path):
    """Load image with Chinese path support."""
    state["img_path"] = Path(img_path)
    state["img_name"] = state["img_path"].name
    img = cv2.imdecode(np.fromfile(str(img_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return False
    state["img"] = img
    state["img_rgb"] = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    state["h"], state["w"] = img.shape[:2]
    state["display"] = img.copy()
    state["masks"] = []
    state["current_mask"] = None
    return True


def redraw():
    """Rebuild display with all accepted masks."""
    disp = state["img"].copy()
    colors = [(0, 0, 255), (0, 255, 0), (255, 0, 0), (255, 255, 0), (255, 0, 255)]
    for i, (mask, label) in enumerate(state["masks"]):
        color = colors[i % len(colors)]
        overlay = disp.copy()
        overlay[mask] = color
        cv2.addWeighted(overlay, 0.4, disp, 0.6, 0, disp)
        contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(disp, contours, -1, color, 2)
    if state["current_mask"] is not None:
        overlay = disp.copy()
        overlay[state["current_mask"]] = (255, 255, 255)
        cv2.addWeighted(overlay, 0.5, disp, 0.5, 0, disp)
    # Info text
    n = len(state["masks"])
    cv2.putText(disp, f"[{state['image_idx']+1}/{len(state['image_list'])}] {state['img_name']}  "
                f"masks:{n}  label:{state['label_name']}  S:save D/A:prev/next Q:quit",
                (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    state["display"] = disp


def on_mouse(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        # Left click: SAM segment at this point
        print(f"  Clicked ({x}, {y}) — asking SAM...", end=" ", flush=True)
        input_point = np.array([[x, y]])
        input_label = np.array([1])  # 1 = foreground

        masks, scores, _ = state["sam_predictor"].predict(
            point_coords=input_point,
            point_labels=input_label,
            multimask_output=True,
        )
        best = np.argmax(scores)
        state["current_mask"] = masks[best]
        print(f"score={scores[best]:.3f}")
        redraw()

    elif event == cv2.EVENT_RBUTTONDOWN:
        # Right click: undo last
        if state["masks"]:
            removed = state["masks"].pop()
            print(f"  撤销: {removed[1]}")
            state["current_mask"] = None
            redraw()
        elif state["current_mask"] is not None:
            state["current_mask"] = None
            redraw()


def mask_to_polygon(mask):
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    all_pts = []
    for cnt in contours:
        if len(cnt) < 3:
            continue
        epsilon = 0.002 * cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, epsilon, True)
        pts = approx.squeeze(1)
        if pts.ndim == 1:
            pts = pts.reshape(-1, 2)
        if len(pts) >= 3:
            all_pts.append(pts.tolist())
    return all_pts


def save_json():
    shapes = []
    for mask, label in state["masks"]:
        polygons = mask_to_polygon(mask)
        for poly in polygons:
            shapes.append({
                "label": label,
                "points": poly,
                "shape_type": "polygon",
                "group_id": None,
            })

    data = {
        "version": "5.1.1",
        "flags": {},
        "shapes": shapes,
        "imagePath": state["img_name"],
        "imageData": None,
        "imageHeight": state["h"],
        "imageWidth": state["w"],
    }
    json_path = state["img_path"].with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  Saved: {json_path.name}  ({len(shapes)} shapes)")


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "projects/obstacle/datasets/images/train"
    label = sys.argv[2] if len(sys.argv) > 2 else "obstacle"

    src_dir = Path(src).resolve()
    if not src_dir.exists():
        print(f"Directory not found: {src_dir}")
        return

    state["image_list"] = sorted(
        [f for f in os.listdir(src_dir) if f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp"))]
    )
    if not state["image_list"]:
        print(f"No images in {src_dir}")
        return

    state["label_name"] = label

    # Load SAM
    print("Loading SAM (ViT-B CPU)...", flush=True)
    from segment_anything import SamPredictor, sam_model_registry
    sam = sam_model_registry["vit_b"](checkpoint=MODEL_PATH)
    sam.to("cpu")
    state["sam_predictor"] = SamPredictor(sam)

    # Open first image
    first = os.path.join(str(src_dir), state["image_list"][0])
    load_image(first)
    state["sam_predictor"].set_image(state["img_rgb"])
    redraw()

    print(f"\n{len(state['image_list'])} images loaded.")
    print(f"Left click = segment | Right click = undo | Enter = accept mask")
    print(f"S = save JSON | D = next | A = prev | 1-9 = switch label | Q = quit\n")

    cv2.namedWindow("SAM Click Labeler", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("SAM Click Labeler", 960, 720)
    cv2.setMouseCallback("SAM Click Labeler", on_mouse)

    label_map = {"1": "obstacle", "2": "cone", "3": "barrier", "4": "person", "5": "red", "6": "green"}

    while True:
        cv2.imshow("SAM Click Labeler", state["display"])
        key = cv2.waitKey(50) & 0xFF

        if key == ord("q"):
            break
        elif key == ord("s"):
            save_json()
        elif key == 13:  # Enter = accept current mask
            if state["current_mask"] is not None:
                state["masks"].append((state["current_mask"].copy(), state["label_name"]))
                print(f"  Accepted: {state['label_name']} (total: {len(state['masks'])})")
                state["current_mask"] = None
                redraw()
        elif key == ord("d") or key == ord(" "):
            # Next image (save current first)
            save_json()
            idx = (state["image_idx"] + 1) % len(state["image_list"])
            state["image_idx"] = idx
            img_path = os.path.join(str(src_dir), state["image_list"][idx])
            load_image(img_path)
            state["sam_predictor"].set_image(state["img_rgb"])
            redraw()
            print(f"\n  → {state['img_name']}")
        elif key == ord("a"):
            idx = (state["image_idx"] - 1) % len(state["image_list"])
            state["image_idx"] = idx
            img_path = os.path.join(str(src_dir), state["image_list"][idx])
            load_image(img_path)
            state["sam_predictor"].set_image(state["img_rgb"])
            redraw()
            print(f"\n  → {state['img_name']}")
        elif key in range(ord("1"), ord("9") + 1):
            k = chr(key)
            if k in label_map:
                state["label_name"] = label_map[k]
                print(f"  Label: {state['label_name']}")
                redraw()

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
