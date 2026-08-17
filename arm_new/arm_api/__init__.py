#!/usr/bin/env python3
# coding: utf-8

"""ArmPi 抓取 API。

包入口尽量保持轻量：只导入 common 和 BusLinker 执行层。
IK 和完整服务层会在真正访问对应名字时再加载。
"""

from .buslinker import BusLinkerExecutor, SerialUnavailable
from .common import (
    INITIAL_POSITION_SERVOS,
    IKNoSolution,
    MotionStep,
    OriginalIKUnavailable,
    angle_to_pulse,
    clamp,
    pulse_to_angle,
    steps_to_commands,
)


_LAZY_IMPORTS = {
    "ArmGrabConfig": (".planner", "ArmGrabConfig"),
    "ArmGrabPlanner": (".planner", "ArmGrabPlanner"),
    "LocalGeometricArmIK": (".planner", "LocalGeometricArmIK"),
    "plan_grab_motion": (".planner", "plan_grab_motion"),
    "ArmGrabPlannerNew": (".planner_new", "ArmGrabPlannerNew"),
    "GeneratedFaceGraspPose": (".planner_new", "GeneratedFaceGraspPose"),
    "PoseConstrainedArmIK": (".planner_new", "PoseConstrainedArmIK"),
    "plan_grab_motion_new": (".planner_new", "plan_grab_motion_new"),
    "plan_place_motion_new": (".planner_new", "plan_place_motion_new"),
    "plan_lie_down": (".posture", "plan_lie_down"),
    "plan_stand_up": (".posture", "plan_stand_up"),
    "FrameTransformer": (".transforms", "FrameTransformer"),
    "TransformError": (".transforms", "TransformError"),
    "load_transform_config": (".transforms", "load_transform_config"),
    "transform_point": (".transforms", "transform_point"),
    "CameraIntrinsics": (".yolo_target", "CameraIntrinsics"),
    "TargetCameraPoint": (".yolo_target", "TargetCameraPoint"),
    "YoloTargetError": (".yolo_target", "YoloTargetError"),
    "choose_detection": (".yolo_target", "choose_detection"),
    "detection_to_camera_point": (".yolo_target", "detection_to_camera_point"),
    "parse_yolo_payload": (".yolo_target", "parse_yolo_payload"),
    "yolo_payload_to_camera_point": (".yolo_target", "yolo_payload_to_camera_point"),
    "ArmService": (".service", "ArmService"),
    "ArmServiceConfig": (".service", "ArmServiceConfig"),
    "ArmServiceResult": (".service", "ArmServiceResult"),
    "make_gripper_smoke_test_steps": (".service", "make_gripper_smoke_test_steps"),
    "make_home_step": (".service", "make_home_step"),
}


def __getattr__(name):
    """按需导入重依赖对象。"""

    if name not in _LAZY_IMPORTS:
        raise AttributeError("module 'arm_api' has no attribute {!r}".format(name))

    module_name, attr_name = _LAZY_IMPORTS[name]
    import importlib

    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


__all__ = [
    "ArmGrabConfig",
    "ArmGrabPlannerNew",
    "ArmGrabPlanner",
    "ArmService",
    "ArmServiceConfig",
    "ArmServiceResult",
    "BusLinkerExecutor",
    "GeneratedFaceGraspPose",
    "INITIAL_POSITION_SERVOS",
    "IKNoSolution",
    "LocalGeometricArmIK",
    "MotionStep",
    "OriginalIKUnavailable",
    "PoseConstrainedArmIK",
    "SerialUnavailable",
    "FrameTransformer",
    "TransformError",
    "CameraIntrinsics",
    "TargetCameraPoint",
    "YoloTargetError",
    "angle_to_pulse",
    "choose_detection",
    "clamp",
    "detection_to_camera_point",
    "load_transform_config",
    "make_gripper_smoke_test_steps",
    "make_home_step",
    "parse_yolo_payload",
    "plan_grab_motion",
    "plan_grab_motion_new",
    "plan_place_motion_new",
    "plan_lie_down",
    "plan_stand_up",
    "pulse_to_angle",
    "steps_to_commands",
    "transform_point",
    "yolo_payload_to_camera_point",
]
