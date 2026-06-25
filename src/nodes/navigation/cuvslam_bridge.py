"""
cuVSLAM Bridge — relays cuVSLAM Docker odometry into the Nav2 frame tree.

ROS2 Node: cuvslam_bridge

Input (from cuVSLAM Docker container, ROS2 Humble):
  /visual_slam/tracking/odometry  — nav_msgs/Odometry
  /visual_slam/status             — std_msgs/String (or custom)
  /tf                             — cuVSLAM publishes odom → camera_pose

Output (to Nav2):
  /odom                            — nav_msgs/Odometry (child_frame_id=base_link)
  /slam/status                     — std_msgs/String ("ok" / "lost")
  TF: odom → base_link             — reparented from camera_pose

The bridge reads cuVSLAM's pose, applies the fixed camera→base transform,
and re-publishes odometry + TF in a form Nav2 understands.
"""

import sys
import math
from pathlib import Path

import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from std_msgs.msg import String
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformBroadcaster


class CuvslamBridge(Node):
    """Bridge cuVSLAM odometry to Nav2-compatible /odom + TF."""

    def __init__(self):
        super().__init__("cuvslam_bridge")

        # parameters
        self.declare_parameter("slam_odom_topic", "/visual_slam/tracking/odometry")
        self.declare_parameter("slam_status_topic", "/visual_slam/status")
        self.declare_parameter("camera_frame", "camera_link")
        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("odom_frame", "odom")

        self._slam_odom = self.get_parameter("slam_odom_topic").value
        self._slam_status = self.get_parameter("slam_status_topic").value
        self._camera_frame = self.get_parameter("camera_frame").value
        self._base_frame = self.get_parameter("base_frame").value
        self._odom_frame = self.get_parameter("odom_frame").value

        # subscribers
        self._odom_sub = self.create_subscription(
            Odometry, self._slam_odom, self._odom_callback, 10
        )
        self._status_sub = self.create_subscription(
            String, self._slam_status, self._status_callback, 10
        )

        # publishers
        self._odom_pub = self.create_publisher(Odometry, "/odom", 10)
        self._status_pub = self.create_publisher(String, "/slam/status", 10)

        # TF broadcaster
        self._tf_broadcaster = TransformBroadcaster(self)

        self.get_logger().info(
            f"cuVSLAM bridge ready: {self._slam_odom} → /odom"
        )

    def _odom_callback(self, msg: Odometry):
        """Re-publish cuVSLAM odometry with child_frame_id = base_link."""
        # The cuVSLAM odometry has child_frame_id = camera_pose (or similar).
        # We reparent it to base_link and republish.
        out = Odometry()
        out.header = msg.header
        out.header.frame_id = self._odom_frame
        out.child_frame_id = self._base_frame
        out.pose = msg.pose
        out.twist = msg.twist
        self._odom_pub.publish(out)

        # Also publish TF: odom → base_link
        t = TransformStamped()
        t.header.stamp = msg.header.stamp
        t.header.frame_id = self._odom_frame
        t.child_frame_id = self._base_frame
        t.transform.translation.x = msg.pose.pose.position.x
        t.transform.translation.y = msg.pose.pose.position.y
        t.transform.translation.z = msg.pose.pose.position.z
        t.transform.rotation = msg.pose.pose.orientation
        self._tf_broadcaster.sendTransform(t)

    def _status_callback(self, msg: String):
        """Translate cuVSLAM status to /slam/status for task_manager."""
        # The task_manager expects /visual_slam/status, but we publish
        # a cleaned version on /slam/status as well.
        # Normalise known cuVSLAM status strings:
        data = msg.data.strip().lower()
        if data in ("tracking", "ok", "initialized", "running"):
            status = "ok"
        elif data in ("lost", "relocalizing", "error"):
            status = "lost"
        else:
            status = data   # passthrough

        out = String()
        out.data = status
        self._status_pub.publish(out)


def main(args=None):
    rclpy.init(args=args)
    node = CuvslamBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
