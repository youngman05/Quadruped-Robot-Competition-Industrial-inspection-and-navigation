"""YOLO detector for spatially paired cabinet letters and gauges."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Mapping, Optional, Sequence, Tuple

import numpy as np


BBox = Tuple[int, int, int, int]
LETTER_CLASSES = frozenset("ABCD")
GAUGE_COLORS = frozenset(("green", "red", "yellow"))
DEFAULT_IMAGE_SIZE = 960
DEFAULT_CONFIDENCE_THRESHOLD = 0.25
DEFAULT_LETTER_CROP_IMAGE_SIZE = 320
DEFAULT_LETTER_CONFIDENCE_THRESHOLD = 0.15


@dataclass(frozen=True)
class LetterDetection:
    letter: str
    confidence: float
    bbox: BBox


@dataclass(frozen=True)
class GaugeDetection:
    color: str
    confidence: float
    bbox: BBox


@dataclass(frozen=True)
class PairedDetection:
    letter: LetterDetection
    gauge: GaugeDetection
    score: float
    horizontal_offset_ratio: float
    vertical_gap_ratio: float


@dataclass
class DetectionResult:
    letters: List[LetterDetection] = field(default_factory=list)
    gauges: List[GaugeDetection] = field(default_factory=list)
    pair: Optional[PairedDetection] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.pair is not None and self.error is None


class YOLODetector:
    """Load one YOLO model and return one unambiguous letter/gauge pair."""

    def __init__(
        self,
        model_path: Path,
        device: str = "0",
        image_size: int = DEFAULT_IMAGE_SIZE,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        letter_crop_image_size: int = DEFAULT_LETTER_CROP_IMAGE_SIZE,
        letter_confidence_threshold: float = DEFAULT_LETTER_CONFIDENCE_THRESHOLD,
        iou_threshold: float = 0.50,
        max_horizontal_offset_ratio: float = 0.75,
        max_vertical_gap_ratio: float = 2.50,
        min_pair_score_margin: float = 0.12,
        model_factory: Optional[Callable[[str], object]] = None,
    ) -> None:
        self.model_path = Path(model_path).expanduser().resolve()
        if not self.model_path.is_file():
            raise FileNotFoundError("YOLO model not found: %s" % self.model_path)

        self.device = str(device).strip()
        self.image_size = int(image_size)
        self.confidence_threshold = float(confidence_threshold)
        self.letter_crop_image_size = int(letter_crop_image_size)
        self.letter_confidence_threshold = float(letter_confidence_threshold)
        self.iou_threshold = float(iou_threshold)
        self.max_horizontal_offset_ratio = float(max_horizontal_offset_ratio)
        self.max_vertical_gap_ratio = float(max_vertical_gap_ratio)
        self.min_pair_score_margin = float(min_pair_score_margin)

        if model_factory is None:
            _install_jetson_nms_workaround()
            from ultralytics import YOLO

            model_factory = YOLO

        self._model = model_factory(str(self.model_path))
        self._names = getattr(self._model, "names", {})
        self._warmup_done = False
        self._warmup()

    @property
    def warmup_done(self) -> bool:
        return self._warmup_done

    def _warmup(self) -> None:
        if self._warmup_done:
            return
        dummy = np.zeros((self.image_size, self.image_size, 3), dtype=np.uint8)
        self._predict(dummy)
        self._warmup_done = True

    def _predict(
        self,
        image: np.ndarray,
        image_size: Optional[int] = None,
        confidence_threshold: Optional[float] = None,
    ):
        kwargs = {
            "source": image,
            "verbose": False,
            "imgsz": self.image_size if image_size is None else int(image_size),
            "conf": (
                self.confidence_threshold
                if confidence_threshold is None
                else float(confidence_threshold)
            ),
            "iou": self.iou_threshold,
        }
        if self.device:
            kwargs["device"] = self.device
        return self._model.predict(**kwargs)

    def detect(self, image: np.ndarray) -> DetectionResult:
        if image is None or not isinstance(image, np.ndarray) or image.size == 0:
            return DetectionResult(error="invalid_image")

        results = self._predict(image)
        if not results:
            return DetectionResult(error="empty_model_result")

        full_letters, gauges = self._extract_detections(
            results[0].boxes,
            confidence_threshold=self.confidence_threshold,
        )
        letters = (
            self._detect_gauge_anchored_letters(image, gauges)
            if gauges
            else full_letters
        )

        pair, error = self._select_pair(letters, gauges)
        return DetectionResult(letters=letters, gauges=gauges, pair=pair, error=error)

    def _detect_gauge_anchored_letters(
        self,
        image: np.ndarray,
        gauges: Sequence[GaugeDetection],
    ) -> List[LetterDetection]:
        height, width = image.shape[:2]
        letters: List[LetterDetection] = []
        for gauge in gauges:
            x1, y1, x2, y2 = gauge.bbox
            gauge_width = max(1.0, float(x2 - x1))
            gauge_height = max(1.0, float(y2 - y1))
            center_x = (x1 + x2) / 2.0
            crop_x1 = max(0, int(center_x - 1.25 * gauge_width))
            crop_x2 = min(width, int(center_x + 1.25 * gauge_width))
            crop_y1 = max(0, int(y1 - 1.75 * gauge_height))
            crop_y2 = min(height, int(y1 + 0.10 * gauge_height))
            if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
                continue

            crop = image[crop_y1:crop_y2, crop_x1:crop_x2]
            results = self._predict(
                crop,
                image_size=self.letter_crop_image_size,
                confidence_threshold=self.letter_confidence_threshold,
            )
            if not results:
                continue
            crop_letters, _ = self._extract_detections(
                results[0].boxes,
                confidence_threshold=self.letter_confidence_threshold,
                offset=(crop_x1, crop_y1),
                letters_only=True,
            )
            letters.extend(crop_letters)
        return _deduplicate_letters(letters)

    def _extract_detections(
        self,
        boxes,
        confidence_threshold: float,
        offset: Tuple[int, int] = (0, 0),
        letters_only: bool = False,
    ) -> Tuple[List[LetterDetection], List[GaugeDetection]]:
        letters: List[LetterDetection] = []
        gauges: List[GaugeDetection] = []
        offset_x, offset_y = offset
        for box in boxes:
            class_id = int(_scalar(box.cls[0]))
            confidence = float(_scalar(box.conf[0]))
            if confidence < confidence_threshold:
                continue
            name = self._class_name(class_id)
            local_bbox = _bbox_tuple(box.xyxy[0])
            bbox = (
                local_bbox[0] + offset_x,
                local_bbox[1] + offset_y,
                local_bbox[2] + offset_x,
                local_bbox[3] + offset_y,
            )

            if name in LETTER_CLASSES:
                letters.append(
                    LetterDetection(letter=name, confidence=confidence, bbox=bbox)
                )
            elif not letters_only and name in GAUGE_COLORS:
                gauges.append(
                    GaugeDetection(color=name, confidence=confidence, bbox=bbox)
                )
        return letters, gauges

    def _class_name(self, class_id: int) -> str:
        if isinstance(self._names, Mapping):
            return str(self._names.get(class_id, ""))
        if isinstance(self._names, Sequence) and 0 <= class_id < len(self._names):
            return str(self._names[class_id])
        return ""

    def _select_pair(
        self,
        letters: Sequence[LetterDetection],
        gauges: Sequence[GaugeDetection],
    ) -> Tuple[Optional[PairedDetection], Optional[str]]:
        if not letters:
            return None, "letter_not_detected"
        if not gauges:
            return None, "gauge_not_detected"

        candidates: List[PairedDetection] = []
        for letter in letters:
            for gauge in gauges:
                pair = self._build_pair(letter, gauge)
                if pair is not None:
                    candidates.append(pair)

        if not candidates:
            return None, "no_spatial_pair"

        candidates.sort(key=lambda item: item.score, reverse=True)
        if (
            len(candidates) > 1
            and candidates[0].score - candidates[1].score < self.min_pair_score_margin
        ):
            return None, "ambiguous_spatial_pair"
        return candidates[0], None

    def _build_pair(
        self,
        letter: LetterDetection,
        gauge: GaugeDetection,
    ) -> Optional[PairedDetection]:
        letter_center_x, letter_center_y = _bbox_center(letter.bbox)
        gauge_center_x, gauge_center_y = _bbox_center(gauge.bbox)
        gauge_width = max(1.0, float(gauge.bbox[2] - gauge.bbox[0]))
        gauge_height = max(1.0, float(gauge.bbox[3] - gauge.bbox[1]))

        horizontal_offset = abs(letter_center_x - gauge_center_x) / gauge_width
        vertical_gap = (gauge_center_y - letter_center_y) / gauge_height
        if vertical_gap <= 0.0 or vertical_gap > self.max_vertical_gap_ratio:
            return None
        if horizontal_offset > self.max_horizontal_offset_ratio:
            return None

        confidence_score = (letter.confidence + gauge.confidence) / 2.0
        geometry_penalty = horizontal_offset * 0.20 + abs(vertical_gap - 1.0) * 0.05
        score = confidence_score - geometry_penalty
        return PairedDetection(
            letter=letter,
            gauge=gauge,
            score=score,
            horizontal_offset_ratio=horizontal_offset,
            vertical_gap_ratio=vertical_gap,
        )


def _bbox_center(bbox: BBox) -> Tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def _deduplicate_letters(
    letters: Sequence[LetterDetection],
) -> List[LetterDetection]:
    kept: List[LetterDetection] = []
    for letter in sorted(letters, key=lambda item: item.confidence, reverse=True):
        duplicate = any(
            letter.letter == existing.letter
            and _bbox_iou(letter.bbox, existing.bbox) >= 0.50
            for existing in kept
        )
        if not duplicate:
            kept.append(letter)
    return kept


def _bbox_iou(first: BBox, second: BBox) -> float:
    x1 = max(first[0], second[0])
    y1 = max(first[1], second[1])
    x2 = min(first[2], second[2])
    y2 = min(first[3], second[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    first_area = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
    second_area = max(0, second[2] - second[0]) * max(0, second[3] - second[1])
    union = first_area + second_area - intersection
    return float(intersection) / float(union) if union > 0 else 0.0


def _scalar(value) -> float:
    if hasattr(value, "item"):
        return value.item()
    return value


def _bbox_tuple(value) -> BBox:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "tolist"):
        value = value.tolist()
    x1, y1, x2, y2 = value
    return int(x1), int(y1), int(x2), int(y2)


def _install_jetson_nms_workaround() -> None:
    """Use a pure-Torch NMS when Jetson's torchvision C++ NMS is unavailable."""
    import torch
    import torchvision

    def py_nms(boxes, scores, iou_threshold):
        if boxes.numel() == 0:
            return torch.empty((0,), dtype=torch.int64, device=boxes.device)

        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 2]
        y2 = boxes[:, 3]
        areas = (x2 - x1) * (y2 - y1)
        _, order = scores.sort(descending=True)
        keep = []

        while order.numel() > 0:
            index = order[0].item()
            keep.append(index)
            if order.numel() == 1:
                break

            remaining = order[1:]
            xx1 = torch.max(x1[index], x1[remaining])
            yy1 = torch.max(y1[index], y1[remaining])
            xx2 = torch.min(x2[index], x2[remaining])
            yy2 = torch.min(y2[index], y2[remaining])
            width = (xx2 - xx1).clamp(min=0)
            height = (yy2 - yy1).clamp(min=0)
            intersection = width * height
            union = areas[index] + areas[remaining] - intersection
            iou = intersection / union.clamp(min=1e-12)
            order = remaining[(iou <= iou_threshold).nonzero(as_tuple=False).squeeze(1)]

        return torch.tensor(keep, dtype=torch.int64, device=boxes.device)

    torchvision.ops.nms = py_nms
