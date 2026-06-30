#!/usr/bin/env python3
"""
比赛总启动文件 — 启动四足机器人竞赛全部 ROS2 节点。

用法:
    ros2 launch launch/competition.launch.py
    ros2 launch launch/competition.launch.py enable_task_manager:=true enable_navigation:=true
"""

from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


# ─── 路径 ────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARAMS_FILE = PROJECT_ROOT / "configs" / "ros" / "competition_params.yaml"


def generate_launch_description() -> LaunchDescription:
    # ─── 启动参数 ───────────────────────────────────
    enable_gauge = LaunchConfiguration("enable_gauge", default="true")
    enable_yolo = LaunchConfiguration("enable_yolo", default="false")
    enable_task_manager = LaunchConfiguration("enable_task_manager", default="false")
    enable_speech = LaunchConfiguration("enable_speech", default="false")
    enable_navigation = LaunchConfiguration("enable_navigation", default="false")
    enable_whz = LaunchConfiguration("enable_whz", default="false")

    # ── 声明参数 ─────────────────────────────────────
    declare_enable_gauge = DeclareLaunchArgument(
        "enable_gauge", default_value="true",
        description="启动仪表检测节点"
    )
    declare_enable_yolo = DeclareLaunchArgument(
        "enable_yolo", default_value="false",
        description="启动 YOLO 检测节点"
    )
    declare_enable_task_manager = DeclareLaunchArgument(
        "enable_task_manager", default_value="false",
        description="启动任务管理器节点"
    )
    declare_enable_speech = DeclareLaunchArgument(
        "enable_speech", default_value="false",
        description="启动语音播报节点"
    )
    declare_enable_navigation = DeclareLaunchArgument(
        "enable_navigation", default_value="false",
        description="启动轻量导航 (A* + 纯追踪 + 深度避障)"
    )
    declare_enable_whz = DeclareLaunchArgument(
        "enable_whz", default_value="false",
        description="启动 whz 巡检 (字母识别+仪表+语音播报)"
    )

    # ═══════════════════════════════════════════════════
    # 感知层 — Perception
    # ═══════════════════════════════════════════════════

    gauge_node = Node(
        package="quadruped_robot_competition",
        executable="gauge_status_publisher",
        name="gauge_status_publisher_node",
        parameters=[str(PARAMS_FILE)],
        output="screen",
        condition=IfCondition(enable_gauge),
    )

    yolo_node = Node(
        package="quadruped_robot_competition",
        executable="yolo_detect_publisher",
        name="yolo_detect_publisher_node",
        parameters=[str(PARAMS_FILE)],
        output="screen",
        condition=IfCondition(enable_yolo),
    )

    # ── whz 巡检 (字母+仪表+语音) ──
    color_image_pub_node = Node(
        package="quadruped_robot_competition",
        executable="color_image_publisher",
        name="color_image_publisher_node",
        output="screen",
        condition=IfCondition(enable_whz),
    )

    whz_inspection_node = Node(
        package="whz",
        executable="inspection_node",
        name="whz_inspection_node",
        output="screen",
        remappings=[
            ("/camera/aligned_depth_to_color/image_raw", "/camera/depth/image_raw"),
        ],
        condition=IfCondition(enable_whz),
    )

    # ═══════════════════════════════════════════════════
    # 决策层 — Decision
    # ═══════════════════════════════════════════════════

    task_manager_node = Node(
        package="quadruped_robot_competition",
        executable="task_manager",
        name="task_manager_node",
        parameters=[str(PARAMS_FILE)],
        output="screen",
        condition=IfCondition(enable_task_manager),
    )

    speech_node = Node(
        package="quadruped_robot_competition",
        executable="speech",
        name="speech_node",
        parameters=[str(PARAMS_FILE)],
        output="screen",
        condition=IfCondition(enable_speech),
    )

    # ═══════════════════════════════════════════════════
    # 执行层 — 轻量导航
    # ═══════════════════════════════════════════════════

    initial_pose_node = Node(
        package="quadruped_robot_competition",
        executable="initial_pose_publisher",
        name="initial_pose_publisher_node",
        output="screen",
        condition=IfCondition(enable_navigation),
    )

    base_to_camera_tf = Node(
        package="tf2_ros",
        executable="static_transform_publisher",
        name="base_to_camera_tf",
        # x=0.080m forward, z=0.493m up, pitch=-30° (camera tilted down)
        arguments=["0.080", "0.000", "0.493", "0", "-0.523599", "0", "base_link", "camera_link"],
        output="screen",
        condition=IfCondition(enable_navigation),
    )

    depth_pub_node = Node(
        package="quadruped_robot_competition",
        executable="depth_publisher",
        name="d455_depth_publisher",
        output="screen",
        condition=IfCondition(enable_navigation),
    )

    # NOTE: point_cloud_xyz_node (depth_image_proc) not available on Jetson Foxy.
    # Depth-based local obstacle detection will be added later via a custom node.

    # ── 启动说明 ────────────────────────────────────
    startup_info = LogInfo(
        msg=[
            "\n",
            "╔════════════════════════════════════════╗\n",
            "║   四足机器人竞赛系统 (轻量版) 启动中   ║\n",
            "╠════════════════════════════════════════╣\n",
            "║ gauge_status     : ", enable_gauge, "  ║\n",
            "║ yolo_detect      : ", enable_yolo, "  ║\n",
            "║ task_manager     : ", enable_task_manager, "  ║\n",
            "║ speech           : ", enable_speech, "  ║\n",
            "║ navigation (A*)  : ", enable_navigation, "  ║\n",
            "╚════════════════════════════════════════╝\n",
        ]
    )

    return LaunchDescription([
        declare_enable_gauge,
        declare_enable_yolo,
        declare_enable_task_manager,
        declare_enable_speech,
        declare_enable_navigation,
        declare_enable_whz,
        startup_info,
        gauge_node,
        yolo_node,
        color_image_pub_node,
        whz_inspection_node,
        task_manager_node,
        speech_node,
        initial_pose_node,
        base_to_camera_tf,
        depth_pub_node,
    ])
