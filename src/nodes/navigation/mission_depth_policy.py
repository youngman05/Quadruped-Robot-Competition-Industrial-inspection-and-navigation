"""Data-driven depth milestones shared by mission and waypoint runners."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional, Set, Tuple

from nodes.navigation.depth_contract import DepthContractError, DepthMode


class MilestoneTrigger(str, Enum):
    MISSION_START = "MISSION_START"
    BEFORE_WAYPOINT = "BEFORE_WAYPOINT"
    WAYPOINT_SUCCEEDED = "WAYPOINT_SUCCEEDED"


@dataclass(frozen=True)
class DepthMilestone:
    trigger: MilestoneTrigger
    mode: DepthMode
    waypoint: str = ""
    requires_completed: Tuple[str, ...] = ()


class StationaryWindow:
    """Require a continuously stationary interval before a resource transition."""

    def __init__(self, duration_sec: float) -> None:
        if duration_sec < 0.0:
            raise ValueError("duration_sec must be non-negative")
        self.duration_sec = float(duration_sec)
        self.stable_since: Optional[float] = None

    def update(self, now: float, stationary: bool) -> bool:
        now = float(now)
        if not stationary:
            self.reset()
            return False
        if self.stable_since is None or now < self.stable_since:
            self.stable_since = now
        return now - self.stable_since >= self.duration_sec

    def reset(self) -> None:
        self.stable_since = None


DEFAULT_DEPTH_MILESTONES = (
    DepthMilestone(MilestoneTrigger.MISSION_START, DepthMode.AVOIDANCE),
    DepthMilestone(
        MilestoneTrigger.WAYPOINT_SUCCEEDED,
        DepthMode.DISABLED,
        waypoint="obstacle_cross_target",
    ),
    DepthMilestone(
        MilestoneTrigger.BEFORE_WAYPOINT,
        DepthMode.DISABLED,
        waypoint="grab_area_approach",
        requires_completed=("pos2b_lower_right",),
    ),
    *(
        DepthMilestone(
            MilestoneTrigger.WAYPOINT_SUCCEEDED,
            DepthMode.MANIPULATION,
            waypoint="placement_%s_approach" % letter,
            requires_completed=("grab_area_approach",),
        )
        for letter in "ABCD"
    ),
)


class MissionDepthPolicy:
    def __init__(self, milestones: Iterable[DepthMilestone] = DEFAULT_DEPTH_MILESTONES):
        self.milestones = tuple(milestones)
        self.completed_waypoints: Set[str] = set()
        self.mode = DepthMode.BOOTING

    def mission_start(self) -> Optional[DepthMode]:
        return self._apply(MilestoneTrigger.MISSION_START, "")

    def before_waypoint(self, waypoint: str) -> Optional[DepthMode]:
        return self._apply(MilestoneTrigger.BEFORE_WAYPOINT, waypoint)

    def waypoint_succeeded(self, waypoint: str) -> Optional[DepthMode]:
        self.completed_waypoints.add(str(waypoint))
        return self._apply(MilestoneTrigger.WAYPOINT_SUCCEEDED, waypoint)

    def _apply(self, trigger: MilestoneTrigger, waypoint: str) -> Optional[DepthMode]:
        matches = [
            milestone
            for milestone in self.milestones
            if milestone.trigger == trigger and milestone.waypoint == waypoint
        ]
        if len(matches) > 1:
            raise DepthContractError(
                "multiple depth milestones match %s %s" % (trigger.value, waypoint)
            )
        if not matches:
            return None
        milestone = matches[0]
        missing = [
            name
            for name in milestone.requires_completed
            if name not in self.completed_waypoints
        ]
        if missing:
            raise DepthContractError(
                "depth milestone %s requires completed waypoints: %s"
                % (waypoint, ", ".join(missing))
            )
        if milestone.mode == self.mode:
            return None
        self.mode = milestone.mode
        return self.mode
