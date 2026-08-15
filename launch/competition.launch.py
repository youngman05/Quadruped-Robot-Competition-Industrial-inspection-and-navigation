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
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution, PythonExpression
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


# ─── 路径 ────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARAMS_FILE = PROJECT_ROOT / "configs" / "ros" / "competition_params.yaml"
DEFAULT_CONE_PARAMS = (
    PROJECT_ROOT / "configs" / "navigation" / "nav2_cone_obstacles.yaml"
)
CONE_BEHAVIOR_TREE = PathJoinSubstitution([
    FindPackageShare("quadruped_robot_competition"),
    "configs",
    "navigation",
    "navigate_cone_w_replanning_and_recovery.xml",
])


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
    enable_depth_pipeline = LaunchConfiguration("enable_depth_pipeline", default="false")
    enable_cone_avoidance = LaunchConfiguration("enable_cone_avoidance", default="false")
    enable_cone_mode_control = LaunchConfiguration("enable_cone_mode_control", default="false")
    enable_apriltag_bridge = LaunchConfiguration(
        "enable_apriltag_bridge", default="false"
    )
    enable_yolo_udp_bridge = LaunchConfiguration(
        "enable_yolo_udp_bridge", default="false"
    )
    enable_arm_motion = LaunchConfiguration("enable_arm_motion", default="false")
    enable_manipulation = LaunchConfiguration("enable_manipulation", default="false")
    manipulation_calibrated = LaunchConfiguration(
        "manipulation_calibrated", default="false"
    )
    manipulation_params_file = LaunchConfiguration("manipulation_params_file")
    arm_motion_params_file = LaunchConfiguration("arm_motion_params_file")
    verify_depth_disable_localization = LaunchConfiguration(
        "verify_depth_disable_localization",
        default="true",
    )
    cone_params_file = LaunchConfiguration("cone_params_file")
    depth_frames_dir = LaunchConfiguration("depth_frames_dir")
    enable_whz = LaunchConfiguration("enable_whz", default="false")
    whz_rtsp_url = LaunchConfiguration("whz_rtsp_url")
    whz_model_path = LaunchConfiguration("whz_model_path")
    whz_device = LaunchConfiguration("whz_device")
    whz_required_frames = LaunchConfiguration("whz_required_frames")
    whz_min_agree_frames = LaunchConfiguration("whz_min_agree_frames")
    auto_advance = LaunchConfiguration("auto_advance", default="false")
    mission_start_armed = LaunchConfiguration("mission_start_armed", default="true")
    max_nav_retries = LaunchConfiguration("max_nav_retries", default="3")
    max_inspection_retries = LaunchConfiguration("max_inspection_retries", default="3")
    finish_after_inspection = LaunchConfiguration("finish_after_inspection", default="false")
    allow_placeholder_manipulation = LaunchConfiguration(
        "allow_placeholder_manipulation", default="false"
    )
    pass_obstacle_timeout_sec = LaunchConfiguration(
        "pass_obstacle_timeout_sec", default="180.0"
    )
    pass_obstacle_waypoint_timeout_sec = LaunchConfiguration(
        "pass_obstacle_waypoint_timeout_sec", default="120.0"
    )
    inspection_timeout_sec = LaunchConfiguration(
        "inspection_timeout_sec", default="300.0"
    )
    waypoint_file = LaunchConfiguration("waypoint_file", default="")
    waypoint_route = LaunchConfiguration(
        "waypoint_route", default="inspection_interleaved"
    )
    expected_map_id = LaunchConfiguration("expected_map_id", default="")
    enable_global_pose_manager = LaunchConfiguration("enable_global_pose_manager", default="false")
    global_pose_mode = LaunchConfiguration("global_pose_mode", default="legacy_static")

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
    declare_enable_depth_pipeline = DeclareLaunchArgument(
        "enable_depth_pipeline",
        default_value="false",
        description="启动共享深度桥、动态障碍层和 fail-closed 速度门。默认关闭。",
    )
    declare_depth_frames_dir = DeclareLaunchArgument(
        "depth_frames_dir",
        default_value=str(
            Path.home() / "workspaces" / "isaac_ros-dev" / "camera_frames"
        ),
        description="Docker depth relay 与 Host bridge 的共享目录。",
    )
    declare_enable_cone_avoidance = DeclareLaunchArgument(
        "enable_cone_avoidance",
        default_value="false",
        description="启动 D455 LaserScan UDP、本地锥桶代价层和 fail-closed 速度门。默认关闭。",
    )
    declare_enable_cone_mode_control = DeclareLaunchArgument(
        "enable_cone_mode_control",
        default_value="false",
        description="越障后动态关闭 D455 depth、锥桶 costmap 与扫描安全门。",
    )
    declare_enable_apriltag_bridge = DeclareLaunchArgument(
        "enable_apriltag_bridge",
        default_value="false",
        description="启动 Host AprilTag UDP bridge（Docker UDP 19003）。",
    )
    declare_enable_yolo_udp_bridge = DeclareLaunchArgument(
        "enable_yolo_udp_bridge",
        default_value="false",
        description="启动 Host D455 YOLO UDP bridge（Docker UDP 19004）。",
    )
    declare_enable_arm_motion = DeclareLaunchArgument(
        "enable_arm_motion",
        default_value="false",
        description="启动机械臂服务节点；运动授权仍由独立参数文件控制。",
    )
    declare_enable_manipulation = DeclareLaunchArgument(
        "enable_manipulation",
        default_value="false",
        description="启用 TaskManager 抓取、放置和精对齐正式实现。",
    )
    declare_manipulation_calibrated = DeclareLaunchArgument(
        "manipulation_calibrated",
        default_value="false",
        description="仅在 AprilTag/I2/抓取/放置标定和分段验收后设为 true。",
    )
    declare_manipulation_params_file = DeclareLaunchArgument(
        "manipulation_params_file",
        default_value=str(
            PROJECT_ROOT / "configs" / "manipulation" / "pick_place.yaml"
        ),
        description="TaskManager 抓放标定参数文件。",
    )
    declare_arm_motion_params_file = DeclareLaunchArgument(
        "arm_motion_params_file",
        default_value=PathJoinSubstitution([
            FindPackageShare("arm_new_ros"), "config", "arm_motion_params.yaml",
        ]),
        description="机械臂服务参数文件。",
    )
    declare_verify_depth_disable_localization = DeclareLaunchArgument(
        "verify_depth_disable_localization",
        default_value="true",
        description="测试时等待 IR/IMU/cuVSLAM/Host odom；比赛可关闭额外等待。",
    )
    declare_cone_params_file = DeclareLaunchArgument(
        "cone_params_file",
        default_value=str(DEFAULT_CONE_PARAMS),
        description="锥桶模式 Nav2 参数 overlay；默认使用已验收正式配置。",
    )
    declare_enable_whz = DeclareLaunchArgument(
        "enable_whz", default_value="false",
        description="启动 whz RTSP 巡检 (YOLO 字母+仪表+语音播报)"
    )
    declare_whz_rtsp_url = DeclareLaunchArgument(
        "whz_rtsp_url",
        default_value="rtsp://192.168.1.120:8554/test",
        description="Lite3 前置相机 RTSP URL",
    )
    declare_whz_model_path = DeclareLaunchArgument(
        "whz_model_path",
        default_value=PathJoinSubstitution([
            FindPackageShare("whz"), "assets", "models", "gauge_best.pt",
        ]),
        description="WHZ YOLO 模型路径",
    )
    declare_whz_device = DeclareLaunchArgument(
        "whz_device", default_value="0",
        description="Ultralytics 推理设备，例如 0 或 cpu",
    )
    declare_whz_required_frames = DeclareLaunchArgument(
        "whz_required_frames", default_value="3",
        description="单次巡检读取的新帧数量",
    )
    declare_whz_min_agree_frames = DeclareLaunchArgument(
        "whz_min_agree_frames", default_value="2",
        description="巡检投票成功所需一致帧数",
    )
    declare_auto_advance = DeclareLaunchArgument(
        "auto_advance", default_value="false",
        description="调试模式：跳过部分任务等待条件"
    )
    declare_mission_start_armed = DeclareLaunchArgument(
        "mission_start_armed", default_value="true",
        description="允许 TaskManager 从 START 推进；正式启动验收期间设为 false。",
    )
    declare_max_nav_retries = DeclareLaunchArgument(
        "max_nav_retries", default_value="3",
        description="TaskManager 对失败 Nav2 goal 的重新提交次数",
    )
    declare_max_inspection_retries = DeclareLaunchArgument(
        "max_inspection_retries", default_value="3",
        description="TaskManager 对失败 WHZ 请求的重新提交次数",
    )
    declare_finish_after_inspection = DeclareLaunchArgument(
        "finish_after_inspection", default_value="false",
        description="完成 WHZ 巡检后进入 FINISH，不进入抓放流程",
    )
    declare_allow_placeholder_manipulation = DeclareLaunchArgument(
        "allow_placeholder_manipulation", default_value="false",
        description="仅台架调试允许 1 秒抓放占位器自动推进",
    )
    declare_pass_obstacle_timeout_sec = DeclareLaunchArgument(
        "pass_obstacle_timeout_sec", default_value="180.0",
        description="三个越障前置航点共用的阶段总超时",
    )
    declare_pass_obstacle_waypoint_timeout_sec = DeclareLaunchArgument(
        "pass_obstacle_waypoint_timeout_sec", default_value="120.0",
        description="单个越障前置航点的独立导航超时",
    )
    declare_inspection_timeout_sec = DeclareLaunchArgument(
        "inspection_timeout_sec", default_value="300.0",
        description="完整 WHZ 巡检阶段独立超时",
    )
    declare_waypoint_file = DeclareLaunchArgument(
        "waypoint_file", default_value="",
        description="已完成标定的正式路点文件；空值使用兼容内置坐标",
    )
    declare_waypoint_route = DeclareLaunchArgument(
        "waypoint_route", default_value="inspection_interleaved",
        description="waypoint_file 中选择的命名路线",
    )
    declare_expected_map_id = DeclareLaunchArgument(
        "expected_map_id", default_value="",
        description="非空时要求路点文件 map_id 精确匹配",
    )
    declare_enable_global_pose_manager = DeclareLaunchArgument(
        "enable_global_pose_manager", default_value="false",
        description="启动唯一 global_pose_manager。默认关闭，保持 legacy_static。",
    )
    declare_global_pose_mode = DeclareLaunchArgument(
        "global_pose_mode", default_value="legacy_static",
        description="global_pose_manager 模式：legacy_static/cuvslam_global/relocalize_hold/fault_hold",
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
    whz_inspection_node = Node(
        package="whz",
        executable="inspection_node",
        name="whz_inspection_node",
        output="screen",
        parameters=[{
            "rtsp_url": whz_rtsp_url,
            "model_path": whz_model_path,
            "device": whz_device,
            "required_frames": ParameterValue(whz_required_frames, value_type=int),
            "min_agree_frames": ParameterValue(whz_min_agree_frames, value_type=int),
        }],
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
            manipulation_params_file,
            {
                "auto_advance": auto_advance,
                "mission_start_armed": ParameterValue(
                    mission_start_armed, value_type=bool
                ),
                "max_nav_retries": ParameterValue(max_nav_retries, value_type=int),
                "max_inspection_retries": ParameterValue(
                    max_inspection_retries, value_type=int
                ),
                "finish_after_inspection": ParameterValue(
                    finish_after_inspection, value_type=bool
                ),
                "allow_placeholder_manipulation": ParameterValue(
                    allow_placeholder_manipulation, value_type=bool
                ),
                "enable_manipulation": ParameterValue(
                    enable_manipulation, value_type=bool
                ),
                "manipulation_calibrated": ParameterValue(
                    manipulation_calibrated, value_type=bool
                ),
                "manipulation_frames_dir": depth_frames_dir,
                "pass_obstacle_timeout_sec": ParameterValue(
                    pass_obstacle_timeout_sec, value_type=float
                ),
                "pass_obstacle_waypoint_timeout_sec": ParameterValue(
                    pass_obstacle_waypoint_timeout_sec, value_type=float
                ),
                "inspection_timeout_sec": ParameterValue(
                    inspection_timeout_sec, value_type=float
                ),
                "waypoint_file": waypoint_file,
                "waypoint_route": waypoint_route,
                "expected_map_id": expected_map_id,
                "enable_cone_controller": ParameterValue(
                    enable_cone_avoidance,
                    value_type=bool,
                ),
                "cone_behavior_tree": CONE_BEHAVIOR_TREE,
                "phase2_map_yaml": str(PROJECT_ROOT / "navi" / "map" / "competition_field_phase2.yaml"),
                "enable_phase2_map_switch": False,
                "enable_depth_milestones": ParameterValue(
                    PythonExpression([
                        "'", enable_depth_pipeline, "' == 'true' or '",
                        enable_cone_mode_control, "' == 'true'",
                    ]),
                    value_type=bool,
                ),
                "require_cone_layer_startup_ready": ParameterValue(
                    enable_cone_mode_control,
                    value_type=bool,
                ),
                "depth_safety_status_topic": PythonExpression([
                    "'/cone_obstacle/safety_gate_status' if '",
                    enable_cone_mode_control,
                    "' == 'true' else '/depth/safety_gate_status'",
                ]),
                "verify_host_odom_after_depth_disable": ParameterValue(
                    verify_depth_disable_localization,
                    value_type=bool,
                ),
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
        condition=IfCondition(PythonExpression([
            "'", enable_navigation, "' == 'true' and ('",
            enable_global_pose_manager, "' == 'false' or '",
            global_pose_mode, "' == 'legacy_static')",
        ])),
    )

    global_pose_node = Node(
        package="quadruped_robot_competition",
        executable="global_pose_manager",
        name="global_pose_manager_node",
        output="screen",
        parameters=[{
            "mode": global_pose_mode,
            "config_file": str(PROJECT_ROOT / "configs" / "navigation" / "global_pose.yaml"),
            "vo_topic": "/odom",
            "slam_topic": "/cuvslam/slam_pose",
        }],
        condition=IfCondition(enable_global_pose_manager),
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
        condition=IfCondition(PythonExpression([
            "'", enable_navigation, "' == 'true' and ('",
            enable_cone_avoidance, "' != 'true' or '",
            enable_manipulation, "' == 'true')",
        ])),
    )

    depth_pub_node = Node(
        package="quadruped_robot_competition",
        executable="depth_publisher",
        name="d455_depth_publisher",
        output="screen",
        condition=IfCondition(enable_depth_publisher),
    )

    apriltag_bridge_node = Node(
        package="quadruped_robot_competition",
        executable="apriltag_udp_bridge",
        name="apriltag_udp_bridge_node",
        output="screen",
        condition=IfCondition(enable_apriltag_bridge),
    )

    yolo_udp_bridge_node = Node(
        package="quadruped_robot_competition",
        executable="yolo_udp_bridge",
        name="yolo_udp_bridge_node",
        output="screen",
        condition=IfCondition(enable_yolo_udp_bridge),
    )

    arm_motion_node = Node(
        package="arm_new_ros",
        executable="arm_motion_node",
        name="arm_motion_node",
        parameters=[arm_motion_params_file],
        output="screen",
        condition=IfCondition(enable_arm_motion),
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
        launch_arguments={
            "enable_depth_pipeline": enable_depth_pipeline,
            "depth_frames_dir": depth_frames_dir,
            "enable_cone_avoidance": enable_cone_avoidance,
            "enable_cone_mode_control": enable_cone_mode_control,
            "cone_params_file": cone_params_file,
        }.items(),
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
            "║ depth_pipeline   : ", enable_depth_pipeline, "  ║\n",
            "║ cone_avoidance   : ", enable_cone_avoidance, "  ║\n",
            "║ AprilTag bridge  : ", enable_apriltag_bridge, "  ║\n",
            "║ YOLO UDP bridge  : ", enable_yolo_udp_bridge, "  ║\n",
            "║ arm motion       : ", enable_arm_motion, "  ║\n",
            "║ manipulation     : ", enable_manipulation, "  ║\n",
            "║ whz_inspection   : ", enable_whz, "  ║\n",
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
        declare_enable_depth_pipeline,
        declare_depth_frames_dir,
        declare_enable_cone_avoidance,
        declare_enable_cone_mode_control,
        declare_enable_apriltag_bridge,
        declare_enable_yolo_udp_bridge,
        declare_enable_arm_motion,
        declare_enable_manipulation,
        declare_manipulation_calibrated,
        declare_manipulation_params_file,
        declare_arm_motion_params_file,
        declare_verify_depth_disable_localization,
        declare_cone_params_file,
        declare_enable_whz,
        declare_whz_rtsp_url,
        declare_whz_model_path,
        declare_whz_device,
        declare_whz_required_frames,
        declare_whz_min_agree_frames,
        declare_auto_advance,
        declare_mission_start_armed,
        declare_max_nav_retries,
        declare_max_inspection_retries,
        declare_finish_after_inspection,
        declare_allow_placeholder_manipulation,
        declare_pass_obstacle_timeout_sec,
        declare_pass_obstacle_waypoint_timeout_sec,
        declare_inspection_timeout_sec,
        declare_waypoint_file,
        declare_waypoint_route,
        declare_expected_map_id,
        declare_enable_global_pose_manager,
        declare_global_pose_mode,
        startup_info,
        gauge_node,
        yolo_node,
        whz_inspection_node,
        task_manager_node,
        speech_node,
        initial_pose_node,
        global_pose_node,
        base_to_camera_tf,
        depth_pub_node,
        apriltag_bridge_node,
        yolo_udp_bridge_node,
        arm_motion_node,
        cmd_vel_bridge_node,
        navigation_launch,
    ])
