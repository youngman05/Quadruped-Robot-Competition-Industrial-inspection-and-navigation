#!/usr/bin/env python3
"""Publish the project-owned static extrinsics from one YAML file.

This launch file reads ``configs/transforms/static_extrinsics.yaml`` and emits
one ``tf2_ros/static_transform_publisher`` node for every transform whose
``publish`` flag is true. It is used by ``arm_new_ros/arm_motion.launch.py``
and can also be launched directly from the competition workspace.
"""

from pathlib import Path

import yaml
from ament_index_python.packages import PackageNotFoundError, get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def _static_extrinsics_path() -> Path:
    """Locate static_extrinsics.yaml in installed or source space."""

    try:
        package_share = Path(get_package_share_directory("quadruped_robot_competition"))
        config_path = package_share / "configs" / "transforms" / "static_extrinsics.yaml"
        if config_path.is_file():
            return config_path
    except PackageNotFoundError:
        pass

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "configs" / "transforms" / "static_extrinsics.yaml"
        if candidate.is_file():
            return candidate
    raise RuntimeError("Cannot locate configs/transforms/static_extrinsics.yaml")


def _quaternion_xyzw(value):
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("rotation_xyzw must contain four numbers")
    return tuple(float(item) for item in value)


def _translation_m(value):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("translation_m must contain three numbers")
    return tuple(float(item) for item in value)


def generate_launch_description():
    config_path = _static_extrinsics_path()
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    nodes = []
    for transform in data.get("static_transforms", []):
        if not transform.get("publish", False):
            continue
        parent_frame = transform.get("parent_frame")
        child_frame = transform.get("child_frame")
        translation = _translation_m(transform.get("translation_m"))
        rotation = _quaternion_xyzw(transform.get("rotation_xyzw"))
        if not parent_frame or not child_frame:
            continue
        nodes.append(
            Node(
                package="tf2_ros",
                executable="static_transform_publisher",
                name="static_tf_{}_{}".format(parent_frame, child_frame),
                arguments=[
                    str(translation[0]),
                    str(translation[1]),
                    str(translation[2]),
                    str(rotation[0]),
                    str(rotation[1]),
                    str(rotation[2]),
                    str(rotation[3]),
                    str(parent_frame),
                    str(child_frame),
                ],
                output="screen",
            )
        )

    return LaunchDescription(nodes)
