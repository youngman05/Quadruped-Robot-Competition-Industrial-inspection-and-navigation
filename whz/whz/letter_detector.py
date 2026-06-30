"""OpenCV A/B/C/D detector based on required real templates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import cv2
import numpy as np


@dataclass
class LetterResult:
    area: str
    score: float
    bbox: Optional[tuple[int, int, int, int]] = None


class LetterDetector:
    """Recognize one large cabinet area letter from a color image."""

    def __init__(
        self,
        template_dir: Path,
        min_score: float = 0.38,
        template_size: int = 96,
    ) -> None:
        self.min_score = float(min_score)
        self.template_size = int(template_size)
        self.templates = self._load_templates(template_dir)

    def detect(self, image: np.ndarray) -> Optional[LetterResult]:
        roi, bbox = self._find_letter_roi(image)
        if roi is None:
            roi = image
            bbox = None

        candidate = self._normalize_letter(roi)
        best_area = ""
        best_score = -1.0

        for area, template in self.templates.items():
            score = float(cv2.matchTemplate(candidate, template, cv2.TM_CCOEFF_NORMED)[0][0])
            if score > best_score:
                best_area = area
                best_score = score

        if best_score < self.min_score:
            return None
        return LetterResult(area=best_area, score=best_score, bbox=bbox)

    def _load_templates(self, template_dir: Path) -> Dict[str, np.ndarray]:
        template_dir = Path(template_dir)
        templates: Dict[str, np.ndarray] = {}
        missing = []

        for area in "ABCD":
            loaded = False
            for suffix in (".png", ".jpg", ".jpeg", ".bmp"):
                path = template_dir / f"{area}{suffix}"
                if not path.exists():
                    continue
                image = cv2.imread(str(path))
                if image is not None:
                    templates[area] = self._normalize_letter(image)
                    loaded = True
                    break
            if not loaded:
                missing.append(area)

        if missing:
            raise FileNotFoundError(
                f"Missing required letter templates in {template_dir}: {', '.join(missing)}"
            )
        return templates

    def _find_letter_roi(self, image: np.ndarray) -> tuple[Optional[np.ndarray], Optional[tuple[int, int, int, int]]]:
        panel_bbox = self._find_white_panel_bbox(image)
        if panel_bbox is not None:
            px, py, pw, ph = panel_bbox
            roi_image = image[py : py + int(ph * 0.58), px : px + pw]
            offset_x = px
            offset_y = py
        else:
            roi_image = image
            offset_x = 0
            offset_y = 0

        gray = cv2.cvtColor(roi_image, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        h, w = gray.shape
        image_area = h * w
        candidates = []
        for contour in contours:
            x, y, cw, ch = cv2.boundingRect(contour)
            area = cw * ch
            if area < image_area * 0.002:
                continue
            if area > image_area * 0.18:
                continue
            if ch < h * 0.10 or cw < w * 0.06:
                continue
            if ch > h * 0.55 or cw > w * 0.45:
                continue
            aspect = cw / max(ch, 1)
            if not 0.25 <= aspect <= 1.4:
                continue
            center_x = x + cw / 2.0
            center_y = y + ch / 2.0
            center_score = 1.0 - abs(center_x - w / 2.0) / max(w / 2.0, 1.0)
            top_score = 1.0 - center_y / max(h, 1)
            score = area * (1.0 + center_score + top_score * 0.5)
            candidates.append((score, x, y, cw, ch))

        if not candidates:
            return None, None

        _, x, y, cw, ch = max(candidates, key=lambda item: item[0])
        pad = int(max(cw, ch) * 0.18)
        x0 = max(0, x - pad) + offset_x
        y0 = max(0, y - pad) + offset_y
        x1 = min(w, x + cw + pad) + offset_x
        y1 = min(h, y + ch + pad) + offset_y
        return image[y0:y1, x0:x1], (x0, y0, x1, y1)

    def _find_white_panel_bbox(self, image: np.ndarray) -> Optional[tuple[int, int, int, int]]:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([0, 0, 135]), np.array([180, 85, 255]))
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        candidates = []
        for contour in contours:
            area = cv2.contourArea(contour)
            x, y, width, height = cv2.boundingRect(contour)
            if area < image.shape[0] * image.shape[1] * 0.01:
                continue
            if width < image.shape[1] * 0.08 or height < image.shape[0] * 0.15:
                continue
            candidates.append((area, x, y, width, height))

        if not candidates:
            return None

        _, x, y, width, height = max(candidates, key=lambda item: item[0])
        return x, y, width, height

    def _normalize_letter(self, image: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        ys, xs = np.where(binary > 0)
        if len(xs) > 0 and len(ys) > 0:
            x0, x1 = int(xs.min()), int(xs.max())
            y0, y1 = int(ys.min()), int(ys.max())
            binary = binary[y0 : y1 + 1, x0 : x1 + 1]

        size = self.template_size
        canvas = np.zeros((size, size), dtype=np.uint8)
        bh, bw = binary.shape[:2]
        scale = min((size * 0.82) / max(bw, 1), (size * 0.82) / max(bh, 1))
        nw = max(1, int(bw * scale))
        nh = max(1, int(bh * scale))
        resized = cv2.resize(binary, (nw, nh), interpolation=cv2.INTER_AREA)
        x = (size - nw) // 2
        y = (size - nh) // 2
        canvas[y : y + nh, x : x + nw] = resized
        return canvas
