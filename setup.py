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
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch",
         glob("launch/*.py")),
        ("share/" + package_name + "/configs/navigation",
         glob("configs/navigation/*.yaml")),
        ("share/" + package_name + "/configs/ros",
         glob("configs/ros/*.yaml")),
        ("share/" + package_name + "/configs/transforms",
         glob("configs/transforms/*.yaml") + glob("configs/transforms/*.json")),
        ("share/" + package_name + "/configs/calibration",
         glob("configs/calibration/*.yaml")),
        ("share/" + package_name + "/configs/yolo",
         glob("configs/yolo/*.yaml") + glob("configs/yolo/*.json")),
        ("share/" + package_name + "/navi/map",
         glob("src/navi/map/*.pgm") + glob("src/navi/map/*.yaml")),
    ],
    include_package_data=True,
    package_data={
        "whz": [
            "assets/audio/*.mp3",
            "assets/templates/*",
        ],
    },
    # ROS2 节点入口 — ros2 run quadruped_robot_competition <name>
    entry_points={
        "console_scripts": [
            # ── 感知层 ──────────────────────────
            "gauge_status_publisher = nodes.perception.gauge_status:main",
            "yolo_detect_publisher = nodes.perception.yolo_detect_publisher:main",
            "yolo_udp_bridge = nodes.perception.yolo_udp_bridge:main",
            "color_image_publisher = nodes.perception.color_image_publisher:main",
            "whz_standalone = nodes.perception.whz_standalone_inspect:main",
            "whz_inspection_node = whz.inspection_node:main",
            "yolo_image_server = nodes.perception.yolo_image_server:main",
            # ── 决策层 ──────────────────────────
            "task_manager = nodes.decision.task_manager:main",
            "grasp_place_manager = nodes.decision.grasp_place_manager:main",
            # "speech_publisher = nodes.decision.speech:main",
            # ── 导航层 (Nav2) ──────────────────
            "depth_publisher = nodes.navigation.depth_publisher:main",
            "initial_pose_publisher = nodes.navigation.initial_pose_publisher:main",
            "cuvslam_bridge = nodes.navigation.cuvslam_bridge:main",
            "ir_imu_bridge = nodes.navigation.ir_imu_bridge:main",
            "cmd_vel_bridge = nodes.navigation.cmd_vel_bridge:main",
        ],
    },
)
