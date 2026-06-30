"""
Color image publisher — reads latest_color.jpg from Docker relay and
publishes as sensor_msgs/Image + CameraInfo on /camera/color/image_raw.

This avoids opening the D455 twice (cuVSLAM already owns it in Docker).
"""

import sys
from pathlib import Path

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image
from cv_bridge import CvBridge

_WS_ROOT = Path(__file__).resolve().parents[3]
if str(_WS_ROOT) not in sys.path:
    sys.path.insert(0, str(_WS_ROOT))


class ColorImagePublisher(Node):
    """Read relay JPEG and publish as ROS Image."""

    def __init__(self):
        super().__init__("color_image_publisher_node")

        self.declare_parameter("publish_rate", 10.0)
        self.declare_parameter("frame_id", "camera_color_optical_frame")
        self.declare_parameter("width", 640)
        self.declare_parameter("height", 480)
        self.declare_parameter("relay_dir",
                              str(Path.home() / "workspaces/isaac_ros-dev/camera_frames"))

        publish_rate = self.get_parameter("publish_rate").value
        self._frame_id = self.get_parameter("frame_id").value
        width = self.get_parameter("width").value
        height = self.get_parameter("height").value
        relay_dir = Path(self.get_parameter("relay_dir").value)

        self._relay_file = relay_dir / "latest_color.jpg"
        self._bridge = CvBridge()

        # Publishers
        self._image_pub = self.create_publisher(Image, "/camera/color/image_raw", 10)
        self._info_pub = self.create_publisher(CameraInfo, "/camera/color/camera_info", 10)

        # Publish camera_info
        self._info_msg = self._build_camera_info(width, height)
        self._info_pub.publish(self._info_msg)

        self._timer = self.create_timer(1.0 / publish_rate, self._publish_callback)

        self.get_logger().info(
            f"Color publisher ready (relay: {self._relay_file})"
        )

    def _build_camera_info(self, width, height):
        msg = CameraInfo()
        msg.header.frame_id = self._frame_id
        msg.height = height
        msg.width = width
        msg.distortion_model = "plumb_bob"
        msg.d = [0.0, 0.0, 0.0, 0.0, 0.0]
        # D455 RGB intrinsics (640x480)
        msg.k = [617.0, 0.0, 320.0, 0.0, 617.0, 240.0, 0.0, 0.0, 1.0]
        msg.p = [617.0, 0.0, 320.0, 0.0, 0.0, 617.0, 240.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        return msg

    def _publish_callback(self):
        if not self._relay_file.exists():
            return
        try:
            img = cv2.imread(str(self._relay_file), cv2.IMREAD_COLOR)
            if img is None:
                return
            stamp = self.get_clock().now().to_msg()
            img_msg = self._bridge.cv2_to_imgmsg(img, encoding="bgr8")
            # cv_bridge on some Foxy versions leaves encoding empty — set explicitly
            img_msg.encoding = "bgr8"
            img_msg.header.stamp = stamp
            img_msg.header.frame_id = self._frame_id
            self._image_pub.publish(img_msg)
            self._info_msg.header.stamp = stamp
            self._info_pub.publish(self._info_msg)
        except Exception as e:
            self.get_logger().error(f"Read error: {e}", throttle_duration_sec=5.0)


def main(args=None):
    rclpy.init(args=args)
    node = ColorImagePublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
