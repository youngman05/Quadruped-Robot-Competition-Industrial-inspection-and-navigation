#!/usr/bin/env python3
"""Publish one project-owned static transform with Host rclpy."""

import rclpy
from geometry_msgs.msg import TransformStamped
from rclpy.node import Node
from tf2_ros.static_transform_broadcaster import StaticTransformBroadcaster


class StaticTransformPublisher(Node):
    def __init__(self) -> None:
        super().__init__("project_static_transform_publisher")
        self.declare_parameter("parent_frame", "base_link")
        self.declare_parameter("child_frame", "camera_link")
        self.declare_parameter("translation_m", [0.0, 0.0, 0.0])
        self.declare_parameter("rotation_xyzw", [0.0, 0.0, 0.0, 1.0])

        parent = str(self.get_parameter("parent_frame").value)
        child = str(self.get_parameter("child_frame").value)
        translation = self.get_parameter("translation_m").value
        rotation = self.get_parameter("rotation_xyzw").value

        message = TransformStamped()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = parent
        message.child_frame_id = child
        message.transform.translation.x = float(translation[0])
        message.transform.translation.y = float(translation[1])
        message.transform.translation.z = float(translation[2])
        message.transform.rotation.x = float(rotation[0])
        message.transform.rotation.y = float(rotation[1])
        message.transform.rotation.z = float(rotation[2])
        message.transform.rotation.w = float(rotation[3])

        self._broadcaster = StaticTransformBroadcaster(self)
        self._broadcaster.sendTransform(message)
        self.get_logger().info("Static TF {} -> {}".format(parent, child))


def main(args=None) -> None:
    rclpy.init(args=args)
    node = StaticTransformPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
