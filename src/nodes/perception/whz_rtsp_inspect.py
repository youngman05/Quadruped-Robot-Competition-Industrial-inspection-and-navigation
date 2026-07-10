"""
WHZ inspection via RTSP front camera + YOLO.

ROS2 service: /whz/inspect (std_srvs/Trigger)

Usage (Jetson):
    LD_PRELOAD=/lib/aarch64-linux-gnu/libgomp.so.1 python3 whz_rtsp_inspect.py
"""

import json
import sys
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_srvs.srv import Trigger

_project_root = Path(__file__).resolve().parents[3]
_src = str(_project_root / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from cv.gauge_detector import GaugeDetector
from cv.rtsp_camera import RTSPCamera
from whz.audio_player import AudioPlayer
from whz.inspection import Inspector, InspectionResult
from whz.paths import default_audio_dir


class WhzRtspNode(Node):
    """WHZ inspection via RTSP + YOLO."""

    def __init__(self):
        super().__init__("whz_rtsp_inspect")

        self.declare_parameter("rtsp_url", "rtsp://192.168.1.120:8554/test")
        self.declare_parameter("num_frames", 3)
        self.declare_parameter("frame_interval", 0.3)
        self.declare_parameter("play_audio", True)

        rtsp_url = self.get_parameter("rtsp_url").value
        self._num_frames = self.get_parameter("num_frames").value
        self._frame_interval = self.get_parameter("frame_interval").value
        play_audio = self.get_parameter("play_audio").value

        self.get_logger().info(f"Opening RTSP: {rtsp_url}")
        self._camera = RTSPCamera(url=rtsp_url)
        self.get_logger().info(f"RTSP ready: {self._camera.width}x{self._camera.height}")

        self._detector = GaugeDetector()
        self._audio_player = AudioPlayer(default_audio_dir())
        self._inspector = Inspector(self._detector, self._audio_player, play_audio=play_audio)

        self._srv = self.create_service(Trigger, "/whz/inspect", self._on_inspect)
        self.get_logger().info("WHZ RTSP inspection ready. /whz/inspect")

    def _on_inspect(self, request, response):
        del request

        frames = []
        for i in range(self._num_frames):
            try:
                frame = self._camera.read()
                if frame is None or frame.size == 0:
                    return self._fail(response, f"empty frame {i}/{self._num_frames}")
                frames.append(frame)
            except Exception as exc:
                return self._fail(response, f"camera error: {exc}")
            if i < self._num_frames - 1:
                time.sleep(self._frame_interval)

        result = self._inspector.inspect_frames(frames)

        response.success = result.ok
        d = result.to_dict()
        d["camera"] = "rtsp_front"
        response.message = json.dumps(d, default=str)
        return response

    def _fail(self, response, error: str):
        response.success = False
        response.message = json.dumps({"ok": False, "error": error})
        return response

    def destroy_node(self):
        self._camera.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = WhzRtspNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
