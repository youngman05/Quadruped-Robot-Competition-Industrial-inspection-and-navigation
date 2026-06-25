#!/usr/bin/env python3
"""
比赛总启动文件 — 启动四足机器人竞赛全部 ROS2 节点。

用法:
    # 启动全部已实现节点
    ros2 launch launch/competition.launch.py

    # 不启动仪表检测
    ros2 launch launch/competition.launch.py enable_gauge:=false

    # 包含占位节点（测试用）
    ros2 launch launch/competition.launch.py enable_placeholders:=true

架构概览:
    ┌──────────────────────────────────────────────┐
    │  感知层 (Perception)                         │
    │  ├── gauge_status_node    ← D455 仪表检测     │
    │  └── yolo_detect_publisher ← YOLO 实例分割     │
    │                                              │
    │  定位层 (Localization)                       │
    │  └── cuVSLAM (Docker 容器)  ← 视觉惯性里程计  │
    │                                              │
    │  决策层 (Decision)                           │
    │  ├── task_manager_node     ← 比赛状态机       │
    │  └── speech_node           ← 语音播报         │
    │                                              │
    │  执行层 (Execution)                          │
    │  └── Nav2 / move_base      ← 路径规划+控制    │
    │  └── Arm Control           ← 机械臂控制       │
    └──────────────────────────────────────────────┘
"""

from pathlib import Path

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    LogInfo,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


# ─── 路径 ────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARAMS_FILE = PROJECT_ROOT / "configs" / "ros" / "competition_params.yaml"


def generate_launch_description() -> LaunchDescription:
    # ─── 启动参数 ───────────────────────────────────
    enable_gauge = LaunchConfiguration("enable_gauge", default="true")
    enable_yolo = LaunchConfiguration("enable_yolo", default="false")        # 需先装 ultralytics torch
    enable_task_manager = LaunchConfiguration("enable_task_manager", default="false")  # 待实现
    enable_speech = LaunchConfiguration("enable_speech", default="false")    # 待实现
    enable_navigation = LaunchConfiguration("enable_navigation", default="false")  # Nav2 导航栈
    enable_placeholders = LaunchConfiguration("enable_placeholders", default="false")

    # ── 声明参数 ─────────────────────────────────────
    declare_enable_gauge = DeclareLaunchArgument(
        "enable_gauge", default_value="true",
        description="启动仪表检测节点"
    )
    declare_enable_yolo = DeclareLaunchArgument(
        "enable_yolo", default_value="false",
        description="启动 YOLO 检测节点（需 pip3 install ultralytics torch）"
    )
    declare_enable_task_manager = DeclareLaunchArgument(
        "enable_task_manager", default_value="false",
        description="启动任务管理器节点（待实现）"
    )
    declare_enable_speech = DeclareLaunchArgument(
        "enable_speech", default_value="false",
        description="启动语音播报节点（待实现）"
    )
    declare_enable_placeholders = DeclareLaunchArgument(
        "enable_placeholders", default_value="false",
        description="同时启动所有占位节点（测试架构用）"
    )
    declare_enable_navigation = DeclareLaunchArgument(
        "enable_navigation", default_value="false",
        description="启动 Nav2 导航栈（需先生成 PGM 地图 + 启动 cuVSLAM Docker）"
    )

    # ═══════════════════════════════════════════════════
    # 感知层 — Perception
    # ═══════════════════════════════════════════════════

    # ── 仪表检测节点 ✅ 已实现 ──────────────────────
    gauge_node = Node(
        package="quadruped_robot_competition",
        executable="gauge_status_publisher",
        name="gauge_status_publisher_node",
        parameters=[str(PARAMS_FILE)],
        output="screen",
        condition=IfCondition(enable_gauge),
    )

    # ── YOLO 检测节点 ⏳ 待实现 ────────────────────
    yolo_node = Node(
        package="quadruped_robot_competition",
        executable="yolo_detect_publisher",
        name="yolo_detect_publisher_node",
        parameters=[str(PARAMS_FILE)],
        output="screen",
        condition=IfCondition(
            [enable_yolo, " or ", enable_placeholders]
        ),
    )

    # ═══════════════════════════════════════════════════
    # 定位层 — Localization
    # ═══════════════════════════════════════════════════
    #
    # cuVSLAM 运行在独立 Docker 容器中，不由本 launch 文件管理。
    # 启动 cuVSLAM 前需要：
    #   1. 确认 D455 IR 双目 + IMU 链路正常:
    #        python3 scripts/realsense_cuvslam_input_test.py
    #   2. 启动桥接节点（将 D455 IR/IMU 发布为 ROS topic）:
    #        （待实现: ir_imu_bridge）
    #   3. 启动 Docker 容器:
    #        docker run --rm --gpus all --network host \
    #          -v ~/workspaces/isaac_ros-dev:/workspaces/isaac_ros-dev \
    #          isaac_ros_cuvslam_runtime:humble-rs \
    #          ros2 launch isaac_ros_visual_slam \
    #            isaac_ros_visual_slam_realsense.launch.py
    #
    # 查看 cuVSLAM 输出:
    #   ros2 topic echo /visual_slam/status      # vo_state
    #   ros2 topic echo /visual_slam/tracking/odometry
    #   ros2 topic echo /tf

    # ═══════════════════════════════════════════════════
    # 决策层 — Decision
    # ═══════════════════════════════════════════════════

    # ── 任务管理器 ⏳ 待实现 ────────────────────────
    task_manager_node = Node(
        package="quadruped_robot_competition",
        executable="task_manager",
        name="task_manager_node",
        parameters=[str(PARAMS_FILE)],
        output="screen",
        condition=IfCondition(
            [enable_task_manager, " or ", enable_placeholders]
        ),
    )

    # ── 语音播报 ⏳ 待实现 ──────────────────────────
    speech_node = Node(
        package="quadruped_robot_competition",
        executable="speech",
        name="speech_node",
        parameters=[str(PARAMS_FILE)],
        output="screen",
        condition=IfCondition(
            [enable_speech, " or ", enable_placeholders]
        ),
    )

    # ═══════════════════════════════════════════════════
    # 执行层 — Execution
    # ═══════════════════════════════════════════════════

    # ── Nav2 导航栈 🆕 ──────────────────────────────
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
            "╔══════════════════════════════════════╗\n",
            "║  四足机器人竞赛系统启动中...        ║\n",
            "╠══════════════════════════════════════╣\n",
            "║ gauge_status_pub   : ", enable_gauge, "  ║\n",
            "║ yolo_detect_pub    : ", enable_yolo, "  ║\n",
            "║ task_manager_node  : ", enable_task_manager, "  ║\n",
            "║ speech_node        : ", enable_speech, "  ║\n",
            "║ navigation         : ", enable_navigation, "  ║\n",
            "╚══════════════════════════════════════╝\n",
        ]
    )

    return LaunchDescription([
        # 启动参数
        declare_enable_gauge,
        declare_enable_yolo,
        declare_enable_task_manager,
        declare_enable_speech,
        declare_enable_placeholders,
        declare_enable_navigation,
        # 启动说明
        startup_info,
        # 感知层
        gauge_node,
        yolo_node,
        # 决策层
        task_manager_node,
        speech_node,
        # 执行层 — 导航
        navigation_launch,
    ])
