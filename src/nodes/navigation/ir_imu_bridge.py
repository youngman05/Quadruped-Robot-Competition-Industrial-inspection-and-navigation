"""
D455 IR/IMU Bridge — publishes infrared stereo + IMU data for cuVSLAM Docker.

ROS2 Node: ir_imu_bridge

Publishes:
  /camera/infra1/image_raw  — sensor_msgs/Image  左红外 (mono8)
  /camera/infra2/image_raw  — sensor_msgs/Image  右红外 (mono8)
  /camera/infra1/camera_info — sensor_msgs/CameraInfo
  /camera/infra2/camera_info — sensor_msgs/CameraInfo
  /camera/imu               — sensor_msgs/Imu    加速度 + 角速度

cuVSLAM 订阅这些话题做视觉惯性里程计。

Jetson note: IR 30fps + IMU 200Hz, 确保 projector OFF.
"""

import sys
from pathlib import Path

import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image, Imu
from cv_bridge import CvBridge

_WS_ROOT = Path(__file__).resolve().parents[3]
if str(_WS_ROOT) not in sys.path:
    sys.path.insert(0, str(_WS_ROOT))

from src.cv.realsense_camera import RealsenseCamera


class IrImuBridge(Node):
    """Publish D455 IR stereo + IMU for cuVSLAM."""

    def __init__(self):
        super().__init__("ir_imu_bridge")

        self.declare_parameter("width", 640)
        self.declare_parameter("height", 480)
        self.declare_parameter("fps", 30)
        self.declare_parameter("ir_frame_id", "camera_infra1_optical_frame")
        self.declare_parameter("imu_frame_id", "camera_imu_optical_frame")
        self.declare_parameter("publish_rate", 30.0)

        width = self.get_parameter("width").value
        height = self.get_parameter("height").value
        fps = self.get_parameter("fps").value
        self._ir_frame_id = self.get_parameter("ir_frame_id").value
        self._imu_frame_id = self.get_parameter("imu_frame_id").value
        publish_rate = self.get_parameter("publish_rate").value

        self._bridge = CvBridge()

        # publishers
        self._infra1_pub = self.create_publisher(Image, "/camera/infra1/image_raw", 10)
        self._infra2_pub = self.create_publisher(Image, "/camera/infra2/image_raw", 10)
        self._info1_pub = self.create_publisher(CameraInfo, "/camera/infra1/camera_info", 10)
        self._info2_pub = self.create_publisher(CameraInfo, "/camera/infra2/camera_info", 10)
        self._imu_pub = self.create_publisher(Imu, "/camera/imu", 50)

        # camera (IR stereo + IMU, projector OFF)
        self.get_logger().info(f"Opening D455 IR+IMU: {width}x{height} @ {fps}fps")
        self._camera = RealsenseCamera.for_cuvslam(
            width=width, height=height,
            accel_rate=200, gyro_rate=200,
        )
        self._camera.start(warmup_frames=30)
        self.get_logger().info(
            f"Camera ready: {self._camera.device_name}  sn={self._camera.serial}"
        )

        # camera_info (latched once)
        self._info1_msg = self._build_infra_info(1)
        self._info2_msg = self._build_infra_info(2)
        self._info1_pub.publish(self._info1_msg)
        self._info2_pub.publish(self._info2_msg)

        # timer
        self._timer = self.create_timer(1.0 / publish_rate, self._publish_ir)
        self._last_imu_seq = 0

    def _build_infra_info(self, index: int) -> CameraInfo:
        msg = CameraInfo()
        msg.header.frame_id = f"camera_infra{index}_optical_frame"
        msg.height = self._camera.height
        msg.width = self._camera.width
        i = self._camera.infrared_intrinsics
        msg.distortion_model = "plumb_bob"
        msg.d = [0.0, 0.0, 0.0, 0.0, 0.0]
        msg.k = [i.fx, 0.0, i.ppx, 0.0, i.fy, i.ppy, 0.0, 0.0, 1.0]
        msg.p = [i.fx, 0.0, i.ppx, 0.0, 0.0, i.fy, i.ppy, 0.0, 0.0, 0.0, 1.0, 0.0]
        return msg

    def _publish_ir(self):
        if not self._camera.is_running:
            return
        try:
            left_ir, right_ir = self._camera.get_infrared_frames()
            stamp = self.get_clock().now().to_msg()

            # infra1
            img1 = self._bridge.cv2_to_imgmsg(left_ir, encoding="mono8")
            img1.header.stamp = stamp
            img1.header.frame_id = self._ir_frame_id
            self._info1_msg.header.stamp = stamp
            self._infra1_pub.publish(img1)
            self._info1_pub.publish(self._info1_msg)

            # infra2
            img2 = self._bridge.cv2_to_imgmsg(right_ir, encoding="mono8")
            img2.header.stamp = stamp
            img2.header.frame_id = self._ir_frame_id
            self._info2_msg.header.stamp = stamp
            self._infra2_pub.publish(img2)
            self._info2_pub.publish(self._info2_msg)

            # IMU (published alongside IR frames, same rate)
            imu_sample = self._camera.get_imu_data()
            imu_msg = Imu()
            imu_msg.header.stamp = stamp
            imu_msg.header.frame_id = self._imu_frame_id
            imu_msg.linear_acceleration.x = imu_sample.accel_x
            imu_msg.linear_acceleration.y = imu_sample.accel_y
            imu_msg.linear_acceleration.z = imu_sample.accel_z
            imu_msg.angular_velocity.x = imu_sample.gyro_x
            imu_msg.angular_velocity.y = imu_sample.gyro_y
            imu_msg.angular_velocity.z = imu_sample.gyro_z
            self._imu_pub.publish(imu_msg)

        except Exception as exc:
            self.get_logger().error(f"Frame error: {exc}", throttle_duration_sec=5.0)

    def destroy_node(self) -> bool:
        self._camera.stop()
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = IrImuBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
