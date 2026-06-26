"""
cuVSLAM Status Bridge — translates cuVSLAM Docker status to a simple
ok/lost signal for task_manager.

ROS2 Node: cuvslam_bridge

Input (from cuVSLAM Docker container, ROS2 Humble):
  /visual_slam/status   — std_msgs/String ("tracking", "lost", etc.)

Output (to task_manager):
  /slam/status          — std_msgs/String  ("ok" | "lost")

Why not publish /odom or TF?  The EKF (robot_localization) now fuses
cuVSLAM's odometry with leg odometry and IMU, and publishes the fused
/odom + TF.  This bridge only handles status translation.
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class CuvslamBridge(Node):
    """Translate cuVSLAM status to /slam/status for task_manager."""

    def __init__(self):
        super().__init__("cuvslam_bridge")

        self.declare_parameter("slam_status_topic", "/visual_slam/status")
        self.declare_parameter("status_out_topic", "/slam/status")

        slam_status = self.get_parameter("slam_status_topic").value
        status_out = self.get_parameter("status_out_topic").value

        self._status_sub = self.create_subscription(
            String, slam_status, self._status_callback, 10,
        )
        self._status_pub = self.create_publisher(String, status_out, 10)

        self.get_logger().info(
            f"cuVSLAM status bridge: {slam_status} → {status_out}"
        )

    def _status_callback(self, msg: String):
        """Normalise cuVSLAM status strings to ok/lost."""
        data = msg.data.strip().lower()
        if data in ("tracking", "ok", "initialized", "running", "nominal"):
            status = "ok"
        elif data in ("lost", "relocalizing", "error", "degraded", "unknown"):
            status = "lost"
        else:
            status = data  # passthrough

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
