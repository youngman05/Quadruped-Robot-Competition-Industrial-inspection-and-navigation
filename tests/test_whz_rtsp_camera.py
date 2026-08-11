import sys
import unittest
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
WHZ_ROOT = REPO_ROOT / "whz"
if str(WHZ_ROOT) not in sys.path:
    sys.path.insert(0, str(WHZ_ROOT))

from whz.rtsp_camera import RTSPCamera


class ScriptedRTSPCamera(RTSPCamera):
    def __init__(self, packets, last_frame_id=None):
        self.frame_timeout_sec = 0.1
        self._closed = False
        self._last_frame_id = last_frame_id
        self._packets = list(packets)
        self.packet_reads = 0

    def _read_packet(self, timeout_sec):
        del timeout_sec
        self.packet_reads += 1
        if not self._packets:
            raise TimeoutError("script exhausted")
        return self._packets.pop(0)


class RTSPCameraTests(unittest.TestCase):
    def test_read_frames_skips_duplicate_stream_identity(self):
        frame1 = np.full((1, 1, 3), 1, dtype=np.uint8)
        duplicate = np.full((1, 1, 3), 99, dtype=np.uint8)
        frame2 = np.full((1, 1, 3), 2, dtype=np.uint8)
        frame3 = np.full((1, 1, 3), 3, dtype=np.uint8)
        camera = ScriptedRTSPCamera(
            [
                (frame1, ("pts", 1)),
                (duplicate, ("pts", 1)),
                (frame2, ("pts", 2)),
                (frame3, ("pts", 3)),
            ]
        )

        frames = camera.read_frames(3, timeout_sec=0.1)

        self.assertEqual([int(frame[0, 0, 0]) for frame in frames], [1, 2, 3])
        self.assertEqual(camera.packet_reads, 4)

    def test_duplicate_only_stream_times_out(self):
        duplicate = np.zeros((1, 1, 3), dtype=np.uint8)
        camera = ScriptedRTSPCamera(
            [(duplicate, ("pts", 7))],
            last_frame_id=("pts", 7),
        )

        with self.assertRaises(TimeoutError):
            camera.read(timeout_sec=0.1)

    def test_invalid_frame_count_is_rejected(self):
        camera = ScriptedRTSPCamera([])
        with self.assertRaises(ValueError):
            camera.read_frames(0)


if __name__ == "__main__":
    unittest.main()
