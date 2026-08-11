"""ROS 2 Trigger service for on-demand Lite3 RTSP inspection."""

from __future__ import annotations

import json

import rclpy
from rcl_interfaces.msg import FloatingPointRange, IntegerRange, ParameterDescriptor
from rclpy.node import Node
from std_srvs.srv import Trigger

from whz.audio_player import AudioPlayer
from whz.inspection import InspectionResult, InspectionRunner, Inspector
from whz.paths import default_audio_dir, default_model_path
from whz.rtsp_camera import DEFAULT_RTSP_URL, RTSPCamera
from whz.yolo_detector import YOLODetector


def _integer_descriptor(description: str, minimum: int, maximum: int) -> ParameterDescriptor:
    return ParameterDescriptor(
        description=description,
        read_only=True,
        integer_range=[
            IntegerRange(from_value=minimum, to_value=maximum, step=1),
        ],
    )


def _float_descriptor(
    description: str,
    minimum: float,
    maximum: float,
) -> ParameterDescriptor:
    return ParameterDescriptor(
        description=description,
        read_only=True,
        floating_point_range=[
            FloatingPointRange(from_value=minimum, to_value=maximum, step=0.0),
        ],
    )


class WhzInspectionNode(Node):
    """Expose `/whz/inspect` while owning one camera and one warmed model."""

    def __init__(self) -> None:
        super().__init__("whz_inspection_node")
        self._camera = None

        self.declare_parameter(
            "rtsp_url",
            DEFAULT_RTSP_URL,
            ParameterDescriptor(description="Lite3 front-camera RTSP URL", read_only=True),
        )
        self.declare_parameter(
            "model_path",
            str(default_model_path()),
            ParameterDescriptor(description="Installed YOLO gauge model path", read_only=True),
        )
        self.declare_parameter(
            "device",
            "0",
            ParameterDescriptor(description="Ultralytics inference device", read_only=True),
        )
        self.declare_parameter(
            "required_frames",
            3,
            _integer_descriptor("Distinct frames per inspection", 1, 10),
        )
        self.declare_parameter(
            "min_agree_frames",
            2,
            _integer_descriptor("Matching votes required for success", 1, 10),
        )
        self.declare_parameter(
            "connect_timeout_sec",
            8.0,
            _float_descriptor("RTSP startup timeout", 0.1, 60.0),
        )
        self.declare_parameter(
            "frame_timeout_sec",
            2.0,
            _float_descriptor("Timeout for each fresh RTSP frame", 0.1, 30.0),
        )
        self.declare_parameter(
            "player_timeout_sec",
            10.0,
            _float_descriptor("MP3 player process timeout", 0.1, 60.0),
        )
        self.declare_parameter(
            "image_size",
            320,
            _integer_descriptor("YOLO square inference size", 160, 1280),
        )
        self.declare_parameter(
            "confidence_threshold",
            0.30,
            _float_descriptor("YOLO confidence threshold", 0.0, 1.0),
        )
        self.declare_parameter(
            "iou_threshold",
            0.50,
            _float_descriptor("YOLO NMS IoU threshold", 0.0, 1.0),
        )
        self.declare_parameter(
            "prefer_hw_decode",
            False,
            ParameterDescriptor(description="Try Jetson hardware H.264 decode first", read_only=True),
        )
        self.declare_parameter(
            "play_audio",
            True,
            ParameterDescriptor(description="Play one MP3 after a successful vote", read_only=True),
        )

        required_frames = int(self.get_parameter("required_frames").value)
        min_agree_frames = int(self.get_parameter("min_agree_frames").value)
        if min_agree_frames > required_frames:
            raise ValueError("min_agree_frames cannot exceed required_frames")

        detector = YOLODetector(
            model_path=self.get_parameter("model_path").value,
            device=self.get_parameter("device").value,
            image_size=int(self.get_parameter("image_size").value),
            confidence_threshold=float(
                self.get_parameter("confidence_threshold").value
            ),
            iou_threshold=float(self.get_parameter("iou_threshold").value),
        )
        inspector = Inspector(
            detector=detector,
            audio_player=AudioPlayer(
                audio_dir=default_audio_dir(),
                timeout_sec=float(self.get_parameter("player_timeout_sec").value),
            ),
            play_audio=bool(self.get_parameter("play_audio").value),
            min_agree_frames=min_agree_frames,
        )
        self._camera = RTSPCamera(
            url=self.get_parameter("rtsp_url").value,
            connect_timeout_sec=float(self.get_parameter("connect_timeout_sec").value),
            frame_timeout_sec=float(self.get_parameter("frame_timeout_sec").value),
            prefer_hw_decode=bool(self.get_parameter("prefer_hw_decode").value),
        )
        self._runner = InspectionRunner(
            camera=self._camera,
            inspector=inspector,
            required_frames=required_frames,
            frame_timeout_sec=float(self.get_parameter("frame_timeout_sec").value),
        )
        self._service = self.create_service(Trigger, "/whz/inspect", self._on_inspect)
        self.get_logger().info(
            "WHZ inspection ready: service=/whz/inspect, model=%s, device=%s, "
            "camera=%dx%d, vote=%d/%d"
            % (
                self.get_parameter("model_path").value,
                self.get_parameter("device").value,
                self._camera.width,
                self._camera.height,
                min_agree_frames,
                required_frames,
            )
        )

    def _on_inspect(
        self,
        request: Trigger.Request,
        response: Trigger.Response,
    ) -> Trigger.Response:
        del request
        try:
            result = self._runner.run()
        except Exception as exc:  # noqa: BLE001
            result = InspectionResult(ok=False, error="inspection_failed: %s" % exc)

        response.success = result.ok
        response.message = json.dumps(result.to_dict(), ensure_ascii=False)
        if result.ok:
            self.get_logger().info(response.message)
        else:
            self.get_logger().warn(response.message)
        return response

    def destroy_node(self):
        if self._camera is not None:
            self._camera.close()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = WhzInspectionNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
