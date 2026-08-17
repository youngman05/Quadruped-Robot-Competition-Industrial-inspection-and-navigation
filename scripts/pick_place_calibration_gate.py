#!/usr/bin/env python3
"""Validate the minimal fixed preset used by the competition pick/place route."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping

import yaml


ARM_PRESET = "competition_v1"
MODEL_ID = "gauge-ad-3ed76de7-v1"
CLASS_SCHEMA = "competition-ad-yellow-red-green-v1"


class CalibrationGateError(ValueError):
    pass


def _node_params(path: Path, node_name: str) -> Dict[str, Any]:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        params = document[node_name]["ros__parameters"]
    except (OSError, TypeError, KeyError, yaml.YAMLError) as exc:
        raise CalibrationGateError(
            "cannot load {} parameters from {}: {}".format(node_name, path, exc)
        ) from exc
    if not isinstance(params, dict):
        raise CalibrationGateError(
            "{} ros__parameters must be a mapping".format(node_name)
        )
    return params


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise CalibrationGateError("{} must be boolean".format(name))
    return value


def _finite_float(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CalibrationGateError("{} must be numeric".format(name)) from exc
    if not math.isfinite(result):
        raise CalibrationGateError("{} must be finite".format(name))
    return result


def _positive_float(value: Any, name: str) -> float:
    result = _finite_float(value, name)
    if result <= 0.0:
        raise CalibrationGateError("{} must be positive".format(name))
    return result


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise CalibrationGateError("{} must be a positive integer".format(name))
    return value


def _finite_vector(value: Any, size: int, name: str) -> List[float]:
    if not isinstance(value, list) or len(value) != size:
        raise CalibrationGateError("{} must contain {} values".format(name, size))
    return [_finite_float(item, name) for item in value]


def _tag_ids(value: Any) -> List[int]:
    if not isinstance(value, list):
        raise CalibrationGateError("pick_red_tag_ids must be a list")
    if any(
        not isinstance(item, int) or isinstance(item, bool) or item < 0
        for item in value
    ):
        raise CalibrationGateError(
            "pick_red_tag_ids must contain non-negative integers"
        )
    if len(value) != 2 or len(set(value)) != 2:
        raise CalibrationGateError(
            "pick_red_tag_ids must contain exactly two unique IDs"
        )
    return list(value)


def _i2_targets(
    params: Mapping[str, Any],
    tag_ids: List[int],
    required: bool,
) -> Dict[str, List[float]]:
    try:
        value = json.loads(str(params.get("pick_i2_targets_json", "{}")))
    except json.JSONDecodeError as exc:
        raise CalibrationGateError("pick_i2_targets_json is invalid JSON") from exc
    if not isinstance(value, dict):
        raise CalibrationGateError("pick_i2_targets_json must be an object")
    expected = {str(tag_id) for tag_id in tag_ids}
    if required and set(value) != expected:
        raise CalibrationGateError(
            "I2 target keys must exactly match pick_red_tag_ids"
        )
    if not required and value:
        raise CalibrationGateError(
            "disabled I2 alignment must not retain active I2 targets"
        )
    normalized: Dict[str, List[float]] = {}
    for tag_id in tag_ids if required else []:
        vector = _finite_vector(value[str(tag_id)], 3, "I2 target {}".format(tag_id))
        if not -math.pi <= vector[2] <= math.pi:
            raise CalibrationGateError(
                "I2 target {} yaw must be within [-pi, pi]".format(tag_id)
            )
        normalized[str(tag_id)] = vector
    return normalized


def _zone_order(value: Any) -> List[str]:
    if not isinstance(value, list):
        raise CalibrationGateError("abnormal_zone_fallback_order must be a list")
    normalized = [str(item).strip().upper() for item in value]
    if len(normalized) != 4 or set(normalized) != set("ABCD"):
        raise CalibrationGateError(
            "abnormal_zone_fallback_order must be a permutation of A/B/C/D"
        )
    return normalized


def validate_calibration(task_path: Path, arm_path: Path) -> Dict[str, Any]:
    task = _node_params(task_path, "task_manager_node")
    arm = _node_params(arm_path, "arm_motion_node")

    task_preset = str(task.get("manipulation_preset", "")).strip()
    arm_preset = str(arm.get("arm_preset", "")).strip()
    if task_preset != ARM_PRESET or arm_preset != ARM_PRESET:
        raise CalibrationGateError(
            "task and arm presets must both be {}".format(ARM_PRESET)
        )
    if task.get("manipulation_model_id") != MODEL_ID:
        raise CalibrationGateError("manipulation_model_id is not accepted")
    if task.get("manipulation_class_schema") != CLASS_SCHEMA:
        raise CalibrationGateError("manipulation_class_schema is not accepted")

    enable_pick_i2 = _bool(
        task.get("enable_pick_i2_alignment"), "enable_pick_i2_alignment"
    )
    enable_place_vision = _bool(
        task.get("enable_place_vision_alignment"),
        "enable_place_vision_alignment",
    )
    if enable_place_vision:
        raise CalibrationGateError(
            "enable_place_vision_alignment must be false: J1 placement alignment is disabled"
        )
    fallback_order = _zone_order(task.get("abnormal_zone_fallback_order"))
    tag_ids = _tag_ids(task.get("pick_red_tag_ids"))
    targets = _i2_targets(task, tag_ids, enable_pick_i2)
    tag_size_m = 0.0
    if enable_pick_i2:
        tag_size_m = _positive_float(
            task.get("apriltag_tag_size_m"), "apriltag_tag_size_m"
        )

    grasp_target = _finite_vector(
        task.get("grasp_target_arm_base"), 3, "grasp_target_arm_base"
    )
    if grasp_target[2] <= 0.0:
        raise CalibrationGateError("grasp_target_arm_base z must be positive")

    place_target_distance_m = _finite_float(
        task.get("place_target_distance_m", 0.0), "place_target_distance_m"
    )

    if arm.get("enable_motion") is not False:
        raise CalibrationGateError(
            "arm preset YAML must keep enable_motion false; launch authorization is separate"
        )
    for key in ("grasp_reference_configured", "place_target_configured"):
        if arm.get(key) is not True:
            raise CalibrationGateError("arm parameter {} must be true".format(key))
    if arm.get("grasp_include_home") is not False:
        raise CalibrationGateError("grasp_include_home must remain false")
    if arm.get("place_include_home") is not False:
        raise CalibrationGateError("place_include_home must remain false")

    grasp_reference = _finite_vector(
        arm.get("grasp_reference_arm_base"), 2, "grasp_reference_arm_base"
    )
    grasp_tolerance = _positive_float(
        arm.get("grasp_reference_xy_tolerance_m"),
        "grasp_reference_xy_tolerance_m",
    )
    grasp_z_min = _positive_float(arm.get("grasp_z_min_m"), "grasp_z_min_m")
    grasp_z_max = _positive_float(arm.get("grasp_z_max_m"), "grasp_z_max_m")
    if grasp_z_max < grasp_z_min:
        raise CalibrationGateError("grasp_z_max_m must be >= grasp_z_min_m")
    if any(
        abs(grasp_target[index] - grasp_reference[index]) > grasp_tolerance
        for index in (0, 1)
    ):
        raise CalibrationGateError(
            "TaskManager grasp target is outside the arm XY preset tolerance"
        )
    if not grasp_z_min <= grasp_target[2] <= grasp_z_max:
        raise CalibrationGateError(
            "TaskManager grasp target is outside the arm preset z range"
        )

    place_reference = _finite_vector(
        arm.get("place_reference_grasp_arm"), 3, "place_reference_grasp_arm"
    )
    if math.sqrt(sum(item * item for item in place_reference)) <= 1e-6:
        raise CalibrationGateError("place_reference_grasp_arm is not configured")

    open_pulse = _positive_int(arm.get("gripper_open_pulse"), "gripper_open_pulse")
    close_pulse = _positive_int(
        arm.get("gripper_close_pulse"), "gripper_close_pulse"
    )
    grasp_open_pulse = _positive_int(
        arm.get("grasp_open_gripper_pulse"), "grasp_open_gripper_pulse"
    )
    if close_pulse in (open_pulse, grasp_open_pulse):
        raise CalibrationGateError("open and close gripper pulses must differ")

    for key in (
        "grasp_pre_distance",
        "grasp_lift_height",
        "grasp_duration_scale",
        "place_descent_m",
        "place_duration_scale",
    ):
        _positive_float(arm.get(key), key)
    for key in (
        "grasp_approach_steps",
        "grasp_approach_step_duration_ms",
        "place_pose_1_duration_ms",
        "place_descent_duration_ms",
    ):
        _positive_int(arm.get(key), key)

    max_sequence_sec = _positive_float(
        arm.get("max_arm_sequence_sec"), "max_arm_sequence_sec"
    )
    service_timeout_sec = _positive_float(
        task.get("arm_service_timeout_sec"), "arm_service_timeout_sec"
    )
    if service_timeout_sec < max_sequence_sec:
        raise CalibrationGateError(
            "arm_service_timeout_sec must be >= max_arm_sequence_sec"
        )

    return {
        "arm_preset": ARM_PRESET,
        "enable_pick_i2_alignment": enable_pick_i2,
        "enable_place_vision_alignment": enable_place_vision,
        "tag_ids": tag_ids,
        "abnormal_zone_fallback_order": fallback_order,
        "tag_size_m": tag_size_m,
        "i2_target_count": len(targets),
        "grasp_target_arm_base": grasp_target,
        "place_target_distance_m": place_target_distance_m,
        "max_arm_sequence_sec": max_sequence_sec,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-params", required=True, type=Path)
    parser.add_argument("--arm-params", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = validate_calibration(args.task_params, args.arm_params)
    except CalibrationGateError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
