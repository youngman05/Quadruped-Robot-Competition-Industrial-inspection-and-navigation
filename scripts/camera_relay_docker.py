#!/usr/bin/env python3
"""Runs inside Docker: subscribes to /camera/color/image_raw, saves jpg to shared dir."""
import rclpy, cv2, time, os
from sensor_msgs.msg import Image
from cv_bridge import CvBridge

OUT_DIR = "/workspaces/isaac_ros-dev/camera_frames"
os.makedirs(OUT_DIR, exist_ok=True)

bridge = CvBridge()
latest_jpg = os.path.join(OUT_DIR, "latest_color.jpg")
count = 0


def callback(msg):
    global count
    cv_image = bridge.imgmsg_to_cv2(msg, "bgr8")
    tmp = latest_jpg + ".tmp"
    cv2.imwrite(tmp, cv_image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    os.rename(tmp, latest_jpg)  # atomic on same filesystem
    count += 1
    if count % 50 == 1:
        print(f"Saved {count} frames", flush=True)


rclpy.init()
node = rclpy.create_node("camera_relay")
node.create_subscription(Image, "/camera/color/image_raw", callback, 10)
node.get_logger().info(f"Writing frames to {latest_jpg}")
rclpy.spin(node)
