"""
whz standalone inspection — reads relay JPEG directly, bypasses DDS.

ROS2 service: /whz/inspect (std_srvs/Trigger)
Same API as whz inspection_node, but reads camera frames from
Docker relay files instead of subscribing to /camera/color/image_raw.

Usage: python3 whz_standalone_inspect.py
"""

import json
import time
from pathlib import Path

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from std_srvs.srv import Trigger

from cv.gauge_detector import GaugeDetector
from whz.paths import default_audio_dir
from whz.audio_player import AudioPlayer
from whz.inspection import Inspector, InspectionResult


class WhzStandaloneNode(Node):
    """whz inspection reading from Docker relay files, no DDS subscriptions."""

    def __init__(self):
        super().__init__("whz_standalone_inspect")

        # Relay file paths
        relay_dir = Path.home() / "workspaces/isaac_ros-dev/camera_frames"
        self._color_jpg = relay_dir / "latest_color.jpg"
        self._depth_raw = relay_dir / "latest_depth.raw"
        self._depth_meta = relay_dir / "latest_depth_meta.txt"

        # YOLO detector + audio
        self._detector = GaugeDetector()
        self._audio_player = AudioPlayer(default_audio_dir(), timeout_sec=10.0)
        self._inspector = Inspector(self._detector, self._audio_player)

        # Create service
        self._srv = self.create_service(Trigger, "/whz/inspect", self._on_inspect)
        self.get_logger().info(
            f"WHZ standalone ready. Color: {self._color_jpg}"
        )

    def _on_inspect(self, request, response):
        del request

        frames = []
        for i in range(3):
            color, _depth = self._read_frame()
            if color is None:
                response.success = False
                response.message = json.dumps({
                    "ok": False,
                    "error": f"Timed out reading frames; got {len(frames)}/3",
                    "total_frames": len(frames),
                })
                return response
            frames.append(color)
            if i < 2:
                time.sleep(0.3)

        result = self._inspector.inspect_frames(frames)

        response.success = result.ok
        d = result.to_dict()
        d["audio_played"] = True
        response.message = json.dumps(d, default=str)
        return response

    def _read_frame(self):
        """Read one color+depth frame from relay files. Returns (bgr, depth_m) or (None, None)."""
        # Color
        if not self._color_jpg.exists():
            return None, None
        for _ in range(10):  # wait up to 1s for fresh frame
            color = cv2.imread(str(self._color_jpg), cv2.IMREAD_COLOR)
            if color is not None and color.shape[0] > 0:
                break
            time.sleep(0.1)
        else:
            return None, None

        # Depth (optional — gauge detector works without it)
        depth = None
        if self._depth_raw.exists():
            try:
                raw = self._depth_raw.read_bytes()
                w, h = 640, 360
                if self._depth_meta.exists():
                    parts = self._depth_meta.read_text().strip().split()
                    if len(parts) >= 2:
                        w, h = int(parts[0]), int(parts[1])
                expected = w * h * 2
                if len(raw) == expected:
                    depth = np.frombuffer(raw, dtype=np.uint16).reshape(h, w).astype(np.float32) * 0.001
            except Exception:
                depth = None

        return color, depth


def main(args=None):
    rclpy.init(args=args)
    node = WhzStandaloneNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
