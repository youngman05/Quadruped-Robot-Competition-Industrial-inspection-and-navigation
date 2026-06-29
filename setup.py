"""Package setup — ament_python compatible."""
from setuptools import setup, find_packages
from glob import glob
import os

package_name = "quadruped_robot_competition"

setup(
    name=package_name,
    version="0.1.0",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.8",
    data_files=[
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob("launch/*.py")),
        ("share/" + package_name + "/configs/navigation",
         glob("configs/navigation/*.yaml")),
        ("share/" + package_name + "/navi/map",
         glob("navi/map/*.pgm") + glob("navi/map/*.yaml")),
    ],
    entry_points={
        "console_scripts": [
            "gauge_status_publisher = nodes.perception.gauge_status:main",
            "yolo_detect_publisher = nodes.perception.yolo_detect_publisher:main",
            "task_manager = nodes.decision.task_manager:main",
            "depth_publisher = nodes.navigation.depth_publisher:main",
            "cuvslam_bridge = nodes.navigation.cuvslam_bridge:main",
            "ir_imu_bridge = nodes.navigation.ir_imu_bridge:main",
            "initial_pose_publisher = nodes.navigation.initial_pose_publisher:main",
        ],
    },
)
