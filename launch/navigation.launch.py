#!/usr/bin/env python3
"""
Navigation stack — 一键启动 Nav2 + 定位桥接 + 初始位姿。

用法:
    ros2 launch launch/navigation.launch.py
    ros2 launch launch/navigation.launch.py map_yaml:=navi/map/competition_field_phase1.yaml

前置: Docker cuVSLAM 已启动, final_bridge 在跑, camera/depth relay 在跑。
"""

from pathlib import Path
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, ExecuteProcess
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

PROJECT_ROOT = Path(__file__).resolve().parents[1]
Foxy_PYTHON = "/opt/ros/foxy/lib/python3.8/site-packages"
SRC = str(PROJECT_ROOT / "src")
DEFAULT_PARAMS = str(PROJECT_ROOT / "configs" / "navigation" / "nav2_params_minimal.yaml")
DEFAULT_MAP = str(PROJECT_ROOT / "navi" / "map" / "competition_field_phase1.yaml")


def py_node(name, script, args=""):
    """Launch Python via bash to ensure ROS2 env is sourced."""
    cmd_str = f"source /opt/ros/foxy/setup.bash && export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_DOMAIN_ID=0 PYTHONPATH={Foxy_PYTHON}:{SRC} && python3 {script} {args}"
    return ExecuteProcess(
        cmd=["bash", "-c", cmd_str],
        name=name,
        output="screen",
    )


def generate_launch_description():
    params_file = LaunchConfiguration("params_file", default=DEFAULT_PARAMS)
    map_yaml = LaunchConfiguration("map_yaml", default=DEFAULT_MAP)

    declare_params = DeclareLaunchArgument("params_file", default_value=DEFAULT_PARAMS)
    declare_map = DeclareLaunchArgument("map_yaml", default_value=DEFAULT_MAP)

    # ═══ 定位层 ═══
    initial_pose = py_node("initial_pose_publisher",
                           str(PROJECT_ROOT / "src/nodes/navigation/initial_pose_publisher.py"))

    base_to_camera_tf = Node(
        package="tf2_ros", executable="static_transform_publisher",
        name="base_to_camera_tf",
        arguments=["0", "0", "0.3", "0", "0", "0", "base_link", "camera_link"],
        output="screen",
    )

    # ═══ 深度发布 (读 Docker relay) ═══
    depth_pub = py_node("depth_publisher",
                        str(PROJECT_ROOT / "src/nodes/navigation/depth_publisher.py"))

    # ═══ Nav2 ═══
    map_server = Node(package="nav2_map_server", executable="map_server",
                      name="map_server", parameters=[params_file], output="screen")
    planner = Node(package="nav2_planner", executable="planner_server",
                   name="planner_server", parameters=[params_file], output="screen")
    controller = Node(package="nav2_controller", executable="controller_server",
                      name="controller_server", parameters=[params_file], output="screen")
    bt_nav = Node(package="nav2_bt_navigator", executable="bt_navigator",
                  name="bt_navigator", parameters=[params_file], output="screen")
    waypoint = Node(package="nav2_waypoint_follower", executable="waypoint_follower",
                    name="waypoint_follower", parameters=[params_file], output="screen")
    lifecycle = Node(package="nav2_lifecycle_manager", executable="lifecycle_manager",
                     name="lifecycle_manager", parameters=[params_file], output="screen")

    startup_info = LogInfo(msg=["Nav2 navigation stack starting...",
                                f"map: {map_yaml}", f"params: {params_file}"])

    return LaunchDescription([
        declare_params, declare_map,
        initial_pose, base_to_camera_tf,
        depth_pub,
        map_server, planner, controller,
        bt_nav, waypoint, lifecycle,
        startup_info,
    ])
