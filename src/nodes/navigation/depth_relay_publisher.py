"""Publish Docker-relayed D455 depth, CameraInfo, and a decimated PointCloud2."""

from __future__ import annotations

import json
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
    qos_profile_sensor_data,
)
from sensor_msgs.msg import CameraInfo, Image, PointCloud2, PointField, RegionOfInterest
from std_msgs.msg import String

from nodes.navigation.depth_contract import (
    CONTROL_REQUEST_FILE,
    CONTROLLER_STATUS_FILE,
    FRAME_METADATA_FILE,
    DepthContractError,
    DepthMode,
    monotonic_age_sec,
    new_control_request,
    parse_depth_mode,
    read_frame_snapshot,
    read_json,
    validate_control_request,
    validate_controller_status,
    write_atomic_json,
)
from nodes.navigation.depth_projection import ProjectionConfig, project_depth_points


class DepthRelayPublisher(Node):
    def __init__(self) -> None:
        super().__init__("depth_relay_publisher")
        self.declare_parameter("frames_dir", str(Path.home() / "workspaces/isaac_ros-dev/camera_frames"))
        self.declare_parameter("poll_rate_hz", 10.0)
        self.declare_parameter("controller_status_timeout_sec", 1.5)
        self.declare_parameter("frame_max_age_sec", 0.50)
        self.declare_parameter("mode_request_topic", "/depth/mode_request")
        self.declare_parameter("mode_status_topic", "/depth/mode_status")
        self.declare_parameter("pipeline_status_topic", "/depth/pipeline_status")
        self.declare_parameter("depth_topic", "/camera/depth/image_rect_raw")
        self.declare_parameter("camera_info_topic", "/camera/depth/camera_info")
        self.declare_parameter("pointcloud_topic", "/camera/depth/points")
        self.declare_parameter("decimation", 4)
        self.declare_parameter("min_range_m", 0.20)
        self.declare_parameter("max_range_m", 3.00)
        self.declare_parameter("crop_left", 0.0)
        self.declare_parameter("crop_right", 1.0)
        self.declare_parameter("crop_top", 0.0)
        self.declare_parameter("crop_bottom", 1.0)
        self.declare_parameter("publish_depth_data", True)

        self._frames_dir = Path(str(self.get_parameter("frames_dir").value)).expanduser()
        rate = max(1.0, float(self.get_parameter("poll_rate_hz").value))
        self._controller_status_timeout = max(
            0.2,
            float(self.get_parameter("controller_status_timeout_sec").value),
        )
        self._frame_max_age = max(
            0.05,
            float(self.get_parameter("frame_max_age_sec").value),
        )
        self._projection = ProjectionConfig(
            decimation=int(self.get_parameter("decimation").value),
            min_range_m=float(self.get_parameter("min_range_m").value),
            max_range_m=float(self.get_parameter("max_range_m").value),
            crop_left=float(self.get_parameter("crop_left").value),
            crop_right=float(self.get_parameter("crop_right").value),
            crop_top=float(self.get_parameter("crop_top").value),
            crop_bottom=float(self.get_parameter("crop_bottom").value),
        ).validate()
        self._publish_depth_data = bool(
            self.get_parameter("publish_depth_data").value
        )

        self._image_pub = self.create_publisher(
            Image,
            str(self.get_parameter("depth_topic").value),
            qos_profile_sensor_data,
        )
        self._info_pub = self.create_publisher(
            CameraInfo,
            str(self.get_parameter("camera_info_topic").value),
            qos_profile_sensor_data,
        )
        self._cloud_pub = self.create_publisher(
            PointCloud2,
            str(self.get_parameter("pointcloud_topic").value),
            qos_profile_sensor_data,
        )
        self._mode_status_pub = self.create_publisher(
            String, str(self.get_parameter("mode_status_topic").value), 10
        )
        self._pipeline_status_pub = self.create_publisher(
            String, str(self.get_parameter("pipeline_status_topic").value), 10
        )
        mode_request_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.create_subscription(
            String,
            str(self.get_parameter("mode_request_topic").value),
            self._on_mode_request,
            mode_request_qos,
        )
        self._active_request = None
        self._controller_status = None
        self._controller_stream_id = ""
        self._last_controller_sequence = 0
        self._last_sequence = 0
        self._last_frame_time = None
        self._last_pointcloud_time = None
        self._last_source_stamp_ns = None
        self._last_error = ""
        self.create_timer(1.0 / rate, self._poll)
        self.get_logger().info(
            "depth relay publisher ready | %s | publish_depth_data=%s"
            % (self._frames_dir, self._publish_depth_data)
        )

    def _on_mode_request(self, msg: String) -> None:
        try:
            payload = json.loads(msg.data)
            if "version" in payload:
                request = validate_control_request(payload)
            else:
                request = new_control_request(
                    parse_depth_mode(payload.get("requested_mode", payload.get("mode"))),
                    request_id=payload.get("request_id"),
                )
            write_atomic_json(self._frames_dir / CONTROL_REQUEST_FILE, request)
            if (
                self._active_request is None
                or self._active_request["request_id"] != request["request_id"]
            ):
                self._last_frame_time = None
                self._last_pointcloud_time = None
                self._last_source_stamp_ns = None
            self._active_request = request
            self._last_error = ""
        except Exception as exc:  # noqa: BLE001
            self._last_error = "mode request rejected: %s" % exc
            self.get_logger().error(self._last_error)

    def _poll(self) -> None:
        now = time.monotonic()
        self._read_controller_status()
        if self._controller_status is not None:
            mode = parse_depth_mode(self._controller_status["mode"])
            if (
                self._publish_depth_data
                and mode.requires_depth
                and self._controller_status["healthy"]
            ):
                self._publish_frame(now)
        self._publish_status(now)

    def _read_controller_status(self) -> None:
        status_path = self._frames_dir / CONTROLLER_STATUS_FILE
        try:
            status = validate_controller_status(read_json(status_path))
            file_age = time.time() - status_path.stat().st_mtime
            if file_age < 0.0 or file_age > self._controller_status_timeout:
                raise DepthContractError(
                    "depth controller status file is stale: %.3fs" % file_age
                )
            age = monotonic_age_sec(
                status["updated_monotonic_ns"],
                label="depth controller heartbeat",
            )
            if age > self._controller_status_timeout:
                raise DepthContractError(
                    "depth controller heartbeat is stale: %.3fs" % age
                )
            stream_id = status["stream_id"]
            if stream_id != self._controller_stream_id:
                self._controller_stream_id = stream_id
                self._last_controller_sequence = status["sequence"]
                self._last_sequence = 0
                self._last_frame_time = None
                self._last_pointcloud_time = None
                self._last_source_stamp_ns = None
            elif status["sequence"] < self._last_controller_sequence:
                raise DepthContractError("depth controller sequence regressed")
            else:
                self._last_controller_sequence = status["sequence"]
            self._controller_status = status
        except (OSError, DepthContractError) as exc:
            self._controller_status = None
            self._last_error = str(exc)

    def _publish_frame(self, now: float) -> None:
        try:
            metadata, raw = read_frame_snapshot(self._frames_dir)
            if metadata.stream_id != self._controller_status["stream_id"]:
                raise DepthContractError("frame stream does not match controller stream")
            controller_mode = parse_depth_mode(self._controller_status["mode"])
            if metadata.mode != controller_mode:
                raise DepthContractError("frame mode does not match controller mode")
            frame_age = monotonic_age_sec(
                metadata.monotonic_stamp_ns,
                label="depth frame",
            )
            if frame_age > self._frame_max_age:
                raise DepthContractError("depth frame is stale: %.3fs" % frame_age)
            metadata_path = self._frames_dir / FRAME_METADATA_FILE
            file_age = time.time() - metadata_path.stat().st_mtime
            if file_age < 0.0 or file_age > self._frame_max_age:
                raise DepthContractError(
                    "depth frame metadata file is stale: %.3fs" % file_age
                )
            if metadata.sequence <= self._last_sequence:
                return
            image = Image()
            image.header.stamp.sec = metadata.source_stamp_ns // 1_000_000_000
            image.header.stamp.nanosec = metadata.source_stamp_ns % 1_000_000_000
            image.header.frame_id = metadata.frame_id
            image.height = metadata.height
            image.width = metadata.width
            image.encoding = metadata.encoding
            image.is_bigendian = metadata.is_bigendian
            image.step = metadata.step
            image.data = raw

            info = self._camera_info_message(metadata)
            info.header = image.header
            points, count = project_depth_points(raw, metadata, self._projection)
            cloud = self._pointcloud_message(image, points, count)
            self._image_pub.publish(image)
            self._info_pub.publish(info)
            self._cloud_pub.publish(cloud)
            self._last_sequence = metadata.sequence
            self._last_frame_time = now
            self._last_pointcloud_time = now
            self._last_source_stamp_ns = metadata.source_stamp_ns
            self._last_error = ""
        except (OSError, DepthContractError) as exc:
            self._last_error = str(exc)

    @staticmethod
    def _camera_info_message(metadata) -> CameraInfo:
        data = metadata.camera_info
        msg = CameraInfo()
        msg.width = data["width"]
        msg.height = data["height"]
        msg.distortion_model = data["distortion_model"]
        msg.d = data["d"]
        msg.k = data["k"]
        msg.r = data["r"]
        msg.p = data["p"]
        msg.binning_x = data["binning_x"]
        msg.binning_y = data["binning_y"]
        roi_data = data.get("roi", {})
        msg.roi = RegionOfInterest(
            x_offset=int(roi_data.get("x_offset", 0)),
            y_offset=int(roi_data.get("y_offset", 0)),
            height=int(roi_data.get("height", 0)),
            width=int(roi_data.get("width", 0)),
            do_rectify=bool(roi_data.get("do_rectify", False)),
        )
        return msg

    @staticmethod
    def _pointcloud_message(image: Image, points: bytes, count: int) -> PointCloud2:
        msg = PointCloud2()
        msg.header = image.header
        msg.height = 1
        msg.width = count
        msg.fields = [
            PointField(name="x", offset=0, datatype=PointField.FLOAT32, count=1),
            PointField(name="y", offset=4, datatype=PointField.FLOAT32, count=1),
            PointField(name="z", offset=8, datatype=PointField.FLOAT32, count=1),
        ]
        msg.is_bigendian = False
        msg.point_step = 12
        msg.row_step = 12 * count
        msg.data = points
        msg.is_dense = True
        return msg

    def _publish_status(self, now: float) -> None:
        controller = self._controller_status or {
            "stream_id": "",
            "mode": DepthMode.BOOTING.value,
            "ack_request_id": "",
            "healthy": False,
            "depth_enabled": False,
            "strategy": "unknown",
            "sequence": 0,
            "updated_monotonic_ns": 0,
            "message": self._last_error,
        }
        active_id = "" if self._active_request is None else self._active_request["request_id"]
        requested_mode = (
            DepthMode.BOOTING.value
            if self._active_request is None
            else self._active_request["requested_mode"]
        )
        acknowledged = bool(
            active_id
            and controller["ack_request_id"] == active_id
            and controller["mode"] == requested_mode
            and controller["healthy"]
            and controller["depth_enabled"]
            == parse_depth_mode(requested_mode).requires_depth
        )
        mode_msg = String()
        mode_msg.data = json.dumps(
            dict(
                controller,
                active_request_id=active_id,
                requested_mode=requested_mode,
                acknowledged=acknowledged,
            ),
            sort_keys=True,
        )
        self._mode_status_pub.publish(mode_msg)
        pipeline_msg = String()
        pipeline_msg.data = json.dumps(
            {
                "mode": controller["mode"],
                "requested_mode": requested_mode,
                "acknowledged": acknowledged,
                "controller_healthy": controller["healthy"],
                "last_frame_time": self._last_frame_time,
                "last_pointcloud_time": self._last_pointcloud_time,
                "last_source_stamp_ns": self._last_source_stamp_ns,
                "last_sequence": self._last_sequence,
                "controller_stream_id": controller["stream_id"],
                "active_request_id": active_id,
                "published_monotonic_time": now,
                "error": self._last_error,
            },
            sort_keys=True,
        )
        self._pipeline_status_pub.publish(pipeline_msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = DepthRelayPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
