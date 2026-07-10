"""
Host-side reader for YOLO detection results from Docker.

The Docker container writes detection JSON to a shared directory.
This module reads it — usable from any host-side Python code (ROS2 Foxy).

Usage:
    from cv.gauge_detector.docker_reader import DockerDetectionReader

    reader = DockerDetectionReader()
    result = reader.read()   # DetectionResult or None if stale / no update
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class LetterInfo:
    label: str
    conf: float
    bbox: Tuple[int, int, int, int]


@dataclass
class GaugeInfo:
    color: str
    conf: float
    bbox: Tuple[int, int, int, int]


@dataclass
class DetectionResult:
    ts: str = ""
    inference_ms: float = 0.0
    letters: List[LetterInfo] = field(default_factory=list)
    gauges: List[GaugeInfo] = field(default_factory=list)

    @property
    def best_letter(self) -> Optional[LetterInfo]:
        return max(self.letters, key=lambda d: d.conf) if self.letters else None

    @property
    def best_gauge(self) -> Optional[GaugeInfo]:
        return max(self.gauges, key=lambda d: d.conf) if self.gauges else None

    @property
    def ok(self) -> bool:
        return self.best_letter is not None


class DockerDetectionReader:
    """Reads YOLO detection JSON from Docker shared directory."""

    def __init__(
        self,
        json_path: str = None,
        max_age_sec: float = 2.0,
    ):
        if json_path is None:
            json_path = os.path.expanduser(
                "~/workspaces/isaac_ros-dev/camera_frames/latest_detection.json"
            )
        self._path = Path(json_path)
        self._max_age = float(max_age_sec)
        self._last_ts = ""
        self._last_read = 0.0

    def read(self) -> Optional[DetectionResult]:
        """Read latest detection. Returns None if file is missing or stale."""
        if not self._path.exists():
            return None

        try:
            mtime = self._path.stat().st_mtime
            if mtime <= self._last_read:
                return None  # already read this version
            self._last_read = mtime

            with open(self._path, "r") as f:
                data = json.load(f)

            if data.get("ts") == self._last_ts:
                return None  # same timestamp, no new data
            self._last_ts = data.get("ts", "")

            # Check staleness
            if time.time() - mtime > self._max_age:
                return None

            result = DetectionResult(
                ts=data.get("ts", ""),
                inference_ms=data.get("inference_ms", 0),
            )

            for item in data.get("letters", []):
                result.letters.append(LetterInfo(
                    label=item["label"],
                    conf=item["conf"],
                    bbox=tuple(item["bbox"]),
                ))

            for item in data.get("gauges", []):
                result.gauges.append(GaugeInfo(
                    color=item["color"],
                    conf=item["conf"],
                    bbox=tuple(item["bbox"]),
                ))

            return result

        except (json.JSONDecodeError, KeyError, OSError):
            return None
