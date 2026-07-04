"""
cuVSLAM Bridge — relays cuVSLAM Docker odometry into the Nav2 frame tree.

ROS2 Node: cuvslam_bridge

Input (from cuVSLAM Docker container):
  /visual_slam/tracking/odometry  — nav_msgs/Odometry
  /visual_slam/status             — std_msgs/String

Output (to Nav2):
  /odom                            — nav_msgs/Odometry (child_frame_id=base_link)
  /slam/status                     — std_msgs/String ("ok" / "lost")
  TF: odom → base_link

定位策略: 完全信任 cuVSLAM 视觉里程计结果, 不融合腿里程计或 IMU。
"""

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

        self.declare_parameter("slam_odom_topic", "/visual_slam/vis/slam_odometry")
        self.declare_parameter("slam_status_topic", "/visual_slam/status")
        self.declare_parameter("camera_frame", "camera_link")
        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("odom_frame", "odom")

        slam_odom = self.get_parameter("slam_odom_topic").value
        slam_status = self.get_parameter("slam_status_topic").value
        self._camera_frame = self.get_parameter("camera_frame").value
        self._base_frame = self.get_parameter("base_frame").value
        self._odom_frame = self.get_parameter("odom_frame").value

        # cuVSLAM composable node uses BEST_EFFORT — must match
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        best_effort = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)

        self._odom_sub = self.create_subscription(
            Odometry, slam_odom, self._odom_callback, best_effort,
        )
        self._status_sub = self.create_subscription(
            String, slam_status, self._status_callback, best_effort,
        )

        self._odom_pub = self.create_publisher(Odometry, "/odom", 10)
        self._status_pub = self.create_publisher(String, "/slam/status", 10)
        self._tf_broadcaster = TransformBroadcaster(self)

        self.get_logger().info(
            f"cuVSLAM bridge: {slam_odom} → /odom + TF"
        )

    def _odom_callback(self, msg: Odometry):
        """Re-publish cuVSLAM odometry with child_frame_id = base_link."""
        out = Odometry()
        out.header = msg.header
        out.header.frame_id = self._odom_frame
        out.child_frame_id = self._base_frame
        out.pose = msg.pose
        out.twist = msg.twist
        self._odom_pub.publish(out)

        # TF: odom → base_link
        t = TransformStamped()
        t.header.stamp = msg.header.stamp
        t.header.frame_id = self._odom_frame
        t.child_frame_id = self._base_frame
        pos = msg.pose.pose.position
        rot = msg.pose.pose.orientation
        t.transform.translation.x = pos.x
        t.transform.translation.y = pos.y
        t.transform.translation.z = pos.z
        t.transform.rotation = rot
        self._tf_broadcaster.sendTransform(t)

    def _status_callback(self, msg: String):
        """Translate cuVSLAM status to /slam/status for task_manager."""
        data = msg.data.strip().lower()
        if data in ("tracking", "ok", "initialized", "running", "nominal"):
            status = "ok"
        elif data in ("lost", "relocalizing", "error", "degraded", "unknown"):
            status = "lost"
        else:
            status = data
        out = String()
        out.data = status
        self._status_pub.publish(out)


def main(args=None):
    import time
    rclpy.init(args=args)
    node = CuvslamBridge()
    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
