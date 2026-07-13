#!/usr/bin/env python3
"""
比赛总启动文件 — 启动四足机器人竞赛全部 ROS2 节点。

用法:
    ros2 launch launch/competition.launch.py
    ros2 launch launch/competition.launch.py enable_task_manager:=true enable_navigation:=true
"""

from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


# ─── 路径 ────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARAMS_FILE = PROJECT_ROOT / "configs" / "ros" / "competition_params.yaml"


def generate_launch_description() -> LaunchDescription:
    # ─── 启动参数 ───────────────────────────────────
    enable_gauge = LaunchConfiguration("enable_gauge", default="false")
    enable_yolo = LaunchConfiguration("enable_yolo", default="true")
    enable_task_manager = LaunchConfiguration("enable_task_manager", default="false")
    enable_speech = LaunchConfiguration("enable_speech", default="false")
    enable_navigation = LaunchConfiguration("enable_navigation", default="false")
    enable_cmd_vel_bridge = LaunchConfiguration("enable_cmd_vel_bridge", default="false")
    cmd_vel_bridge_init_dog = LaunchConfiguration("cmd_vel_bridge_init_dog", default="false")
    enable_depth_publisher = LaunchConfiguration("enable_depth_publisher", default="false")
    enable_whz = LaunchConfiguration("enable_whz", default="false")
    auto_advance = LaunchConfiguration("auto_advance", default="false")

    # ── 声明参数 ─────────────────────────────────────
    declare_enable_gauge = DeclareLaunchArgument(
        "enable_gauge", default_value="false",
        description="启动仪表检测节点"
    )
    declare_enable_yolo = DeclareLaunchArgument(
        "enable_yolo", default_value="true",
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
        description="启动官方 Nav2 导航栈 (NavFn A* + DWB)"
    )
    declare_enable_cmd_vel_bridge = DeclareLaunchArgument(
        "enable_cmd_vel_bridge", default_value="false",
        description="启动 /cmd_vel -> Lite3 UDP 桥接。默认关闭，用于安全 dry-run。"
    )
    declare_cmd_vel_bridge_init_dog = DeclareLaunchArgument(
        "cmd_vel_bridge_init_dog", default_value="false",
        description="cmd_vel_bridge 启动时是否发送 Lite3 auto/motion 初始化。默认关闭，避免改变站立/趴下状态。"
    )
    declare_enable_depth_publisher = DeclareLaunchArgument(
        "enable_depth_publisher", default_value="false",
        description="启动 Host D455 depth publisher。默认关闭，避免和 Docker/cuVSLAM 抢占 D455。"
    )
    declare_enable_whz = DeclareLaunchArgument(
        "enable_whz", default_value="false",
        description="启动 whz 巡检 (字母识别+仪表+语音播报)"
    )
    declare_auto_advance = DeclareLaunchArgument(
        "auto_advance", default_value="false",
        description="调试模式：跳过部分任务等待条件"
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
        parameters=[
            str(PARAMS_FILE),
            {
                "auto_advance": auto_advance,
                "phase2_map_yaml": str(PROJECT_ROOT / "navi" / "map" / "competition_field_phase2.yaml"),
            },
        ],
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
    # 定位/传感器辅助层 — Nav2 prerequisites
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
        # base_link -> camera_link: x=0.080m forward, z=0.493m up,
        # pitch=+30 deg tilts the camera X axis downward in ROS frames.
        arguments=[
            "0.080", "0.000", "0.493",
            "0.000000", "0.258819", "0.000000", "0.965926",
            "base_link", "camera_link",
        ],
        output="screen",
        condition=IfCondition(enable_navigation),
    )

    depth_pub_node = Node(
        package="quadruped_robot_competition",
        executable="depth_publisher",
        name="d455_depth_publisher",
        output="screen",
        condition=IfCondition(enable_depth_publisher),
    )

    # Optional fallback bridge. The preferred dog path remains Nav2 /cmd_vel
    # -> Lite3 transfer driver from scripts/start_competition.sh --dog.
    cmd_vel_bridge_node = Node(
        package="quadruped_robot_competition",
        executable="cmd_vel_bridge",
        name="cmd_vel_bridge_node",
        output="screen",
        parameters=[{
            "init_dog": cmd_vel_bridge_init_dog,
        }],
        condition=IfCondition(enable_cmd_vel_bridge),
    )

    # ═══════════════════════════════════════════════════
    # 执行层 — official Nav2
    # ═══════════════════════════════════════════════════

    navigation_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            str(PROJECT_ROOT / "launch" / "navigation.launch.py")
        ),
        condition=IfCondition(enable_navigation),
    )

    # ── 启动说明 ────────────────────────────────────
    startup_info = LogInfo(
        msg=[
            "\n",
            "╔════════════════════════════════════════╗\n",
            "║   四足机器人竞赛系统 (Nav2版) 启动中   ║\n",
            "╠════════════════════════════════════════╣\n",
            "║ gauge_status     : ", enable_gauge, "  ║\n",
            "║ yolo_detect      : ", enable_yolo, "  ║\n",
            "║ task_manager     : ", enable_task_manager, "  ║\n",
            "║ speech           : ", enable_speech, "  ║\n",
            "║ navigation (Nav2): ", enable_navigation, "  ║\n",
            "║ cmd_vel_bridge   : ", enable_cmd_vel_bridge, "  ║\n",
            "║ depth_publisher  : ", enable_depth_publisher, "  ║\n",
            "╚════════════════════════════════════════╝\n",
        ]
    )

    return LaunchDescription([
        declare_enable_gauge,
        declare_enable_yolo,
        declare_enable_task_manager,
        declare_enable_speech,
        declare_enable_navigation,
        declare_enable_cmd_vel_bridge,
        declare_cmd_vel_bridge_init_dog,
        declare_enable_depth_publisher,
        declare_enable_whz,
        declare_auto_advance,
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
        cmd_vel_bridge_node,
        navigation_launch,
    ])
