from setuptools import setup

package_name = "arm_new_ros"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name, "arm_api"],
    package_dir={
        "arm_api": "../arm_api",
    },
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/config", ["../config/arm_motion_params.yaml"]),
        ("share/" + package_name + "/launch", ["launch/arm_motion.launch.py"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="arm_new",
    maintainer_email="todo@example.com",
    description="ROS2 adapter node for the arm_new Python arm API.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "arm_motion_node = arm_new_ros.arm_motion_node:main",
        ],
    },
)
