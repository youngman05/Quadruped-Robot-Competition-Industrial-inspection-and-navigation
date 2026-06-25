"""
D455 Depth Publisher — publishes depth images + camera_info for
depth_image_proc/point_cloud_xyz_node to convert into PointCloud2.

ROS2 Node: d455_depth_publisher
Topics:
  /camera/depth/image_raw    — sensor_msgs/Image (16UC1, mm)
  /camera/depth/camera_info  — sensor_msgs/CameraInfo

Intended chain:
  d455_depth_publisher → depth_image_proc/point_cloud_xyz_node
                       → /camera/depth/points (PointCloud2)
                       → Nav2 local_costmap / global_costmap

Jetson note: publishes at 10 Hz to keep CPU usage low.
Camera runs at 15 fps internally.
"""

import sys
from pathlib import Path

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image
from cv_bridge import CvBridge

# Allow importing from the workspace root so we can reach src.cv.realsense_camera
_WS_ROOT = Path(__file__).resolve().parents[3]  # navigation → nodes → src → root
if str(_WS_ROOT) not in sys.path:
    sys.path.insert(0, str(_WS_ROOT))

from src.cv.realsense_camera import RealsenseCamera


class DepthPublisher(Node):
    """Publish D455 depth frames as ROS Image + CameraInfo."""

    def __init__(self):
        super().__init__("d455_depth_publisher")

        # parameters
        self.declare_parameter("width", 640)
        self.declare_parameter("height", 480)
        self.declare_parameter("fps", 15)
        self.declare_parameter("publish_rate", 10.0)
        self.declare_parameter("frame_id", "camera_link")

        width = self.get_parameter("width").value
        height = self.get_parameter("height").value
        fps = self.get_parameter("fps").value
        publish_rate = self.get_parameter("publish_rate").value
        self._frame_id = self.get_parameter("frame_id").value

        self._bridge = CvBridge()

        # publishers
        self._image_pub = self.create_publisher(Image, "/camera/depth/image_raw", 10)
        self._info_pub = self.create_publisher(CameraInfo, "/camera/depth/camera_info", 10)

        # camera
        self.get_logger().info(f"Opening D455: {width}x{height} @ {fps} fps depth only")
        self._camera = RealsenseCamera(
            width=width,
            height=height,
            fps=fps,
            enable_color=False,
            enable_depth=True,
            enable_infrared=False,
            enable_imu=False,
            align_depth=False,
        )
        self._camera.start(warmup_frames=30)
        self.get_logger().info(f"Camera ready: {self._camera.device_name}  sn={self._camera.serial}")

        # publish camera_info once (latched / periodic)
        self._camera_info_msg = self._build_camera_info()
        self._info_pub.publish(self._camera_info_msg)

        # timer
        self._timer = self.create_timer(1.0 / publish_rate, self._publish_callback)

    def _build_camera_info(self) -> CameraInfo:
        msg = CameraInfo()
        msg.header.frame_id = self._frame_id
        msg.height = self._camera.height
        msg.width = self._camera.width

        intrinsics = self._camera.depth_intrinsics
        msg.distortion_model = "plumb_bob"
        msg.d = [0.0, 0.0, 0.0, 0.0, 0.0]  # D455 depth has no distortion
        msg.k = [
            intrinsics.fx, 0.0, intrinsics.ppx,
            0.0, intrinsics.fy, intrinsics.ppy,
            0.0, 0.0, 1.0,
        ]
        msg.p = [
            intrinsics.fx, 0.0, intrinsics.ppx, 0.0,
            0.0, intrinsics.fy, intrinsics.ppy, 0.0,
            0.0, 0.0, 1.0, 0.0,
        ]
        return msg

    def _publish_callback(self):
        if not self._camera.is_running:
            self.get_logger().warn("Camera not running, skipping frame", throttle_duration_sec=5.0)
            return

        try:
            depth_frame = self._camera.get_depth_image()
            if depth_frame is None:
                return
        except Exception as exc:
            self.get_logger().error(f"Frame grab error: {exc}", throttle_duration_sec=5.0)
            return

        stamp = self.get_clock().now().to_msg()

        # depth image
        img_msg = self._bridge.cv2_to_imgmsg(depth_frame, encoding="16UC1")
        img_msg.header.stamp = stamp
        img_msg.header.frame_id = self._frame_id
        self._image_pub.publish(img_msg)

        # camera_info (re-publish periodically for late subscribers)
        self._camera_info_msg.header.stamp = stamp
        self._info_pub.publish(self._camera_info_msg)

    def destroy_node(self) -> bool:
        self.get_logger().info("Stopping depth camera...")
        self._camera.stop()
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = DepthPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
