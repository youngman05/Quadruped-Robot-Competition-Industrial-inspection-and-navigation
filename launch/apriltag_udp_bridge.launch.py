#!/usr/bin/env python3
"""Start the Host AprilTag pose bridge."""

from pathlib import Path

from launch import LaunchDescription
from launch_ros.actions import Node


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription([
        Node(
            package="quadruped_robot_competition",
            executable="apriltag_udp_bridge",
            name="apriltag_udp_bridge_node",
            parameters=[str(PROJECT_ROOT / "configs" / "ros" / "competition_params.yaml")],
            output="screen",
        ),
    ])
