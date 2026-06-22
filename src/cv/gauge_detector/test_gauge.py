#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动测试脚本：
1. 从原始图像（image.png）裁剪出6个仪表盘
2. 对每个仪表盘生成多种变换（亮度、对比度、旋转、透视）
3. 运行识别并输出准确率报告
"""

import cv2
import numpy as np
import os
import sys
import math
import random
from gauge_detector import detect_gauge, print_result

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, "test_output")
os.makedirs(OUT_DIR, exist_ok=True)


# ──────────────────────────────────────────────
# Step 1：生成6个标准测试仪表盘图像
# ──────────────────────────────────────────────

def generate_gauge_image(needle_angle_deg: float, zone: str,
                          size: int = 400) -> np.ndarray:
    """
    程序化合成一张仪表盘图像（模拟真实仪表盘外观）
    needle_angle_deg: 指针角度（相对水平右方，逆时针为正）
    zone: 'yellow' / 'green' / 'red'
    """
    img = np.ones((size, size, 3), dtype=np.uint8) * 240  # 浅灰背景
    cx, cy = size // 2, size // 2
    R = int(size * 0.44)

    # 外圈金属边框
    cv2.circle(img, (cx, cy), R + 12, (100, 100, 100), -1)
    cv2.circle(img, (cx, cy), R + 10, (180, 180, 180), 3)
    # 表盘白色背景
    cv2.circle(img, (cx, cy), R, (245, 245, 245), -1)

    # ── 绘制彩色弧段（仪表盘量程 225° 到 -45°，顺时针）──
    # 仪表盘量程：约从 225° 到 -45°（共 270°），顺时针
    # Yellow: 225° ~ 165°（左下区域）
    # Green:  165° ~ 45°（上方区域）
    # Red:     45° ~ -45°（右下区域）
    arc_r_outer = int(R * 0.92)
    arc_r_inner = int(R * 0.75)
    arc_thickness = arc_r_outer - arc_r_inner

    def draw_arc(img, cx, cy, r, start_deg, end_deg, color_bgr, thickness):
        pts_outer, pts_inner = [], []
        for a in np.linspace(start_deg, end_deg, 60):
            rad = math.radians(a)
            pts_outer.append([int(cx + r * math.cos(rad)), int(cy - r * math.sin(rad))])
            pts_inner.append([int(cx + (r - thickness) * math.cos(rad)),
                              int(cy - (r - thickness) * math.sin(rad))])
        pts = np.array(pts_outer + pts_inner[::-1], dtype=np.int32)
        cv2.fillPoly(img, [pts], color_bgr)

    draw_arc(img, cx, cy, arc_r_outer, 165, 225, (0, 220, 220), arc_thickness)   # 黄 BGR=(0,220,220)
    draw_arc(img, cx, cy, arc_r_outer,  45, 165, (0, 180,  0), arc_thickness)   # 绿 BGR=(0,180,0)
    draw_arc(img, cx, cy, arc_r_outer, -45,  45, (0,  0, 220), arc_thickness)   # 红 BGR=(0,0,220)

    # 刻度线
    for i in range(28):
        a = math.radians(225 - i * 270 / 27)
        is_major = (i % 5 == 0)
        r1 = int(R * (0.72 if is_major else 0.76))
        r2 = int(R * 0.92)
        x1 = int(cx + r1 * math.cos(a))
        y1 = int(cy - r1 * math.sin(a))
        x2 = int(cx + r2 * math.cos(a))
        y2 = int(cy - r2 * math.sin(a))
        cv2.line(img, (x1, y1), (x2, y2), (60, 60, 60), 2 if is_major else 1)

    # 指针
    needle_rad = math.radians(needle_angle_deg)
    nx = int(cx + R * 0.78 * math.cos(needle_rad))
    ny = int(cy - R * 0.78 * math.sin(needle_rad))
    # 尾部
    tail_x = int(cx - R * 0.18 * math.cos(needle_rad))
    tail_y = int(cy + R * 0.18 * math.sin(needle_rad))
    cv2.line(img, (tail_x, tail_y), (nx, ny), (20, 20, 20), 5)
    cv2.line(img, (tail_x, tail_y), (nx, ny), (50, 50, 50), 3)
    cv2.circle(img, (cx, cy), int(R * 0.07), (80, 80, 80), -1)
    cv2.circle(img, (cx, cy), int(R * 0.05), (160, 160, 160), -1)

    # MPa 文字
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(img, "MPa", (cx - 22, cy + int(R * 0.45)), font, 0.5, (60, 60, 60), 1)

    return img


# 6个仪表盘的地面真值配置
# 角度说明（数学坐标系，屏幕y轴向下，0°=右，逆时针为正）：
#   黄色区域：165°~225°（左下）→ 角度约 180~210°
#   绿色区域：45°~165°（上方） → 角度约 60°~150°
#   红色区域：-45°~45°（右下） → 角度约 -30°~30°
GAUGE_CONFIGS = [
    {"id": 1, "angle": 195, "zone": "yellow", "label": "偏低/异常"},   # 黄区中段
    {"id": 2, "angle": 100, "zone": "green",  "label": "正常/正常"},   # 绿区中段
    {"id": 3, "angle": 65,  "zone": "green",  "label": "正常/正常"},   # 绿区右侧
    {"id": 4, "angle": 150, "zone": "green",  "label": "正常/正常"},   # 绿区左侧
    {"id": 5, "angle": 20,  "zone": "red",    "label": "偏高/异常"},   # 红区中段
    {"id": 6, "angle": -25, "zone": "red",    "label": "偏高/异常"},   # 红区深处
]


# ──────────────────────────────────────────────
# Step 2：图像变换（模拟真实环境）
# ──────────────────────────────────────────────

def adjust_brightness(img, factor):
    """亮度调整 factor: 0.3=很暗, 1.0=正常, 1.8=很亮"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 2] = np.clip(hsv[:, :, 2] * factor, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def add_noise(img, sigma=20):
    noise = np.random.normal(0, sigma, img.shape).astype(np.int16)
    return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def rotate_image(img, angle_deg):
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle_deg, 1.0)
    return cv2.warpAffine(img, M, (w, h), borderValue=(220, 220, 220))


