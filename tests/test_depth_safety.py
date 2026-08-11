import unittest

from nodes.navigation.depth_contract import DepthMode
from nodes.navigation.depth_safety import (
    ZERO_COMMAND,
    DepthReadiness,
    DepthSafetyPolicy,
    costmap_confirms_depth_generation,
    is_fresh_monotonic,
)


def ready(mode, now):
    return DepthReadiness(
        controller_mode=mode,
        request_acknowledged=True,
        controller_healthy=True,
        last_frame_time=now - 0.1,
        last_pointcloud_time=now - 0.1,
        last_tf_time=now - 0.1,
        costmap_ready=True,
    )


class DepthSafetyPolicyTests(unittest.TestCase):
    def test_required_mode_is_fail_closed_on_stale_data(self):
        policy = DepthSafetyPolicy(max_data_age_sec=0.5)
        readiness = ready(DepthMode.AVOIDANCE, 10.0)
        readiness = DepthReadiness(
            **dict(readiness.__dict__, last_frame_time=9.0)
        )
        decision = policy.evaluate(
            (0.1, 0.0, 0.0),
            DepthMode.AVOIDANCE,
            readiness,
            now=10.0,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.command, ZERO_COMMAND)

    def test_required_mode_passes_only_when_all_health_is_ready(self):
        policy = DepthSafetyPolicy(max_data_age_sec=0.5)
        decision = policy.evaluate(
            (0.1, 0.0, -0.1),
            DepthMode.MANIPULATION,
            ready(DepthMode.MANIPULATION, 10.0),
            now=10.0,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.command, (0.1, 0.0, -0.1))

    def test_disabled_mode_does_not_require_depth_data(self):
        policy = DepthSafetyPolicy(max_data_age_sec=0.5)
        unavailable = DepthReadiness(
            controller_mode=DepthMode.DISABLED,
            request_acknowledged=True,
            controller_healthy=True,
            last_frame_time=None,
            last_pointcloud_time=None,
            last_tf_time=None,
            costmap_ready=False,
        )
        decision = policy.evaluate(
            (0.1, 0.0, 0.0),
            DepthMode.DISABLED,
            unavailable,
            now=10.0,
        )
        self.assertTrue(decision.allowed)

    def test_disabled_mode_waits_for_explicit_ack(self):
        policy = DepthSafetyPolicy(max_data_age_sec=0.5)
        pending = DepthReadiness(
            controller_mode=DepthMode.AVOIDANCE,
            request_acknowledged=False,
            controller_healthy=True,
            last_frame_time=10.0,
            last_pointcloud_time=10.0,
            last_tf_time=10.0,
            costmap_ready=True,
        )
        decision = policy.evaluate(
            (0.1, 0.0, 0.0),
            DepthMode.DISABLED,
            pending,
            now=10.0,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.command, ZERO_COMMAND)

    def test_future_monotonic_data_is_not_fresh(self):
        self.assertFalse(is_fresh_monotonic(10.1, now=10.0, max_age_sec=0.5))

    def test_costmap_must_follow_a_cloud_from_the_current_generation(self):
        self.assertFalse(
            costmap_confirms_depth_generation(
                mode_started_time=10.0,
                last_pointcloud_time=9.9,
                source_stamp_ns=100,
                costmap_stamp_ns=101,
            )
        )
        self.assertFalse(
            costmap_confirms_depth_generation(
                mode_started_time=10.0,
                last_pointcloud_time=10.1,
                source_stamp_ns=102,
                costmap_stamp_ns=101,
            )
        )
        self.assertTrue(
            costmap_confirms_depth_generation(
                mode_started_time=10.0,
                last_pointcloud_time=10.1,
                source_stamp_ns=101,
                costmap_stamp_ns=101,
            )
        )


if __name__ == "__main__":
    unittest.main()
