#!/usr/bin/env python3
"""Run the proven Nav2 inspection route with WHZ at observation waypoints."""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Tuple

import rclpy
from std_srvs.srv import Trigger

from nav2_waypoint_sequence_probe import (
    Nav2WaypointSequenceProbe,
    make_output_dir,
    parse_args,
    validate_args,
    write_outputs,
)
from nodes.decision.inspection_workflow import (
    InspectionContractError,
    InspectionReading,
    InspectionStage,
    InspectionWorkflow,
)
from nodes.navigation.waypoint_calibration import describe_waypoint_route


EXPECTED_ROUTE = (
    "obstacle_cross_target",
    "pos1_left_clear",
    "pos1_middle",
    "upper_corner_clear",
    "pos2a_upper_right",
    "upper_corner_clear",
    "pos1_middle_turned",
    "lower_corner_clear",
    "pos2b_lower_right",
)
OBSERVATION_PREFIX = "observe_"


@dataclass(frozen=True)
class InspectionConfig:
    targets: Tuple[str, ...]
    expected_areas: Dict[str, str]
    service_name: str
    startup_timeout_sec: float
    service_wait_sec: float
    response_timeout_sec: float
    settle_duration_sec: float
    settle_timeout_sec: float
    odom_max_age_sec: float
    cmd_max_age_sec: float
    max_linear_speed_mps: float
    max_angular_speed_rps: float


