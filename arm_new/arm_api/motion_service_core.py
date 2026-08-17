"""Pure planning and validation helpers for arm_motion_node services."""

from __future__ import annotations

import math
from typing import Any, Iterable, List, Sequence, Tuple

from .common import MotionStep


Point3 = Tuple[float, float, float]


class MotionServiceValidationError(ValueError):
    """Raised when a service request or its safety configuration is invalid."""


def as_point3(values: Iterable[float], field_name: str) -> Point3:
    """Return three finite coordinates, rejecting malformed service values."""

    try:
        point = tuple(float(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise MotionServiceValidationError(f"{field_name} must contain three numeric values") from exc
    if len(point) != 3 or not all(math.isfinite(value) for value in point):
        raise MotionServiceValidationError(f"{field_name} must contain three finite values")
    return point  # type: ignore[return-value]


def arm_base_to_api(point_arm_base: Sequence[float]) -> Point3:
    """Convert ROS arm_base_link coordinates to the ArmPi API coordinate frame."""

    x_base, y_base, z_base = as_point3(point_arm_base, "target_arm_base")
    return (-y_base, x_base, z_base)


def validate_grasp_target(
    point_arm_base: Sequence[float],
    reference_xy: Sequence[float],
    xy_tolerance_m: float,
    z_min_m: float,
    z_max_m: float,
) -> Point3:
    """Validate the I1-aligned grasp point before arm planning starts."""

    target = as_point3(point_arm_base, "target_arm_base")
    try:
        reference = as_point3(
            (reference_xy[0], reference_xy[1], 0.0),
            "grasp_reference_arm_base",
        )
    except IndexError as exc:
        raise MotionServiceValidationError(
            "grasp_reference_arm_base must contain x and y"
        ) from exc
    tolerance = float(xy_tolerance_m)
    z_min = float(z_min_m)
    z_max = float(z_max_m)
    if not math.isfinite(tolerance) or tolerance < 0.0:
        raise MotionServiceValidationError("grasp_reference_xy_tolerance_m must be non-negative")
    if not math.isfinite(z_min) or not math.isfinite(z_max) or z_min > z_max:
        raise MotionServiceValidationError("invalid grasp z range")
    if abs(target[0] - reference[0]) > tolerance or abs(target[1] - reference[1]) > tolerance:
        raise MotionServiceValidationError(
            "target_arm_base x/y is outside the I1 reference tolerance: "
            f"target=({target[0]:.4f}, {target[1]:.4f}), "
            f"reference=({reference[0]:.4f}, {reference[1]:.4f}), tolerance={tolerance:.4f}"
        )
    if not z_min <= target[2] <= z_max:
        raise MotionServiceValidationError(
            f"target_arm_base z={target[2]:.4f} is outside [{z_min:.4f}, {z_max:.4f}]"
        )
    return target


def scale_steps(steps: Sequence[MotionStep], duration_scale: float) -> List[MotionStep]:
    """Apply the same optional duration scaling used by the standalone scripts."""

    scale = float(duration_scale)
    if not math.isfinite(scale) or scale < 0.1:
        raise MotionServiceValidationError("duration_scale must be finite and at least 0.1")
    if abs(scale - 1.0) < 1e-9:
        return list(steps)
    return [
        MotionStep(
            step.name,
            step.coordinate,
            max(1, int(round(step.duration_ms * scale))),
            step.servos,
            step.ik_angles,
            step.used_pitch,
        )
        for step in steps
    ]


def plan_face_approach_grasp(
    planner,
    target_arm_base: Sequence[float],
    rotation_deg: float,
    pre_distance_m: float,
    lift_height_m: float,
    duration_scale: float = 1.0,
) -> Tuple[Point3, Any, List[MotionStep]]:
    """Reuse face_approach_grab.py's pose generation and planning sequence."""

    target_api = arm_base_to_api(target_arm_base)
    pose = planner.make_horizontal_face_grasp_pose(
        target_api,
        rotation_deg=float(rotation_deg),
        pre_distance=float(pre_distance_m),
        lift_height=float(lift_height_m),
    )
    steps = planner.plan_grasp_pose(pose, include_home=False)
    return target_api, pose, scale_steps(steps, duration_scale)


def plan_fixed_place(
    planner,
    grasp_reference_arm: Sequence[float],
    grasp_lift_height_m: float,
    descent_m: float,
    pose1_duration_ms: int,
    descent_duration_ms: int,
    duration_scale: float = 1.0,
) -> Tuple[Point3, List[MotionStep]]:
    """Move directly to the grasp point and release the gripper. Legacy lift/descent arguments remain for interface compatibility."""

    grasp_api = as_point3(grasp_reference_arm, "place_reference_grasp_arm")
    steps = planner.plan_place(
        grasp_api,
        duration_ms=max(1, int(pose1_duration_ms)),
        include_home=False,
    )
    return grasp_api, scale_steps(steps, duration_scale)
