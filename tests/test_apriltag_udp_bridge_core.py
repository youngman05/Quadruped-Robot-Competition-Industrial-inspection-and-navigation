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
        self.assertEqual(translation, (0.231724440, 0.077561412, 0.503275873))
        for actual, expected in zip(
            rotation,
            (0.000900958, 0.240529563, -0.013474058, 0.970547870),
        ):
            self.assertAlmostEqual(actual, expected, places=9)

    def test_bridge_and_package_use_project_static_extrinsics(self):
        bridge = (
            ROOT / "src" / "nodes" / "perception" / "apriltag_udp_bridge.py"
        ).read_text(encoding="utf-8")
        setup_source = (ROOT / "setup.py").read_text(encoding="utf-8")
        self.assertIn('/ "transforms"', bridge)
        self.assertIn('/ "static_extrinsics.yaml"', bridge)
        self.assertNotIn("cuvslam_camera_extrinsics.yaml", bridge)
        self.assertIn('glob("configs/transforms/*.yaml")', setup_source)


if __name__ == "__main__":
    unittest.main()
