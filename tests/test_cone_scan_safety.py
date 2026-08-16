import unittest

from nodes.navigation.cone_scan_safety import (
    ZERO_COMMAND,
    ConeLayerAppliedTracker,
    ConeScanHealthTracker,
)


class ConeScanSafetyTests(unittest.TestCase):
    @staticmethod
    def layer_status(enabled, revision, sequence):
        return {
            "plugin": "cone_obstacle_layer",
            "requested_enabled": enabled,
            "applied_enabled": enabled,
            "applied_revision": revision,
            "status_sequence": sequence,
        }

    def test_layer_transition_requires_both_post_baseline_revisions(self):
        tracker = ConeLayerAppliedTracker()
        tracker.observe("local", self.layer_status(True, 0, 3), 1.0)
        tracker.observe("global", self.layer_status(True, 0, 7), 1.0)
        self.assertTrue(tracker.begin_transition(False))
        self.assertFalse(tracker.readiness()[0])

        tracker.observe("local", self.layer_status(False, 1, 4), 1.1)
        self.assertFalse(tracker.readiness()[0])
        tracker.observe("global", self.layer_status(False, 1, 8), 1.2)
        self.assertEqual(tracker.readiness(), (True, "local/global cone layers applied"))

    def test_retained_pre_transition_status_cannot_acknowledge(self):
        tracker = ConeLayerAppliedTracker()
        tracker.observe("local", self.layer_status(True, 2, 10), 1.0)
        tracker.observe("global", self.layer_status(True, 2, 20), 1.0)
        tracker.begin_transition(True)
        tracker.observe("local", self.layer_status(True, 2, 11), 1.1)
        tracker.observe("global", self.layer_status(True, 2, 21), 1.1)
        ready, reason = tracker.readiness()
        self.assertFalse(ready)
        self.assertIn("applied revision", reason)

    def test_unchanged_disabled_state_can_acknowledge_after_parameter_readback(self):
        tracker = ConeLayerAppliedTracker()
        tracker.observe("local", self.layer_status(False, 2, 10), 1.0)
        tracker.observe("global", self.layer_status(False, 3, 20), 1.0)
        tracker.begin_transition(False)

        self.assertEqual(
            tracker.current_state_matches(False),
            (True, "local/global cone layers already applied"),
        )
        self.assertFalse(tracker.readiness()[0])

    def test_unchanged_ack_rejects_any_layer_state_mismatch(self):
        tracker = ConeLayerAppliedTracker()
        tracker.observe("local", self.layer_status(False, 2, 10), 1.0)
        tracker.observe("global", self.layer_status(True, 3, 20), 1.0)

        ready, reason = tracker.current_state_matches(False)
        self.assertFalse(ready)
        self.assertIn("global cone layer requested state mismatch", reason)

    def test_layer_state_mismatch_fails_closed(self):
        tracker = ConeLayerAppliedTracker()
        tracker.observe("local", self.layer_status(True, 0, 1), 1.0)
        tracker.observe("global", self.layer_status(True, 0, 1), 1.0)
        tracker.begin_transition(False)
        tracker.observe("local", self.layer_status(False, 1, 2), 1.1)
        mismatch = self.layer_status(False, 1, 2)
        mismatch["applied_enabled"] = True
        tracker.observe("global", mismatch, 1.1)
        ready, reason = tracker.readiness()
        self.assertFalse(ready)
        self.assertIn("applied state mismatch", reason)

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

    def test_disabled_mode_bypass_keeps_command_watchdog(self):
        tracker = ConeScanHealthTracker(required_consecutive=3, max_age_sec=0.25)
        decision = tracker.evaluate(
            (0.1, 0.0, -0.1),
            command_time=2.0,
            now=2.1,
            command_timeout_sec=0.35,
            require_scan_health=False,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.command, (0.1, 0.0, -0.1))
        self.assertEqual(decision.reason, "cone avoidance bypassed")

        stale = tracker.evaluate(
            (0.1, 0.0, -0.1),
            command_time=1.0,
            now=2.0,
            command_timeout_sec=0.35,
            require_scan_health=False,
        )
        self.assertFalse(stale.allowed)
        self.assertEqual(stale.command, ZERO_COMMAND)


if __name__ == "__main__":
    unittest.main()
