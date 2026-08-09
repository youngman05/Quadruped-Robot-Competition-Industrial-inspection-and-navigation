#!/usr/bin/env python3
# coding: utf-8

"""YOLO detection result -> camera-frame 3D target point.

This module only does geometry and JSON parsing. It does not depend on ROS2,
RealSense, NumPy, or the arm IK/execution stack.
"""

from __future__ import print_function

import json


class YoloTargetError(ValueError):
    """YOLO result is missing the data needed for 3D back-projection."""


class CameraIntrinsics(object):
    """Pinhole camera intrinsics for pixel -> camera optical coordinate."""

    def __init__(self, fx=617.0, fy=617.0, cx=320.0, cy=240.0):
        self.fx = float(fx)
        self.fy = float(fy)
        self.cx = float(cx)
        self.cy = float(cy)
        if abs(self.fx) <= 1e-12 or abs(self.fy) <= 1e-12:
            raise YoloTargetError("camera fx/fy must be non-zero")

    def to_dict(self):
        return {
            "fx": self.fx,
            "fy": self.fy,
            "cx": self.cx,
            "cy": self.cy,
        }


class TargetCameraPoint(object):
    """Selected YOLO target and its 3D point in camera optical frame."""

    def __init__(
        self,
        point,
        pixel,
        distance_m,
        class_name=None,
        class_id=None,
        confidence=None,
        detection=None,
        frame_id=None,
    ):
        self.point = tuple(float(v) for v in point)
        self.pixel = tuple(float(v) for v in pixel)
        self.distance_m = float(distance_m)
        self.class_name = class_name
        self.class_id = class_id
        self.confidence = confidence
        self.detection = detection or {}
        self.frame_id = frame_id

    def to_dict(self):
        return {
            "point_camera": {
                "x": self.point[0],
                "y": self.point[1],
                "z": self.point[2],
            },
            "pixel": {
                "u": self.pixel[0],
                "v": self.pixel[1],
            },
            "distance_m": self.distance_m,
            "class_name": self.class_name,
            "class_id": self.class_id,
            "confidence": self.confidence,
            "frame_id": self.frame_id,
        }


def parse_yolo_payload(payload):
    """Return a YOLO payload dict from a dict, JSON string, or bytes."""

    if isinstance(payload, dict):
        return payload
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise YoloTargetError("invalid YOLO JSON: {}".format(exc)) from None
    raise YoloTargetError("payload must be dict, JSON string, or bytes")


def choose_detection(
    payload,
    target_classes=("red",),
    target_class_ids=None,
    min_confidence=0.0,
):
    """Select the best matching detection from a YOLO payload.

    The competition YOLO protocol is: 0=red, 1=green, 2=obstacle.
    """

    data = parse_yolo_payload(payload)
    detections = data.get("detections")
    if not isinstance(detections, list):
        raise YoloTargetError("YOLO payload must contain a detections list")

    target_classes = set(str(name) for name in (target_classes or ()))
    target_class_ids = set(int(v) for v in (target_class_ids or ()))
    min_confidence = float(min_confidence)

    candidates = []
    for detection in detections:
        if not isinstance(detection, dict):
            continue
        class_name = str(detection.get("class_name", ""))
        class_id = detection.get("class_id")
        try:
            class_id_int = int(class_id)
        except (TypeError, ValueError):
            class_id_int = None

        name_ok = not target_classes or class_name in target_classes
        id_ok = bool(target_class_ids) and class_id_int in target_class_ids
        if not (name_ok or id_ok):
            continue

        confidence = detection.get("confidence", 0.0)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < min_confidence:
            continue
        candidates.append((confidence, detection))

    if not candidates:
        raise YoloTargetError(
            "no detection matched classes={} class_ids={} min_confidence={}".format(
                sorted(target_classes),
                sorted(target_class_ids),
                min_confidence,
            )
        )

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def detection_to_camera_point(detection, intrinsics=None, frame_id=None):
    """Back-project one YOLO detection into the camera optical frame.

    Coordinate convention:
      +X = image right, +Y = image down, +Z = camera forward, unit = meters.
    """

    if not isinstance(detection, dict):
        raise YoloTargetError("detection must be a dict")

    intrinsics = intrinsics or CameraIntrinsics()
    center = detection.get("center")
    if not isinstance(center, dict):
        raise YoloTargetError("detection is missing center {x, y}")
    try:
        u = float(center["x"])
        v = float(center["y"])
    except (KeyError, TypeError, ValueError):
        raise YoloTargetError("detection center must contain numeric x/y") from None

    distance = detection.get("distance_m")
    if distance is None:
        raise YoloTargetError(
            "detection is missing distance_m; YOLO node must run with aligned depth"
        )
    try:
        z = float(distance)
    except (TypeError, ValueError):
        raise YoloTargetError("distance_m must be numeric") from None
    if z <= 0.0:
        raise YoloTargetError("distance_m must be positive")

    x = (u - intrinsics.cx) * z / intrinsics.fx
    y = (v - intrinsics.cy) * z / intrinsics.fy

    return TargetCameraPoint(
        point=(x, y, z),
        pixel=(u, v),
        distance_m=z,
        class_name=detection.get("class_name"),
        class_id=detection.get("class_id"),
        confidence=detection.get("confidence"),
        detection=detection,
        frame_id=frame_id,
    )


def yolo_payload_to_camera_point(
    payload,
    intrinsics=None,
    target_classes=("red",),
    target_class_ids=None,
    min_confidence=0.0,
):
    """Select a YOLO target and return its camera-frame 3D point."""

    data = parse_yolo_payload(payload)
    detection = choose_detection(
        data,
        target_classes=target_classes,
        target_class_ids=target_class_ids,
        min_confidence=min_confidence,
    )
    header = data.get("header") or {}
    return detection_to_camera_point(
        detection,
        intrinsics=intrinsics,
        frame_id=header.get("frame_id"),
    )
