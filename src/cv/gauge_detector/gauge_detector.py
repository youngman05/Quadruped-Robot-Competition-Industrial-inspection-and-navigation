#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仪表盘状态识别脚本 v2
功能：识别仪表盘指针所在区域（黄=偏低/异常，绿=正常，红=偏高/异常）
算法：霍夫线段检测 + 颜色区域采样，双重备份策略
适用：2026年中国高校智能机器人创意大赛 四足大型组
"""

import cv2
import numpy as np
import math
import sys
import os


# ────────────────────────────────────────────────────────────────
# HSV 颜色范围（覆盖打印/屏幕显示常见偏差）
# ────────────────────────────────────────────────────────────────
COLOR_RANGES = {
    "yellow": [
        (np.array([15, 80,  80]),  np.array([38, 255, 255])),
    ],
    "green": [
        (np.array([36, 50,  50]),  np.array([90, 255, 255])),
    ],
    "red": [
        (np.array([0,  70,  70]),  np.array([15, 255, 255])),
        (np.array([160, 70, 70]),  np.array([180, 255, 255])),
    ],
}

STATUS_MAP = {
    "yellow": ("偏低", "异常"),
    "green":  ("正常", "正常"),
    "red":    ("偏高", "异常"),
}

COLOR_PRIORITY = ["yellow", "red", "green"]   # 异常优先确认


def preprocess(image: np.ndarray) -> np.ndarray:
    """CLAHE增强 + 双边滤波去噪 + 轻度高斯平滑"""
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    enhanced = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
    # 双边滤波保留颜色边界同时去噪
    denoised = cv2.bilateralFilter(enhanced, d=9, sigmaColor=75, sigmaSpace=75)
    # 轻度高斯，平滑边缘便于霍夫线检测
    return cv2.GaussianBlur(denoised, (3, 3), 0.8)


def build_color_mask(hsv: np.ndarray, color: str,
                      open_k: int = 3, dilate_k: int = 5) -> np.ndarray:
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lo, hi in COLOR_RANGES[color]:
        mask |= cv2.inRange(hsv, lo, hi)
    ek_o = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_k, open_k))
    ek_d = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_k, dilate_k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,   ek_o, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE, ek_d, iterations=1)
    return mask


def find_gauge_circle(image: np.ndarray):
    """HoughCircles 定位表盘圆"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (9, 9), 2)
    h, w = gray.shape
    min_r = int(min(h, w) * 0.25)
    max_r = int(min(h, w) * 0.52)
    circles = cv2.HoughCircles(
        gray, cv2.HOUGH_GRADIENT,
        dp=1.2, minDist=min(h, w) * 0.4,
        param1=60, param2=30,
        minRadius=min_r, maxRadius=max_r,
    )
    if circles is not None:
        circles = np.uint16(np.around(circles))
        cx0, cy0 = w / 2, h / 2
        best = min(circles[0], key=lambda c: (c[0]-cx0)**2 + (c[1]-cy0)**2)
        return int(best[0]), int(best[1]), int(best[2]), True
    r = int(min(h, w) * 0.42)
    return w // 2, h // 2, r, False


def find_needle_angle_hough(image: np.ndarray, cx: int, cy: int, radius: int):
    """
    主算法：霍夫线段检测
    在表盘ROI内提取暗色细线，找到过圆心（或接近）的最长线段，
    计算其指向针尖方向的角度。
    """
    h, w = image.shape[:2]
    # 圆形ROI，排除外圈金属框和中心轴帽
    roi_mask = np.zeros((h, w), dtype=np.uint8)
    cv2.circle(roi_mask, (cx, cy), int(radius * 0.90), 255, -1)
    cv2.circle(roi_mask, (cx, cy), int(radius * 0.10), 0,   -1)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # 方法A：边缘检测 + 霍夫线
    edges = cv2.Canny(gray, 40, 120)
    edges = cv2.bitwise_and(edges, roi_mask)

    lines = cv2.HoughLinesP(
        edges,
        rho=1, theta=np.pi / 180,
        threshold=25,
        minLineLength=int(radius * 0.30),
        maxLineGap=int(radius * 0.15),
    )

    best_angle = None
    best_score = -1

    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            length = math.hypot(x2 - x1, y2 - y1)
            # 线段到圆心的最短距离
            dist = abs((y2-y1)*cx - (x2-x1)*cy + x2*y1 - y2*x1) / (length + 1e-6)
            if dist > radius * 0.25:
                continue  # 不过圆心，跳过

            # 角度：选择远离圆心的端点方向（针尖方向）
            d1 = math.hypot(x1 - cx, y1 - cy)
            d2 = math.hypot(x2 - cx, y2 - cy)
            if d1 > d2:
                tip_x, tip_y = x1, y1
            else:
                tip_x, tip_y = x2, y2

            angle = math.degrees(math.atan2(-(tip_y - cy), tip_x - cx))
            score = length - dist * 2  # 越长、越近圆心越好
            if score > best_score:
                best_score = score
                best_angle = angle

    return best_angle


