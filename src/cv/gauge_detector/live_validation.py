#!/usr/bin/env python3
"""Validation helpers for live gauge recognition outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


VALID_COLORS = {"yellow", "green", "red"}


@dataclass(frozen=True)
class GaugeValidationConfig:
    min_color_ratio: float = 0.04
    min_direction_score: int = 100
    min_zone_pixels: int = 300
    max_zone_fraction: float = 0.62
    min_direction_margin: float = 2.0


def is_valid_gauge_result(
    result: Optional[Dict[str, Any]],
    config: GaugeValidationConfig,
) -> Tuple[bool, str]:
    if result is None:
        return False, "no_result"
    if not result.get("circle_detected"):
        return False, "no_hough_circle"
    if result.get("angle") is None:
        return False, "no_needle_angle"

    level = result.get("level")
    status = result.get("status")
    color = result.get("color")
    if not level or not status or color not in VALID_COLORS:
        return False, "unknown_state"

    coverage = result.get("color_coverage") or {}
    color_ratio = float(coverage.get("ratio") or 0.0)
    if color_ratio < config.min_color_ratio:
        return False, f"low_color_ratio={color_ratio:.4f}"

    zone_counts = coverage.get("counts") or {}
    weak_zones = [
        color
        for color in ("yellow", "green", "red")
        if int(zone_counts.get(color) or 0) < config.min_zone_pixels
    ]
    if weak_zones:
        return False, f"weak_color_zones={weak_zones}"

    color_total = max(sum(int(v or 0) for v in zone_counts.values()), 1)
    max_fraction = (
        max(int(zone_counts.get(color) or 0) for color in ("yellow", "green", "red"))
        / color_total
    )
    if max_fraction > config.max_zone_fraction:
        return False, f"dominant_color_fraction={max_fraction:.3f}"

    direction_scores = result.get("direction_scores") or {}
    direction_score = int(direction_scores.get(color) or 0)
    if direction_score < config.min_direction_score:
        return False, f"low_direction_score={direction_score}"

    sorted_scores = sorted((int(v or 0) for v in direction_scores.values()), reverse=True)
    second_score = sorted_scores[1] if len(sorted_scores) > 1 else 0
    if second_score > 0 and direction_score / second_score < config.min_direction_margin:
        return False, f"weak_direction_margin={direction_score}/{second_score}"

    return True, "ok"


def make_status_payload(
    result: Optional[Dict[str, Any]],
    valid: bool,
    reason: str,
    frame_id: str,
    stamp_sec: int,
    stamp_nanosec: int,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "header": {
            "stamp": {
                "sec": int(stamp_sec),
                "nanosec": int(stamp_nanosec),
            },
            "frame_id": frame_id,
        },
        "detected": bool(valid),
        "reason": reason,
        "level": None,
        "status": None,
        "color": None,
        "angle": None,
        "circle_detected": False,
        "color_coverage_ratio": 0.0,
        "zone_counts": {},
        "direction_scores": {},
    }

    if not result:
        return payload

    coverage = result.get("color_coverage") or {}
    payload.update(
        {
            "level": result.get("level"),
            "status": result.get("status"),
            "color": result.get("color"),
            "angle": result.get("angle"),
            "circle_detected": bool(result.get("circle_detected")),
            "color_coverage_ratio": float(coverage.get("ratio") or 0.0),
            "zone_counts": coverage.get("counts") or {},
            "direction_scores": result.get("direction_scores") or {},
        }
    )
    return payload
