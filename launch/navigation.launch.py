#!/usr/bin/env python3
"""Launch the Foxy Nav2 stack for the single Phase 1 competition map."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, TimerAction
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PARAMS = str(PROJECT_ROOT / "configs" / "navigation" / "nav2_params.yaml")
DEFAULT_DEPTH_PARAMS = str(
    PROJECT_ROOT / "configs" / "navigation" / "nav2_depth_obstacles.yaml"
)
DEFAULT_MAP = str(PROJECT_ROOT / "navi" / "map" / "competition_field_phase1.yaml")
DEFAULT_BT_XML = str(
    Path(get_package_share_directory("nav2_bt_navigator"))
    / "behavior_trees"
    / "navigate_w_replanning_and_recovery.xml"
)


def generate_launch_description() -> LaunchDescription:
    params_file = LaunchConfiguration("params_file")
    map_yaml = LaunchConfiguration("map_yaml")
    enable_depth_pipeline = LaunchConfiguration("enable_depth_pipeline")
    depth_params_file = LaunchConfiguration("depth_params_file")
    depth_frames_dir = LaunchConfiguration("depth_frames_dir")

    declare_params = DeclareLaunchArgument(
        "params_file",
        default_value=DEFAULT_PARAMS,
        description="Absolute path to the stable Nav2 parameter YAML.",
    )
    declare_map = DeclareLaunchArgument(
        "map_yaml",
        default_value=DEFAULT_MAP,
        description="Absolute path to the active Nav2 map YAML.",
    )
    declare_enable_depth_pipeline = DeclareLaunchArgument(
        "enable_depth_pipeline",
        default_value="false",
        description=(
            "Enable relayed D455 pointcloud, dynamic costmaps, and the "
            "fail-closed velocity gate."
        ),
    )
    declare_depth_params = DeclareLaunchArgument(
        "depth_params_file",
        default_value=DEFAULT_DEPTH_PARAMS,
        description="Nav2 dynamic-obstacle parameter overlay.",
    )
    declare_depth_frames_dir = DeclareLaunchArgument(
        "depth_frames_dir",
        default_value=str(
            Path.home() / "workspaces" / "isaac_ros-dev" / "camera_frames"
        ),
        description="Host directory shared with the Docker depth relay.",
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

    planner_static = Node(
        package="nav2_planner",
        executable="planner_server",
        name="planner_server",
        output="screen",
        parameters=[params_file],
        condition=UnlessCondition(enable_depth_pipeline),
    )
    planner_depth = Node(
        package="nav2_planner",
        executable="planner_server",
        name="planner_server",
        output="screen",
        parameters=[params_file, depth_params_file],
        condition=IfCondition(enable_depth_pipeline),
    )

    controller_static = Node(
        package="nav2_controller",
        executable="controller_server",
        name="controller_server",
        output="screen",
        parameters=[params_file],
        remappings=[("/cmd_vel", "/cmd_vel_nav2")],
        condition=UnlessCondition(enable_depth_pipeline),
    )
    controller_depth = Node(
        package="nav2_controller",
        executable="controller_server",
        name="controller_server",
        output="screen",
        parameters=[params_file, depth_params_file],
        remappings=[("/cmd_vel", "/cmd_vel_nav2")],
        condition=IfCondition(enable_depth_pipeline),
    )

    recoveries = Node(
        package="nav2_recoveries",
        executable="recoveries_server",
        name="recoveries_server",
        output="screen",
        parameters=[params_file],
        remappings=[("/cmd_vel", "/cmd_vel_nav2")],
    )

    cmd_vel_arbiter_direct = Node(
        package="quadruped_robot_competition",
        executable="cmd_vel_arbiter",
        name="cmd_vel_arbiter",
        output="screen",
        parameters=[{"output_topic": "/cmd_vel"}],
        condition=UnlessCondition(enable_depth_pipeline),
    )
    cmd_vel_arbiter_gated = Node(
        package="quadruped_robot_competition",
        executable="cmd_vel_arbiter",
        name="cmd_vel_arbiter",
        output="screen",
        parameters=[{"output_topic": "/cmd_vel_selected"}],
        condition=IfCondition(enable_depth_pipeline),
    )

    depth_relay_publisher = Node(
        package="quadruped_robot_competition",
        executable="depth_relay_publisher",
        name="depth_relay_publisher",
        output="screen",
        parameters=[{"frames_dir": depth_frames_dir}],
        condition=IfCondition(enable_depth_pipeline),
    )
    depth_optical_tf = Node(
        package="tf2_ros",
        executable="static_transform_publisher",
        name="camera_depth_optical_tf",
        arguments=[
            "0", "0", "0",
            "-0.5", "0.5", "-0.5", "0.5",
            "camera_link", "camera_depth_optical_frame",
        ],
        output="screen",
        condition=IfCondition(enable_depth_pipeline),
    )
    depth_safety_gate = Node(
        package="quadruped_robot_competition",
        executable="depth_safety_gate",
        name="depth_safety_gate",
        output="screen",
        condition=IfCondition(enable_depth_pipeline),
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
            " | depth_pipeline: ",
            enable_depth_pipeline,
            " | cmd_vel: Nav2/precision -> arbiter -> optional depth gate -> /cmd_vel",
        ]
    )

    return LaunchDescription([
        declare_params,
        declare_map,
        declare_enable_depth_pipeline,
        declare_depth_params,
        declare_depth_frames_dir,
        startup_info,
        map_server,
        cmd_vel_arbiter_direct,
        cmd_vel_arbiter_gated,
        depth_relay_publisher,
        depth_optical_tf,
        depth_safety_gate,
        planner_static,
        planner_depth,
        controller_static,
        controller_depth,
        recoveries,
        bt_navigator,
        TimerAction(period=3.0, actions=[lifecycle]),
    ])
