import unittest

from nodes.navigation.cone_scan_safety import (
    ZERO_COMMAND,
    ConeScanHealthTracker,
)


class ConeScanSafetyTests(unittest.TestCase):
    def test_requires_three_consecutive_healthy_frames(self):
        tracker = ConeScanHealthTracker(required_consecutive=3, max_age_sec=0.25)
        for sequence in (1, 2):
            tracker.observe("stream-a", sequence, True, sequence * 0.05)
        decision = tracker.evaluate((0.1, 0.0, 0.0), 0.10, 0.10, 0.35)
        self.assertFalse(decision.allowed)
        tracker.observe("stream-a", 3, True, 0.15)
        decision = tracker.evaluate((0.1, 0.0, -0.1), 0.15, 0.15, 0.35)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.command, (0.1, 0.0, -0.1))

    def test_unhealthy_or_stale_health_fails_closed(self):
        tracker = ConeScanHealthTracker(required_consecutive=1, max_age_sec=0.25)
        tracker.observe("stream-a", 1, True, 1.0)
        self.assertTrue(tracker.readiness(1.20)[0])
        self.assertFalse(tracker.readiness(1.26)[0])
        decision = tracker.evaluate((0.1, 0.0, 0.0), 1.26, 1.26, 0.35)
        self.assertEqual(decision.command, ZERO_COMMAND)

    def test_stream_change_and_sequence_regression_reset_warmup(self):
        tracker = ConeScanHealthTracker(required_consecutive=2, max_age_sec=0.25)
        tracker.observe("stream-a", 1, True, 1.0)
        tracker.observe("stream-a", 2, True, 1.1)
        self.assertTrue(tracker.readiness(1.1)[0])
        tracker.observe("stream-b", 1, True, 1.2)
        self.assertFalse(tracker.readiness(1.2)[0])
        tracker.observe("stream-b", 1, True, 1.21)
        self.assertFalse(tracker.readiness(1.21)[0])

    def test_stale_command_is_zero_even_with_healthy_scan(self):
        tracker = ConeScanHealthTracker(required_consecutive=1, max_age_sec=0.25)
        tracker.observe("stream-a", 1, True, 2.0)
        decision = tracker.evaluate((0.1, 0.0, 0.0), 1.0, 2.0, 0.35)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.command, ZERO_COMMAND)


if __name__ == "__main__":
    unittest.main()
