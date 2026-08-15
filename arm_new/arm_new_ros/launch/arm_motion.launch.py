#!/usr/bin/env python3
"""Launch the arm service node without publishing project TF."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    package_share = Path(get_package_share_directory("arm_new_ros"))
    default_params = package_share / "config" / "arm_motion_params.yaml"

    return LaunchDescription([
        DeclareLaunchArgument(
            "params_file",
            default_value=str(default_params),
            description="Path to arm_motion_node ROS parameters",
        ),
        Node(
            package="arm_new_ros",
            executable="arm_motion_node",
            name="arm_motion_node",
            # Keep the production defaults when a small supervised-test
            # parameter file overrides only motion authorization or placement.
            parameters=[default_params, LaunchConfiguration("params_file")],
            output="screen",
        ),
    ])
