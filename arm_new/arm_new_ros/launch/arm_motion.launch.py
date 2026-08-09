#!/usr/bin/env python3
"""Launch the standalone camera_link-to-arm motion node."""

from pathlib import Path

from ament_index_python.packages import PackageNotFoundError, get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _static_transforms_launch() -> Path:
    """Locate the canonical static-transform launch in source or install space."""

    try:
        package_share = Path(get_package_share_directory("quadruped_robot_competition"))
        launch_path = package_share / "launch" / "static_transforms.launch.py"
        if launch_path.is_file():
            return launch_path
    except PackageNotFoundError:
        pass

    for parent in Path(__file__).resolve().parents:
        if (
            (parent / "configs" / "transforms" / "static_extrinsics.yaml").is_file()
            and (parent / "launch" / "static_transforms.launch.py").is_file()
        ):
            return parent
    raise RuntimeError(
        "Cannot locate configs/transforms/static_extrinsics.yaml. "
        "Launch the arm node from the competition workspace or disable "
        "publish_static_transforms and start launch/static_transforms.launch.py separately."
    )


STATIC_TRANSFORMS_LAUNCH = _static_transforms_launch()


def generate_launch_description():
    package_share = Path(get_package_share_directory("arm_new_ros"))
    default_params = package_share / "config" / "arm_motion_params.yaml"

    return LaunchDescription([
        DeclareLaunchArgument(
            "params_file",
            default_value=str(default_params),
            description="Path to arm_motion_node ROS parameters",
        ),
        DeclareLaunchArgument(
            "publish_static_transforms",
            default_value="true",
            description="Publish canonical project static TF from configs/transforms/static_extrinsics.yaml",
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(STATIC_TRANSFORMS_LAUNCH)),
            condition=IfCondition(LaunchConfiguration("publish_static_transforms")),
        ),
        Node(
            package="arm_new_ros",
            executable="arm_motion_node",
            name="arm_motion_node",
            parameters=[LaunchConfiguration("params_file")],
            output="screen",
        ),
    ])
