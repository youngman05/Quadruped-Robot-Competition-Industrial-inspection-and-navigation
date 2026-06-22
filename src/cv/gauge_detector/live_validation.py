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


class GaugeStabilityTracker:
    """Track consecutive valid gauge states before marking output stable."""

    def __init__(self, required_count: int = 3) -> None:
        self.required_count = max(1, int(required_count))
        self._candidate_key: Optional[Tuple[str, str, str]] = None
        self._candidate_count = 0

    def update(self, result: Optional[Dict[str, Any]], valid: bool) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "stable_detected": False,
            "stable_reason": "invalid_frame",
            "stable_count": 0,
            "stable_required_count": self.required_count,
            "stable_level": None,
            "stable_status": None,
            "stable_color": None,
            "stable_angle": None,
        }

        if not valid or not result:
            self._candidate_key = None
            self._candidate_count = 0
            return payload

        color = result.get("color")
        level = result.get("level")
        status = result.get("status")
        if color not in VALID_COLORS or not level or not status:
            self._candidate_key = None
            self._candidate_count = 0
            payload["stable_reason"] = "unknown_state"
            return payload

        key = (str(color), str(level), str(status))
        if key == self._candidate_key:
            self._candidate_count += 1
        else:
            self._candidate_key = key
            self._candidate_count = 1

        stable = self._candidate_count >= self.required_count
        payload.update(
            {
                "stable_detected": stable,
                "stable_reason": "stable"
                if stable
                else f"warming_up={self._candidate_count}/{self.required_count}",
                "stable_count": self._candidate_count,
                "stable_level": level if stable else None,
                "stable_status": status if stable else None,
                "stable_color": color if stable else None,
                "stable_angle": result.get("angle") if stable else None,
            }
        )
        return payload


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
    stability: Optional[Dict[str, Any]] = None,
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
        "stable_detected": False,
        "stable_reason": "not_evaluated",
        "stable_count": 0,
        "stable_required_count": 0,
        "stable_level": None,
        "stable_status": None,
        "stable_color": None,
        "stable_angle": None,
    }

    if stability:
        payload.update(stability)

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