def _float_env(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise SystemExit("%s must be numeric" % name) from exc
    if not math.isfinite(value):
        raise SystemExit("%s must be finite" % name)
    return value


def _parse_csv(value: str) -> Tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _parse_expected_areas(value: str) -> Dict[str, str]:
    expected = {}
    for item in _parse_csv(value):
        if "=" not in item:
            raise SystemExit(
                "WHZ_EXPECTED_AREAS entries must use waypoint=A syntax"
            )
        waypoint, area = (part.strip() for part in item.split("=", 1))
        area = area.upper()
        if not waypoint or area not in frozenset("ABCD"):
            raise SystemExit("invalid expected area entry: %s" % item)
        if waypoint in expected:
            raise SystemExit("duplicate expected waypoint: %s" % waypoint)
        expected[waypoint] = area
    return expected


def load_inspection_config(args) -> InspectionConfig:
    if args.waypoint_route != "inspection_interleaved":
        raise SystemExit(
            "dedicated inspection runner requires --waypoint-route inspection_interleaved"
        )

    description = describe_waypoint_route(
        args.waypoint_document,
        args.waypoint_route,
        expected_frame=args.frame_id,
    )
    steps = description["steps"]
    route = tuple(step["label"] for step in steps)
    if route != EXPECTED_ROUTE:
        raise SystemExit("inspection route does not match the validated 9-step route")

    observation_waypoints = tuple(
        step["label"]
        for step in steps
        if str(step.get("action", "")).startswith(OBSERVATION_PREFIX)
    )
    if len(observation_waypoints) != 4:
        raise SystemExit("inspection route must contain exactly four observation actions")

    targets = _parse_csv(os.environ.get("WHZ_INSPECTION_TARGETS", ""))
    if not targets:
        targets = observation_waypoints
    if len(set(targets)) != len(targets):
        raise SystemExit("WHZ_INSPECTION_TARGETS contains duplicates")
    unknown = set(targets) - set(observation_waypoints)
    if unknown:
        raise SystemExit("unknown inspection target(s): %s" % ",".join(sorted(unknown)))

    expected_areas = _parse_expected_areas(
        os.environ.get("WHZ_EXPECTED_AREAS", "")
    )
    if set(expected_areas) - set(targets):
        raise SystemExit("WHZ_EXPECTED_AREAS contains an unselected waypoint")
    if len(targets) < 4 and set(expected_areas) != set(targets):
        raise SystemExit("partial inspection requires an expected area for every target")

    config = InspectionConfig(
        targets=targets,
        expected_areas=expected_areas,
        service_name=os.environ.get("WHZ_SERVICE", "/whz/inspect"),
        startup_timeout_sec=_float_env("WHZ_STARTUP_TIMEOUT_SEC", 60.0),
        service_wait_sec=_float_env("WHZ_SERVICE_WAIT_SEC", 15.0),
        response_timeout_sec=_float_env("WHZ_RESPONSE_TIMEOUT_SEC", 30.0),
        settle_duration_sec=_float_env("WHZ_SETTLE_DURATION_SEC", 1.0),
        settle_timeout_sec=_float_env("WHZ_SETTLE_TIMEOUT_SEC", 10.0),
        odom_max_age_sec=_float_env("WHZ_ODOM_MAX_AGE_SEC", 0.5),
        cmd_max_age_sec=_float_env("WHZ_CMD_MAX_AGE_SEC", 0.5),
        max_linear_speed_mps=_float_env("WHZ_MAX_LINEAR_SPEED_MPS", 0.02),
        max_angular_speed_rps=_float_env("WHZ_MAX_ANGULAR_SPEED_RPS", 0.05),
    )
    positive = {
        "WHZ_STARTUP_TIMEOUT_SEC": config.startup_timeout_sec,
        "WHZ_SERVICE_WAIT_SEC": config.service_wait_sec,
        "WHZ_RESPONSE_TIMEOUT_SEC": config.response_timeout_sec,
        "WHZ_SETTLE_TIMEOUT_SEC": config.settle_timeout_sec,
        "WHZ_ODOM_MAX_AGE_SEC": config.odom_max_age_sec,
        "WHZ_CMD_MAX_AGE_SEC": config.cmd_max_age_sec,
    }
    for name, value in positive.items():
        if value <= 0.0:
            raise SystemExit("%s must be > 0" % name)
    nonnegative = {
        "WHZ_SETTLE_DURATION_SEC": config.settle_duration_sec,
        "WHZ_MAX_LINEAR_SPEED_MPS": config.max_linear_speed_mps,
        "WHZ_MAX_ANGULAR_SPEED_RPS": config.max_angular_speed_rps,
    }
    for name, value in nonnegative.items():
        if value < 0.0:
            raise SystemExit("%s must be >= 0" % name)
    return config


class Nav2WhzInspectionProbe(Nav2WaypointSequenceProbe):
    """Add stop-gated, one-shot WHZ inspection to successful Nav2 segments."""

    def __init__(self, args, config: InspectionConfig):
        self.latest_odom_received_monotonic = float("-inf")
        super().__init__(args)
        self.config = config
        self.whz_client = self.create_client(Trigger, config.service_name)
        self.workflow = InspectionWorkflow(
            step_count=len(config.targets),
            settle_duration_sec=config.settle_duration_sec,
            max_nav_retries=0,
            max_inspection_retries=0,
        )
        self.request_counts = {waypoint: 0 for waypoint in config.targets}
        self.inspection_results = []
        self.startup_gate = None

    def _odom_callback(self, msg):
        self.latest_odom_received_monotonic = time.monotonic()
        super()._odom_callback(msg)

    def _stationary_sample(self):
        now = time.monotonic()
        odom = self.latest_odom
        output = self.latest_output_cmd
        odom_age = now - self.latest_odom_received_monotonic
        cmd_age = (
            now - output["monotonic_time"]
            if output is not None
            else float("inf")
        )
        linear_speed = float("inf")
        angular_speed = float("inf")
        if odom is not None:
            linear_speed = math.hypot(
                float(odom.twist.twist.linear.x),
                float(odom.twist.twist.linear.y),
            )
            angular_speed = abs(float(odom.twist.twist.angular.z))
        command_zero = bool(
            output is not None and self._output_command_is_zero(output)
        )
        stationary = bool(
            odom is not None
            and odom_age <= self.config.odom_max_age_sec
            and output is not None
            and cmd_age <= self.config.cmd_max_age_sec
            and command_zero
            and linear_speed <= self.config.max_linear_speed_mps
            and angular_speed <= self.config.max_angular_speed_rps
        )
        return {
            "stationary": stationary,
            "odom_age_sec": odom_age,
            "cmd_age_sec": cmd_age,
            "linear_speed_mps": linear_speed,
            "angular_speed_rps": angular_speed,
            "command_zero": command_zero,
        }

    def _wait_service(self, timeout_sec):
        deadline = time.monotonic() + timeout_sec
        while rclpy.ok() and time.monotonic() < deadline:
            if self.whz_client.service_is_ready():
                return True
            rclpy.spin_once(self, timeout_sec=0.05)
        return False

    def _wait_stationary_window(self, duration_sec, timeout_sec):
        deadline = time.monotonic() + timeout_sec
        stable_since = None
        last_sample = self._stationary_sample()
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
            now = time.monotonic()
            last_sample = self._stationary_sample()
            if last_sample["stationary"]:
                if stable_since is None:
                    stable_since = now
                if now - stable_since >= duration_sec:
                    result = dict(last_sample)
                    result["succeeded"] = True
                    result["stable_duration_sec"] = now - stable_since
                    return result
            else:
                stable_since = None
        result = dict(last_sample)
        result["succeeded"] = False
        result["stable_duration_sec"] = 0.0
        result["error"] = "stationary window timed out"
        return result

    def _run_startup_gate(self):
        started = time.monotonic()
        self.get_logger().info("Startup gate: waiting for NavigateToPose")
        if not self.action_client.wait_for_server(
            timeout_sec=self.config.startup_timeout_sec
        ):
            return {"succeeded": False, "error": "navigate_to_pose unavailable"}

        self.get_logger().info("Startup gate: waiting for %s" % self.config.service_name)
        if not self._wait_service(self.config.startup_timeout_sec):
            return {"succeeded": False, "error": "WHZ service unavailable"}

        self.spin_for(1.0)
        task_managers = [
            name for name in self.get_node_names() if "task_manager" in name.lower()
        ]
        if task_managers:
            return {
                "succeeded": False,
                "error": "TaskManager must remain disabled: %s" % task_managers,
            }

        self.get_logger().info("Startup gate: confirming fresh odom and continuous zero")
        stop_gate = self._wait_stationary_window(
            self.config.settle_duration_sec,
            self.config.startup_timeout_sec,
        )
        stop_gate["action_server_ready"] = True
        stop_gate["whz_service_ready"] = True
        stop_gate["task_manager_nodes"] = task_managers
        stop_gate["elapsed_sec"] = time.monotonic() - started
        return stop_gate

    def _wait_observation_stop(self):
        self.workflow.navigation_succeeded()
        deadline = time.monotonic() + self.config.settle_timeout_sec
        last_sample = self._stationary_sample()
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
            now = time.monotonic()
            last_sample = self._stationary_sample()
            if self.workflow.update_stationary(now, last_sample["stationary"]):
                result = dict(last_sample)
                result["succeeded"] = True
                result["stable_duration_sec"] = self.config.settle_duration_sec
                return result
        self.workflow.abort("observation_stationary_timeout")
        result = dict(last_sample)
        result["succeeded"] = False
        result["error"] = self.workflow.abort_reason
        return result

    def _inspect_waypoint(self, waypoint):
        result = {
            "waypoint": waypoint,
            "succeeded": False,
            "request_count": self.request_counts[waypoint],
        }
        stop_gate = self._wait_observation_stop()
        result["stop_gate"] = stop_gate
        if not stop_gate["succeeded"]:
            result["error"] = stop_gate["error"]
            return result

        if not self._wait_service(self.config.service_wait_sec):
            self.workflow.abort("whz_service_unavailable")
            result["error"] = self.workflow.abort_reason
            return result
        if self.request_counts[waypoint] != 0:
            self.workflow.abort("duplicate_whz_request=%s" % waypoint)
            result["error"] = self.workflow.abort_reason
            return result

        self.request_counts[waypoint] += 1
        result["request_count"] = self.request_counts[waypoint]
        self.workflow.service_started()
        requested_at = time.monotonic()
        try:
            future = self.whz_client.call_async(Trigger.Request())
        except Exception as exc:  # noqa: BLE001
            self.workflow.abort("whz_call_failed: %s" % exc)
            result["error"] = self.workflow.abort_reason
            return result

        deadline = requested_at + self.config.response_timeout_sec
        while rclpy.ok() and not future.done() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
        result["response_elapsed_sec"] = time.monotonic() - requested_at
        if not future.done():
            self.workflow.inspection_timed_out(
                "response exceeded %.1fs" % self.config.response_timeout_sec
            )
            result["error"] = self.workflow.abort_reason
            return result

        try:
            response = future.result()
            if response is None:
                raise InspectionContractError("empty_service_response")
            result["service_success"] = bool(response.success)
            result["raw_message"] = str(response.message)
            reading = InspectionReading.from_trigger(
                bool(response.success),
                str(response.message),
                require_audio=True,
            )
        except Exception as exc:  # noqa: BLE001
            self.workflow.abort("whz_response_invalid: %s" % exc)
            result["error"] = self.workflow.abort_reason
            return result

        expected_area = self.config.expected_areas.get(waypoint)
        if expected_area is not None and reading.area != expected_area:
            self.workflow.abort(
                "unexpected_area=%s expected=%s waypoint=%s"
                % (reading.area, expected_area, waypoint)
            )
            result["reading"] = asdict(reading)
            result["error"] = self.workflow.abort_reason
            return result

        self.workflow.inspection_succeeded(reading)
        result["reading"] = asdict(reading)
        if self.workflow.stage == InspectionStage.ABORTED:
            result["error"] = self.workflow.abort_reason
            return result
        result["succeeded"] = True
        return result

    def run_segment(self, index, goal):
        segment = super().run_segment(index, goal)
        navigation_succeeded = bool(segment.get("succeeded"))
        segment["navigation_succeeded"] = navigation_succeeded
        if not navigation_succeeded:
            return segment

        waypoint = str(goal.get("label", ""))
        action = str(goal.get("action", ""))
        if waypoint not in self.config.targets:
            return segment
        if not action.startswith(OBSERVATION_PREFIX):
            segment["succeeded"] = False
            segment["error"] = "selected waypoint is not an observation action"
            self.workflow.abort(segment["error"])
            return segment

        inspection = self._inspect_waypoint(waypoint)
        segment["inspection"] = inspection
        self.inspection_results.append(inspection)
        if not inspection["succeeded"]:
            segment["succeeded"] = False
            segment["error"] = inspection.get("error", "inspection failed")
        return segment

    def run(self):
        self.startup_gate = self._run_startup_gate()
        if not self.startup_gate.get("succeeded"):
            self.workflow.abort("startup_gate_failed: %s" % self.startup_gate["error"])
            summary = {
                "ok": False,
                "error": self.workflow.abort_reason,
                "segments": [],
            }
        else:
            summary = super().run()

        if summary.get("ok") and self.workflow.stage == InspectionStage.COMPLETE:
            if len(self.config.targets) == 4:
                self.workflow.require_complete_abcd()
            if any(count != 1 for count in self.request_counts.values()):
                self.workflow.abort("each selected waypoint must have exactly one WHZ request")
        elif self.workflow.stage != InspectionStage.ABORTED:
            first_failure = next(
                (
                    segment.get("error")
                    for segment in summary.get("segments", [])
                    if not segment.get("succeeded")
                ),
                summary.get("error", "inspection route incomplete"),
            )
            self.workflow.abort("route_failed: %s" % first_failure)

        terminal_state = (
            "FINISH"
            if summary.get("ok") and self.workflow.stage == InspectionStage.COMPLETE
            else "ABORT"
        )
        summary["ok"] = terminal_state == "FINISH"
        summary["terminal_state"] = terminal_state
        summary["startup_gate"] = self.startup_gate
        summary["inspection"] = {
            "targets": list(self.config.targets),
            "expected_areas": dict(self.config.expected_areas),
            "request_counts": dict(self.request_counts),
            "stage": self.workflow.stage.value,
            "abort_reason": self.workflow.abort_reason,
            "areas": sorted(self.workflow.readings),
            "readings": {
                area: asdict(reading)
                for area, reading in self.workflow.readings.items()
            },
            "results": self.inspection_results,
        }
        if not summary["ok"]:
            summary["error"] = self.workflow.abort_reason or summary.get("error")
        return summary


def main():
    args = parse_args()
    validate_args(args)
    config = load_inspection_config(args)
    if args.describe_route:
        description = describe_waypoint_route(
            args.waypoint_document,
            args.waypoint_route,
            expected_frame=args.frame_id,
        )
        description["waypoint_file"] = str(
            Path(args.waypoint_file).expanduser().resolve()
        )
        description["inspection_targets"] = list(config.targets)
        description["expected_areas"] = dict(config.expected_areas)
        print(json.dumps(description, indent=2))
        return

    output_dir = make_output_dir(args.output_dir)
    rclpy.init()
    node = Nav2WhzInspectionProbe(args, config)
    try:
        try:
            summary = node.run()
        except Exception as exc:  # noqa: BLE001
            summary = {
                "ok": False,
                "terminal_state": "ABORT",
                "error": "unhandled_runner_error: %s" % exc,
                "segments": node.segments,
            }
        summary = write_outputs(summary, output_dir)
        print(json.dumps(summary, indent=2, sort_keys=True))
        if not summary.get("ok"):
            raise SystemExit(2)
    finally:
        node.destroy_client(node.whz_client)
        node.shutdown_background_listeners()
        node.action_client.destroy()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
