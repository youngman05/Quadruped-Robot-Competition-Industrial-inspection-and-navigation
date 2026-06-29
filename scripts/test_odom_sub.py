import rclpy, time
from nav_msgs.msg import Odometry
from rclpy.qos import QoSProfile, ReliabilityPolicy
rclpy.init()
be = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
n = rclpy.create_node("verif")
c = [0]
def cb(m):
    c[0] += 1
    if c[0] == 1: n.get_logger().info(f"GOT /odom: x={m.pose.pose.position.x:.2f}")
n.create_subscription(Odometry, "/odom", cb, be)
n.get_logger().info("listening for /odom...")
t0 = time.time()
while time.time() - t0 < 6:
    rclpy.spin_once(n, timeout_sec=0.1)
n.get_logger().info(f"total: {c[0]}")
rclpy.shutdown()
