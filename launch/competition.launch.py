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
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


# ─── 路径 ────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARAMS_FILE = PROJECT_ROOT / "configs" / "ros" / "competition_params.yaml"
TASK_MANAGER_PARAMS_FILE = PROJECT_ROOT / "configs" / "ros" / "task_manager_params.yaml"
COMPETITION_ROUTE_PARAMS_FILE = PROJECT_ROOT / "configs" / "ros" / "competition_route_params.yaml"
PICK_I2_APRILTAG_FILE = PROJECT_ROOT / "configs" / "calibration" / "pick_i2_apriltag.yaml"
ARM_MOTION_PARAMS_FILE = PROJECT_ROOT / "arm_new" / "config" / "arm_motion_params.yaml"


def generate_launch_description() -> LaunchDescription:
    # ─── 启动参数 ───────────────────────────────────
    enable_gauge = LaunchConfiguration("enable_gauge", default="false")
    enable_yolo = LaunchConfiguration("enable_yolo", default="false")
    enable_yolo_udp_bridge = LaunchConfiguration("enable_yolo_udp_bridge", default="false")
    enable_apriltag_udp_bridge = LaunchConfiguration("enable_apriltag_udp_bridge", default="false")
    enable_task_manager = LaunchConfiguration("enable_task_manager", default="false")
    enable_competition_manager = LaunchConfiguration("enable_competition_manager", default="false")
    enable_arm = LaunchConfiguration("enable_arm", default="false")
    enable_speech = LaunchConfiguration("enable_speech", default="false")
    enable_navigation = LaunchConfiguration("enable_navigation", default="false")
    enable_cmd_vel_bridge = LaunchConfiguration("enable_cmd_vel_bridge", default="false")
    enable_whz = LaunchConfiguration("enable_whz", default="false")
    route_mode = LaunchConfiguration("route_mode", default="full")
    segment_name = LaunchConfiguration("segment_name", default="")
    enable_route_execution = LaunchConfiguration("enable_route_execution", default="false")

    # ── 声明参数 ─────────────────────────────────────
    declare_enable_gauge = DeclareLaunchArgument(
        "enable_gauge", default_value="false",
        description="启动仪表检测节点"
    )
    declare_enable_yolo = DeclareLaunchArgument(
        "enable_yolo", default_value="false",
        description="启动旧 Host YOLO 调试节点（不能与 UDP bridge 同时使用）"
    )
    declare_enable_yolo_udp_bridge = DeclareLaunchArgument(
        "enable_yolo_udp_bridge", default_value="false",
        description="Start Host UDP bridge for Docker D455 YOLO 3-D detections",
    )
    declare_enable_apriltag_udp_bridge = DeclareLaunchArgument(
        "enable_apriltag_udp_bridge", default_value="false",
        description="Start Host UDP bridge for Docker D455 AprilTag poses",
    )
    declare_enable_task_manager = DeclareLaunchArgument(
        "enable_task_manager", default_value="false",
        description="启动任务管理器节点"
    )
    declare_enable_competition_manager = DeclareLaunchArgument(
        "enable_competition_manager", default_value="false",
        description="Start the new flat competition route scaffold (disabled by default)",
    )
    declare_enable_arm = DeclareLaunchArgument(
        "enable_arm", default_value="false",
        description="Start the production arm service node (motion remains controlled by its own enable_motion parameter)",
    )
    declare_enable_speech = DeclareLaunchArgument(
        "enable_speech", default_value="false",
        description="启动语音播报节点"
    )
    declare_enable_navigation = DeclareLaunchArgument(
        "enable_navigation", default_value="false",
        description="启动 Nav2 导航栈 (map_server + planner + controller + BT + waypoint)"
    )
    declare_enable_cmd_vel_bridge = DeclareLaunchArgument(
        "enable_cmd_vel_bridge", default_value="false",
        description="Use the Python Lite3 bridge fallback. The default dog backend is the official transfer driver.",
    )
    declare_enable_whz = DeclareLaunchArgument(
        "enable_whz", default_value="false",
        description="启动 whz 巡检 (字母识别+仪表+语音播报)"
    )
    declare_route_mode = DeclareLaunchArgument(
        "route_mode", default_value="full",
        description="Competition manager route mode: full or segment",
    )
    declare_segment_name = DeclareLaunchArgument(
        "segment_name", default_value="",
        description="Cumulative segment test name when route_mode=segment",
    )
    declare_enable_route_execution = DeclareLaunchArgument(
        "enable_route_execution", default_value="false",
        description="Allow the competition manager to move hardware after start service",
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
        package="quadruped_robot_competition",
        executable="whz_inspection_node",
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
        parameters=[str(TASK_MANAGER_PARAMS_FILE)],
        output="screen",
        condition=IfCondition(enable_task_manager),
    )

    competition_manager_node = Node(
        package="quadruped_robot_competition",
        executable="competition_manager",
        name="competition_manager_node",
        parameters=[
            str(COMPETITION_ROUTE_PARAMS_FILE),
            str(PICK_I2_APRILTAG_FILE),
            {
                "route_mode": route_mode,
                "segment_name": segment_name,
                "enable_route_execution": ParameterValue(enable_route_execution, value_type=bool),
            },
        ],
        output="screen",
        condition=IfCondition(enable_competition_manager),
    )

    arm_motion_node = Node(
        package="arm_new_ros",
        executable="arm_motion_node",
        name="arm_motion_node",
        parameters=[str(ARM_MOTION_PARAMS_FILE)],
        output="screen",
        condition=IfCondition(enable_arm),
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
    # 定位层 — Localization (Nav2 导航需要)
    # ═══════════════════════════════════════════════════

    initial_pose_node = Node(
        package="quadruped_robot_competition",
        executable="initial_pose_publisher",
        name="initial_pose_publisher_node",
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

    # ── /cmd_vel → 狗 UDP 桥接 ──
    cmd_vel_bridge_node = Node(
        package="quadruped_robot_competition",
        executable="cmd_vel_bridge",
        name="cmd_vel_bridge_node",
        output="screen",
        condition=IfCondition(enable_cmd_vel_bridge),
    )

    # ═══════════════════════════════════════════════════
    # 执行层 — Nav2 导航栈
    # ═══════════════════════════════════════════════════

    navigation_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            str(PROJECT_ROOT / "launch" / "navigation.launch.py")
        ),
        launch_arguments={"publish_static_transforms": "false"}.items(),
        condition=IfCondition(enable_navigation),
    )

    static_transform_needed = PythonExpression([
        "'", enable_navigation, "' in ['true', 'True', '1'] or '",
        enable_yolo_udp_bridge, "' in ['true', 'True', '1'] or '",
        enable_apriltag_udp_bridge, "' in ['true', 'True', '1'] or '",
        enable_competition_manager, "' in ['true', 'True', '1'] or '",
        enable_arm, "' in ['true', 'True', '1']",
    ])
    static_transforms = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(PROJECT_ROOT / "launch" / "static_transforms.launch.py")),
        condition=IfCondition(static_transform_needed),
    )
    yolo_udp_bridge = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(PROJECT_ROOT / "launch" / "yolo_udp_bridge.launch.py")),
        launch_arguments={"publish_static_transforms": "false"}.items(),
        condition=IfCondition(enable_yolo_udp_bridge),
    )
    apriltag_udp_bridge = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(PROJECT_ROOT / "launch" / "apriltag_udp_bridge.launch.py")),
        condition=IfCondition(enable_apriltag_udp_bridge),
    )

    # ── 启动说明 ────────────────────────────────────
    startup_info = LogInfo(
        msg=[
            "\n",
            "╔════════════════════════════════════════╗\n",
            "║   四足机器人竞赛系统 (Nav2版) 启动中  ║\n",
            "╠════════════════════════════════════════╣\n",
            "║ gauge_status     : ", enable_gauge, "  ║\n",
            "║ yolo_detect      : ", enable_yolo, "  ║\n",
            "║ yolo_udp_bridge  : ", enable_yolo_udp_bridge, "  ║\n",
        "║ task_manager     : ", enable_task_manager, "  ║\n",
        "║ competition_mgr  : ", enable_competition_manager, "  ║\n",
        "║ arm_motion       : ", enable_arm, "  ║\n",
            "║ speech           : ", enable_speech, "  ║\n",
            "║ navigation (Nav2): ", enable_navigation, "  ║\n",
            "║ whz inspect      : ", enable_whz, "  ║\n",
            "╚════════════════════════════════════════╝\n",
        ]
    )

    return LaunchDescription([
        declare_enable_gauge,
        declare_enable_yolo,
        declare_enable_yolo_udp_bridge,
        declare_enable_apriltag_udp_bridge,
        declare_enable_task_manager,
        declare_enable_competition_manager,
        declare_enable_arm,
        declare_enable_speech,
        declare_enable_navigation,
        declare_enable_cmd_vel_bridge,
        declare_enable_whz,
        declare_route_mode,
        declare_segment_name,
        declare_enable_route_execution,
        startup_info,
        gauge_node,
        yolo_node,
        color_image_pub_node,
        whz_inspection_node,
        task_manager_node,
        competition_manager_node,
        arm_motion_node,
        speech_node,
        initial_pose_node,
        depth_pub_node,
        cmd_vel_bridge_node,
        navigation_launch,
        static_transforms,
        yolo_udp_bridge,
        apriltag_udp_bridge,
    ])
