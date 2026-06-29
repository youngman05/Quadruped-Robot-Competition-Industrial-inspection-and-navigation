#!/usr/bin/env python3
"""Bridge v2: Docker cuVSLAM → host /odom. Uses MultiThreadedExecutor for DDS."""
import subprocess, re, threading
import rclpy
from rclpy.executors import MultiThreadedExecutor
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformBroadcaster
from rclpy.qos import QoSProfile, ReliabilityPolicy

rclpy.init()
be = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
node = rclpy.create_node("final_bridge")
pub = node.create_publisher(Odometry, "/odom", be)
tf_br = TransformBroadcaster(node)

# Find Docker container
out = subprocess.check_output(["docker", "ps", "--format", "{{.Names}}"]).decode()
container = [l for l in out.strip().split("\n") if "cuvslam" in l][0]
node.get_logger().info(f"Docker: {container}")

proc = subprocess.Popen(
    ["docker", "exec", container, "bash", "-c",
     "source /opt/ros/humble/setup.bash && "
     "source /workspaces/isaac_ros-dev/install/setup.bash && "
     "stdbuf -oL ros2 topic echo /visual_slam/vis/slam_odometry 2>/dev/null"],
    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)

c = [0]
x = y = z = 0.0
ox = oy = oz = 0.0
ow = 1.0
running = True


def parser_thread():
    global x, y, z, ox, oy, oz, ow, running
    for line in proc.stdout:
        m = re.match(r"\s*x:\s*(-?[\d.]+)", line)
        if m: x = float(m.group(1))
        m = re.match(r"\s*y:\s*(-?[\d.]+)", line)
        if m: y = float(m.group(1))
        m = re.match(r"\s*z:\s*(-?[\d.]+)", line)
        if m: z = float(m.group(1))
        qm = re.search(r"x:\s*(-?[\d.]+).*y:\s*(-?[\d.]+).*z:\s*(-?[\d.]+).*w:\s*(-?[\d.]+)", line)
        if qm:
            ox, oy, oz, ow = map(float, qm.groups())
        if "---" in line and c[0] > 0:
            c[0] += 1
        elif "---" in line:
            c[0] = 1
    running = False


def publish_timer():
    while running:
        if c[0] > 0:
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
            t.transform.translation.x, t.transform.translation.y, t.transform.translation.z = x, y, z
            t.transform.rotation.x, t.transform.rotation.y, t.transform.rotation.z, t.transform.rotation.w = ox, oy, oz, ow
            tf_br.sendTransform(t)
        rclpy.spin_once(node, timeout_sec=0.015)


node.get_logger().info("bridge v2 running (MultiThreaded)...")
t1 = threading.Thread(target=parser_thread, daemon=True)
t1.start()

# 30-second startup then periodic status
import time
t0 = time.time()
while running and time.time() - t0 < 300:
    publish_timer()
    if c[0] > 0 and c[0] % 500 == 1:
        node.get_logger().info(f"bridged {c[0]} msgs")

node.get_logger().info(f"done: {c[0]}")
rclpy.shutdown()
