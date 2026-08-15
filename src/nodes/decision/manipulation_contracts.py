"""Shared ROS-independent manipulation result contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Tuple


Point3 = Tuple[float, float, float]


@dataclass(frozen=True)
class SegmentResult:
    success: bool
    reason: str
    alignment_success: bool = False
    grasp_success: bool = False
    place_success: bool = False
    outputs: Mapping[str, Any] = field(default_factory=dict)
