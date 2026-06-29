"""
Initial Pose Publisher — publishes the static map→odom TF transform.

ROS2 Node: initial_pose_publisher

Publishes:
  TF: map → odom  — static transform aligning cuVSLAM odometry origin
                    with the known robot start position on the competition field.

The lightweight navigator applies this same offset internally, so this
node provides the TF tree for any other consumers that need it.
"""

import sys
import math
from pathlib import Path

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import TransformStamped
from tf2_ros import StaticTransformBroadcaster


# Resolve workspace root for navi_map_data import (4 levels up from this file)
_WS_ROOT = Path(__file__).resolve().parents[3]  # navigation → nodes → src → root
_NAVI_MAP = _WS_ROOT / "navi" / "map"
if str(_NAVI_MAP) not in sys.path:
    sys.path.insert(0, str(_NAVI_MAP))

from navi_map_data import FIELD, ROBOT_START_POSE


def _mm_to_ros(x_mm: float, y_mm: float):
    """Convert mm field coords to ROS map coords."""
    ros_x = x_mm / 1000.0
    ros_y = (FIELD["height"] - y_mm) / 1000.0
    return ros_x, ros_y


def _yaw_to_quaternion(yaw_deg: float):
    """Convert yaw degrees (mm coords, 0=right) to ROS quaternion."""
    half = math.radians(yaw_deg) / 2.0
    return (0.0, 0.0, math.sin(half), math.cos(half))


class InitialPosePublisher(Node):
    """Publish initial robot pose + map→odom transform."""

    def __init__(self):
        super().__init__("initial_pose_publisher")

        self.declare_parameter("publish_rate", 1.0)
        self.declare_parameter("map_frame", "map")
        self.declare_parameter("odom_frame", "odom")

        publish_rate = self.get_parameter("publish_rate").value
        self._map_frame = self.get_parameter("map_frame").value
        self._odom_frame = self.get_parameter("odom_frame").value

        self._tf_broadcaster = StaticTransformBroadcaster(self)

        # compute start pose
        ros_x, ros_y = _mm_to_ros(ROBOT_START_POSE["x_mm"], ROBOT_START_POSE["y_mm"])
        qx, qy, qz, qw = _yaw_to_quaternion(ROBOT_START_POSE["yaw_deg"])

        self.get_logger().info(
            f"Robot start pose — ROS: ({ros_x:.2f}, {ros_y:.2f})  "
            f"yaw: {ROBOT_START_POSE['yaw_deg']}°  "
            f"({ROBOT_START_POSE['note']})"
        )

        # Build the map → odom static transform
        self._map_to_odom = TransformStamped()
        self._map_to_odom.header.frame_id = self._map_frame
        self._map_to_odom.child_frame_id = self._odom_frame
        self._map_to_odom.transform.translation.x = ros_x
        self._map_to_odom.transform.translation.y = ros_y
        self._map_to_odom.transform.translation.z = 0.0
        self._map_to_odom.transform.rotation.x = qx
        self._map_to_odom.transform.rotation.y = qy
        self._map_to_odom.transform.rotation.z = qz
        self._map_to_odom.transform.rotation.w = qw

        # Publish TF periodically
        self._publish_tf_once()
        self._timer = self.create_timer(1.0 / publish_rate, self._publish_callback)

    def _publish_tf_once(self):
        stamp = self.get_clock().now().to_msg()
        self._map_to_odom.header.stamp = stamp
        self._tf_broadcaster.sendTransform(self._map_to_odom)
        self.get_logger().info("map→odom TF published")

    def _publish_callback(self):
        """Re-publish map→odom TF periodically."""
        stamp = self.get_clock().now().to_msg()
        self._map_to_odom.header.stamp = stamp
        self._tf_broadcaster.sendTransform(self._map_to_odom)


def main(args=None):
    rclpy.init(args=args)
    node = InitialPosePublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
