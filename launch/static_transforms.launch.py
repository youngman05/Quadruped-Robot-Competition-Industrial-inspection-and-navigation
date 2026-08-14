#!/usr/bin/env python3
"""Publish project-owned static transforms from the canonical YAML config."""

from pathlib import Path

import yaml
from launch import LaunchDescription
from launch_ros.actions import Node


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "configs" / "transforms" / "static_extrinsics.yaml"


def _load_transforms():
    with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)

    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise RuntimeError(f"Unsupported static extrinsics config: {CONFIG_PATH}")
    if config.get("convention", {}).get("quaternion_order") != "xyzw":
        raise RuntimeError("Static extrinsics must use xyzw quaternions")

    transforms = config.get("static_transforms")
    if not isinstance(transforms, list):
        raise RuntimeError("static_transforms must be a list")

    children = set()
    published = []
    for transform in transforms:
        if not isinstance(transform, dict) or not transform.get("publish", False):
            continue
        parent = transform.get("parent_frame")
        child = transform.get("child_frame")
        translation = transform.get("translation_m")
        rotation = transform.get("rotation_xyzw")
        if not isinstance(parent, str) or not isinstance(child, str) or parent == child:
            raise RuntimeError(f"Invalid static transform frames: {transform}")
        if child in children:
            raise RuntimeError(f"Duplicate static-transform child frame: {child}")
        if not isinstance(translation, list) or len(translation) != 3:
            raise RuntimeError(f"Invalid translation for {parent}->{child}")
        if not isinstance(rotation, list) or len(rotation) != 4:
            raise RuntimeError(f"Invalid xyzw quaternion for {parent}->{child}")
        norm_squared = sum(float(value) ** 2 for value in rotation)
        if not 0.999 <= norm_squared <= 1.001:
            raise RuntimeError(f"Non-unit quaternion for {parent}->{child}")
        children.add(child)
        published.append((parent, child, translation, rotation))
    return published


def generate_launch_description() -> LaunchDescription:
    transform_nodes = []
    for index, (parent, child, translation, rotation) in enumerate(_load_transforms()):
        transform_nodes.append(Node(
            package="quadruped_robot_competition",
            executable="project_static_transform_publisher",
            name=f"project_static_tf_{index}",
            parameters=[{
                "parent_frame": parent,
                "child_frame": child,
                "translation_m": [float(value) for value in translation],
                "rotation_xyzw": [float(value) for value in rotation],
            }],
            output="screen",
        ))
    return LaunchDescription(transform_nodes)