def find_needle_angle_dark(image: np.ndarray, cx: int, cy: int, radius: int):
    """
    备用算法：暗色像素质心法
    提取表盘内最暗的像素，用距圆心最远的那批像素的质心确定方向。
    """
    h, w = image.shape[:2]
    roi_mask = np.zeros((h, w), dtype=np.uint8)
    cv2.circle(roi_mask, (cx, cy), int(radius * 0.88), 255, -1)
    cv2.circle(roi_mask, (cx, cy), int(radius * 0.13), 0,   -1)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # 只在ROI内取最暗前15%像素
    roi_pixels = gray[roi_mask > 0]
    if len(roi_pixels) == 0:
        return None
    threshold = int(np.percentile(roi_pixels, 15))
    dark_mask = (gray < threshold).astype(np.uint8) * 255
    dark_mask = cv2.bitwise_and(dark_mask, roi_mask)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    dark_mask = cv2.morphologyEx(dark_mask, cv2.MORPH_OPEN, kernel, iterations=2)

    ys, xs = np.where(dark_mask > 0)
    if len(xs) < 8:
        return None

    dists = np.sqrt((xs - cx)**2 + (ys - cy)**2)
    # 只用距圆心 40%~90% 半径的像素（针杆区域）
    far = (dists > radius * 0.38) & (dists < radius * 0.91)
    xs_f = xs[far]
    ys_f = ys[far]
    if len(xs_f) < 5:
        xs_f, ys_f = xs, ys

    tip_x = float(np.mean(xs_f))
    tip_y = float(np.mean(ys_f))
    return math.degrees(math.atan2(-(tip_y - cy), tip_x - cx))


def angle_to_color_zone(angle: float, cx: int, cy: int, radius: int,
                         hsv: np.ndarray, sweep_deg: float = 20.0) -> str:
    """
    在角度方向附近 ±sweep_deg 范围的刻度弧带上采样颜色。
    采样半径：65%~93% R（彩色弧段所在位置）。
    """
    sample_mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for da in np.linspace(-sweep_deg, sweep_deg, 30):
        a = math.radians(angle + da)
        for r_frac in np.linspace(0.65, 0.93, 10):
            r = radius * r_frac
            px = int(cx + r * math.cos(a))
            py = int(cy - r * math.sin(a))
            if 0 <= px < hsv.shape[1] and 0 <= py < hsv.shape[0]:
                cv2.circle(sample_mask, (px, py), 4, 255, -1)

    best_color, best_n = None, 0
    for color in COLOR_PRIORITY:
        m = build_color_mask(hsv, color)
        n = cv2.countNonZero(cv2.bitwise_and(m, sample_mask))
        if n > best_n:
            best_n, best_color = n, color
    return best_color if best_n > 0 else None


def color_zone_scores(angle: float, cx: int, cy: int, radius: int,
                      hsv: np.ndarray, sweep_deg: float = 20.0) -> dict:
    """Return HSV color hit counts near the needle direction."""
    sample_mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for da in np.linspace(-sweep_deg, sweep_deg, 30):
        a = math.radians(angle + da)
        for r_frac in np.linspace(0.65, 0.93, 10):
            r = radius * r_frac
            px = int(cx + r * math.cos(a))
            py = int(cy - r * math.sin(a))
            if 0 <= px < hsv.shape[1] and 0 <= py < hsv.shape[0]:
                cv2.circle(sample_mask, (px, py), 4, 255, -1)

    scores = {}
    for color in COLOR_PRIORITY:
        m = build_color_mask(hsv, color)
        scores[color] = cv2.countNonZero(cv2.bitwise_and(m, sample_mask))
    return scores


def fallback_color_ratio(cx: int, cy: int, radius: int,
                          hsv: np.ndarray, angle=None) -> str:
    """
    备用：仅统计表盘内三色像素比，选最多的。
    若 angle 已知则对该方向附近 ±30° 区域给予 3× 权重。
    """
    ring_mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    cv2.circle(ring_mask, (cx, cy), int(radius * 0.93), 255, -1)
    cv2.circle(ring_mask, (cx, cy), int(radius * 0.65), 0,   -1)

    counts = {}
    for color in COLOR_PRIORITY:
        m = build_color_mask(hsv, color)
        counts[color] = cv2.countNonZero(cv2.bitwise_and(m, ring_mask))

    if angle is not None:
        # 权重加成
        dir_mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        for da in np.linspace(-30, 30, 25):
            a = math.radians(angle + da)
            for r_frac in np.linspace(0.65, 0.93, 8):
                r = radius * r_frac
                px = int(cx + r * math.cos(a))
                py = int(cy - r * math.sin(a))
                if 0 <= px < hsv.shape[1] and 0 <= py < hsv.shape[0]:
                    cv2.circle(dir_mask, (px, py), 5, 255, -1)
        for color in COLOR_PRIORITY:
            m = build_color_mask(hsv, color)
            bonus = cv2.countNonZero(cv2.bitwise_and(m, dir_mask))
            counts[color] += bonus * 2  # 方向区域权重加倍

    return max(counts, key=counts.get)


