"""Package setup with ROS2 node entry points."""
from setuptools import setup, find_packages

setup(
    name="quadruped-robot-competition",
    version="0.1.0",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.8",
    # ROS2 节点入口 — ros2 run quadruped_robot_competition <name>
    entry_points={
        "console_scripts": [
            # ── 感知层 ──────────────────────────
            "gauge_status_publisher = nodes.perception.gauge_status:main",
            "yolo_detect_publisher = nodes.perception.yolo_detect_publisher:main",
            # ── 决策层 ──────────────────────────
            "task_manager = nodes.decision.task_manager:main",
            # "speech_publisher = nodes.decision.speech:main",
            # ── 导航层 ──────────────────────────
            "depth_publisher = nodes.navigation.depth_publisher:main",
            "cuvslam_bridge = nodes.navigation.cuvslam_bridge:main",
            "initial_pose_publisher = nodes.navigation.initial_pose_publisher:main",
        ],
    },
)
