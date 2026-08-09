#!/usr/bin/env python3
# coding: utf-8

"""ROS2 adapter for the arm_new grasp pipeline.

This node intentionally stays thin:
  /yolo/detections JSON -> arm_new API -> optional BusLinker execution.

All services use std_srvs/Trigger in the first version. The response message is
JSON so the pipeline can be tested without adding custom ROS interfaces yet.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.time import Time
from std_msgs.msg import String
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformListener


def _find_arm_new_root() -> Path:
    """Find the arm_new root from this package location."""

    env_root = os.environ.get("ARM_NEW_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()

    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "arm_api").is_dir():
            return parent
    # Installed layout fallback: allow caller to pass arm_new_root parameter.
    return current.parents[2]


_DEFAULT_ARM_NEW_ROOT = _find_arm_new_root()
if str(_DEFAULT_ARM_NEW_ROOT) not in sys.path:
    sys.path.insert(0, str(_DEFAULT_ARM_NEW_ROOT))

from arm_api import (  # noqa: E402
    ArmGrabConfig,
    ArmGrabPlannerNew,
    BusLinkerExecutor,
    CameraIntrinsics,
    MotionStep,
    yolo_payload_to_camera_point,
)


Point3 = Tuple[float, float, float]


class ArmGraspNode(Node):
    """Bridge ROS2 detections to arm_new planning/execution APIs."""

    def __init__(self) -> None:
        super().__init__("arm_grasp_node")

        self.declare_parameter("arm_new_root", str(_DEFAULT_ARM_NEW_ROOT))
        self.declare_parameter("yolo_topic", "/yolo/detections")
        self.declare_parameter("target_class_name", "red")
        self.declare_parameter("target_class_id", 0)
        self.declare_parameter("min_confidence", 0.5)
        self.declare_parameter("expected_frame_id", "d455_color_optical_frame")
        self.declare_parameter("target_tf_frame", "arm_base_link")
        self.declare_parameter("tf_lookup_timeout_s", 1.0)
        self.declare_parameter("transform_calibrated", False)
        self.declare_parameter("max_detection_age_sec", 1.0)

        self.declare_parameter("camera_fx", 617.0)
        self.declare_parameter("camera_fy", 617.0)
        self.declare_parameter("camera_cx", 320.0)
        self.declare_parameter("camera_cy", 240.0)

        self.declare_parameter("port", "/dev/ttyACM0")
        self.declare_parameter("baud", 115200)
        self.declare_parameter("pause_s", 0.2)
        self.declare_parameter("scan_first", True)
        self.declare_parameter("enable_motion", False)

        self.declare_parameter("rotation_deg", 0.0)
        self.declare_parameter("pre_distance", 0.05)
        self.declare_parameter("lift_height", 0.08)
        self.declare_parameter("include_home", False)
        self.declare_parameter("approach_steps", 8)
        self.declare_parameter("approach_step_duration_ms", 180)

        self.declare_parameter("release_gripper_pulse", 75)
        self.declare_parameter("release_duration_ms", 600)
        self.declare_parameter("release_go_home", True)

        self._arm_new_root = Path(str(self.get_parameter("arm_new_root").value)).resolve()
        self._target_class_name = str(self.get_parameter("target_class_name").value)
        self._target_class_id = int(self.get_parameter("target_class_id").value)
        self._min_confidence = float(self.get_parameter("min_confidence").value)
        self._expected_frame_id = str(self.get_parameter("expected_frame_id").value)
        self._target_tf_frame = str(self.get_parameter("target_tf_frame").value)
        self._tf_lookup_timeout_s = max(
            0.0, float(self.get_parameter("tf_lookup_timeout_s").value)
        )
        self._transform_calibrated = bool(
            self.get_parameter("transform_calibrated").value
        )
        self._max_detection_age_sec = float(self.get_parameter("max_detection_age_sec").value)

        self._port = str(self.get_parameter("port").value)
        self._baud = int(self.get_parameter("baud").value)
        self._pause_s = float(self.get_parameter("pause_s").value)
        self._scan_first = bool(self.get_parameter("scan_first").value)
        self._enable_motion = bool(self.get_parameter("enable_motion").value)

        self._rotation_deg = float(self.get_parameter("rotation_deg").value)
        self._pre_distance = float(self.get_parameter("pre_distance").value)
        self._lift_height = float(self.get_parameter("lift_height").value)
        self._include_home = bool(self.get_parameter("include_home").value)

        self._latest_yolo: Optional[str] = None
        self._latest_yolo_time: Optional[float] = None

        self._intrinsics = CameraIntrinsics(
            fx=float(self.get_parameter("camera_fx").value),
            fy=float(self.get_parameter("camera_fy").value),
            cx=float(self.get_parameter("camera_cx").value),
            cy=float(self.get_parameter("camera_cy").value),
        )
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)

        planner_config = ArmGrabConfig(
            approach_steps=max(1, int(self.get_parameter("approach_steps").value)),
            approach_step_duration_ms=max(
                1,
                int(self.get_parameter("approach_step_duration_ms").value),
            ),
        )
        self._planner = ArmGrabPlannerNew(config=planner_config)

        yolo_topic = str(self.get_parameter("yolo_topic").value)
        self._yolo_sub = self.create_subscription(
            String,
            yolo_topic,
            self._on_yolo,
            1,
        )

        self.create_service(Trigger, "/arm/debug_get_camera_target", self._srv_camera_target)
        self.create_service(Trigger, "/arm/debug_get_arm_target", self._srv_arm_target)
        self.create_service(Trigger, "/arm/dry_run_grab_red", self._srv_dry_run_grab)
        self.create_service(Trigger, "/arm/grab_red", self._srv_grab_red)
        self.create_service(Trigger, "/arm/release_fixed", self._srv_release_fixed)

        self.get_logger().info(
            "arm_grasp_node ready: yolo_topic={} arm_new_root={} tf={} -> {} "
            "transform_calibrated={}".format(
                yolo_topic,
                self._arm_new_root,
                self._expected_frame_id,
                self._target_tf_frame,
                self._transform_calibrated,
            )
        )

    def _on_yolo(self, msg: String) -> None:
        self._latest_yolo = msg.data
        self._latest_yolo_time = time.monotonic()

    def _srv_camera_target(self, _request: Trigger.Request, response: Trigger.Response) -> Trigger.Response:
        return self._finish_trigger(response, lambda: self._build_target_context(include_arm=False))

    def _srv_arm_target(self, _request: Trigger.Request, response: Trigger.Response) -> Trigger.Response:
        return self._finish_trigger(response, lambda: self._build_target_context(include_arm=True))

    def _srv_dry_run_grab(self, _request: Trigger.Request, response: Trigger.Response) -> Trigger.Response:
        return self._finish_trigger(response, lambda: self._plan_grab(dry_run=True, execute=False))

    def _srv_grab_red(self, _request: Trigger.Request, response: Trigger.Response) -> Trigger.Response:
        return self._finish_trigger(response, lambda: self._plan_grab(dry_run=False, execute=True))

    def _srv_release_fixed(self, _request: Trigger.Request, response: Trigger.Response) -> Trigger.Response:
        return self._finish_trigger(response, lambda: self._release_fixed())

    def _finish_trigger(self, response: Trigger.Response, fn) -> Trigger.Response:
        try:
            result = fn()
            response.success = bool(result.get("ok", False))
            response.message = json.dumps(result, ensure_ascii=False, sort_keys=True)
        except Exception as exc:  # Keep ROS service alive and return a useful error.
            self.get_logger().error(str(exc))
            response.success = False
            response.message = json.dumps(
                {
                    "ok": False,
                    "message": str(exc),
                    "error_type": exc.__class__.__name__,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        return response

    def _build_target_context(self, include_arm: bool = True) -> Dict[str, Any]:
        payload = self._fresh_yolo_payload()
        target = yolo_payload_to_camera_point(
            payload,
            intrinsics=self._intrinsics,
            target_classes=(self._target_class_name,),
            target_class_ids=(self._target_class_id,),
            min_confidence=self._min_confidence,
        )
        self._check_frame_id(target.frame_id)

        result: Dict[str, Any] = {
            "ok": True,
            "message": "ok",
            "target_class_name": self._target_class_name,
            "target_class_id": self._target_class_id,
            "target_camera": target.to_dict(),
            "detection_age_sec": self._detection_age(),
        }

        if include_arm:
            point_arm_base = self._camera_to_arm_base(target.point, target.frame_id)
            point_arm = self._arm_base_to_api(point_arm_base)
            result["target_arm_base_link"] = self._point_dict(point_arm_base)
            result["target_arm"] = self._point_dict(point_arm)
        return result

    def _fresh_yolo_payload(self) -> str:
        if self._latest_yolo is None or self._latest_yolo_time is None:
            raise RuntimeError("no /yolo/detections message has been received")
        age = self._detection_age()
        if age > self._max_detection_age_sec:
            raise RuntimeError(
                "latest /yolo/detections is too old: {:.3f}s > {:.3f}s".format(
                    age,
                    self._max_detection_age_sec,
                )
            )
        return self._latest_yolo

    def _detection_age(self) -> float:
        if self._latest_yolo_time is None:
            return float("inf")
        return time.monotonic() - self._latest_yolo_time

    def _check_frame_id(self, frame_id: Optional[str]) -> None:
        if not self._expected_frame_id:
            return
        if frame_id != self._expected_frame_id:
            raise RuntimeError(
                "unexpected YOLO frame_id: {!r}, expected {!r}".format(
                    frame_id,
                    self._expected_frame_id,
                )
            )

    def _camera_to_arm_base(
        self, point_camera: Point3, source_frame: Optional[str]
    ) -> Point3:
        if not source_frame:
            raise RuntimeError("YOLO target does not contain a source frame_id")
        transform = self._tf_buffer.lookup_transform(
            self._target_tf_frame,
            source_frame,
            Time(),
            timeout=Duration(seconds=self._tf_lookup_timeout_s),
        )
        translation = transform.transform.translation
        rotation = transform.transform.rotation
        return self._rotate_and_translate(
            point_camera,
            (rotation.x, rotation.y, rotation.z, rotation.w),
            (translation.x, translation.y, translation.z),
        )

    @staticmethod
    def _arm_base_to_api(point_arm_base: Point3) -> Point3:
        x_base, y_base, z_base = point_arm_base
        return (-y_base, x_base, z_base)

    @staticmethod
    def _rotate_and_translate(
        point: Point3,
        quaternion_xyzw: Tuple[float, float, float, float],
        translation: Point3,
    ) -> Point3:
        x, y, z, w = (float(value) for value in quaternion_xyzw)
        px, py, pz = point
        tx, ty, tz = translation
        return (
            (1.0 - 2.0 * (y * y + z * z)) * px
            + 2.0 * (x * y - z * w) * py
            + 2.0 * (x * z + y * w) * pz
            + tx,
            2.0 * (x * y + z * w) * px
            + (1.0 - 2.0 * (x * x + z * z)) * py
            + 2.0 * (y * z - x * w) * pz
            + ty,
            2.0 * (x * z - y * w) * px
            + 2.0 * (y * z + x * w) * py
            + (1.0 - 2.0 * (x * x + y * y)) * pz
            + tz,
        )

    def _plan_grab(self, dry_run: bool, execute: bool) -> Dict[str, Any]:
        context = self._build_target_context(include_arm=True)
        point_arm = self._point_tuple(context["target_arm"])
        steps = self._planner.plan_horizontal_face_grab(
            point_arm,
            rotation_deg=self._rotation_deg,
            pre_distance=self._pre_distance,
            lift_height=self._lift_height,
            include_home=self._include_home,
        )
        context["steps"] = self._steps_to_dicts(steps)
        context["num_steps"] = len(steps)
        context["dry_run"] = bool(dry_run)
        context["executed"] = False

        if execute:
            self._require_motion_enabled("/arm/grab_red")
            self._execute_steps(steps, dry_run=False)
            context["executed"] = True
            context["message"] = "motion finished"
        else:
            self._execute_steps(steps, dry_run=True)
            context["message"] = "dry-run finished"
        return context

    def _release_fixed(self) -> Dict[str, Any]:
        release_pulse = int(self.get_parameter("release_gripper_pulse").value)
        duration_ms = int(self.get_parameter("release_duration_ms").value)
        release_go_home = bool(self.get_parameter("release_go_home").value)

        steps: List[MotionStep] = [
            MotionStep(
                "release_open_gripper",
                None,
                duration_ms,
                ((1, release_pulse),),
            )
        ]
        if release_go_home:
            steps.append(self._planner._home_step())

        self._require_motion_enabled("/arm/release_fixed")
        self._execute_steps(steps, dry_run=False)
        return {
            "ok": True,
            "message": "release finished",
            "steps": self._steps_to_dicts(steps),
            "num_steps": len(steps),
            "executed": True,
        }

    def _require_motion_enabled(self, service_name: str) -> None:
        if not self._enable_motion:
            raise RuntimeError(
                "{} refused: enable_motion is false; use /arm/dry_run_grab_red "
                "or start node with enable_motion:=true".format(service_name)
            )
        if not self._transform_calibrated:
            raise RuntimeError(
                "{} refused: camera-to-arm TF is provisional; validate it and set "
                "transform_calibrated:=true before real motion".format(service_name)
            )

    def _execute_steps(self, steps: List[MotionStep], dry_run: bool) -> None:
        executor = BusLinkerExecutor(self._port, self._baud)
        if dry_run:
            executor.execute_steps(
                steps,
                dry_run=True,
                scan_first=False,
                pause_s=self._pause_s,
            )
            return
        with executor:
            executor.execute_steps(
                steps,
                dry_run=False,
                scan_first=self._scan_first,
                pause_s=self._pause_s,
            )

    @staticmethod
    def _point_dict(point: Point3) -> Dict[str, float]:
        return {
            "x": float(point[0]),
            "y": float(point[1]),
            "z": float(point[2]),
        }

    @staticmethod
    def _point_tuple(point: Dict[str, Any]) -> Point3:
        return (float(point["x"]), float(point["y"]), float(point["z"]))

    @staticmethod
    def _steps_to_dicts(steps: List[MotionStep]) -> List[Dict[str, Any]]:
        return [step.to_command() for step in steps]


def main(args: Optional[List[str]] = None) -> None:
    rclpy.init(args=args)
    node = ArmGraspNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
