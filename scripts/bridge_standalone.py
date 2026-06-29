#!/usr/bin/env python3
"""Standalone bridge - subscribe cuVSLAM (best_effort) -> publish /odom + TF."""
import rclpy
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformBroadcaster
from rclpy.qos import QoSProfile, ReliabilityPolicy

rclpy.init()
be = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
node = rclpy.create_node("bridge")
pub = node.create_publisher(Odometry, "/odom", be)
tf_br = TransformBroadcaster(node)
count = [0]


def cb(msg):
    count[0] += 1
    out = Odometry()
    out.header = msg.header
    out.header.frame_id = "odom"
    out.child_frame_id = "base_link"
    out.pose = msg.pose
    out.twist = msg.twist
    pub.publish(out)

    t = TransformStamped()
    t.header.stamp = msg.header.stamp
    t.header.frame_id = "odom"
    t.child_frame_id = "base_link"
    t.transform.translation.x = msg.pose.pose.position.x
    t.transform.translation.y = msg.pose.pose.position.y
    t.transform.translation.z = msg.pose.pose.position.z
    t.transform.rotation = msg.pose.pose.orientation
    tf_br.sendTransform(t)

    if count[0] % 100 == 1:
        node.get_logger().info(f"RX {count[0]} msgs")


node.create_subscription(
    Odometry, "/visual_slam/vis/slam_odometry", cb, be)
node.get_logger().info("bridge running, waiting for DDS discovery...")

while rclpy.ok():
    rclpy.spin_once(node, timeout_sec=0.1)

node.destroy_node()
rclpy.shutdown()
