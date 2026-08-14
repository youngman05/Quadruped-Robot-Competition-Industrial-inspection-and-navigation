import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nodes.perception.apriltag_udp_bridge_core import (
    PacketValidationError,
    load_static_extrinsic,
    validate_packet,
)


def packet():
    return {
        "schema_version": 1,
        "sequence": 8,
        "stamp": {"sec": 12, "nanosec": 34},
        "frame_id": "camera_link",
        "detections": [
            {"tag_id": 0, "position_m": [0.1, 0.2, 0.8], "orientation_xyzw": [0, 0, 0, 1], "reprojection_error_px": 0.2},
            {"tag_id": 3, "position_m": [-0.1, 0.2, 0.9], "orientation_xyzw": [0, 0, 1, 0], "reprojection_error_px": 0.3},
        ],
        "detection_ms": 4.2,
    }


class AprilTagPacketTest(unittest.TestCase):
    def test_accepts_multi_tag_packet(self):
        self.assertEqual(len(validate_packet(packet())["detections"]), 2)

    def test_rejects_duplicate_ids(self):
        value = packet()
        value["detections"][1]["tag_id"] = 0
        with self.assertRaises(PacketValidationError):
            validate_packet(value)

    def test_loads_calibrated_camera_extrinsic(self):
        translation, rotation = load_static_extrinsic(
            ROOT / "configs" / "transforms" / "static_extrinsics.yaml",
            "base_link",
            "camera_link",
        )
        self.assertEqual(translation, (0.23172444, 0.077561412, 0.503275873))
        self.assertEqual(
            rotation,
            (0.000900958, 0.240529563, -0.013474058, 0.97054787),
        )


if __name__ == "__main__":
    unittest.main()
