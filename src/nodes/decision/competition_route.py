"""Pure state-machine route for the competition workflow.

The route owns only sequencing, checkpoint names, and competition context.
Navigation and local task execution are supplied by the ROS adapter so this
module remains testable without ROS or robot hardware.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


class StepKind(str, Enum):
    """The only three kinds of work the top-level route may schedule."""

    NAV = "nav"
    LOCAL = "local"
    DECISION = "decision"


class RouteState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    FINISHED = "finished"
    ABORTED = "aborted"


class RouteContractError(ValueError):
    """Raised when a caller violates a route completion contract."""


@dataclass(frozen=True)
class RouteStep:
    """One explicit route step.

    ``end_checkpoint`` is a fixed navigation target only for ``NAV`` steps.
    Local steps may use symbolic dynamic end states such as I1 or J1; they are
    recorded for diagnostics but must never be passed to Nav2 as waypoints.
    """

    step_id: str
    group: str
    kind: StepKind
    executor: str
    start_checkpoint: Optional[str] = None
    end_checkpoint: Optional[str] = None
    zone: Optional[str] = None
    completion_flag: Optional[str] = None
    timeout_s: float = 60.0
    max_retries: int = 1


@dataclass
class CompetitionContext:
    """Mutable state shared by route steps, with one owner: RouteRunner."""

    abnormal_zones: Tuple[str, ...] = ()
    job_index: int = 0
    carrying_block: bool = False
    current_checkpoint: str = "start"
    last_completed_step: str = ""
    outputs: Dict[str, Mapping[str, Any]] = field(default_factory=dict)

    @property
    def current_zone(self) -> str:
        if self.job_index >= len(self.abnormal_zones):
            return ""
        return self.abnormal_zones[self.job_index]

    @property
    def jobs_complete(self) -> bool:
        return bool(self.abnormal_zones) and self.job_index >= len(self.abnormal_zones)


def normalise_abnormal_zones(zones: Iterable[str], required_count: int = 2) -> Tuple[str, ...]:
    """Validate the competition result before any manipulation route is added."""

    cleaned = tuple(sorted({str(zone).strip().upper() for zone in zones if str(zone).strip()}))
    if len(cleaned) != required_count or any(zone not in {"A", "B", "C", "D"} for zone in cleaned):
        raise RouteContractError("exactly two distinct abnormal zones from A/B/C/D are required")
    return cleaned


def build_competition_route() -> List[RouteStep]:
    """Build the fixed portion of the competition route.

    Manipulation steps are inserted only after inspection supplies the two
    abnormal zones.  This keeps the A/B/C/D branch explicit and prevents the
    number of visible red blocks from becoming the task queue.
    """

    return [
        RouteStep(
            "nav_obstacle_exit", "obstacle", StepKind.NAV, "navigate",
            start_checkpoint="start", end_checkpoint="obstacle_cross_target", timeout_s=90.0,
        ),
        RouteStep(
            "nav_p1a", "inspection", StepKind.NAV, "navigate",
            end_checkpoint="pos1_middle", timeout_s=60.0,
        ),
        RouteStep(
            "inspect_p1a", "inspection", StepKind.LOCAL, "inspect_face",
            start_checkpoint="pos1_middle", timeout_s=30.0,
        ),
        RouteStep(
            "nav_p1b", "inspection", StepKind.NAV, "navigate",
            end_checkpoint="pos1_middle_turned", timeout_s=30.0,
        ),
        RouteStep(
            "inspect_p1b", "inspection", StepKind.LOCAL, "inspect_face",
            start_checkpoint="pos1_middle_turned", timeout_s=30.0,
        ),
        RouteStep(
            "nav_p2a", "inspection", StepKind.NAV, "navigate",
            end_checkpoint="pos2a_upper_right", timeout_s=60.0,
        ),
        RouteStep(
            "inspect_p2a", "inspection", StepKind.LOCAL, "inspect_face",
            start_checkpoint="pos2a_upper_right", timeout_s=30.0,
        ),
        RouteStep(
            "nav_p2b", "inspection", StepKind.NAV, "navigate",
            end_checkpoint="pos2b_lower_right", timeout_s=60.0,
        ),
        RouteStep(
            "inspect_p2b", "inspection", StepKind.LOCAL, "inspect_face",
            start_checkpoint="pos2b_lower_right", timeout_s=30.0,
        ),
        RouteStep(
            "prepare_jobs", "inspection", StepKind.DECISION, "prepare_jobs",
            completion_flag="jobs_prepared", timeout_s=10.0, max_retries=0,
        ),
    ]


def build_manipulation_steps(zones: Iterable[str]) -> List[RouteStep]:
    """Build two pick/place cycles for the validated inspection result."""

    steps: List[RouteStep] = []
    for index, zone in enumerate(normalise_abnormal_zones(zones), start=1):
        steps.extend([
            RouteStep(
                "nav_i0_{}".format(index), "manipulation", StepKind.NAV, "navigate",
                end_checkpoint="grasp_i0", zone=zone, timeout_s=90.0,
            ),
            RouteStep(
                "pick_one_{}".format(index), "manipulation", StepKind.LOCAL, "pick_one",
                start_checkpoint="grasp_i0", end_checkpoint="i2", zone=zone,
                completion_flag="grasp_success", timeout_s=90.0,
            ),
            RouteStep(
                "nav_j0_{}".format(zone), "manipulation", StepKind.NAV, "navigate",
                end_checkpoint="placement_{}".format(zone), zone=zone, timeout_s=90.0,
            ),
            RouteStep(
                "place_one_{}".format(zone), "manipulation", StepKind.LOCAL, "place_one",
                start_checkpoint="placement_{}".format(zone), end_checkpoint="j1", zone=zone,
                completion_flag="place_success", timeout_s=60.0,
            ),
        ])
    return steps


def build_segment_route(segment_name: str, zone: str = "") -> List[RouteStep]:
    """Build one supervised segment or a cumulative Nav2-to-pick test."""

    name = str(segment_name).strip().lower()
    inspect_points = {
        "inspect_p1a": "pos1_middle",
        "inspect_p1b": "pos1_middle_turned",
        "inspect_p2a": "pos2a_upper_right",
        "inspect_p2b": "pos2b_lower_right",
    }
    if name in inspect_points:
        return [RouteStep(name, "inspection", StepKind.LOCAL, "inspect_face", start_checkpoint=inspect_points[name])]
    nav_i0_test = RouteStep(
        "nav_i0_test", "navigation", StepKind.NAV, "navigate",
        end_checkpoint="grasp_i0", completion_flag="nav_success", timeout_s=120.0,
    )
    if name == "pick_until_i0":
        return [nav_i0_test]
    if name == "pick_i0_to_i2":
        return [RouteStep(
            "pick_i0_to_i2", "manipulation", StepKind.LOCAL, "pick_i0_to_i2",
            start_checkpoint="grasp_i0", end_checkpoint="i2",
            completion_flag="alignment_success", timeout_s=90.0,
        )]
    pick_tests = {
        "pick_until_i2": ("pick_until_i2", "alignment_success", "i2"),
        "pick_align_only": ("pick_align_only", "alignment_success", "i2"),
        "pick_one": ("pick_one", "grasp_success", "grasped"),
    }
    if name in pick_tests:
        executor, flag, end_checkpoint = pick_tests[name]
        return [
            nav_i0_test,
            RouteStep(
                name, "manipulation", StepKind.LOCAL, executor,
                start_checkpoint="grasp_i0", end_checkpoint=end_checkpoint,
                completion_flag=flag, timeout_s=90.0,
            ),
        ]
    if name == "place_one":
        target_zone = str(zone).strip().upper()
        if target_zone not in {"A", "B", "C", "D"}:
            raise RouteContractError("place_one requires zone A, B, C, or D")
        return [RouteStep(
            "place_one_{}".format(target_zone), "manipulation", StepKind.LOCAL, "place_one",
            start_checkpoint="placement_{}".format(target_zone), end_checkpoint="j1", zone=target_zone,
            completion_flag="place_success", timeout_s=60.0,
        )]
    raise RouteContractError("unknown local segment: {}".format(segment_name))


class RouteRunner:
    """Advance a single explicit route step at a time.

    The ROS adapter starts and polls the current step.  It reports only an
    explicit success or failure back here; this class never drives hardware.
    """

    def __init__(self, steps: Iterable[RouteStep], context: Optional[CompetitionContext] = None) -> None:
        self._steps = list(steps)
        if not self._steps:
            raise RouteContractError("route must contain at least one step")
        self.context = context or CompetitionContext()
        self.state = RouteState.IDLE
        self._index = 0
        self._retries = 0
        self.error = ""

    @property
    def steps(self) -> Tuple[RouteStep, ...]:
        return tuple(self._steps)

    @property
    def current_step(self) -> Optional[RouteStep]:
        if self.state in {RouteState.FINISHED, RouteState.ABORTED}:
            return None
        return self._steps[self._index]

    @property
    def retry_count(self) -> int:
        return self._retries

    def start(self) -> RouteStep:
        if self.state != RouteState.IDLE:
            raise RouteContractError("route can only be started from idle")
        self.state = RouteState.RUNNING
        return self._steps[self._index]

    def prepare_jobs(self, zones: Iterable[str]) -> RouteStep:
        """Expand the route after the four inspection results are available."""

        step = self._require_current("prepare_jobs")
        if step.kind != StepKind.DECISION:
            raise RouteContractError("jobs can only be prepared at the decision step")
        normalised = normalise_abnormal_zones(zones)
        self.context.abnormal_zones = normalised
        self.context.job_index = 0
        self._steps[self._index + 1:self._index + 1] = build_manipulation_steps(normalised)
        return self.complete_current({"jobs_prepared": True, "zones": list(normalised)})

    def complete_current(self, result: Optional[Mapping[str, Any]] = None) -> RouteStep:
        """Record a successful step result and return the next step.

        Pick and place steps require the corresponding arm service success flag
        even when their local executor itself reports completion.
        """

        step = self._require_running_step()
        payload = dict(result or {})
        if step.completion_flag and payload.get(step.completion_flag) is not True:
            raise RouteContractError(
                "{} requires explicit {}=true".format(step.step_id, step.completion_flag)
            )
        if step.executor == "pick_one":
            self.context.carrying_block = True
        elif step.executor == "place_one":
            if not self.context.carrying_block:
                raise RouteContractError("place_one cannot complete without a carried block")
            if step.zone != self.context.current_zone:
                raise RouteContractError("place_one zone does not match the current job")
            self.context.carrying_block = False
            self.context.job_index += 1

        if step.end_checkpoint:
            self.context.current_checkpoint = step.end_checkpoint
        self.context.last_completed_step = step.step_id
        self.context.outputs[step.step_id] = payload
        self._retries = 0
        self._index += 1
        if self._index >= len(self._steps):
            self.state = RouteState.FINISHED
            return step
        return self._steps[self._index]

    def fail_current(self, reason: str) -> Optional[RouteStep]:
        """Retry the active step within its budget or abort the route."""

        step = self._require_running_step()
        self.error = str(reason)
        if self._retries < step.max_retries:
            self._retries += 1
            return step
        self.state = RouteState.ABORTED
        return None

    def abort(self, reason: str) -> None:
        self.error = str(reason)
        self.state = RouteState.ABORTED

    def status_dict(self) -> Dict[str, Any]:
        step = self.current_step
        return {
            "route_state": self.state.value,
            "current_step": "" if step is None else step.step_id,
            "step_kind": "" if step is None else step.kind.value,
            "group": "" if step is None else step.group,
            "current_checkpoint": self.context.current_checkpoint,
            "current_zone": self.context.current_zone,
            "job_index": self.context.job_index,
            "job_count": len(self.context.abnormal_zones),
            "carrying_block": self.context.carrying_block,
            "retry_count": self._retries,
            "error": self.error,
        }

    def _require_running_step(self) -> RouteStep:
        if self.state != RouteState.RUNNING:
            raise RouteContractError("route is not running")
        return self._steps[self._index]

    def _require_current(self, step_id: str) -> RouteStep:
        step = self._require_running_step()
        if step.step_id != step_id:
            raise RouteContractError("current step is {}, expected {}".format(step.step_id, step_id))
        return step
