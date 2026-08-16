"""Package setup with ROS2 node entry points."""
from setuptools import setup, find_packages
from glob import glob

package_name = "quadruped_robot_competition"

setup(
    name=package_name,
    version="0.1.0",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.8",
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob("launch/*.py")),
        (
            "share/" + package_name + "/configs/navigation",
            glob("configs/navigation/*.yaml") + glob("configs/navigation/*.xml"),
        ),
        (
            "share/" + package_name + "/configs/manipulation",
            glob("configs/manipulation/*.yaml"),
        ),
        (
            "share/" + package_name + "/configs/transforms",
            glob("configs/transforms/*.yaml"),
        ),
        ("share/" + package_name + "/configs/ros", glob("configs/ros/*")),
        ("share/" + package_name + "/navi/map", glob("navi/map/*.pgm") + glob("navi/map/*.yaml")),
    ],
    # ROS2 节点入口 — ros2 run quadruped_robot_competition <name>
    entry_points={
        "console_scripts": [
            # ── 感知层 ──────────────────────────
            "gauge_status_publisher = nodes.perception.gauge_status:main",
            "yolo_detect_publisher = nodes.perception.yolo_detect_publisher:main",
            "color_image_publisher = nodes.perception.color_image_publisher:main",
            "yolo_image_server = nodes.perception.yolo_image_server:main",
            "apriltag_udp_bridge = nodes.perception.apriltag_udp_bridge:main",
            "yolo_udp_bridge = nodes.perception.yolo_udp_bridge:main",
            # ── 决策层 ──────────────────────────
            "task_manager = nodes.decision.task_manager:main",
            # "speech_publisher = nodes.decision.speech:main",
            # ── 导航层 ──────────────────────────
            "depth_publisher = nodes.navigation.depth_publisher:main",
            "initial_pose_publisher = nodes.navigation.initial_pose_publisher:main",
            "global_pose_manager = nodes.navigation.global_pose_manager:main",
            "cuvslam_bridge = nodes.navigation.cuvslam_bridge:main",
            "ir_imu_bridge = nodes.navigation.ir_imu_bridge:main",
            "cmd_vel_arbiter = nodes.navigation.cmd_vel_arbiter:main",
            "cmd_vel_bridge = nodes.navigation.cmd_vel_bridge:main",
            "depth_relay_publisher = nodes.navigation.depth_relay_publisher:main",
            "depth_safety_gate = nodes.navigation.depth_safety_gate:main",
            "cone_scan_udp_bridge = nodes.navigation.cone_scan_udp_bridge:main",
            "cone_scan_safety_gate = nodes.navigation.cone_scan_safety_gate:main",
        ],
    },
)
