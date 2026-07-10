"""YOLO-based cabinet gauge + letter detector.

Replaces the old template-matching detector. Uses the trained YOLOv8 model
from InstanceSegmentation/projects/gauge/model/best.pt.

Classes: A(0), B(1), C(2), D(3), green(4), red(5), yellow(6)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

import torch
import torchvision

# Jetson torchvision NMS workaround
def _py_nms(boxes, scores, iou_threshold):
    if boxes.numel() == 0:
        return torch.empty((0,), dtype=torch.int64, device=boxes.device)
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    _, order = scores.sort(descending=True)
    keep = []
    while order.numel() > 0:
        i = order[0].item(); keep.append(i)
        if order.numel() == 1: break
        xx1 = torch.max(x1[i], x1[order[1:]]); yy1 = torch.max(y1[i], y1[order[1:]])
        xx2 = torch.min(x2[i], x2[order[1:]]); yy2 = torch.min(y2[i], y2[order[1:]])
        w = (xx2 - xx1).clamp(min=0); h = (yy2 - yy1).clamp(min=0)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter)
        order = order[(iou <= iou_threshold).nonzero(as_tuple=False).squeeze(1) + 1]
    return torch.tensor(keep, dtype=torch.int64, device=boxes.device)
torchvision.ops.nms = _py_nms

from ultralytics import YOLO

# ── Dataclasses ──

@dataclass
class LetterDetection:
    letter: str         # A/B/C/D
    confidence: float
    bbox: Tuple[int, int, int, int]  # x1, y1, x2, y2


@dataclass
class GaugeDetection:
    color: str          # green / yellow / red
    confidence: float
    bbox: Tuple[int, int, int, int]


@dataclass
class DetectionResult:
    letters: List[LetterDetection] = field(default_factory=list)
    gauges: List[GaugeDetection] = field(default_factory=list)

    @property
    def best_letter(self) -> Optional[LetterDetection]:
        return max(self.letters, key=lambda d: d.confidence) if self.letters else None

    @property
    def best_gauge(self) -> Optional[GaugeDetection]:
        return max(self.gauges, key=lambda d: d.confidence) if self.gauges else None

    @property
    def ok(self) -> bool:
        return self.best_letter is not None


_GAUGE_COLORS = {"green", "red", "yellow"}

# ── Detector ──

class GaugeDetector:
    """YOLO-based cabinet gauge + letter detector."""

    def __init__(
        self,
        model_path: str = None,
        imgsz: int = 320,
        conf: float = 0.3,
        iou: float = 0.5,
    ):
        if model_path is None:
            model_path = str(
                Path(__file__).resolve().parents[3]
                / "InstanceSegmentation" / "projects" / "gauge" / "model" / "best.pt"
            )
        self._model = YOLO(model_path)
        self._names = list(self._model.names.values())  # ['A','B','C','D','green','red','yellow']
        self._imgsz = int(imgsz)
        self._conf = float(conf)
        self._iou = float(iou)

        # Warmup
        dummy = np.zeros((320, 320, 3), dtype=np.uint8)
        self._model(dummy, verbose=False, imgsz=self._imgsz)

    def detect(self, image: np.ndarray) -> DetectionResult:
        """Run detection on a BGR image. Returns structured result."""
        results = self._model(
            image, verbose=False,
            imgsz=self._imgsz, conf=self._conf, iou=self._iou,
        )[0]

        letters = []
        gauges = []
        for box in results.boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            name = self._names[cls_id]
            x1, y1, x2, y2 = map(int, box.xyxy[0])

            if name in _GAUGE_COLORS:
                gauges.append(GaugeDetection(color=name, confidence=conf, bbox=(x1, y1, x2, y2)))
            else:
                letters.append(LetterDetection(letter=name, confidence=conf, bbox=(x1, y1, x2, y2)))

        return DetectionResult(letters=letters, gauges=gauges)

    def draw(self, image: np.ndarray, result: DetectionResult = None) -> np.ndarray:
        """Draw detection boxes on image. If result is None, runs detection first."""
        if result is None:
            result = self.detect(image)

        colors = {
            "A": (0, 0, 255), "B": (0, 255, 0), "C": (255, 0, 0), "D": (255, 255, 0),
            "green": (0, 200, 0), "red": (0, 0, 200), "yellow": (0, 200, 200),
        }

        for det in result.letters + result.gauges:
            name = det.letter if isinstance(det, LetterDetection) else det.color
            x1, y1, x2, y2 = det.bbox
            color = colors.get(name, (255, 255, 255))
            cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
            label = f"{name} {det.confidence:.2f}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
            cv2.rectangle(image, (x1, y1 - th - 4), (x1 + tw, y1), color, -1)
            cv2.putText(image, label, (x1, y1 - 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        return image


# ── Legacy API (backward-compatible with old gauge_detector) ──

_default_detector: Optional[GaugeDetector] = None


def _get_detector() -> GaugeDetector:
    global _default_detector
    if _default_detector is None:
        _default_detector = GaugeDetector()
    return _default_detector


def detect_gauge(image: np.ndarray, depth_image=None) -> DetectionResult:
    """Legacy API: same signature as old template-matching detect_gauge.
    Returns DetectionResult with .ok, .best_letter, .best_gauge, etc.
    """
    return _get_detector().detect(image)


def draw_detections(image: np.ndarray) -> np.ndarray:
    """Convenience: detect and draw in one call."""
    det = _get_detector()
    return det.draw(image, det.detect(image))
