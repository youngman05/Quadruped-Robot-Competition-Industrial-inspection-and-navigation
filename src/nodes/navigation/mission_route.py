"""Shared route semantics for the probe, calibration, and TaskManager."""

from __future__ import annotations

from typing import Dict, Tuple

from nodes.navigation.waypoint_calibration import DEFAULT_INSPECTION_ROUTE


OBSERVATION_DESCRIPTIONS = {
    "pos1_middle": "仰头看上柜底面 (上区仪表)",
    "pos2a_upper_right": "看上柜右侧面 (上区字母)",
    "pos1_middle_turned": "180度转身看下柜顶面 (下区仪表)",
    "pos2b_lower_right": "看下柜右侧面 (下区字母)",
}

TRANSIT_DESCRIPTIONS = {
    "upper_corner_clear": "绕行上柜拐角",
    "lower_corner_clear": "绕行下柜拐角",
}

OBSTACLE_TO_INSPECTION_HANDOFF = "pos1_middle"
_HANDOFF_INDEX = DEFAULT_INSPECTION_ROUTE.index(OBSTACLE_TO_INSPECTION_HANDOFF)
OBSTACLE_ROUTE: Tuple[str, ...] = tuple(
    DEFAULT_INSPECTION_ROUTE[: _HANDOFF_INDEX + 1]
)
INSPECTION_ROUTE: Tuple[str, ...] = tuple(
    DEFAULT_INSPECTION_ROUTE[_HANDOFF_INDEX:]
)
MISSION_NAV_WAYPOINTS: Tuple[str, ...] = tuple(
    dict.fromkeys(OBSTACLE_ROUTE + INSPECTION_ROUTE)
)


def observation_steps() -> Tuple[Dict[str, str], ...]:
    return tuple(
        {
            "waypoint": waypoint,
            "desc": OBSERVATION_DESCRIPTIONS[waypoint],
            "kind": "observe",
        }
        for waypoint in DEFAULT_INSPECTION_ROUTE
        if waypoint in OBSERVATION_DESCRIPTIONS
    )


def inspection_route_steps() -> Tuple[Dict[str, str], ...]:
    steps = []
    for waypoint in INSPECTION_ROUTE:
        if waypoint in OBSERVATION_DESCRIPTIONS:
            kind = "observe"
            description = OBSERVATION_DESCRIPTIONS[waypoint]
        else:
            kind = "transit"
            description = TRANSIT_DESCRIPTIONS.get(waypoint, waypoint)
        steps.append({"waypoint": waypoint, "desc": description, "kind": kind})
    return tuple(steps)
