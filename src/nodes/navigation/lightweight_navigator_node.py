"""
Lightweight Navigator — standalone ROS2 node wrapper for testing.

Normally the Navigator is used as a library by task_manager.
This node allows testing the navigator independently by sending
goals via a ROS2 topic.

Subscribes:
  /nav/goal (String) — waypoint name to navigate to

Usage:
  ros2 run quadruped_robot_competition lightweight_navigator
  ros2 topic pub /nav/goal std_msgs/String "data: 'pos1_middle'"
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from navigation.navigator import Navigator


class LightweightNavigatorNode(Node):
    """Standalone node wrapping the Navigator library for testing."""

    def __init__(self):
        super().__init__("lightweight_navigator")
        self._nav = Navigator(self)

        self._goal_sub = self.create_subscription(
            String, "/nav/goal", self._goal_callback, 10,
        )
        self._status_pub = self.create_publisher(String, "/nav/status", 10)

        self._timer = self.create_timer(0.5, self._status_timer)

        self.get_logger().info("Lightweight Navigator ready — send waypoint names to /nav/goal")

    def _goal_callback(self, msg: String):
        name = msg.data.strip()
        if not name:
            return
        self._nav.cancel()
        self._nav.reset()
        ok = self._nav.navigate_to_waypoint(name)
        self.get_logger().info(
            f"Goal '{name}': {'path found' if ok else 'PLANNING FAILED'}"
        )

    def _status_timer(self):
        if self._nav.is_done():
            status = "succeeded" if self._nav.succeeded() else "failed"
            self.get_logger().info(f"Navigation {status}")
            self._nav.reset()
        elif self._nav.goal_sent:
            x, y, yaw = self._nav.get_current_pose()
            msg = String()
            msg.data = f"moving | pose=({x:.2f},{y:.2f},{yaw:.2f})"
            self._status_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = LightweightNavigatorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
