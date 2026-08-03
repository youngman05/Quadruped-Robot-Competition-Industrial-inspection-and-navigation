#!/usr/bin/env python3
"""Start the Host D455 YOLO UDP bridge with its project static TF tree."""

from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARAMS_FILE = PROJECT_ROOT / "configs" / "ros" / "competition_params.yaml"
STATIC_TRANSFORMS_LAUNCH = PROJECT_ROOT / "launch" / "static_transforms.launch.py"


def generate_launch_description() -> LaunchDescription:
    publish_static_transforms = LaunchConfiguration("publish_static_transforms", default="true")
    return LaunchDescription([
        DeclareLaunchArgument(
            "publish_static_transforms", default_value="true",
            description="Publish project-owned static extrinsics from config",
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(STATIC_TRANSFORMS_LAUNCH)),
            condition=IfCondition(publish_static_transforms),
        ),
        Node(
            package="quadruped_robot_competition",
            executable="yolo_udp_bridge",
            name="yolo_udp_bridge_node",
            parameters=[str(PARAMS_FILE)],
            output="screen",
        ),
    ])
