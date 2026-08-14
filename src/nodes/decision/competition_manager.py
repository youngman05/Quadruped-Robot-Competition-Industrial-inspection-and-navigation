#!/usr/bin/env python3
"""ROS adapter for navigation, AprilTag/red pickup, and fixed-zone placement."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import List, Optional

import rclpy
from geometry_msgs.msg import Point, Twist
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.time import Time
from std_msgs.msg import String
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformException, TransformListener

from arm_new_interfaces.srv import ExecuteGraspFixed
from navi.navigation_client import NavigationClient
from nodes.decision.competition_route import (
    RouteContractError,
    RouteRunner,
    RouteState,
    StepKind,
    build_competition_route,
    build_segment_route,
)
from nodes.decision.manipulation_segments import (
    DetectionFrame,
    PlaceConfig,
    PlaceOneExecutor,
    SegmentResult,
    parse_detection_frame,
)
from nodes.decision.pick_alignment_core import (
    FiducialDetectionFrame,
    I2Target,
    PickConfig,
    PickOneExecutor,
    parse_fiducial_frame,
)


class RosManipulationRuntime:
    """The only ROS-dependent adapter consumed by the local executors."""

    def __init__(self, manager: "CompetitionManager") -> None:
        self._manager = manager

    def now(self) -> float:
        return time.monotonic()

    def stop(self) -> None:
        self._manager._cmd_vel_pub.publish(Twist())

    def command(self, axis: str, speed: float) -> None:
        command = Twist()
        if axis == "x":
            command.linear.x = speed
        elif axis == "y":
            command.linear.y = speed
        elif axis == "yaw":
            command.angular.z = speed
        else:
            raise ValueError("unknown velocity axis {}".format(axis))
        self._manager._cmd_vel_pub.publish(command)

    def next_detection(self) -> Optional[DetectionFrame]:
        frame = self._manager._latest_detection
        stale_after_s = float(self._manager.get_parameter("yolo_stale_timeout_s").value)
        if stale_after_s > 0.0 and time.monotonic() - self._manager._latest_detection_received_s > stale_after_s:
            return None
        if frame is None or frame.sequence <= self._manager._last_consumed_sequence:
            return None
        self._manager._last_consumed_sequence = frame.sequence
        return frame

    def current_fiducial_frame(self) -> Optional[FiducialDetectionFrame]:
        frame = self._manager._latest_tag_frame
        stale_after_s = float(self._manager.get_parameter("tag_stale_timeout_s").value)
        if frame is None or time.monotonic() - self._manager._latest_tag_received_s > stale_after_s:
            return None
        return frame

    def start_grasp(self):
        return self._manager._start_grasp()

    def grasp_result(self):
        return self._manager._grasp_result()

    def placement_error(self, zone: str):
        return self._manager._placement_error(zone)

    def start_place(self):
        return self._manager._start_trigger("place", self._manager._place_client)

    def place_result(self):
        return self._manager._trigger_result("place")


class CompetitionManager(Node):
    """Run one explicit NAV, LOCAL, or DECISION route step at a time."""

    def __init__(self) -> None:
        super().__init__("competition_manager_node")
        self._declare_parameters()

        self._status_pub = self.create_publisher(String, "/task/route_status", 10)
        self._phase_pub = self.create_publisher(String, "/task/phase", 10)
        self._cmd_vel_pub = self.create_publisher(
            Twist, str(self.get_parameter("cmd_vel_topic").value), 10
        )
        self._yolo_sub = self.create_subscription(
            String, str(self.get_parameter("yolo_topic").value), self._on_yolo, 10
        )
        self._tag_sub = self.create_subscription(
            String, str(self.get_parameter("tag_detections_topic").value), self._on_tag_detections, 10
        )
        self._start_srv = self.create_service(Trigger, "/task/start_route", self._on_start)
        self._abort_srv = self.create_service(Trigger, "/task/abort_route", self._on_abort)
        self._nav = NavigationClient(self)
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)
        self._place_client = self.create_client(Trigger, "/arm/execute_place_fixed")
        self._grasp_client = self.create_client(ExecuteGraspFixed, "/arm/execute_grasp_fixed")
        self._runner = None
        self._nav_step_started = False
        self._local_wait_reported = False
        self._active_executor = None
        self._latest_detection = None
        self._latest_detection_received_s = 0.0
        self._last_consumed_sequence = -1
        self._latest_tag_frame = None
        self._latest_tag_received_s = 0.0
        self._service_futures = {}
        self._picked_tag_ids = set()
        self._sites_data = None
        self._manual_abnormal_zones = []
        self._timer = self.create_timer(
            1.0 / float(self.get_parameter("tick_rate").value), self._tick
        )

        self._publish_status("idle; call /task/start_route when explicitly enabled")

    def _declare_parameters(self) -> None:
        self.declare_parameter("tick_rate", 10.0)
        self.declare_parameter("route_mode", "full")
        self.declare_parameter("segment_name", "")
        self.declare_parameter("segment_zone", "")
        self.declare_parameter("manual_abnormal_zones", [])
        self.declare_parameter("manual_carrying_block", False)
        self.declare_parameter("scenario_file", "")
        self.declare_parameter("scenario_name", "")
        self.declare_parameter("enable_route_execution", False)
        self.declare_parameter("yolo_topic", "/yolo/detections")
        self.declare_parameter("cmd_vel_topic", "/cmd_vel")
        self.declare_parameter("min_yolo_confidence", 0.50)
        self.declare_parameter("min_depth_valid_ratio", 0.60)
        self.declare_parameter("yolo_stale_timeout_s", 0.50)
        self.declare_parameter("tag_detections_topic", "/apriltag/detections_base")
        self.declare_parameter("tag_stale_timeout_s", 0.50)
        self.declare_parameter("tf_timeout_s", 0.20)
        self.declare_parameter("sites_file", "configs/calibration/competition_sites.yaml")

        self.declare_parameter("pick_initial_settle_s", 0.5)
        self.declare_parameter("pick_red_tag_ids", [0, 1])
        self.declare_parameter("pick_forced_tag_id", -1)
        for tag_id in range(4):
            self.declare_parameter("pick_i2_tag_{}_taught".format(tag_id), False)
            self.declare_parameter("pick_i2_tag_{}_xyyaw".format(tag_id), [0.0, 0.0, 0.0])
        self.declare_parameter("pick_grasp_target_arm_base", [0.42, 0.0, 0.20])
        self.declare_parameter("pick_qr_x_tolerance_m", 0.03)
        self.declare_parameter("pick_qr_y_tolerance_m", 0.03)
        self.declare_parameter("pick_qr_yaw_tolerance_rad", math.radians(3.0))
        self.declare_parameter("pick_qr_linear_speed_mps", 0.025)
        self.declare_parameter("pick_qr_x_speed_mps", 0.025)
        self.declare_parameter("pick_qr_y_speed_mps", 0.025)
        self.declare_parameter("pick_qr_yaw_speed_rps", 0.10)
        self.declare_parameter("pick_qr_linear_gain", 0.5)
        self.declare_parameter("pick_qr_x_gain", 0.5)
        self.declare_parameter("pick_qr_y_gain", 0.5)
        self.declare_parameter("pick_qr_yaw_gain", 0.8)
        self.declare_parameter("pick_qr_min_linear_speed_mps", 0.0125)
        self.declare_parameter("pick_qr_min_x_speed_mps", 0.0125)
        self.declare_parameter("pick_qr_min_y_speed_mps", 0.0125)
        self.declare_parameter("pick_qr_min_yaw_speed_rps", 0.05)
        self.declare_parameter("pick_qr_pulse_min_s", 1.50)
        self.declare_parameter("pick_qr_pulse_max_s", 1.50)
        self.declare_parameter("pick_qr_pulse_settle_s", 0.50)
        self.declare_parameter("pick_qr_stable_frames", 3)
        self.declare_parameter("pick_qr_timeout_s", 80.0)
        self.declare_parameter("pick_lifted_hold_s", 3.2)

        self.declare_parameter("place_settle_s", 1.0)
        self.declare_parameter("place_align_timeout_s", 30.0)
        self.declare_parameter("place_tolerance_m", 0.04)
        self.declare_parameter("place_yaw_tolerance_rad", 0.0873)
        self.declare_parameter("place_gain_xy", 0.5)
        self.declare_parameter("place_gain_yaw", 0.8)
        self.declare_parameter("place_max_speed_mps", 0.05)
        self.declare_parameter("place_min_speed_mps", 0.025)
        self.declare_parameter("place_max_yaw_rps", 0.20)
        self.declare_parameter("place_pulse_min_s", 0.15)
        self.declare_parameter("place_pulse_max_s", 0.40)
        self.declare_parameter("place_pulse_settle_s", 0.70)

    def _on_start(self, _request: Trigger.Request, response: Trigger.Response) -> Trigger.Response:
        if self._runner is not None and self._runner.state == RouteState.RUNNING:
            response.success = False
            response.message = "route is already running"
            return response
        if not bool(self.get_parameter("enable_route_execution").value):
            response.success = False
            response.message = "route execution is disabled; set enable_route_execution=true for a supervised run"
            return response

        try:
            self._runner = self._build_runner()
            step = self._runner.start()
        except RouteContractError as exc:
            response.success = False
            response.message = str(exc)
            return response

        self._nav.reset()
        self._nav_step_started = False
        self._local_wait_reported = False
        self._active_executor = None
        self._last_consumed_sequence = -1
        self._service_futures.clear()
        self._picked_tag_ids.clear()
        self._publish_status("route started")
        response.success = True
        response.message = "started at {}".format(step.step_id)
        return response

    def _on_abort(self, _request: Trigger.Request, response: Trigger.Response) -> Trigger.Response:
        if self._runner is not None and self._runner.state == RouteState.RUNNING:
            self._nav.cancel()
            self._runner.abort("operator requested abort")
            self._publish_status("operator requested abort")
        response.success = True
        if self._active_executor is not None:
            self._active_executor.cancel("operator requested abort")
            self._active_executor = None
        self._cmd_vel_pub.publish(Twist())
        response.message = "navigation and local executor cancellation requested"
        return response

    def _build_runner(self) -> RouteRunner:
        scenario = self._load_test_scenario()
        mode = str(scenario.get("route_mode", self.get_parameter("route_mode").value)).strip().lower()
        segment_name = str(scenario.get("segment_name", self.get_parameter("segment_name").value))
        segment_zone = str(scenario.get("segment_zone", self.get_parameter("segment_zone").value))
        manual_carrying = scenario.get(
            "manual_carrying_block", self.get_parameter("manual_carrying_block").value
        )
        if not isinstance(manual_carrying, bool):
            raise RouteContractError("manual_carrying_block must be boolean")
        if mode == "full":
            zones = scenario.get("abnormal_zones", self.get_parameter("manual_abnormal_zones").value)
            if not isinstance(zones, (list, tuple)):
                raise RouteContractError("manual abnormal_zones must be an array")
            self._manual_abnormal_zones = list(zones)
            return RouteRunner(build_competition_route())
        if mode == "segment":
            runner = RouteRunner(build_segment_route(
                segment_name,
                segment_zone,
            ))
            if manual_carrying:
                if segment_name.strip().lower() != "place_one":
                    raise RouteContractError("manual_carrying_block is valid only for a place_one segment test")
                runner.context.carrying_block = True
            return runner
        raise RouteContractError("route_mode must be 'full' or 'segment'")

    def _load_test_scenario(self):
        configured = str(self.get_parameter("scenario_file").value).strip()
        name = str(self.get_parameter("scenario_name").value).strip()
        if not configured and not name:
            return {}
        if not configured or not name:
            raise RouteContractError("scenario_file and scenario_name must be set together")
        try:
            import yaml
            path = Path(configured)
            if not path.is_absolute():
                path = Path.cwd() / path
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            scenario = data["scenarios"][name]
        except Exception as exc:
            raise RouteContractError("cannot load test scenario: {}".format(exc))
        if not isinstance(scenario, dict):
            raise RouteContractError("test scenario '{}' must be a mapping".format(name))
        return scenario

    def _on_yolo(self, message: String) -> None:
        try:
            self._latest_detection = parse_detection_frame(
                json.loads(message.data),
                float(self.get_parameter("min_yolo_confidence").value),
                float(self.get_parameter("min_depth_valid_ratio").value),
            )
            self._latest_detection_received_s = time.monotonic()
        except (json.JSONDecodeError, ValueError) as exc:
            self.get_logger().warn("ignored invalid /yolo/detections: {}".format(exc), throttle_duration_sec=2.0)

    def _on_tag_detections(self, message: String) -> None:
        try:
            self._latest_tag_frame = parse_fiducial_frame(json.loads(message.data))
            self._latest_tag_received_s = time.monotonic()
        except (json.JSONDecodeError, ValueError) as exc:
            self.get_logger().warn(
                "ignored invalid /apriltag/detections_base: {}".format(exc),
                throttle_duration_sec=2.0,
            )

    def _tick(self) -> None:
        if self._runner is None or self._runner.state != RouteState.RUNNING:
            return
        step = self._runner.current_step
        if step is None:
            return
        if step.kind == StepKind.NAV:
            self._tick_navigation(step)
        elif step.kind == StepKind.DECISION:
            self._tick_decision(step)
        else:
            self._tick_local(step)

    def _tick_navigation(self, step) -> None:
        if not self._nav_step_started:
            if not step.end_checkpoint:
                self._runner.fail_current("navigation step has no target checkpoint")
                self._publish_status("invalid navigation step")
                return
            if not self._nav.navigate_to_waypoint(step.end_checkpoint):
                self._runner.fail_current("failed to send navigation goal for {}".format(step.end_checkpoint))
                self._publish_status("navigation goal rejected")
                return
            self._nav_step_started = True
            self._publish_status("navigation goal sent")
            return
        if not self._nav.is_done():
            return
        if self._nav.succeeded():
            self._nav.reset()
            self._nav_step_started = False
            self._runner.complete_current({"nav_success": True})
            self._publish_status("navigation completed")
            return
        self._nav.reset()
        self._nav_step_started = False
        self._runner.fail_current("navigation failed for {}".format(step.end_checkpoint))
        self._publish_status("navigation failed")

    def _tick_decision(self, step) -> None:
        if step.executor != "prepare_jobs":
            self._runner.fail_current("no decision adapter for {}".format(step.executor))
            self._publish_status("unknown decision step")
            return
        zones = self._manual_abnormal_zones
        if not zones:
            self._publish_status("waiting for inspection result adapter")
            return
        try:
            self._runner.prepare_jobs(zones)
        except RouteContractError as exc:
            self._runner.fail_current(str(exc))
            self._publish_status("inspection result rejected")
            return
        self._publish_status("inspection jobs prepared")

    def _tick_local(self, step) -> None:
        pick_executors = {
            "pick_i0_to_i2",
            "pick_until_i2",
            "pick_align_only",
            "pick_one",
        }
        if step.executor not in pick_executors | {"place_one"}:
            if not self._local_wait_reported:
                self._local_wait_reported = True
                self._publish_status("waiting for local executor '{}'".format(step.executor))
            return
        try:
            if self._active_executor is None:
                self._active_executor = self._make_executor(step)
                self._active_executor.start()
                self._publish_status("local executor started")
            result = self._active_executor.tick()
        except (RuntimeError, TransformException, ValueError) as exc:
            self._cmd_vel_pub.publish(Twist())
            self._runner.fail_current("local executor error: {}".format(exc))
            self._active_executor = None
            self._publish_status("local executor error")
            return
        if result is None:
            return
        self._active_executor = None
        if result.success:
            if result.grasp_success and "target_tag_id" in result.outputs:
                self._picked_tag_ids.add(int(result.outputs["target_tag_id"]))
            try:
                self._runner.complete_current(self._route_payload(result))
            except RouteContractError as exc:
                self._runner.fail_current(str(exc))
                self._publish_status("local result rejected")
                return
            self._publish_status("local executor completed")
            return
        self._runner.fail_current(result.reason)
        self._publish_status("local executor failed")

    def _make_executor(self, step):
        runtime = RosManipulationRuntime(self)
        stop_stages = {
            "pick_i0_to_i2": "i2",
            "pick_until_i2": "i2",
            "pick_align_only": "i2",
            "pick_one": "grasped",
        }
        if step.executor in stop_stages:
            return PickOneExecutor(runtime, self._pick_config(stop_stages[step.executor]))
        return PlaceOneExecutor(runtime, step.zone or "", self._place_config())

    @staticmethod
    def _route_payload(result: SegmentResult):
        payload = dict(result.outputs)
        payload["alignment_success"] = result.alignment_success
        payload["grasp_success"] = result.grasp_success
        payload["place_success"] = result.place_success
        payload["reason"] = result.reason
        return payload

    def _pick_config(self, stop_after_stage: str) -> PickConfig:
        i2_targets = {}
        for tag_id in range(4):
            if not bool(self.get_parameter("pick_i2_tag_{}_taught".format(tag_id)).value):
                continue
            values = tuple(
                float(value)
                for value in self.get_parameter("pick_i2_tag_{}_xyyaw".format(tag_id)).value
            )
            if len(values) != 3:
                raise ValueError("I2 tag {} requires [x, y, yaw]".format(tag_id))
            i2_targets[tag_id] = I2Target(*values)
        forced_tag_id = int(self.get_parameter("pick_forced_tag_id").value)
        if forced_tag_id not in {-1, 0, 1, 2, 3}:
            raise ValueError("pick_forced_tag_id must be -1 or a Tag ID from 0 to 3")
        return PickConfig(
            red_tag_ids=tuple(int(value) for value in self.get_parameter("pick_red_tag_ids").value),
            excluded_tag_ids=tuple(sorted(self._picked_tag_ids)),
            forced_tag_id=None if forced_tag_id == -1 else forced_tag_id,
            i2_targets=i2_targets,
            initial_settle_s=float(self.get_parameter("pick_initial_settle_s").value),
            x_tolerance_m=float(self.get_parameter("pick_qr_x_tolerance_m").value),
            y_tolerance_m=float(self.get_parameter("pick_qr_y_tolerance_m").value),
            yaw_tolerance_rad=float(self.get_parameter("pick_qr_yaw_tolerance_rad").value),
            linear_speed_mps=float(self.get_parameter("pick_qr_linear_speed_mps").value),
            x_speed_mps=float(self.get_parameter("pick_qr_x_speed_mps").value),
            y_speed_mps=float(self.get_parameter("pick_qr_y_speed_mps").value),
            yaw_speed_rps=float(self.get_parameter("pick_qr_yaw_speed_rps").value),
            linear_gain=float(self.get_parameter("pick_qr_linear_gain").value),
            x_gain=float(self.get_parameter("pick_qr_x_gain").value),
            y_gain=float(self.get_parameter("pick_qr_y_gain").value),
            yaw_gain=float(self.get_parameter("pick_qr_yaw_gain").value),
            min_linear_speed_mps=float(self.get_parameter("pick_qr_min_linear_speed_mps").value),
            min_x_speed_mps=float(self.get_parameter("pick_qr_min_x_speed_mps").value),
            min_y_speed_mps=float(self.get_parameter("pick_qr_min_y_speed_mps").value),
            min_yaw_speed_rps=float(self.get_parameter("pick_qr_min_yaw_speed_rps").value),
            pulse_min_s=float(self.get_parameter("pick_qr_pulse_min_s").value),
            pulse_max_s=float(self.get_parameter("pick_qr_pulse_max_s").value),
            pulse_settle_s=float(self.get_parameter("pick_qr_pulse_settle_s").value),
            stable_frames=int(self.get_parameter("pick_qr_stable_frames").value),
            timeout_s=float(self.get_parameter("pick_qr_timeout_s").value),
            lifted_hold_s=float(self.get_parameter("pick_lifted_hold_s").value),
            stop_after_stage=stop_after_stage,
        )

    def _place_config(self) -> PlaceConfig:
        return PlaceConfig(
            settle_s=float(self.get_parameter("place_settle_s").value),
            align_timeout_s=float(self.get_parameter("place_align_timeout_s").value),
            tolerance_m=float(self.get_parameter("place_tolerance_m").value),
            yaw_tolerance_rad=float(self.get_parameter("place_yaw_tolerance_rad").value),
            gain_xy=float(self.get_parameter("place_gain_xy").value),
            gain_yaw=float(self.get_parameter("place_gain_yaw").value),
            max_speed_mps=float(self.get_parameter("place_max_speed_mps").value),
            min_speed_mps=float(self.get_parameter("place_min_speed_mps").value),
            max_yaw_rps=float(self.get_parameter("place_max_yaw_rps").value),
            pulse_min_s=float(self.get_parameter("place_pulse_min_s").value),
            pulse_max_s=float(self.get_parameter("place_pulse_max_s").value),
            pulse_settle_s=float(self.get_parameter("place_pulse_settle_s").value),
        )

    def _start_trigger(self, name: str, client) -> bool:
        if name in self._service_futures or not client.wait_for_service(timeout_sec=0.0):
            return False
        self._service_futures[name] = client.call_async(Trigger.Request())
        return True

    def _trigger_result(self, name: str) -> Optional[bool]:
        future = self._service_futures.get(name)
        if future is None:
            return False
        if not future.done():
            return None
        del self._service_futures[name]
        try:
            return bool(future.result().success)
        except Exception as exc:
            self.get_logger().error("{} service call failed: {}".format(name, exc))
            return False

    def _start_grasp(self) -> bool:
        if "grasp" in self._service_futures or not self._grasp_client.wait_for_service(timeout_sec=0.0):
            return False
        target_arm = self.get_parameter("pick_grasp_target_arm_base").value
        if len(target_arm) != 3:
            raise ValueError("pick_grasp_target_arm_base must contain xyz")
        request = ExecuteGraspFixed.Request()
        request.target_arm_base = Point(x=float(target_arm[0]), y=float(target_arm[1]), z=float(target_arm[2]))
        self._service_futures["grasp"] = self._grasp_client.call_async(request)
        return True

    def _grasp_result(self) -> Optional[bool]:
        future = self._service_futures.get("grasp")
        if future is None:
            return False
        if not future.done():
            return None
        del self._service_futures["grasp"]
        try:
            return bool(future.result().success)
        except Exception as exc:
            self.get_logger().error("grasp service call failed: {}".format(exc))
            return False

    def _transform_point(self, target_frame: str, source_frame: str, point):
        transform = self._tf_buffer.lookup_transform(
            target_frame,
            source_frame,
            Time(),
            timeout=Duration(seconds=float(self.get_parameter("tf_timeout_s").value)),
        )
        q = transform.transform.rotation
        t = transform.transform.translation
        x, y, z, w = q.x, q.y, q.z, q.w
        px, py, pz = point
        return (
            (1 - 2 * (y * y + z * z)) * px + 2 * (x * y - z * w) * py + 2 * (x * z + y * w) * pz + t.x,
            2 * (x * y + z * w) * px + (1 - 2 * (x * x + z * z)) * py + 2 * (y * z - x * w) * pz + t.y,
            2 * (x * z - y * w) * px + 2 * (y * z + x * w) * py + (1 - 2 * (x * x + y * y)) * pz + t.z,
        )

    def _placement_error(self, zone: str):
        target_x, target_y, target_yaw = self._placement_pose(zone)
        transform = self._tf_buffer.lookup_transform(
            "map", "base_link", Time(),
            timeout=Duration(seconds=float(self.get_parameter("tf_timeout_s").value)),
        )
        current_x = transform.transform.translation.x
        current_y = transform.transform.translation.y
        q = transform.transform.rotation
        current_yaw = math.atan2(
            2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z),
        )
        dx, dy = target_x - current_x, target_y - current_y
        return (
            math.cos(current_yaw) * dx + math.sin(current_yaw) * dy,
            -math.sin(current_yaw) * dx + math.cos(current_yaw) * dy,
            math.atan2(math.sin(target_yaw - current_yaw), math.cos(target_yaw - current_yaw)),
        )

    def _placement_pose(self, zone: str):
        try:
            import yaml
            if self._sites_data is None:
                path = self._resolve_sites_file()
                self._sites_data = yaml.safe_load(path.read_text(encoding="utf-8"))
            entry = self._sites_data["dog_poses"]["placement_{}".format(str(zone).upper())]
            if entry.get("status") != "calibrated":
                raise ValueError("placement_{} is not calibrated".format(str(zone).upper()))
            pose = entry["pose_map_m_rad"]
            if not isinstance(pose, list) or len(pose) != 3:
                raise ValueError("invalid placement pose")
            return tuple(float(value) for value in pose)
        except (ImportError, OSError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("cannot load calibrated placement pose: {}".format(exc))

    def _resolve_sites_file(self) -> Path:
        configured = Path(str(self.get_parameter("sites_file").value))
        candidates = [configured] if configured.is_absolute() else [Path.cwd() / configured]
        candidates.append(Path(__file__).resolve().parents[3] / "configs" / "calibration" / "competition_sites.yaml")
        try:
            from ament_index_python.packages import get_package_share_directory
            candidates.append(
                Path(get_package_share_directory("quadruped_robot_competition")) /
                "configs" / "calibration" / "competition_sites.yaml"
            )
        except ImportError:
            pass
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise OSError("sites_file was not found: {}".format(configured))

    def _publish_status(self, reason: str) -> None:
        payload = {"reason": reason, "adapter": "competition_manager"}
        if self._runner is not None:
            payload.update(self._runner.status_dict())
            step = self._runner.current_step
            phase = "" if step is None else step.group
        else:
            phase = "idle"
        phase_msg = String()
        phase_msg.data = phase
        self._phase_pub.publish(phase_msg)
        status_msg = String()
        status_msg.data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self._status_pub.publish(status_msg)

    def destroy_node(self) -> bool:
        if self._active_executor is not None:
            self._active_executor.cancel("node shutdown")
            self._active_executor = None
        self._cmd_vel_pub.publish(Twist())
        if self._runner is not None and self._runner.state == RouteState.RUNNING:
            self._nav.cancel()
            self._runner.abort("node shutdown")
        return super().destroy_node()


def main(args: List[str] = None) -> None:
    rclpy.init(args=args)
    node = CompetitionManager()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
