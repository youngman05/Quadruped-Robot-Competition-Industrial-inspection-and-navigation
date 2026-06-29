#!/usr/bin/env python3
"""Host-side bridge: reads cuVSLAM odometry via docker exec, publishes /odom.
Uses stdbuf + regex parsing (no --csv, works on Humble)."""
import subprocess, re, time
import rclpy
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformBroadcaster
from rclpy.qos import QoSProfile, ReliabilityPolicy


def find_container():
    out = subprocess.check_output(["docker", "ps", "--format", "{{.Names}}"]).decode()
    for line in out.strip().split("\n"):
        if "cuvslam" in line:
            return line.strip()
    raise RuntimeError("No cuvslam container found")


def main():
    rclpy.init()
    be = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
    node = rclpy.create_node("docker_bridge")
    pub = node.create_publisher(Odometry, "/odom", be)
    tf_br = TransformBroadcaster(node)

    container = find_container()
    node.get_logger().info(f"container: {container}")

    proc = subprocess.Popen(
        ["docker", "exec", container, "bash", "-c",
         "source /opt/ros/humble/setup.bash && "
         "source /workspaces/isaac_ros-dev/install/setup.bash && "
         "stdbuf -oL ros2 topic echo /visual_slam/vis/slam_odometry 2>/dev/null"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1
    )

    node.get_logger().info("connected, waiting for data...")
    c = 0
    x = y = z = ox = oy = oz = ow = 0.0; ow = 1.0

    for line in proc.stdout:
        m = re.match(r"\s*x:\s*(-?[\d.]+)", line)
        if m: x = float(m.group(1))
        m = re.match(r"\s*y:\s*(-?[\d.]+)", line)
        if m: y = float(m.group(1))
        m = re.match(r"\s*z:\s*(-?[\d.]+)", line)
        if m: z = float(m.group(1))
        m = re.match(r".*x:\s*(-?[\d.]+).*y:\s*(-?[\d.]+).*z:\s*(-?[\d.]+).*w:\s*(-?[\d.]+)", line)
        if m: ox, oy, oz, ow = map(float, m.groups())

        if "---" in line and c > 0:
            c += 1
            msg = Odometry()
            msg.header.stamp = node.get_clock().now().to_msg()
            msg.header.frame_id = "odom"
            msg.child_frame_id = "base_link"
            msg.pose.pose.position.x = x
            msg.pose.pose.position.y = y
            msg.pose.pose.position.z = z
            msg.pose.pose.orientation.x = ox
            msg.pose.pose.orientation.y = oy
            msg.pose.pose.orientation.z = oz
            msg.pose.pose.orientation.w = ow
            pub.publish(msg)

            t = TransformStamped()
            t.header.stamp = msg.header.stamp
            t.header.frame_id = "odom"
            t.child_frame_id = "base_link"
            t.transform.translation.x = x
            t.transform.translation.y = y
            t.transform.translation.z = z
            t.transform.rotation.x = ox
            t.transform.rotation.y = oy
            t.transform.rotation.z = oz
            t.transform.rotation.w = ow
            tf_br.sendTransform(t)

            if c % 300 == 1:
                node.get_logger().info(f"bridged {c} msgs ({x:.2f},{y:.2f})")
        elif "---" in line:
            c = 1  # first message

    node.get_logger().info(f"done: {c}")
    rclpy.shutdown()


if __name__ == "__main__":
    main()
