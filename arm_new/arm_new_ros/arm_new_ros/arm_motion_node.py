#!/usr/bin/env python3
# coding: utf-8

"""Production ROS 2 service node for ArmPi grasping and fixed placement.

The task manager owns perception and target selection.  This node accepts an
already locked target in ``arm_base_link`` coordinates, plans the corresponding
arm sequence, and optionally executes it through BusLinker.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.time import Time
from std_msgs.msg import String
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformException, TransformListener

from arm_new_interfaces.srv import ExecuteGraspFixed


def _find_arm_new_root() -> Path:
    env_root = os.environ.get("ARM_NEW_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()

    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "arm_api").is_dir():
            return parent
    return current.parents[2]


_DEFAULT_ARM_NEW_ROOT = _find_arm_new_root()
if str(_DEFAULT_ARM_NEW_ROOT) not in sys.path:
    sys.path.insert(0, str(_DEFAULT_ARM_NEW_ROOT))

from arm_api import ArmGrabConfig, ArmGrabPlannerNew, BusLinkerExecutor  # noqa: E402
from arm_api.motion_service_core import (  # noqa: E402
    MotionServiceValidationError,
    plan_face_approach_grasp,
    plan_fixed_place,
    validate_grasp_target,
)


Point3 = Tuple[float, float, float]


class ArmMotionNode(Node):
    """Execute one serial arm action at a time through explicit ROS services."""

    def __init__(self) -> None:
        super().__init__("arm_motion_node")
        self._declare_parameters()

        self._port = str(self.get_parameter("port").value)
        self._baud = int(self.get_parameter("baud").value)
        self._pause_s = float(self.get_parameter("pause_s").value)
        self._scan_first = bool(self.get_parameter("scan_first").value)
        self._enable_motion = bool(self.get_parameter("enable_motion").value)
        self._transform_calibrated = bool(self.get_parameter("transform_calibrated").value)
        self._grasp_reference_configured = bool(
            self.get_parameter("grasp_reference_configured").value
        )
        self._place_target_configured = bool(
            self.get_parameter("place_target_configured").value
        )
        self._grasp_reference = tuple(
            self.get_parameter("grasp_reference_arm_base").value
        )
        self._grasp_xy_tolerance_m = float(
            self.get_parameter("grasp_reference_xy_tolerance_m").value
        )
        self._grasp_z_min_m = float(self.get_parameter("grasp_z_min_m").value)
        self._grasp_z_max_m = float(self.get_parameter("grasp_z_max_m").value)
        self._grasp_include_home = bool(self.get_parameter("grasp_include_home").value)
        self._place_include_home = bool(self.get_parameter("place_include_home").value)
        self._place_target_arm = tuple(self.get_parameter("place_target_arm").value)
        self._require_tf_in_preflight = bool(
            self.get_parameter("require_tf_in_preflight").value
        )
        self._tf_parent_frame = self._normalize_frame(
            str(self.get_parameter("tf_parent_frame").value)
        )
        self._tf_child_frame = self._normalize_frame(
            str(self.get_parameter("tf_child_frame").value)
        )
        self._tf_lookup_timeout_s = max(
            0.0, float(self.get_parameter("tf_lookup_timeout_s").value)
        )

        planner_config = ArmGrabConfig(
            approach_steps=max(1, int(self.get_parameter("grasp_approach_steps").value)),
            approach_step_duration_ms=max(
                1,
                int(self.get_parameter("grasp_approach_step_duration_ms").value),
            ),
        )
        self._planner = ArmGrabPlannerNew(config=planner_config)
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)
        self._busy_lock = threading.Lock()
        self._active_action = ""

        self._grasp_actions_pub = self.create_publisher(
            String, str(self.get_parameter("grasp_actions_topic").value), 10
        )
        self._place_actions_pub = self.create_publisher(
            String, str(self.get_parameter("place_actions_topic").value), 10
        )
        self._status_pub = self.create_publisher(
            String, str(self.get_parameter("status_topic").value), 10
        )
        self._grasp_service = self.create_service(
            ExecuteGraspFixed,
            "/arm/execute_grasp_fixed",
            self._srv_execute_grasp_fixed,
        )
        self._place_service = self.create_service(
            Trigger,
            "/arm/execute_place_fixed",
            self._srv_execute_place_fixed,
        )
        self._preflight_service = self.create_service(
            Trigger,
            "/arm/preflight",
            self._srv_preflight,
        )

        self.get_logger().info(
            "arm_motion_node ready: services=/arm/execute_grasp_fixed, "
            "/arm/execute_place_fixed, /arm/preflight; motion_enabled={} "
            "transform_calibrated={}".format(
                self._enable_motion,
                self._transform_calibrated,
            )
        )

    def _declare_parameters(self) -> None:
        self.declare_parameter("grasp_actions_topic", "/arm/grasp_actions")
        self.declare_parameter("place_actions_topic", "/arm/place_actions")
        self.declare_parameter("status_topic", "/arm/status")

        self.declare_parameter("port", "/dev/ttyACM0")
        self.declare_parameter("baud", 115200)
        self.declare_parameter("pause_s", 0.2)
        self.declare_parameter("scan_first", True)
        self.declare_parameter("enable_motion", False)
        self.declare_parameter("transform_calibrated", False)

        self.declare_parameter("tf_parent_frame", "base_link")
        self.declare_parameter("tf_child_frame", "arm_base_link")
        self.declare_parameter("tf_lookup_timeout_s", 1.0)
        self.declare_parameter("require_tf_in_preflight", True)

        self.declare_parameter("grasp_reference_configured", False)
        self.declare_parameter("grasp_reference_arm_base", [0.40, 0.00])
        self.declare_parameter("grasp_reference_xy_tolerance_m", 0.02)
        self.declare_parameter("grasp_z_min_m", 0.02)
        self.declare_parameter("grasp_z_max_m", 0.12)
        self.declare_parameter("grasp_rotation_deg", 0.0)
        self.declare_parameter("grasp_pre_distance", 0.05)
        self.declare_parameter("grasp_lift_height", 0.08)
        self.declare_parameter("grasp_duration_scale", 1.0)
        self.declare_parameter("grasp_include_home", False)
        self.declare_parameter("grasp_approach_steps", 8)
        self.declare_parameter("grasp_approach_step_duration_ms", 180)

        self.declare_parameter("place_target_configured", False)
        self.declare_parameter("place_target_arm", [0.0, 0.0, 0.0])
        self.declare_parameter("place_duration_ms", 1200)
        self.declare_parameter("place_duration_scale", 1.0)
        self.declare_parameter("place_include_home", False)

    def _srv_execute_grasp_fixed(
        self,
        request: ExecuteGraspFixed.Request,
        response: ExecuteGraspFixed.Response,
    ) -> ExecuteGraspFixed.Response:
        target = (
            float(request.target_arm_base.x),
            float(request.target_arm_base.y),
            float(request.target_arm_base.z),
        )
        return self._finish_service(
            response,
            "grasp",
            lambda: self._execute_grasp(target),
        )

    def _srv_execute_place_fixed(
        self,
        _request: Trigger.Request,
        response: Trigger.Response,
    ) -> Trigger.Response:
        return self._finish_service(response, "place", self._execute_place)

    def _srv_preflight(
        self,
        _request: Trigger.Request,
        response: Trigger.Response,
    ) -> Trigger.Response:
        return self._finish_service(response, "preflight", self._run_preflight)

    def _finish_service(self, response, action: str, operation):
        if not self._busy_lock.acquire(blocking=False):
            payload = self._error_payload(
                action,
                "arm is busy with {}".format(self._active_action or "another request"),
            )
        else:
            self._active_action = action
            self._publish_status({
                "ok": False,
                "action": action,
                "state": "running",
                "motion_enabled": self._enable_motion,
            })
            try:
                payload = operation()
            except Exception as exc:
                self.get_logger().error("{} request failed: {}".format(action, exc))
                payload = self._error_payload(action, str(exc), exc.__class__.__name__)
            finally:
                self._active_action = ""
                self._busy_lock.release()

        response.success = bool(payload.get("ok", False))
        response.message = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        self._publish_status(payload)
        return response

    def _execute_grasp(self, target_arm_base: Point3) -> Dict[str, Any]:
        if not self._grasp_reference_configured:
            raise MotionServiceValidationError(
                "grasp_reference_configured is false; calibrate I1 and the grasp z range first"
            )
        if self._grasp_include_home:
            raise MotionServiceValidationError("grasp_include_home must remain false for transport")

        target = validate_grasp_target(
            target_arm_base,
            self._grasp_reference,
            self._grasp_xy_tolerance_m,
            self._grasp_z_min_m,
            self._grasp_z_max_m,
        )
        target_api, pose, steps = plan_face_approach_grasp(
            self._planner,
            target,
            rotation_deg=float(self.get_parameter("grasp_rotation_deg").value),
            pre_distance_m=float(self.get_parameter("grasp_pre_distance").value),
            lift_height_m=float(self.get_parameter("grasp_lift_height").value),
            duration_scale=float(self.get_parameter("grasp_duration_scale").value),
        )
        payload = self._action_payload(
            "grasp",
            steps,
            target_arm_base=target,
            target_arm_api=target_api,
            pose={
                "pre_point": list(pose.pre_point),
                "grasp_point": list(pose.grasp_point),
                "lift_point": list(pose.lift_point),
            },
        )
        self._publish_json(self._grasp_actions_pub, payload)
        return self._execute_or_plan(payload, steps)

    def _execute_place(self) -> Dict[str, Any]:
        if not self._place_target_configured:
            raise MotionServiceValidationError(
                "place_target_configured is false; calibrate place_target_arm first"
            )
        if self._place_include_home:
            raise MotionServiceValidationError("place_include_home must remain false for fixed placement")

        target_api, steps = plan_fixed_place(
            self._planner,
            self._place_target_arm,
            duration_ms=int(self.get_parameter("place_duration_ms").value),
            duration_scale=float(self.get_parameter("place_duration_scale").value),
        )
        payload = self._action_payload(
            "place",
            steps,
            target_arm_api=target_api,
        )
        self._publish_json(self._place_actions_pub, payload)
        return self._execute_or_plan(payload, steps)

    def _execute_or_plan(self, payload: Dict[str, Any], steps: Sequence[Any]) -> Dict[str, Any]:
        blocked_reason = self._motion_block_reason()
        if blocked_reason:
            payload["ok"] = False
            payload["state"] = "planned"
            payload["message"] = "motion not executed: {}".format(blocked_reason)
            return payload

        self._execute_steps(list(steps))
        payload["ok"] = True
        payload["state"] = "executed"
        payload["message"] = "motion sequence completed"
        return payload

    def _run_preflight(self) -> Dict[str, Any]:
        issues: List[str] = []
        checks: Dict[str, Any] = {
            "motion_enabled": self._enable_motion,
            "transform_calibrated": self._transform_calibrated,
            "grasp_reference_configured": self._grasp_reference_configured,
            "place_target_configured": self._place_target_configured,
            "tf_parent_frame": self._tf_parent_frame,
            "tf_child_frame": self._tf_child_frame,
            "servo_ids": [],
        }
        blocked_reason = self._motion_block_reason()
        if blocked_reason:
            issues.append(blocked_reason)
        if not self._grasp_reference_configured:
            issues.append("grasp_reference_arm_base is not marked calibrated")

        try:
            validate_grasp_target(
                (
                    float(self._grasp_reference[0]),
                    float(self._grasp_reference[1]),
                    (self._grasp_z_min_m + self._grasp_z_max_m) / 2.0,
                ),
                self._grasp_reference,
                self._grasp_xy_tolerance_m,
                self._grasp_z_min_m,
                self._grasp_z_max_m,
            )
        except Exception as exc:
            issues.append("invalid grasp configuration: {}".format(exc))

        try:
            if self._place_target_configured:
                plan_fixed_place(
                    self._planner,
                    self._place_target_arm,
                    duration_ms=int(self.get_parameter("place_duration_ms").value),
                    duration_scale=float(self.get_parameter("place_duration_scale").value),
                )
            else:
                issues.append("place_target_arm is not marked calibrated")
        except Exception as exc:
            issues.append("fixed placement plan failed: {}".format(exc))

        if self._require_tf_in_preflight:
            try:
                self._tf_buffer.lookup_transform(
                    self._tf_parent_frame,
                    self._tf_child_frame,
                    Time(),
                    timeout=Duration(seconds=self._tf_lookup_timeout_s),
                )
                checks["tf_available"] = True
            except TransformException as exc:
                checks["tf_available"] = False
                issues.append("required TF is unavailable: {}".format(exc))

        try:
            executor = BusLinkerExecutor(self._port, self._baud)
            with executor:
                checks["servo_ids"] = executor.require_servos_online()
        except Exception as exc:
            issues.append("servo preflight failed: {}".format(exc))

        return {
            "ok": not issues,
            "action": "preflight",
            "state": "passed" if not issues else "failed",
            "message": "preflight passed" if not issues else "; ".join(issues),
            "checks": checks,
        }

    def _motion_block_reason(self) -> str:
        reasons = []
        if not self._enable_motion:
            reasons.append("enable_motion is false")
        if not self._transform_calibrated:
            reasons.append("transform_calibrated is false")
        if self._grasp_include_home:
            reasons.append("grasp_include_home must be false")
        if self._place_include_home:
            reasons.append("place_include_home must be false")
        return "; ".join(reasons)

    def _execute_steps(self, steps: List[Any]) -> None:
        executor = BusLinkerExecutor(self._port, self._baud)
        with executor:
            executor.execute_steps(
                steps,
                dry_run=False,
                scan_first=self._scan_first,
                pause_s=self._pause_s,
            )

    def _action_payload(
        self,
        action: str,
        steps: Sequence[Any],
        target_arm_base: Point3 = None,
        target_arm_api: Point3 = None,
        pose: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "ok": False,
            "action": action,
            "state": "planned",
            "motion_enabled": self._enable_motion,
            "transform_calibrated": self._transform_calibrated,
            "num_steps": len(steps),
            "steps": [step.to_command() for step in steps],
        }
        if target_arm_base is not None:
            payload["target_arm_base_link"] = self._point_dict(target_arm_base)
        if target_arm_api is not None:
            payload["target_arm_api"] = self._point_dict(target_arm_api)
        if pose is not None:
            payload["pose"] = pose
        return payload

    def _error_payload(self, action: str, message: str, error_type: str = "") -> Dict[str, Any]:
        payload = {
            "ok": False,
            "action": action,
            "state": "error",
            "message": message,
            "motion_enabled": self._enable_motion,
            "transform_calibrated": self._transform_calibrated,
        }
        if error_type:
            payload["error_type"] = error_type
        return payload

    def _publish_status(self, payload: Dict[str, Any]) -> None:
        status = dict(payload)
        status.pop("steps", None)
        self._publish_json(self._status_pub, status)

    @staticmethod
    def _point_dict(point: Point3) -> Dict[str, float]:
        return {"x": float(point[0]), "y": float(point[1]), "z": float(point[2])}

    @staticmethod
    def _normalize_frame(frame_id: str) -> str:
        return str(frame_id).strip().lstrip("/")

    @staticmethod
    def _publish_json(publisher, payload: Dict[str, Any]) -> None:
        message = String()
        message.data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        publisher.publish(message)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ArmMotionNode()
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
