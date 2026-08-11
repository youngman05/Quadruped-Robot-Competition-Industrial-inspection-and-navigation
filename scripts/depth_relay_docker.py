#!/usr/bin/env python3
"""Docker-side depth relay and staged depth-mode controller.

The node subscribes to the RealSense topics already owned by the cuVSLAM
container. It never opens the D455 directly. ``consumer_only`` is the default
strategy; changing the RealSense ``enable_depth`` parameter is opt-in because
it must first pass a stationary cuVSLAM A/B test on the actual Jetson image.
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image

try:
    from depth_contract import (
        CONTROL_REQUEST_FILE,
        CONTROLLER_STATUS_FILE,
        FRAME_DATA_FILE,
        FRAME_METADATA_FILE,
        DepthContractError,
        DepthMode,
        build_frame_metadata,
        new_controller_status,
        monotonic_age_sec,
        parse_depth_mode,
        read_json,
        validate_control_request,
        write_atomic_bytes,
        write_atomic_json,
    )
except ImportError:
    from nodes.navigation.depth_contract import (  # type: ignore
        CONTROL_REQUEST_FILE,
        CONTROLLER_STATUS_FILE,
        FRAME_DATA_FILE,
        FRAME_METADATA_FILE,
        DepthContractError,
        DepthMode,
        build_frame_metadata,
        new_controller_status,
        monotonic_age_sec,
        parse_depth_mode,
        read_json,
        validate_control_request,
        write_atomic_bytes,
        write_atomic_json,
    )


def _camera_info_dict(msg: CameraInfo) -> dict:
    roi = msg.roi
    return {
        "width": int(msg.width),
        "height": int(msg.height),
        "distortion_model": msg.distortion_model,
        "d": [float(value) for value in msg.d],
        "k": [float(value) for value in msg.k],
        "r": [float(value) for value in msg.r],
        "p": [float(value) for value in msg.p],
        "binning_x": int(msg.binning_x),
        "binning_y": int(msg.binning_y),
        "roi": {
            "x_offset": int(roi.x_offset),
            "y_offset": int(roi.y_offset),
            "height": int(roi.height),
            "width": int(roi.width),
            "do_rectify": bool(roi.do_rectify),
        },
    }


class DepthRelayController(Node):
    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__("depth_relay_controller")
        self.args = args
        self.output_dir = Path(args.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.stream_id = uuid.uuid4().hex
        self.started_monotonic_ns = time.monotonic_ns()
        self.mode = DepthMode.BOOTING
        self.healthy = True
        self.message = "waiting for mission depth request"
        self.ack_request_id = ""
        self.frame_sequence = 0
        self.last_request_id = ""
        self.camera_info = None
        self.pending_parameter_future = None
        self.pending_parameter_request = None
        self.pending_parameter_started_ns = 0
        self.parameter_client = None

        if args.control_strategy == "parameter":
            from rclpy.parameter_client import AsyncParameterClient

            self.parameter_client = AsyncParameterClient(self, args.realsense_node)

        self.create_subscription(
            CameraInfo,
            args.camera_info_topic,
            self._on_info,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            Image,
            args.depth_topic,
            self._on_depth,
            qos_profile_sensor_data,
        )
        self.create_timer(0.10, self._poll_control)
        self.create_timer(0.50, self._write_status)
        self._write_status()
        self.get_logger().info(
            "depth relay ready | strategy=%s output=%s"
            % (args.control_strategy, self.output_dir)
        )

    def _on_info(self, msg: CameraInfo) -> None:
        try:
            self.camera_info = _camera_info_dict(msg)
        except Exception as exc:  # noqa: BLE001
            self.healthy = False
            self.mode = DepthMode.FAULT
            self.message = "invalid CameraInfo: %s" % exc

    def _on_depth(self, msg: Image) -> None:
        if not self.mode.requires_depth or not self.healthy or self.camera_info is None:
            return
        if msg.encoding not in ("16UC1", "mono16"):
            self._fault("unsupported image encoding: %s" % msg.encoding)
            return
        raw = bytes(msg.data)
        try:
            self.frame_sequence += 1
            source_stamp_ns = (
                int(msg.header.stamp.sec) * 1_000_000_000
                + int(msg.header.stamp.nanosec)
            )
            metadata = build_frame_metadata(
                raw=raw,
                stream_id=self.stream_id,
                sequence=self.frame_sequence,
                source_stamp_ns=source_stamp_ns,
                width=msg.width,
                height=msg.height,
                step=msg.step,
                encoding=msg.encoding,
                is_bigendian=bool(msg.is_bigendian),
                frame_id=self.args.optical_frame,
                depth_scale=self.args.depth_scale,
                camera_info=self.camera_info,
                mode=self.mode,
            )
            write_atomic_bytes(self.output_dir / FRAME_DATA_FILE, raw)
            write_atomic_json(self.output_dir / FRAME_METADATA_FILE, metadata.to_dict())
        except Exception as exc:  # noqa: BLE001
            self._fault("depth frame write failed: %s" % exc)

    def _poll_control(self) -> None:
        self._poll_parameter_result()
        if self.pending_parameter_future is not None:
            return
        request_path = self.output_dir / CONTROL_REQUEST_FILE
        if not request_path.exists():
            return
        try:
            request = validate_control_request(read_json(request_path))
        except DepthContractError as exc:
            self._fault("invalid control request: %s" % exc)
            return
        if request["request_id"] == self.last_request_id:
            return
        self.last_request_id = request["request_id"]
        try:
            monotonic_age_sec(
                request["created_monotonic_ns"],
                label="control request timestamp",
            )
        except DepthContractError as exc:
            self._fault("invalid control request time: %s" % exc)
            return
        if request["created_monotonic_ns"] < self.started_monotonic_ns:
            self.message = "ignored control request left by a previous relay process"
            self.get_logger().warn(self.message)
            return
        desired = parse_depth_mode(request["requested_mode"])
        if self.args.control_strategy == "consumer_only":
            self._apply_mode(desired, request["request_id"])
            return
        self._start_parameter_transition(desired, request)

    def _start_parameter_transition(self, desired: DepthMode, request: dict) -> None:
        from rclpy.parameter import Parameter

        if not self.parameter_client.wait_for_service(timeout_sec=0.0):
            self._fault("RealSense parameter service unavailable")
            return
        enabled = desired.requires_depth
        parameter = Parameter(
            self.args.enable_depth_parameter,
            Parameter.Type.BOOL,
            enabled,
        )
        self.pending_parameter_request = (desired, request["request_id"])
        self.pending_parameter_future = self.parameter_client.set_parameters([parameter])
        self.pending_parameter_started_ns = time.monotonic_ns()
        self.message = "waiting for RealSense enable_depth acknowledgement"

    def _poll_parameter_result(self) -> None:
        future = self.pending_parameter_future
        if future is None:
            return
        if not future.done():
            if monotonic_age_sec(
                self.pending_parameter_started_ns,
                label="parameter transition start",
            ) > self.args.parameter_timeout_sec:
                self.pending_parameter_future = None
                self.pending_parameter_request = None
                self.pending_parameter_started_ns = 0
                self._fault("RealSense enable_depth transition timed out")
            return
        desired, request_id = self.pending_parameter_request
        self.pending_parameter_future = None
        self.pending_parameter_request = None
        self.pending_parameter_started_ns = 0
        try:
            response = future.result()
            results = list(getattr(response, "results", []))
            if not results or not all(result.successful for result in results):
                reasons = "; ".join(
                    result.reason for result in results if not result.successful
                )
                raise RuntimeError(reasons or "parameter change was rejected")
        except Exception as exc:  # noqa: BLE001
            self._fault("enable_depth transition failed: %s" % exc)
            return
        self._apply_mode(desired, request_id)

    def _apply_mode(self, mode: DepthMode, request_id: str) -> None:
        self.mode = mode
        self.healthy = True
        self.ack_request_id = request_id
        self.message = "mode acknowledged"
        self._write_status()

    def _fault(self, message: str) -> None:
        self.mode = DepthMode.FAULT
        self.healthy = False
        self.message = str(message)
        self.get_logger().error(self.message)
        self._write_status()

    def _write_status(self) -> None:
        status = new_controller_status(
            mode=self.mode,
            stream_id=self.stream_id,
            ack_request_id=self.ack_request_id,
            healthy=self.healthy,
            depth_enabled=self.mode.requires_depth,
            strategy=self.args.control_strategy,
            sequence=self.frame_sequence,
            message=self.message,
        )
        try:
            write_atomic_json(self.output_dir / CONTROLLER_STATUS_FILE, status)
        except OSError as exc:
            self.get_logger().error("status write failed: %s" % exc)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default="/workspaces/isaac_ros-dev/camera_frames",
    )
    parser.add_argument("--depth-topic", default="/camera/depth/image_rect_raw")
    parser.add_argument("--camera-info-topic", default="/camera/depth/camera_info")
    parser.add_argument("--optical-frame", default="camera_depth_optical_frame")
    parser.add_argument("--depth-scale", type=float, default=0.001)
    parser.add_argument(
        "--control-strategy",
        choices=("consumer_only", "parameter"),
        default="consumer_only",
    )
    parser.add_argument("--realsense-node", default="/camera/realsense2_camera")
    parser.add_argument("--enable-depth-parameter", default="enable_depth")
    parser.add_argument("--parameter-timeout-sec", type=float, default=5.0)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    rclpy.init(args=None)
    node = DepthRelayController(args)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
