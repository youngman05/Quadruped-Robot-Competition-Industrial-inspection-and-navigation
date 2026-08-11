import struct
import unittest

from nodes.navigation.depth_contract import DepthMode, build_frame_metadata
from nodes.navigation.depth_projection import ProjectionConfig, project_depth_points


class DepthProjectionTests(unittest.TestCase):
    def test_projects_valid_depth_and_filters_zero_and_range(self):
        raw = struct.pack("<HHHH", 1000, 0, 500, 4000)
        camera_info = {
            "width": 2,
            "height": 2,
            "distortion_model": "plumb_bob",
            "d": [0.0] * 5,
            "k": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
            "r": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
            "p": [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        }
        metadata = build_frame_metadata(
            raw=raw,
            stream_id="stream-a",
            sequence=1,
            source_stamp_ns=1,
            width=2,
            height=2,
            step=4,
            frame_id="camera_depth_optical_frame",
            depth_scale=0.001,
            camera_info=camera_info,
            mode=DepthMode.AVOIDANCE,
        )
        points, count = project_depth_points(
            raw,
            metadata,
            ProjectionConfig(decimation=1, min_range_m=0.2, max_range_m=2.0),
        )
        self.assertEqual(count, 2)
        first = struct.unpack_from("<fff", points, 0)
        second = struct.unpack_from("<fff", points, 12)
        self.assertEqual(first, (0.0, 0.0, 1.0))
        self.assertEqual(second, (0.0, 0.5, 0.5))


if __name__ == "__main__":
    unittest.main()
