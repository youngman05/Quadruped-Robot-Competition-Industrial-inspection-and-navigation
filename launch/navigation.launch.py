#!/usr/bin/env python3
"""
Navigation stack launch file — 启动完整的 Nav2 导航系统。

用法:
    # 默认: NavFn planner + RegulatedPurePursuit controller
    ros2 launch launch/navigation.launch.py

    # 指定地图路径
    ros2 launch launch/navigation.launch.py map_yaml:=navi/map/competition_field.yaml

    # 使用 Smac Hybrid-A* planner (需要 ros-foxy-nav2-smac-planner)
    ros2 launch launch/navigation.launch.py planner:=smac

    # 使用 TEB controller (需要先源码编译 teb_local_planner)
    ros2 launch launch/navigation.launch.py controller:=teb

依赖:
    - Nav2 Foxy 全家桶 (见 scripts/install_nav2_deps.sh)
    - cuVSLAM Docker 容器已运行
    - D455 相机已连接
    - competition_field.pgm + .yaml 已生成
"""

from pathlib import Path

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    LogInfo,
    SetEnvironmentVariable,
)
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node, SetParameter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PARAMS = PROJECT_ROOT / "configs" / "navigation" / "nav2_params.yaml"
DEFAULT_MAP = PROJECT_ROOT / "navi" / "map" / "competition_field.yaml"


def generate_launch_description() -> LaunchDescription:
    # ── 启动参数 ─────────────────────────────────────────
    params_file = LaunchConfiguration("params_file", default=str(DEFAULT_PARAMS))
    map_yaml = LaunchConfiguration("map_yaml", default=str(DEFAULT_MAP))
    use_sim_time = LaunchConfiguration("use_sim_time", default="false")
    planner = LaunchConfiguration("planner", default="navfn")
    controller = LaunchConfiguration("controller", default="rpp")

    declare_params = DeclareLaunchArgument(
        "params_file", default_value=str(DEFAULT_PARAMS),
        description="Nav2 params YAML path"
    )
    declare_map = DeclareLaunchArgument(
        "map_yaml", default_value=str(DEFAULT_MAP),
        description="PGM map YAML path"
    )
    declare_sim_time = DeclareLaunchArgument(
        "use_sim_time", default_value="false",
        description="Use simulation (Gazebo) time"
    )
    declare_planner = DeclareLaunchArgument(
        "planner", default_value="navfn",
        description="Global planner: navfn | smac"
    )
    declare_controller = DeclareLaunchArgument(
        "controller", default_value="rpp",
        description="Controller: rpp (RegulatedPurePursuit) | teb"
    )

    # ═══════════════════════════════════════════════════════
    # 定位层
    # ═══════════════════════════════════════════════════════

    # ── cuVSLAM 桥接 ──────────────────────────────────
    cuvslam_bridge_node = Node(
        package="quadruped_robot_competition",
        executable="cuvslam_bridge",
        name="cuvslam_bridge",
        output="screen",
    )

    # ── 初始位姿 ──────────────────────────────────────
    initial_pose_node = Node(
        package="quadruped_robot_competition",
        executable="initial_pose_publisher",
        name="initial_pose_publisher",
        output="screen",
    )

    # ── 静态 TF: base_link → camera_link ──────────────
    # cuVSLAM publishes odom → camera_pose; we need base_link → camera_link
    # (实际偏移需要根据机器人 URDF 测量，这里先设 identity)
    base_to_camera_tf = Node(
        package="tf2_ros",
        executable="static_transform_publisher",
        name="base_to_camera_tf",
        arguments=[
            "--x", "0.0", "--y", "0.0", "--z", "0.3",
            "--roll", "0.0", "--pitch", "0.0", "--yaw", "0.0",
            "base_link", "camera_link",
        ],
        output="screen",
    )

    # ═══════════════════════════════════════════════════════
    # 感知层 — 深度相机
    # ═══════════════════════════════════════════════════════

    # ── D455 深度发布 ────────────────────────────────
    depth_publisher_node = Node(
        package="quadruped_robot_competition",
        executable="depth_publisher",
        name="d455_depth_publisher",
        output="screen",
    )

    # ── 深度图 → PointCloud2 ─────────────────────────
    point_cloud_node = Node(
        package="depth_image_proc",
        executable="point_cloud_xyz_node",
        name="point_cloud_xyz_node",
        remappings=[
            ("/image_rect", "/camera/depth/image_raw"),
            ("/camera_info", "/camera/depth/camera_info"),
            ("/points", "/camera/depth/points"),
        ],
        output="screen",
    )

    # ═══════════════════════════════════════════════════════
    # 执行层 — Nav2
    # ═══════════════════════════════════════════════════════

    # ── Map Server ────────────────────────────────────
    map_server_node = Node(
        package="nav2_map_server",
        executable="map_server",
        name="map_server",
        parameters=[params_file],
        output="screen",
    )

    # ── Planner Server ────────────────────────────────
    planner_node = Node(
        package="nav2_planner",
        executable="planner_server",
        name="planner_server",
        parameters=[params_file],
        output="screen",
    )

    # ── Controller Server ─────────────────────────────
    controller_node = Node(
        package="nav2_controller",
        executable="controller_server",
        name="controller_server",
        parameters=[params_file],
        output="screen",
    )

    # ── BT Navigator ──────────────────────────────────
    bt_navigator_node = Node(
        package="nav2_bt_navigator",
        executable="bt_navigator",
        name="bt_navigator",
        parameters=[params_file],
        output="screen",
    )

    # ── Behavior Server ───────────────────────────────
    behavior_node = Node(
        package="nav2_behaviors",
        executable="behavior_server",
        name="behavior_server",
        parameters=[params_file],
        output="screen",
    )

    # ── Waypoint Follower ─────────────────────────────
    waypoint_node = Node(
        package="nav2_waypoint_follower",
        executable="waypoint_follower",
        name="waypoint_follower",
        parameters=[params_file],
        output="screen",
    )

    # ── Velocity Smoother ─────────────────────────────
    velocity_smoother_node = Node(
        package="nav2_velocity_smoother",
        executable="velocity_smoother",
        name="velocity_smoother",
        parameters=[params_file],
        output="screen",
    )

    # ── Lifecycle Manager ─────────────────────────────
    lifecycle_node = Node(
        package="nav2_lifecycle_manager",
        executable="lifecycle_manager",
        name="lifecycle_manager",
        parameters=[params_file],
        output="screen",
    )

    # ── 启动信息 ──────────────────────────────────────
    startup_info = LogInfo(
        msg=[
            "\n",
            "╔══════════════════════════════════════════╗\n",
            "║  Nav2 导航栈启动中...                  ║\n",
            "╠══════════════════════════════════════════╣\n",
            "║ 全局规划器 : ", planner, "\n",
            "║ 控制器     : ", controller, "\n",
            "║ 地图       : ", map_yaml, "\n",
            "╚══════════════════════════════════════════╝\n",
        ]
    )

    return LaunchDescription([
        # 参数声明
        declare_params,
        declare_map,
        declare_sim_time,
        declare_planner,
        declare_controller,
        # 位置 + 姿态
        cuvslam_bridge_node,
        initial_pose_node,
        base_to_camera_tf,
        # 深度 → 点云
        depth_publisher_node,
        point_cloud_node,
        # Nav2
        map_server_node,
        planner_node,
        controller_node,
        bt_navigator_node,
        behavior_node,
        waypoint_node,
        velocity_smoother_node,
        lifecycle_node,
        # 信息
        startup_info,
    ])
