#!/usr/bin/env python3
# coding: utf-8

"""Fixed ArmPi posture planning without serial or ROS dependencies."""

from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from .common import INITIAL_POSITION_SERVOS, MotionStep


ServoTarget = Tuple[int, int]

LIE_DOWN_ORDER = (6, 5, 4, 3, 2)
STAND_UP_ORDER = (6, 2, 3, 4, 5)

# ID1 is intentionally absent. Posture changes must preserve the gripper state.
LYING_POSITION_SERVOS = (
    (2, 512),
    (3, 447),
    (4, 434),
    (5, 863),
    (6, 220),
)


def _without_gripper(servos: Iterable[ServoTarget]) -> Dict[int, int]:
    return {int(servo_id): int(pulse) for servo_id, pulse in servos if int(servo_id) != 1}


def _plan_posture(
    action: str,
    targets: Iterable[ServoTarget],
    order: Sequence[int],
    default_duration_ms: int,
    duration_overrides_ms: Mapping[int, int],
) -> List[MotionStep]:
    target_by_id = {
        int(servo_id): int(pulse)
        for servo_id, pulse in targets
    }
    expected_ids = set(int(servo_id) for servo_id in order)
    if set(target_by_id) != expected_ids:
        raise ValueError(
            "{} targets must contain exactly servo IDs {}".format(
                action,
                sorted(expected_ids),
            )
        )

    default_duration = max(1, int(default_duration_ms))
    steps = []
    for servo_id in order:
        duration_ms = max(
            1,
            int(duration_overrides_ms.get(int(servo_id), default_duration)),
        )
        steps.append(
            MotionStep(
                "{}_id{}".format(action, servo_id),
                None,
                duration_ms,
                ((servo_id, target_by_id[servo_id]),),
            )
        )
    return steps


def plan_lie_down(
    default_duration_ms: int = 1200,
    servo4_duration_ms: int = 1500,
    servo6_duration_ms: int = 1000,
) -> List[MotionStep]:
    """Plan the calibrated lying posture while preserving servo ID1."""

    return _plan_posture(
        "lie_down",
        # Keep the lying posture's ID2..6 sequence unchanged and never
        # generate a command for the gripper servo ID1.
        _without_gripper(LYING_POSITION_SERVOS),
        LIE_DOWN_ORDER,
        default_duration_ms,
        {4: servo4_duration_ms, 6: servo6_duration_ms},
    )


def plan_stand_up(
    default_duration_ms: int = 1200,
    servo4_duration_ms: int = 1500,
    servo6_duration_ms: int = 1000,
) -> List[MotionStep]:
    """Plan the calibrated initial posture while preserving servo ID1."""

    return _plan_posture(
        "stand_up",
        # INITIAL_POSITION_SERVOS also documents ID1, but stand_up must leave
        # the current gripper position untouched and only generate IDs 2..6.
        _without_gripper(INITIAL_POSITION_SERVOS),
        STAND_UP_ORDER,
        default_duration_ms,
        {4: servo4_duration_ms, 6: servo6_duration_ms},
    )