def gauge_color_coverage(cx: int, cy: int, radius: int, hsv: np.ndarray) -> dict:
    """Count colored pixels in the gauge ring used as confidence evidence."""
    ring_mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    cv2.circle(ring_mask, (cx, cy), int(radius * 0.93), 255, -1)
    cv2.circle(ring_mask, (cx, cy), int(radius * 0.65), 0, -1)

    ring_area = max(cv2.countNonZero(ring_mask), 1)
    counts = {}
    for color in COLOR_PRIORITY:
        m = build_color_mask(hsv, color)
        counts[color] = cv2.countNonZero(cv2.bitwise_and(m, ring_mask))

    total = sum(counts.values())
    return {
        "counts": counts,
        "total": total,
        "ring_area": ring_area,
        "ratio": total / ring_area,
    }


def detect_gauge(image_path: str, debug: bool = False, debug_out: str = None) -> dict:
    """
    主识别函数
    返回: {"status": str, "level": str, "color": str, "angle": float|None}
    """
    img_orig = cv2.imread(image_path)
    if img_orig is None:
        print(f"[错误] 无法读取图像：{image_path}")
        return None

    h, w = img_orig.shape[:2]
    if max(h, w) > 900:
        scale = 900 / max(h, w)
        img_orig = cv2.resize(img_orig, (int(w * scale), int(h * scale)))

    img = preprocess(img_orig.copy())
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    cx, cy, radius, circle_detected = find_gauge_circle(img)
    coverage = gauge_color_coverage(cx, cy, radius, hsv)

    # ── 指针角度检测（优先霍夫线，备用暗色质心）──
    angle = find_needle_angle_hough(img, cx, cy, radius)
    if angle is None:
        angle = find_needle_angle_dark(img, cx, cy, radius)

    # ── 颜色区域判断 ──
    if angle is not None:
        direction_scores = color_zone_scores(angle, cx, cy, radius, hsv, sweep_deg=22)
        zone_color = max(direction_scores, key=direction_scores.get)
        if direction_scores[zone_color] <= 0:
            zone_color = None
        if zone_color is None:
            zone_color = fallback_color_ratio(cx, cy, radius, hsv, angle)
    else:
        direction_scores = {}
        zone_color = fallback_color_ratio(cx, cy, radius, hsv, None)

    level, status = STATUS_MAP.get(zone_color, ("未知", "未知"))

    result = {
        "status": status, "level": level,
        "color": zone_color,
        "angle": round(angle, 1) if angle is not None else None,
        "circle": (cx, cy, radius),
        "circle_detected": circle_detected,
        "color_coverage": coverage,
        "direction_scores": direction_scores,
    }

    # ── 调试可视化 ──
    if debug:
        vis = img_orig.copy()
        cv2.circle(vis, (cx, cy), radius, (200, 180, 0), 2)
        cv2.circle(vis, (cx, cy), 5, (0, 0, 255), -1)
        if angle is not None:
            ex = int(cx + radius * 0.82 * math.cos(math.radians(angle)))
            ey = int(cy - radius * 0.82 * math.sin(math.radians(angle)))
            cv2.arrowedLine(vis, (cx, cy), (ex, ey), (0, 255, 255), 2, tipLength=0.2)
        # 彩色掩码叠加
        color_vis = {"yellow": (0,220,220), "green": (0,200,0), "red": (0,0,220)}
        for c in ("yellow","green","red"):
            m = build_color_mask(hsv, c)
            ov = vis.copy(); ov[m>0] = color_vis[c]
            vis = cv2.addWeighted(vis, 0.72, ov, 0.28, 0)
        lc = {"yellow":(0,210,255), "green":(0,230,0), "red":(30,30,255)}.get(zone_color, (180,180,180))
        cv2.putText(vis, f"{level}({status})", (10,38), cv2.FONT_HERSHEY_SIMPLEX, 1.0, lc, 2)
        if angle is not None:
            cv2.putText(vis, f"angle={angle:.1f}", (10,68), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200,200,200), 1)
        if debug_out:
            cv2.imwrite(debug_out, vis)

    return result


def print_result(name: str, result: dict):
    color_cn = {"yellow":"黄色区域","green":"绿色区域","red":"红色区域"}.get(result["color"],"未知")
    print(f"【{name}】指针位于{color_cn} → {result['level']}，状态：{result['status']}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 gauge_detector.py <图像路径> [--debug]")
        sys.exit(1)
    img_path = sys.argv[1]
    debug_mode = "--debug" in sys.argv
    debug_path = (os.path.splitext(img_path)[0] + "_debug.jpg") if debug_mode else None
    res = detect_gauge(img_path, debug=debug_mode, debug_out=debug_path)
    if res:
        print_result(os.path.basename(img_path), res)
        if debug_mode and debug_path:
            print(f"调试图像已保存：{debug_path}")
