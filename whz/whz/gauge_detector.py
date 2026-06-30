"""OpenCV gauge state detector for yellow/green/red dial regions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional

import cv2
import numpy as np


COLOR_RANGES = {
    "yellow": [(np.array([15, 20, 60]), np.array([45, 255, 255]))],
    "green": [(np.array([36, 50, 50]), np.array([90, 255, 255]))],
    "red": [
        (np.array([0, 70, 70]), np.array([15, 255, 255])),
        (np.array([160, 70, 70]), np.array([180, 255, 255])),
    ],
}

STATUS_MAP = {
    "yellow": ("low", "偏低", "异常"),
    "green": ("middle", "正常", "正常"),
    "red": ("high", "偏高", "异常"),
}

MIN_DIRECTION_SCORE = 30
MIN_DIRECTION_TOTAL = 60
MIN_CONFIDENCE = 0.55
MIN_SCORE_MARGIN = 1.35
DEPTH_MIN_M = 0.15
DEPTH_MAX_M = 6.0
DEPTH_BIN_WIDTH_M = 0.08
DEPTH_NEAR_MARGIN_M = 0.12
DEPTH_FAR_MARGIN_M = 0.35
MIN_DEPTH_PLANE_AREA_RATIO = 0.005


@dataclass
class GaugeResult:
    state_key: str
    level: str
    status: str
    color: str
    angle: Optional[float]
    circle_detected: bool
    confidence: float
    center_x: int
    center_y: int
    radius: int


def detect_gauge(image: np.ndarray, depth_image: Optional[np.ndarray] = None) -> Optional[GaugeResult]:
    if image is None or image.size == 0:
        return None

    img, scale = _resize_if_needed(image)
    depth = _resize_depth(depth_image, img.shape[:2]) if depth_image is not None else None
    plane_mask = _nearest_plane_mask(depth) if depth is not None else None
    raw_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    processed = _preprocess(img)
    hsv = cv2.cvtColor(processed, cv2.COLOR_BGR2HSV)
    cx, cy, radius, circle_detected = _find_circle(processed, hsv, raw_hsv, plane_mask)
    angle = _find_needle_angle_hough(processed, cx, cy, radius)
    if angle is None:
        angle = _find_needle_angle_dark(processed, cx, cy, radius)

    if angle is None:
        return None

    scores = _direction_color_scores(angle, cx, cy, radius, hsv)
    if not _valid_direction_scores(scores):
        return None

    color = max(scores, key=scores.get)
    confidence = scores[color] / max(sum(scores.values()), 1)

    if color not in STATUS_MAP:
        return None

    state_key, level, status = STATUS_MAP[color]
    return GaugeResult(
        state_key=state_key,
        level=level,
        status=status,
        color=color,
        angle=round(angle, 1) if angle is not None else None,
        circle_detected=circle_detected,
        confidence=float(confidence),
        center_x=int(round(cx / scale)),
        center_y=int(round(cy / scale)),
        radius=int(round(radius / scale)),
    )


def _valid_direction_scores(scores: Dict[str, int]) -> bool:
    if not scores:
        return False

    sorted_scores = sorted((int(value) for value in scores.values()), reverse=True)
    best = sorted_scores[0]
    second = sorted_scores[1] if len(sorted_scores) > 1 else 0
    total = sum(sorted_scores)
    confidence = best / max(total, 1)
    margin = best / max(second, 1)

    if total < MIN_DIRECTION_TOTAL:
        return False
    if best < MIN_DIRECTION_SCORE:
        return False
    if confidence < MIN_CONFIDENCE:
        return False
    if second > 0 and margin < MIN_SCORE_MARGIN:
        return False
    return True


def _resize_if_needed(image: np.ndarray, max_side: int = 900) -> tuple[np.ndarray, float]:
    h, w = image.shape[:2]
    if max(h, w) <= max_side:
        return image.copy(), 1.0
    scale = max_side / max(h, w)
    return cv2.resize(image, (int(w * scale), int(h * scale))), scale


def _resize_depth(depth: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    if depth is None or depth.size == 0:
        return depth
    target_h, target_w = shape
    if depth.shape[:2] == (target_h, target_w):
        return depth.astype(np.float32, copy=True)
    return cv2.resize(
        depth.astype(np.float32),
        (target_w, target_h),
        interpolation=cv2.INTER_NEAREST,
    )


def _nearest_plane_mask(depth: np.ndarray) -> Optional[np.ndarray]:
    valid = np.isfinite(depth) & (depth >= DEPTH_MIN_M) & (depth <= DEPTH_MAX_M)
    valid_values = depth[valid]
    if valid_values.size < 200:
        return None

    bins = np.arange(DEPTH_MIN_M, DEPTH_MAX_M + DEPTH_BIN_WIDTH_M, DEPTH_BIN_WIDTH_M)
    hist, edges = np.histogram(valid_values, bins=bins)
    min_bin_count = max(200, int(valid_values.size * 0.005))
    plane_depth = None
    for idx, count in enumerate(hist):
        if count >= min_bin_count:
            plane_depth = float((edges[idx] + edges[idx + 1]) * 0.5)
            break
    if plane_depth is None:
        plane_depth = float(np.percentile(valid_values, 5))

    mask = (
        valid
        & (depth >= plane_depth - DEPTH_NEAR_MARGIN_M)
        & (depth <= plane_depth + DEPTH_FAR_MARGIN_M)
    )
    mask = mask.astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < depth.shape[0] * depth.shape[1] * MIN_DEPTH_PLANE_AREA_RATIO:
        return None

    plane_mask = np.zeros(depth.shape[:2], dtype=np.uint8)
    cv2.drawContours(plane_mask, [largest], -1, 255, -1)
    return plane_mask


def _preprocess(image: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    l_channel = clahe.apply(l_channel)
    enhanced = cv2.cvtColor(cv2.merge([l_channel, a_channel, b_channel]), cv2.COLOR_LAB2BGR)
    denoised = cv2.bilateralFilter(enhanced, d=9, sigmaColor=75, sigmaSpace=75)
    return cv2.GaussianBlur(denoised, (3, 3), 0.8)


def _color_mask(hsv: np.ndarray, color: str) -> np.ndarray:
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lower, upper in COLOR_RANGES[color]:
        mask |= cv2.inRange(hsv, lower, upper)
    open_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, open_kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE, dilate_kernel, iterations=1)
    return mask


def _find_circle(
    image: np.ndarray,
    hsv: np.ndarray,
    raw_hsv: np.ndarray,
    plane_mask: Optional[np.ndarray],
) -> tuple[int, int, int, bool]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (9, 9), 2)
    h, w = gray.shape
    panel_bbox = _find_white_panel_bbox(raw_hsv)
    search_bbox = _mask_bbox(plane_mask) if plane_mask is not None else panel_bbox
    if search_bbox is None:
        search_bbox = (0, 0, w, h)

    rx, ry, rw, rh = _expand_bbox(search_bbox, w, h, margin=12)
    roi_gray = gray[ry : ry + rh, rx : rx + rw]
    if roi_gray.size == 0:
        return w // 2, h // 2, int(min(h, w) * 0.18), False

    candidates = []
    for param2 in (10, 12, 14, 16, 18, 22, 26, 30, 34):
        circles = cv2.HoughCircles(
            roi_gray,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=max(8, min(rh, rw) * 0.08),
            param1=60,
            param2=param2,
            minRadius=0,
            maxRadius=max(1, int(min(rh, rw) * 0.5)),
        )
        if circles is not None:
            for circle in np.uint16(np.around(circles))[0]:
                candidates.append((int(circle[0]) + rx, int(circle[1]) + ry, int(circle[2])))

    if not candidates:
        return w // 2, h // 2, int(min(h, w) * 0.18), False

    def score_circle(circle) -> float:
        cx, cy, radius = int(circle[0]), int(circle[1]), int(circle[2])
        color_pixels, color_density = _ring_color_score(hsv, cx, cy, radius)
        score = color_pixels * 2.0 + color_density * 3000.0

        if plane_mask is not None:
            overlap = _circle_mask_overlap(plane_mask, cx, cy, radius)
            if overlap <= 0.35:
                return score - 100000.0
            return score + overlap * 5000.0

        if panel_bbox is None:
            center_x, center_y = w / 2, h / 2
            return score - math.hypot(cx - center_x, cy - center_y) * 0.02

        px, py, pw, ph = panel_bbox
        inside_panel_gauge_area = (
            px <= cx <= px + pw
            and py + ph * 0.45 <= cy <= py + ph + radius * 0.35
        )
        if not inside_panel_gauge_area:
            return score - 100000.0

        expected_x = px + pw * 0.5
        expected_y = py + ph * 0.78
        expected_radius = pw * 0.33
        geometry_score = (
            3000.0
            - abs(cx - expected_x) * 25.0
            - abs(cy - expected_y) * 10.0
            - abs(radius - expected_radius) * 15.0
        )
        return score + 5000.0 + geometry_score

    best = max(candidates, key=score_circle)
    return int(best[0]), int(best[1]), int(best[2]), True


def _mask_bbox(mask: Optional[np.ndarray]) -> Optional[tuple[int, int, int, int]]:
    if mask is None or mask.size == 0:
        return None
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    return cv2.boundingRect(contour)


def _expand_bbox(
    bbox: tuple[int, int, int, int],
    image_width: int,
    image_height: int,
    margin: int,
) -> tuple[int, int, int, int]:
    x, y, width, height = bbox
    x0 = max(0, x - margin)
    y0 = max(0, y - margin)
    x1 = min(image_width, x + width + margin)
    y1 = min(image_height, y + height + margin)
    return x0, y0, max(1, x1 - x0), max(1, y1 - y0)


def _find_white_panel_bbox(raw_hsv: np.ndarray) -> Optional[tuple[int, int, int, int]]:
    mask = cv2.inRange(raw_hsv, np.array([0, 0, 135]), np.array([180, 85, 255]))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        x, y, width, height = cv2.boundingRect(contour)
        if area < 3000 or width < 80 or height < 120:
            continue
        candidates.append((area, x, y, width, height))

    if not candidates:
        return None

    _, x, y, width, height = max(candidates, key=lambda item: item[0])
    return x, y, width, height


def _ring_color_total(hsv: np.ndarray, cx: int, cy: int, radius: int) -> int:
    return _ring_color_score(hsv, cx, cy, radius)[0]


def _ring_color_score(hsv: np.ndarray, cx: int, cy: int, radius: int) -> tuple[int, float]:
    ring_mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    cv2.circle(ring_mask, (cx, cy), int(radius * 1.10), 255, -1)
    cv2.circle(ring_mask, (cx, cy), int(radius * 0.35), 0, -1)
    color_pixels = sum(
        cv2.countNonZero(cv2.bitwise_and(_color_mask(hsv, color), ring_mask))
        for color in ("yellow", "green", "red")
    )
    ring_pixels = cv2.countNonZero(ring_mask)
    return int(color_pixels), color_pixels / max(ring_pixels, 1)


def _circle_mask_overlap(mask: np.ndarray, cx: int, cy: int, radius: int) -> float:
    circle_mask = np.zeros(mask.shape[:2], dtype=np.uint8)
    cv2.circle(circle_mask, (cx, cy), int(radius), 255, -1)
    circle_pixels = cv2.countNonZero(circle_mask)
    if circle_pixels <= 0:
        return 0.0
    overlap_pixels = cv2.countNonZero(cv2.bitwise_and(mask, circle_mask))
    return overlap_pixels / circle_pixels


def _find_needle_angle_hough(image: np.ndarray, cx: int, cy: int, radius: int) -> Optional[float]:
    h, w = image.shape[:2]
    roi_mask = np.zeros((h, w), dtype=np.uint8)
    cv2.circle(roi_mask, (cx, cy), int(radius * 0.90), 255, -1)
    cv2.circle(roi_mask, (cx, cy), int(radius * 0.10), 0, -1)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.bitwise_and(cv2.Canny(gray, 40, 120), roi_mask)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=25,
        minLineLength=int(radius * 0.30),
        maxLineGap=int(radius * 0.15),
    )
    if lines is None:
        return None

    best_angle = None
    best_score = -1.0
    for line in lines:
        x1, y1, x2, y2 = line[0]
        length = math.hypot(x2 - x1, y2 - y1)
        dist = abs((y2 - y1) * cx - (x2 - x1) * cy + x2 * y1 - y2 * x1) / (length + 1e-6)
        if dist > radius * 0.25:
            continue
        d1 = math.hypot(x1 - cx, y1 - cy)
        d2 = math.hypot(x2 - cx, y2 - cy)
        tip_x, tip_y = (x1, y1) if d1 > d2 else (x2, y2)
        angle = math.degrees(math.atan2(-(tip_y - cy), tip_x - cx))
        score = length - dist * 2
        if score > best_score:
            best_score = score
            best_angle = angle
    return best_angle


def _find_needle_angle_dark(image: np.ndarray, cx: int, cy: int, radius: int) -> Optional[float]:
    h, w = image.shape[:2]
    roi_mask = np.zeros((h, w), dtype=np.uint8)
    cv2.circle(roi_mask, (cx, cy), int(radius * 0.88), 255, -1)
    cv2.circle(roi_mask, (cx, cy), int(radius * 0.13), 0, -1)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    roi_pixels = gray[roi_mask > 0]
    if len(roi_pixels) == 0:
        return None
    threshold = int(np.percentile(roi_pixels, 15))
    dark_mask = cv2.bitwise_and((gray < threshold).astype(np.uint8) * 255, roi_mask)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    dark_mask = cv2.morphologyEx(dark_mask, cv2.MORPH_OPEN, kernel, iterations=2)
    ys, xs = np.where(dark_mask > 0)
    if len(xs) < 8:
        return None
    dists = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
    selected = (dists > radius * 0.38) & (dists < radius * 0.91)
    xs_selected = xs[selected] if np.any(selected) else xs
    ys_selected = ys[selected] if np.any(selected) else ys
    return math.degrees(math.atan2(-(float(np.mean(ys_selected)) - cy), float(np.mean(xs_selected)) - cx))


def _direction_color_scores(angle: float, cx: int, cy: int, radius: int, hsv: np.ndarray) -> Dict[str, int]:
    sample_mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for delta in np.linspace(-22, 22, 30):
        a = math.radians(angle + delta)
        for radius_fraction in np.linspace(0.65, 0.93, 10):
            r = radius * radius_fraction
            px = int(cx + r * math.cos(a))
            py = int(cy - r * math.sin(a))
            if 0 <= px < hsv.shape[1] and 0 <= py < hsv.shape[0]:
                cv2.circle(sample_mask, (px, py), 4, 255, -1)

    return {
        color: cv2.countNonZero(cv2.bitwise_and(_color_mask(hsv, color), sample_mask))
        for color in ("yellow", "red", "green")
    }


def _fallback_color(hsv: np.ndarray, cx: int, cy: int, radius: int) -> tuple[str, float]:
    ring_mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    cv2.circle(ring_mask, (cx, cy), int(radius * 0.93), 255, -1)
    cv2.circle(ring_mask, (cx, cy), int(radius * 0.65), 0, -1)
    counts = {
        color: cv2.countNonZero(cv2.bitwise_and(_color_mask(hsv, color), ring_mask))
        for color in ("yellow", "red", "green")
    }
    color = max(counts, key=counts.get)
    return color, counts[color] / max(sum(counts.values()), 1)