def perspective_warp(img, strength=0.08):
    h, w = img.shape[:2]
    s = strength
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([
        [w * random.uniform(0, s),   h * random.uniform(0, s)],
        [w * (1 - random.uniform(0, s)), h * random.uniform(0, s)],
        [w * (1 - random.uniform(0, s)), h * (1 - random.uniform(0, s))],
        [w * random.uniform(0, s),   h * (1 - random.uniform(0, s))],
    ])
    M = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(img, M, (w, h), borderValue=(220, 220, 220))


def simulate_camera_blur(img, ksize=5):
    return cv2.GaussianBlur(img, (ksize, ksize), 1.5)


TRANSFORMS = [
    ("正常",       lambda img: img.copy()),
    ("变暗(-50%)", lambda img: adjust_brightness(img, 0.5)),
    ("变亮(+80%)", lambda img: adjust_brightness(img, 1.8)),
    ("顺时针旋转15°", lambda img: rotate_image(img, 15)),
    ("逆时针旋转20°", lambda img: rotate_image(img, -20)),
    ("透视变形",    lambda img: perspective_warp(img, 0.07)),
    ("加噪声",     lambda img: add_noise(img, 25)),
    ("轻微模糊",   lambda img: simulate_camera_blur(img, 5)),
    ("暗+旋转",    lambda img: rotate_image(adjust_brightness(img, 0.55), 12)),
    ("亮+透视",    lambda img: perspective_warp(adjust_brightness(img, 1.6), 0.06)),
]


# ──────────────────────────────────────────────
# Step 3：运行测试
# ──────────────────────────────────────────────

def run_test(source_image_path=None):
    print("=" * 60)
    print("仪表盘识别系统 — 自动测试报告")
    print("=" * 60)

    total = 0
    correct = 0
    failed_cases = []

    for cfg in GAUGE_CONFIGS:
        gid = cfg["id"]
        gt_zone = cfg["zone"]
        gt_label = cfg["label"]

        # 生成/加载基础图像
        if source_image_path and os.path.exists(source_image_path):
            base_img = cv2.imread(source_image_path)
        else:
            base_img = generate_gauge_image(cfg["angle"], gt_zone)

        print(f"\n── 仪表盘 #{gid}  真值：{gt_label} ──")

        gauge_correct = 0
        gauge_total = len(TRANSFORMS)

        for t_name, t_fn in TRANSFORMS:
            aug_img = t_fn(base_img)
            # 保存临时文件供 detect_gauge 读取
            tmp_path = os.path.join(OUT_DIR, f"gauge{gid}_{t_name.replace('/', '_')}.jpg")
            debug_path = os.path.join(OUT_DIR, f"gauge{gid}_{t_name.replace('/', '_')}_debug.jpg")
            cv2.imwrite(tmp_path, aug_img)

            res = detect_gauge(tmp_path, debug=True, debug_out=debug_path)
            total += 1

            if res is None:
                print(f"  [{t_name:12s}] ❌ 识别失败（读取错误）")
                failed_cases.append((gid, t_name, gt_zone, "ERROR"))
                continue

            ok = (res["color"] == gt_zone)
            if ok:
                correct += 1
                gauge_correct += 1
                mark = "✅"
            else:
                failed_cases.append((gid, t_name, gt_zone, res["color"]))
                mark = "❌"

            print(f"  [{t_name:14s}] {mark}  识别：{res['level']}({res['status']})  "
                  f"颜色={res['color']:<8s} 角度={res['angle']}")

        print(f"  → 该仪表盘准确率：{gauge_correct}/{gauge_total} = "
              f"{gauge_correct/gauge_total*100:.0f}%")

    print("\n" + "=" * 60)
    print(f"总体准确率：{correct}/{total} = {correct/total*100:.1f}%")
    print("=" * 60)

    if failed_cases:
        print("\n失败案例汇总：")
        for gid, t_name, gt, pred in failed_cases:
            print(f"  仪表盘#{gid} [{t_name}]  真值:{gt} → 预测:{pred}")
    else:
        print("\n🎉 所有测试用例全部通过！")

    print(f"\n调试图像已保存至：{OUT_DIR}/")
    return correct / total


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else None
    acc = run_test(src)
    print(f"\n最终准确率：{acc*100:.1f}%")
