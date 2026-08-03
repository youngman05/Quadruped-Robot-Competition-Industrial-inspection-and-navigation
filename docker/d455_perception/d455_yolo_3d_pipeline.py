"""Shared YOLO segmentation and raw-depth 3-D pipeline.

This module intentionally has no ROS dependency. The live validation script
and the production ROS node use the same model invocation and geometry path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

import cv2
import numpy as np

from d455_yolo_3d_core import (
    CameraIntrinsics,
    RigidTransform,
    estimate_mask_3d_from_raw_depth,
)


def install_torchvision_nms_fallback() -> None:
    """Install the Jetson-compatible NMS fallback used by yolo_live_test.py."""

    import torch
    import torchvision.ops

    def pure_nms(boxes, scores, iou_thres):
        if len(boxes) == 0:
            return torch.zeros(0, dtype=torch.int64)
        boxes_np = boxes.cpu().numpy()
        scores_np = scores.cpu().numpy()
        x1, y1 = boxes_np[:, 0], boxes_np[:, 1]
        x2, y2 = boxes_np[:, 2], boxes_np[:, 3]
        areas = (x2 - x1) * (y2 - y1)
        order = scores_np.argsort()[::-1]
        keep = []
        while order.size > 0:
            index = order[0]
            keep.append(index)
            xx1 = np.maximum(x1[index], x1[order[1:]])
            yy1 = np.maximum(y1[index], y1[order[1:]])
            xx2 = np.minimum(x2[index], x2[order[1:]])
            yy2 = np.minimum(y2[index], y2[order[1:]])
            width = np.maximum(0.0, xx2 - xx1)
            height = np.maximum(0.0, yy2 - yy1)
            intersection = width * height
            iou = intersection / (areas[index] + areas[order[1:]] - intersection + 1e-9)
            order = order[np.where(iou <= iou_thres)[0] + 1]
        return torch.tensor(keep, dtype=torch.int64)

    torchvision.ops.nms = pure_nms


@dataclass(frozen=True)
class Yolo3DConfig:
    confidence: float = 0.5
    iou: float = 0.5
    image_size: int = 640
    device: str = "0"
    min_depth_m: float = 0.2
    max_depth_m: float = 4.0
    trim_fraction: float = 0.1
    mask_erosion_iterations: int = 2
    min_valid_pixels: int = 20
    min_valid_ratio: float = 0.6


@dataclass(frozen=True)
class Detection3D:
    class_id: int
    class_name: str
    confidence: float
    bbox: List[int]
    center_px: List[int]
    mask_area_px: int
    depth_m: Optional[float]
    depth_valid_ratio: float
    position_valid: bool
    position_m: Optional[List[float]]
    mask: np.ndarray

    def packet_dict(self) -> Dict[str, Any]:
        return {
            "class_id": self.class_id,
            "class_name": self.class_name,
            "confidence": self.confidence,
            "bbox": self.bbox,
            "center_px": self.center_px,
            "mask_area_px": self.mask_area_px,
            "depth_m": self.depth_m,
            "depth_valid_ratio": self.depth_valid_ratio,
            "position_valid": self.position_valid,
            "position_m": self.position_m,
        }


class Yolo3DPipeline:
    """Run the competition segmentation model and estimate camera-frame XYZ."""

    def __init__(self, model_path: str, config: Yolo3DConfig) -> None:
        install_torchvision_nms_fallback()
        from ultralytics import YOLO

        self._config = config
        self._model = YOLO(model_path)
        self.class_names = {
            int(class_id): str(name)
            for class_id, name in self._model.names.items()
        }

    def warmup(self, image_shape: tuple[int, int, int]) -> None:
        """Initialize GPU execution before live frames arrive."""

        image = np.zeros(image_shape, dtype=np.uint8)
        self._model(
            image,
            conf=self._config.confidence,
            iou=self._config.iou,
            imgsz=self._config.image_size,
            device=self._config.device,
            retina_masks=True,
            verbose=False,
        )

    def infer(
        self,
        color_bgr: np.ndarray,
        raw_depth_mm: np.ndarray,
        depth_intrinsics: CameraIntrinsics,
        color_intrinsics: CameraIntrinsics,
        depth_to_color: RigidTransform,
        color_to_output: RigidTransform,
    ) -> List[Detection3D]:
        """Infer segmentation and return detections in the requested output frame."""

        result = self._model(
            color_bgr,
            conf=self._config.confidence,
            iou=self._config.iou,
            imgsz=self._config.image_size,
            device=self._config.device,
            retina_masks=True,
            verbose=False,
        )[0]
        if result.boxes is None or len(result.boxes) == 0 or result.masks is None:
            return []

        masks = result.masks.data.cpu().numpy().astype(bool)
        boxes = result.boxes
        detections: List[Detection3D] = []
        for index, mask in enumerate(masks):
            mask = self._resize_mask(mask, color_bgr.shape[:2])
            class_id = int(boxes.cls[index])
            confidence = float(boxes.conf[index])
            bbox = [int(value) for value in boxes.xyxy[index].cpu().numpy()]
            estimate = estimate_mask_3d_from_raw_depth(
                raw_depth_mm,
                mask,
                depth_intrinsics,
                color_intrinsics,
                depth_to_color,
                min_depth_m=self._config.min_depth_m,
                max_depth_m=self._config.max_depth_m,
                trim_fraction=self._config.trim_fraction,
                erosion_iterations=self._config.mask_erosion_iterations,
                min_valid_pixels=self._config.min_valid_pixels,
            )
            position_valid = estimate.valid and estimate.valid_ratio >= self._config.min_valid_ratio
            position_m: Optional[List[float]] = None
            if position_valid and estimate.position_m is not None:
                output_point = color_to_output.apply(np.array([estimate.position_m]))[0]
                position_m = [float(value) for value in output_point]

            detections.append(Detection3D(
                class_id=class_id,
                class_name=self.class_names.get(class_id, f"cls{class_id}"),
                confidence=confidence,
                bbox=bbox,
                center_px=[estimate.center_px[0], estimate.center_px[1]],
                mask_area_px=estimate.mask_area_px,
                depth_m=estimate.depth_m,
                depth_valid_ratio=estimate.valid_ratio,
                position_valid=position_valid,
                position_m=position_m,
                mask=mask,
            ))
        return detections

    @staticmethod
    def _resize_mask(mask: np.ndarray, color_shape: tuple[int, int]) -> np.ndarray:
        height, width = color_shape
        if mask.shape == (height, width):
            return mask
        return cv2.resize(
            mask.astype(np.uint8),
            (width, height),
            interpolation=cv2.INTER_NEAREST,
        ).astype(bool)
