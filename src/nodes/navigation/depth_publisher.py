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

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image
from cv_bridge import CvBridge


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

        # 深度数据来自 Docker depth relay 共享文件
        self.get_logger().info("Reading depth from Docker relay")
        self._camera_info_msg = self._build_camera_info(width, height)
        self._info_pub.publish(self._camera_info_msg)

        # timer
        self._timer = self.create_timer(1.0 / publish_rate, self._publish_callback)

    def _build_camera_info(self, width: int, height: int) -> CameraInfo:
        msg = CameraInfo()
        msg.header.frame_id = self._frame_id
        msg.height = height
        msg.width = width
        # D455 depth intrinsics (640x480)
        msg.distortion_model = "plumb_bob"
        msg.d = [0.0, 0.0, 0.0, 0.0, 0.0]
        msg.k = [389.252, 0.0, 319.830, 0.0, 389.252, 241.714, 0.0, 0.0, 1.0]
        msg.p = [389.252, 0.0, 319.830, 0.0, 0.0, 389.252, 241.714, 0.0, 0.0, 0.0, 1.0, 0.0]
        return msg

    def _publish_callback(self):
        import numpy as np
        from pathlib import Path
        relay_raw = Path.home() / "workspaces/isaac_ros-dev/camera_frames/latest_depth.raw"
        relay_meta = Path.home() / "workspaces/isaac_ros-dev/camera_frames/latest_depth_meta.txt"
        if not relay_raw.exists():
            return

        try:
            import numpy as np
            raw = relay_raw.read_bytes()
            # 从 meta 文件读取实际分辨率 (默认 640x360 匹配 Docker planar_60fps)
            w, h = 640, 360
            if relay_meta.exists():
                parts = relay_meta.read_text().strip().split()
                if len(parts) >= 2:
                    w, h = int(parts[0]), int(parts[1])
            expected = w * h * 2  # uint16 = 2 bytes
            if len(raw) != expected:
                # Try common resolutions
                if len(raw) == 640 * 360 * 2: w, h = 640, 360
                elif len(raw) == 640 * 480 * 2: w, h = 640, 480
            depth_frame = np.frombuffer(raw, dtype=np.uint16).reshape(h, w)
        except Exception as exc:
            self.get_logger().error(f"Depth read error: {exc}", throttle_duration_sec=5.0)
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
        self.get_logger().info("Depth publisher stopped")
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
