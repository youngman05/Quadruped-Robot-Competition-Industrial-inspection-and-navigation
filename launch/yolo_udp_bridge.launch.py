#!/usr/bin/env python3
"""Start the Host D455 YOLO UDP bridge using the existing DWB TF tree."""

from pathlib import Path

from launch import LaunchDescription
from launch_ros.actions import Node


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARAMS_FILE = PROJECT_ROOT / "configs" / "ros" / "competition_params.yaml"


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription([
        Node(
            package="quadruped_robot_competition",
            executable="yolo_udp_bridge",
            name="yolo_udp_bridge_node",
            parameters=[str(PARAMS_FILE)],
            output="screen",
        ),
    ])
