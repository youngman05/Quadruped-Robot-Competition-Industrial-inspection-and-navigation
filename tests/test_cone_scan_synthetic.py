import math
import unittest
import uuid

from nodes.navigation.cone_scan_protocol import (
    ConeScanContractError,
    decode_packet,
    depth_coverage_is_healthy,
    scan_observation_is_healthy,
)
from nodes.navigation.cone_scan_synthetic import (
    BEAM_COUNT,
    SCENARIOS,
    scenario_frame,
    scenario_packet,
)


class ConeScanSyntheticTests(unittest.TestCase):
    def test_healthy_cone_is_180_beam_816_byte_packet(self):
        frame = scenario_frame(
            "healthy-cone",
            stream_id=uuid.UUID(int=11).hex,
            sequence=7,
            now_ns=2_000_000_000,
        )
        self.assertEqual(len(frame.payload), 816)
        packet = decode_packet(frame.payload)
        self.assertEqual(packet.beam_count, BEAM_COUNT)
        self.assertEqual(packet.sequence, 7)
        self.assertTrue(packet.depth_healthy)
        self.assertTrue(scan_observation_is_healthy(packet.ranges))
        self.assertGreaterEqual(sum(math.isfinite(value) for value in packet.ranges), 3)

    def test_clear_scan_has_healthy_depth_and_no_finite_returns(self):
        frame = scenario_frame("clear", now_ns=2_000_000_000)
        packet = decode_packet(frame.payload)
        self.assertTrue(frame.expected_scan)
        self.assertTrue(frame.expected_health)
        self.assertTrue(packet.depth_healthy)
        self.assertTrue(all(math.isinf(value) for value in packet.ranges))
        self.assertTrue(scan_observation_is_healthy(packet.ranges))

    def test_isolated_and_short_runs_are_rejected_geometrically(self):
        for scenario in ("isolated-point", "short-run"):
            packet = decode_packet(
                scenario_frame(scenario, now_ns=2_000_000_000).payload
            )
            self.assertTrue(packet.depth_healthy)
            self.assertFalse(scan_observation_is_healthy(packet.ranges))

    def test_unhealthy_depth_coverage_is_explicit(self):
        packet = scenario_packet("unhealthy-depth", now_ns=2_000_000_000)
        coverage = (
            packet.valid_ratio,
            packet.left_coverage,
            packet.center_coverage,
            packet.right_coverage,
        )
        self.assertFalse(packet.depth_healthy)
        self.assertFalse(depth_coverage_is_healthy(coverage))

    def test_stale_and_future_source_stamps_are_one_second_offset(self):
        now_ns = 2_000_000_000
        self.assertEqual(
            scenario_packet("stale", now_ns=now_ns).source_stamp_ns,
            now_ns - 1_000_000_000,
        )
        self.assertEqual(
            scenario_packet("future", now_ns=now_ns).source_stamp_ns,
            now_ns + 1_000_000_000,
        )

    def test_bad_crc_is_not_decodable(self):
        frame = scenario_frame("bad-crc", now_ns=2_000_000_000)
        with self.assertRaisesRegex(ConeScanContractError, "CRC"):
            decode_packet(frame.payload)

    def test_silence_sends_no_payload(self):
        frame = scenario_frame("silence")
        self.assertIsNone(frame.payload)
        self.assertFalse(frame.expected_health)

    def test_required_acceptance_scenarios_are_present(self):
        self.assertEqual(
            set(SCENARIOS),
            {
                "healthy-cone",
                "clear",
                "isolated-point",
                "short-run",
                "unhealthy-depth",
                "stale",
                "future",
                "bad-crc",
                "sequence-regression",
                "backlog",
                "silence",
                "stream-restart",
            },
        )


if __name__ == "__main__":
    unittest.main()
