"""Tests for Host-side D455 YOLO UDP contract validation and TF geometry."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "src" / "nodes" / "perception" / "yolo_udp_bridge_core.py"
SPEC = importlib.util.spec_from_file_location("yolo_udp_bridge_core", CORE_PATH)
CORE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = CORE
SPEC.loader.exec_module(CORE)


def valid_packet():
    return {
        "schema_version": 1,
        "sequence": 7,
        "stamp": {"sec": 1, "nanosec": 2},
        "frame_id": "camera_link",
        "inference_ms": 81.5,
        "detections": [{
            "class_id": 2,
            "class_name": "obstacle",
            "confidence": 0.9,
            "bbox": [10, 20, 30, 40],
            "center_px": [20, 30],
            "mask_area_px": 100,
            "depth_m": 1.2,
            "depth_valid_ratio": 0.9,
            "position_valid": True,
            "position_m": [1.0, 0.0, 0.0],
        }],
    }


class YoloUdpBridgeCoreTest(unittest.TestCase):
    def test_accepts_valid_d455_packet(self) -> None:
        packet = valid_packet()
        self.assertIs(CORE.validate_source_packet(packet), packet)
        self.assertAlmostEqual(CORE.packet_stamp_seconds(packet), 1.000000002)

    def test_rejects_unknown_or_inconsistent_class(self) -> None:
        packet = valid_packet()
        packet["detections"][0]["class_name"] = "red"
        with self.assertRaises(CORE.PacketValidationError):
            CORE.validate_source_packet(packet)

    def test_rejects_invalid_position_contract(self) -> None:
        packet = valid_packet()
        packet["detections"][0]["position_valid"] = False
        with self.assertRaises(CORE.PacketValidationError):
            CORE.validate_source_packet(packet)

    def test_camera_point_transforms_to_base_link(self) -> None:
        # Nominal transform from configs/transforms/static_extrinsics.yaml.
        point = CORE.transform_point(
            [1.0, 0.0, 0.0],
            [0.080, 0.000, 0.493],
            [0.000000, 0.258819, 0.000000, 0.965926],
        )
        self.assertAlmostEqual(point[0], 0.946025, places=6)
        self.assertAlmostEqual(point[1], 0.0, places=6)
        self.assertAlmostEqual(point[2], -0.007000, places=6)


if __name__ == "__main__":
    unittest.main()
