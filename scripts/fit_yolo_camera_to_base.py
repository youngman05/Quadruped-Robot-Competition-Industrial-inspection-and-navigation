#!/usr/bin/env python3
"""Fit ``base_link <- camera_link`` from raw-D455 UDP recorder CSV files.

For calibration, invoke ``scripts/cv/record_yolo_xyz_udp.py`` with the
surveyed *base_link* target point as its ``--expected-*`` values.  Its measured
columns remain camera-link observations; this utility fits the static TF.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import numpy as np
import yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True, help="recorder CSV; repeat for each target")
    parser.add_argument("--report", type=Path, required=True, help="YAML fit report")
    return parser.parse_args()


def quaternion_xyzw(rotation: np.ndarray) -> list[float]:
    trace = float(np.trace(rotation))
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        values = [(rotation[2, 1] - rotation[1, 2]) / scale, (rotation[0, 2] - rotation[2, 0]) / scale,
                  (rotation[1, 0] - rotation[0, 1]) / scale, 0.25 * scale]
    else:
        index = int(np.argmax(np.diag(rotation)))
        if index == 0:
            scale = math.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2]) * 2.0
            values = [0.25 * scale, (rotation[0, 1] + rotation[1, 0]) / scale,
                      (rotation[0, 2] + rotation[2, 0]) / scale, (rotation[2, 1] - rotation[1, 2]) / scale]
        elif index == 1:
            scale = math.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2]) * 2.0
            values = [(rotation[0, 1] + rotation[1, 0]) / scale, 0.25 * scale,
                      (rotation[1, 2] + rotation[2, 1]) / scale, (rotation[0, 2] - rotation[2, 0]) / scale]
        else:
            scale = math.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1]) * 2.0
            values = [(rotation[0, 2] + rotation[2, 0]) / scale, (rotation[1, 2] + rotation[2, 1]) / scale,
                      0.25 * scale, (rotation[1, 0] - rotation[0, 1]) / scale]
    quaternion = np.asarray(values, dtype=np.float64)
    quaternion /= np.linalg.norm(quaternion)
    if quaternion[3] < 0:
        quaternion *= -1.0
    return [float(value) for value in quaternion]


def load_point(path: Path) -> tuple[np.ndarray, np.ndarray, int]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"No samples in {path}")
    fields = [f"{prefix}_{axis}_m" for prefix in ("measured", "expected") for axis in "xyz"]
    if any(field not in rows[0] for field in fields):
        raise ValueError(f"{path} is not a record_yolo_xyz_udp.py CSV")
    camera = np.asarray([[float(row[f"measured_{axis}_m"]) for axis in "xyz"] for row in rows])
    base = np.asarray([[float(row[f"expected_{axis}_m"]) for axis in "xyz"] for row in rows])
    if not np.all(np.isfinite(camera)) or not np.all(np.isfinite(base)):
        raise ValueError(f"Non-finite coordinate in {path}")
    if np.max(np.ptp(base, axis=0)) > 1e-6:
        raise ValueError(f"Truth coordinate changes within {path}")
    return np.median(camera, axis=0), base[0], len(rows)


def fit(camera: np.ndarray, base: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if camera.shape != base.shape or camera.shape[0] < 3:
        raise ValueError("Need at least three paired points")
    camera_centered = camera - camera.mean(axis=0)
    base_centered = base - base.mean(axis=0)
    if np.linalg.matrix_rank(camera_centered) < 2 or np.linalg.matrix_rank(base_centered) < 2:
        raise ValueError("Targets must span a two-dimensional area")
    left, _singular, right_t = np.linalg.svd(base_centered.T @ camera_centered)
    rotation = left @ right_t
    if np.linalg.det(rotation) < 0:
        left[:, -1] *= -1.0
        rotation = left @ right_t
    return rotation, base.mean(axis=0) - rotation @ camera.mean(axis=0)


def main() -> int:
    args = parse_args()
    points = [load_point(path) for path in args.input]
    camera = np.asarray([point[0] for point in points])
    base = np.asarray([point[1] for point in points])
    rotation, translation = fit(camera, base)
    predicted = camera @ rotation.T + translation
    residuals = predicted - base
    norms = np.linalg.norm(residuals, axis=1)
    report = {
        "schema_version": 1,
        "parent_frame": "base_link",
        "child_frame": "camera_link",
        "translation_m": [float(value) for value in translation],
        "rotation_xyzw": quaternion_xyzw(rotation),
        "fit_rmse_m": float(math.sqrt(np.mean(norms ** 2))),
        "fit_max_error_m": float(np.max(norms)),
        "points": [{"source_csv": str(path), "samples": count,
                    "camera_link_m": [float(value) for value in observation],
                    "base_link_truth_m": [float(value) for value in truth],
                    "fit_error_norm_m": float(error)}
                   for path, (observation, truth, count), error in zip(args.input, points, norms)],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(yaml.safe_dump(report, sort_keys=False), encoding="utf-8")
    print(yaml.safe_dump(report, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
