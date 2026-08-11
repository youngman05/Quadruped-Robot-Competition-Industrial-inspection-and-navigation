import math
import unittest
import uuid

from nodes.navigation.cone_scan_protocol import (
    ConeScanContractError,
    ConeScanPacket,
    decode_packet,
    depth_coverage_from_image,
    depth_coverage_is_healthy,
    encode_packet,
    filter_short_finite_runs,
    scan_returns_are_healthy,
)


def packet(**overrides):
    values = {
        "stream_id": uuid.UUID(int=1).hex,
        "sequence": 7,
        "source_stamp_ns": 1_000_000_000,
        "sent_wall_time_ns": 1_010_000_000,
        "angle_min": -0.5,
        "angle_max": 0.5,
        "angle_increment": 0.25,
        "time_increment": 0.0,
        "scan_time": 0.1,
        "range_min": 0.2,
        "range_max": 3.0,
        "valid_ratio": 0.8,
        "left_coverage": 0.7,
        "center_coverage": 0.9,
        "right_coverage": 0.8,
        "ranges": (float("inf"), 0.5, 1.0, float("inf")),
        "depth_healthy": True,
    }
    values.update(overrides)
    return ConeScanPacket(**values)


class ConeScanProtocolTests(unittest.TestCase):
    def test_binary_packet_round_trip(self):
        actual = decode_packet(encode_packet(packet()))
        self.assertEqual(actual.stream_id, uuid.UUID(int=1).hex)
        self.assertEqual(actual.sequence, 7)
        self.assertEqual(actual.beam_count, 4)
        self.assertTrue(actual.depth_healthy)
        self.assertTrue(math.isinf(actual.ranges[0]))
        self.assertAlmostEqual(actual.ranges[2], 1.0)

    def test_crc_and_length_are_enforced(self):
        raw = bytearray(encode_packet(packet()))
        raw[-8] ^= 0x01
        with self.assertRaisesRegex(ConeScanContractError, "CRC"):
            decode_packet(raw)
        with self.assertRaises(ConeScanContractError):
            decode_packet(encode_packet(packet())[:-1])

    def test_nonfinite_and_out_of_range_beams_are_rejected(self):
        with self.assertRaises(ConeScanContractError):
            encode_packet(packet(ranges=(0.3, math.nan)))
        with self.assertRaises(ConeScanContractError):
            encode_packet(packet(ranges=(0.1, 0.3)))

    def test_depth_coverage_uses_all_pixels_and_three_zones(self):
        # width=6, with valid counts left=2/2, center=1/2, right=0/2.
        raw = b"\x01\x00\x02\x00\x03\x00\x00\x00\x00\x00\x00\x00"
        coverage = depth_coverage_from_image(raw, width=6, height=1, step=12)
        self.assertEqual(coverage, (0.5, 1.0, 0.5, 0.0))
        self.assertFalse(depth_coverage_is_healthy(coverage))

    def test_empty_and_single_pixel_images_are_unhealthy(self):
        empty = depth_coverage_from_image(b"\x00\x00" * 6, 6, 1, 12)
        single = depth_coverage_from_image(
            b"\x01\x00" + b"\x00\x00" * 5,
            6,
            1,
            12,
        )
        self.assertFalse(depth_coverage_is_healthy(empty))
        self.assertFalse(depth_coverage_is_healthy(single))

    def test_empty_scan_and_flying_points_are_unhealthy(self):
        self.assertFalse(scan_returns_are_healthy([math.inf] * 180))
        self.assertFalse(scan_returns_are_healthy([math.inf, 0.5, math.inf]))
        self.assertFalse(scan_returns_are_healthy([0.5, math.inf, 0.6, 0.7]))
        self.assertTrue(scan_returns_are_healthy([math.inf, 0.5, 0.6, 0.7]))

    def test_short_flying_point_runs_are_removed(self):
        actual = filter_short_finite_runs(
            [0.5, math.inf, 0.6, 0.7, math.inf, 0.8, 0.9, 1.0]
        )
        self.assertTrue(all(math.isinf(value) for value in actual[:5]))
        self.assertEqual(actual[5:], (0.8, 0.9, 1.0))


if __name__ == "__main__":
    unittest.main()
