#!/usr/bin/env python3
"""Launch the Foxy Nav2 stack for the competition map.

Prerequisites:
  - /odom and odom -> base_link TF are published by the cuVSLAM bridge.
  - base_link -> camera_link static TF is published by competition.launch.py.
  - Nav2 and precision control are arbitrated into one /cmd_vel output.
"""

from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, TimerAction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PARAMS = str(PROJECT_ROOT / "configs" / "navigation" / "nav2_params.yaml")
DEFAULT_MAP = str(PROJECT_ROOT / "navi" / "map" / "competition_field_phase1.yaml")
DEFAULT_BT_XML = str(
    Path(get_package_share_directory("nav2_bt_navigator"))
    / "behavior_trees"
    / "navigate_w_replanning_and_recovery.xml"
)


def generate_launch_description() -> LaunchDescription:
    params_file = LaunchConfiguration("params_file")
    map_yaml = LaunchConfiguration("map_yaml")

    declare_params = DeclareLaunchArgument(
        "params_file",
        default_value=DEFAULT_PARAMS,
        description="Absolute path to Nav2 parameter YAML.",
    )
    declare_map = DeclareLaunchArgument(
        "map_yaml",
        default_value=DEFAULT_MAP,
        description="Absolute path to the active Nav2 map YAML.",
    )

    map_server = Node(
        package="nav2_map_server",
        executable="map_server",
        name="map_server",
        output="screen",
        parameters=[{
            "use_sim_time": False,
            "yaml_filename": map_yaml,
            "frame_id": "map",
            "topic_name": "/map",
        }],
    )

    planner = Node(
        package="nav2_planner",
        executable="planner_server",
        name="planner_server",
        output="screen",
        parameters=[params_file],
    )

    controller = Node(
        package="nav2_controller",
        executable="controller_server",
        name="controller_server",
        output="screen",
        parameters=[params_file],
        remappings=[("/cmd_vel", "/cmd_vel_nav2")],
    )

    recoveries = Node(
        package="nav2_recoveries",
        executable="recoveries_server",
        name="recoveries_server",
        output="screen",
        parameters=[params_file],
        remappings=[("/cmd_vel", "/cmd_vel_nav2")],
    )

    cmd_vel_arbiter = Node(
        package="quadruped_robot_competition",
        executable="cmd_vel_arbiter",
        name="cmd_vel_arbiter",
        output="screen",
    )

    bt_navigator = Node(
        package="nav2_bt_navigator",
        executable="bt_navigator",
        name="bt_navigator",
        output="screen",
        parameters=[params_file, {"default_bt_xml_filename": DEFAULT_BT_XML}],
    )

    lifecycle = Node(
        package="nav2_lifecycle_manager",
        executable="lifecycle_manager",
        name="lifecycle_manager",
        output="screen",
        parameters=[params_file],
    )

    startup_info = LogInfo(
        msg=[
            "Nav2 Foxy DWB stack starting | map: ",
            map_yaml,
            " | params: ",
            params_file,
            " | cmd_vel: /cmd_vel_nav2 + /cmd_vel_precision -> /cmd_vel",
        ]
    )

    return LaunchDescription([
        declare_params,
        declare_map,
        startup_info,
        map_server,
        cmd_vel_arbiter,
        planner,
        controller,
        recoveries,
        bt_navigator,
        TimerAction(period=3.0, actions=[lifecycle]),
    ])
