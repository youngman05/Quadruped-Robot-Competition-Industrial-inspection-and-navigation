#!/usr/bin/env python3
"""Publish the box QR pose from the Lite3 built-in RTSP camera."""

from __future__ import annotations

import numpy as np
import cv2
import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node

from cv.qr_pose import (
    compose_pose,
    detect_qr_pose,
    quaternion_xyzw_from_rotation,
    rotation_from_quaternion_xyzw,
)
from cv.rtsp_camera import RTSPCamera


class Lite3QrPosePublisher(Node):
    def __init__(self) -> None:
        super().__init__("lite3_qr_pose_publisher")
        self._declare_parameters()
        if not bool(self.get_parameter("calibration_configured").value):
            raise RuntimeError("Lite3 front-camera intrinsics are not calibrated")

        self._camera_matrix = np.asarray(
            self.get_parameter("camera_matrix").value, dtype=np.float64
        ).reshape(3, 3)
        self._distortion = np.asarray(
            self.get_parameter("distortion_coefficients").value, dtype=np.float64
        )
        self._distortion_model = str(self.get_parameter("distortion_model").value)
        self._payload = str(self.get_parameter("qr_payload").value)
        self._marker_verified = False
        self._side_m = float(self.get_parameter("qr_side_m").value)
        self._detector = cv2.QRCodeDetector()
        self._camera_frame = str(self.get_parameter("camera_frame").value)
        self._base_frame = str(self.get_parameter("base_frame").value)
        self._base_from_camera_translation = tuple(
            self.get_parameter("base_from_camera_translation_m").value
        )
        self._base_from_camera_rotation = rotation_from_quaternion_xyzw(
            self.get_parameter("base_from_camera_orientation_xyzw").value
        )
        self._camera = RTSPCamera(
            url=str(self.get_parameter("rtsp_url").value),
            prefer_hw=bool(self.get_parameter("prefer_hw_decode").value),
        )
        self._publisher = self.create_publisher(
            PoseStamped, str(self.get_parameter("pose_topic").value), 10
        )
        self._timer = self.create_timer(
            1.0 / float(self.get_parameter("process_rate_hz").value), self._process_frame
        )
        self.get_logger().info(
            "Lite3 QR pose: {} -> {}".format(self._camera_frame, self._base_frame)
        )

    def _declare_parameters(self) -> None:
        self.declare_parameter("rtsp_url", "rtsp://192.168.1.120:8554/test")
        self.declare_parameter("prefer_hw_decode", False)
        self.declare_parameter("process_rate_hz", 10.0)
        self.declare_parameter("pose_topic", "/box/qr_pose")
        self.declare_parameter("camera_frame", "dog_camera_optical_frame")
        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("base_from_camera_translation_m", [0.50, 0.0, 0.0])
        self.declare_parameter("base_from_camera_orientation_xyzw", [0.5, -0.5, 0.5, -0.5])
        self.declare_parameter("qr_payload", "QRCOMP:BOX_CENTER:V1")
        self.declare_parameter("qr_side_m", 0.15)
        self.declare_parameter("calibration_configured", False)
        self.declare_parameter("camera_matrix", [0.0] * 9)
        self.declare_parameter("distortion_coefficients", [0.0] * 5)
        self.declare_parameter("distortion_model", "pinhole")

    def _process_frame(self) -> None:
        optical_pose = detect_qr_pose(
            self._camera.read(),
            self._camera_matrix,
            self._distortion,
            self._side_m,
            self._payload,
            self._detector,
            allow_unverified_corners=self._marker_verified,
            distortion_model=self._distortion_model,
        )
        if optical_pose is None:
            return
        if optical_pose.payload == self._payload:
            self._marker_verified = True
        base_pose = compose_pose(
            self._base_from_camera_rotation,
            self._base_from_camera_translation,
            optical_pose,
        )
        orientation = quaternion_xyzw_from_rotation(base_pose.rotation)
        message = PoseStamped()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = self._base_frame
        message.pose.position.x, message.pose.position.y, message.pose.position.z = base_pose.position_m
        (
            message.pose.orientation.x,
            message.pose.orientation.y,
            message.pose.orientation.z,
            message.pose.orientation.w,
        ) = orientation
        self._publisher.publish(message)

    def destroy_node(self) -> bool:
        self._camera.close()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = Lite3QrPosePublisher()
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
