"""
whz standalone inspection — reads relay JPEG directly, bypasses DDS.

ROS2 service: /whz/inspect (std_srvs/Trigger)
Same API as whz inspection_node, but reads camera frames from
Docker relay files instead of subscribing to /camera/color/image_raw.

Usage: python3 whz_standalone_inspect.py
"""

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from std_srvs.srv import Trigger

# whz modules
_WS = Path(__file__).resolve().parents[3]
_WHZ = _WS / "src" / "whz" / "whz"
if str(_WHZ) not in sys.path:
    sys.path.insert(0, str(_WHZ))

from paths import default_audio_dir, default_template_dir
from letter_detector import LetterDetector
from gauge_detector import detect_gauge
from audio_player import AudioPlayer
from inspection import InspectionResult, Inspector


class WhzStandaloneNode(Node):
    """whz inspection reading from Docker relay files, no DDS subscriptions."""

    def __init__(self):
        super().__init__("whz_standalone_inspect")

        # Relay file paths
        relay_dir = Path.home() / "workspaces/isaac_ros-dev/camera_frames"
        self._color_jpg = relay_dir / "latest_color.jpg"
        self._depth_raw = relay_dir / "latest_depth.raw"
        self._depth_meta = relay_dir / "latest_depth_meta.txt"

        # whz detectors
        template_dir = default_template_dir()
        audio_dir = default_audio_dir()
        self._letter_detector = LetterDetector(template_dir, min_score=0.38)
        self._audio_player = AudioPlayer(audio_dir, timeout_sec=10.0)

        # Create service
        self._srv = self.create_service(Trigger, "/whz/inspect", self._on_inspect)
        self.get_logger().info(
            f"WHZ standalone ready. Color: {self._color_jpg}  "
            f"Depth: {self._depth_raw}"
        )

    def _on_inspect(self, request, response):
        """Handle /whz/inspect service call."""
        del request

        # Read 3 frames with delay between
        frames = []
        for i in range(3):
            color, depth = self._read_frame()
            if color is None:
                response.success = False
                response.message = json.dumps({
                    "ok": False,
                    "error": f"Timed out reading frames; got {len(frames)}/3",
                    "total_frames": len(frames),
                })
                return response
            frames.append((color, depth))
            if i < 2:
                time.sleep(0.3)

        # Run detection on each frame
        results = []
        for color, depth in frames:
            try:
                letter = self._letter_detector.detect(color)
                gauge = detect_gauge(color, depth)
                if letter is None or gauge is None:
                    results.append(InspectionResult(
                        ok=False,
                        area=letter.area if letter else None,
                        error="letter_not_detected" if letter is None else "gauge_not_detected",
                    ))
                    continue
                if letter.bbox:
                    x0, y0, x1, y1 = letter.bbox
                    ly = (y0 + y1) / 2.0
                    above = ly < gauge.center_y
                else:
                    above = False
                audio = self._audio_player.audio_path_for(letter.area, gauge.state_key)
                results.append(InspectionResult(
                    ok=True,
                    area=letter.area,
                    state_key=gauge.state_key,
                    level=gauge.level,
                    status=gauge.status,
                    color=gauge.color,
                    audio_file=str(audio),
                    letter_score=round(letter.score, 4),
                    gauge_confidence=round(gauge.confidence, 4),
                    letter_above_gauge=above,
                ))
            except Exception as e:
                results.append(InspectionResult(ok=False, error=str(e)))

        # Majority vote
        from collections import Counter
        successes = [r for r in results if r.ok]
        if not successes:
            response.success = False
            response.message = json.dumps({
                "ok": False,
                "error": "no_successful_detection",
                "total_frames": 3,
                "details": [r.to_dict() if hasattr(r, 'to_dict') else str(r) for r in results],
            })
            return response

        votes = Counter((r.area, r.state_key) for r in successes)
        (area, state_key), count = votes.most_common(1)[0]
        if count < 2:
            response.success = False
            response.message = json.dumps({
                "ok": False, "error": f"vote={count}/2",
                "area": area, "state_key": state_key,
            })
            return response

        best = max(
            [r for r in successes if r.area == area and r.state_key == state_key],
            key=lambda r: (r.letter_score or 0) + (r.gauge_confidence or 0),
        )
        best.agree_frames = count
        best.total_frames = 3

        # Play audio
        if best.audio_file:
            try:
                self._audio_player.play(Path(best.audio_file))
            except Exception as e:
                pass  # Audio failure is non-fatal

        response.success = best.ok
        d = best.to_dict() if hasattr(best, 'to_dict') else vars(best)
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
