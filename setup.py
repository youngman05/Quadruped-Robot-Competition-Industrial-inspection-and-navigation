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
            # 仪表检测节点（已实现）
            "gauge_status = quadruped_robot_competition.nodes.gauge_status:main",
            # YOLO 检测节点（已实现，需 pip install ultralytics torch）
            "yolo_detect = quadruped_robot_competition.nodes.yolo_detect:main",
            # 比赛状态机
            "task_manager = quadruped_robot_competition.nodes.task_manager:main",
            # 语音播报（待实现）
            # "speech = quadruped_robot_competition.nodes.speech:main",
        ],
    },
)
