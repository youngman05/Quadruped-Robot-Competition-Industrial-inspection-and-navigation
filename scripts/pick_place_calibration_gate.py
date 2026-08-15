#!/usr/bin/env python3
"""Fail-closed validation for the full pick/place route calibration files."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List

import yaml


class CalibrationGateError(ValueError):
    pass


def _node_params(path: Path, node_name: str) -> Dict[str, Any]:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        params = document[node_name]["ros__parameters"]
    except (OSError, TypeError, KeyError, yaml.YAMLError) as exc:
        raise CalibrationGateError(
            f"cannot load {node_name} parameters from {path}: {exc}"
        ) from exc
    if not isinstance(params, dict):
        raise CalibrationGateError(f"{node_name} ros__parameters must be a mapping")
    return params


def _finite_vector(value: Any, size: int, name: str) -> List[float]:
    if not isinstance(value, list) or len(value) != size:
        raise CalibrationGateError(f"{name} must contain {size} values")
    try:
        result = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise CalibrationGateError(f"{name} must be numeric") from exc
    if not all(math.isfinite(item) for item in result):
        raise CalibrationGateError(f"{name} must be finite")
    return result


def _unique_non_negative_ids(values: Any, name: str) -> List[int]:
    if (
        not isinstance(values, list)
        or not values
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in values
        )
        or len(set(values)) != len(values)
    ):
        raise CalibrationGateError(
            f"{name} must contain unique non-negative integers"
        )
    return list(values)


def _require_true(params: Dict[str, Any], keys: Iterable[str]) -> None:
    for key in keys:
        if params.get(key) is not True:
            raise CalibrationGateError(f"arm parameter {key} must be true")


def validate_calibration(
    task_path: Path,
    arm_path: Path,
    tag_ids_json: str,
    tag_size_text: str,
) -> Dict[str, Any]:
    task = _node_params(task_path, "task_manager_node")
    arm = _node_params(arm_path, "arm_motion_node")

    try:
        tag_ids = _unique_non_negative_ids(
            json.loads(tag_ids_json), "AprilTag IDs"
        )
        tag_size = float(tag_size_text)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise CalibrationGateError(f"invalid AprilTag calibration: {exc}") from exc
    if not math.isfinite(tag_size) or tag_size <= 0.0:
        raise CalibrationGateError("AprilTag size must be positive")

    red_ids = _unique_non_negative_ids(task.get("pick_red_tag_ids"), "pick_red_tag_ids")
    if not set(red_ids).issubset(tag_ids):
        raise CalibrationGateError("pick_red_tag_ids must be a subset of AprilTag IDs")

    try:
        i2_targets = json.loads(task.get("pick_i2_targets_json", "{}"))
    except (json.JSONDecodeError, TypeError) as exc:
        raise CalibrationGateError("pick_i2_targets_json is invalid") from exc
    if not isinstance(i2_targets, dict):
        raise CalibrationGateError("pick_i2_targets_json must be an object")
    missing = [tag_id for tag_id in tag_ids if str(tag_id) not in i2_targets]
    if missing:
        raise CalibrationGateError(
            f"missing independently calibrated I2 targets: {missing}"
        )
    normalized_targets = [
        tuple(
            round(value, 6)
            for value in _finite_vector(
                i2_targets[str(tag_id)], 3, f"I2 target {tag_id}"
            )
        )
        for tag_id in tag_ids
    ]
    if len(set(normalized_targets)) != len(normalized_targets):
        raise CalibrationGateError("I2 targets are duplicated")

    grasp_target = _finite_vector(
        task.get("grasp_target_arm_base"), 3, "grasp_target_arm_base"
    )
    if grasp_target[2] <= 0.0:
        raise CalibrationGateError("grasp_target_arm_base z must be positive")
    try:
        place_distance = float(task.get("place_target_distance_m", 0.0))
    except (TypeError, ValueError) as exc:
        raise CalibrationGateError("place_target_distance_m must be numeric") from exc
    if not math.isfinite(place_distance) or place_distance <= 0.0:
        raise CalibrationGateError("place_target_distance_m is not calibrated")

    _require_true(
        arm,
        (
            "enable_motion",
            "transform_calibrated",
            "grasp_reference_configured",
            "place_target_configured",
            "require_tf_in_preflight",
        ),
    )
    grasp_reference = _finite_vector(
        arm.get("grasp_reference_arm_base"), 2, "grasp_reference_arm_base"
    )
    place_reference = _finite_vector(
        arm.get("place_reference_grasp_arm"), 3, "place_reference_grasp_arm"
    )
    if math.sqrt(sum(value * value for value in place_reference)) <= 1e-6:
        raise CalibrationGateError("place_reference_grasp_arm is not calibrated")

    try:
        tolerance = float(arm.get("grasp_reference_xy_tolerance_m", 0.0))
        z_min = float(arm.get("grasp_z_min_m", 0.0))
        z_max = float(arm.get("grasp_z_max_m", 0.0))
    except (TypeError, ValueError) as exc:
        raise CalibrationGateError("arm grasp limits must be numeric") from exc
    if not all(math.isfinite(value) for value in (tolerance, z_min, z_max)):
        raise CalibrationGateError("arm grasp limits must be finite")
    if tolerance <= 0.0 or z_min <= 0.0 or z_max < z_min:
        raise CalibrationGateError("arm grasp limits are invalid")
    if any(
        abs(grasp_target[index] - grasp_reference[index]) > tolerance
        for index in (0, 1)
    ):
        raise CalibrationGateError(
            "TaskManager grasp target is outside the arm XY reference tolerance"
        )
    if not z_min <= grasp_target[2] <= z_max:
        raise CalibrationGateError("TaskManager grasp target is outside the arm z range")

    return {
        "tag_ids": tag_ids,
        "tag_size_m": tag_size,
        "i2_target_count": len(normalized_targets),
        "red_tag_ids": red_ids,
        "grasp_target_arm_base": grasp_target,
        "place_target_distance_m": place_distance,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-params", required=True, type=Path)
    parser.add_argument("--arm-params", required=True, type=Path)
    parser.add_argument("--tag-ids", required=True)
    parser.add_argument("--tag-size-m", required=True)
    args = parser.parse_args()
    try:
        result = validate_calibration(
            args.task_params,
            args.arm_params,
            args.tag_ids,
            args.tag_size_m,
        )
    except CalibrationGateError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
