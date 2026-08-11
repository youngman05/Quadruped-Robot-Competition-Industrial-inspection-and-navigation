import unittest

from nodes.navigation.depth_contract import (
    DepthContractError,
    DepthMode,
    new_controller_status,
)
from nodes.navigation.depth_mode import DepthModeCoordinator


class DepthModeCoordinatorTests(unittest.TestCase):
    def test_unsolicited_stale_operational_status_does_not_make_boot_ready(self):
        coordinator = DepthModeCoordinator(transition_timeout_sec=2.0)
        coordinator.observe_status(
            new_controller_status(
                DepthMode.AVOIDANCE,
                stream_id="stream-a",
                ack_request_id="previous-run",
                updated_monotonic_ns=1,
            )
        )
        readiness = coordinator.readiness(now_ns=2)
        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.mode, DepthMode.BOOTING)

    def test_transition_requires_stopped_robot_and_matching_ack(self):
        coordinator = DepthModeCoordinator(transition_timeout_sec=2.0)
        with self.assertRaises(DepthContractError):
            coordinator.request(DepthMode.AVOIDANCE, robot_stopped=False, now_ns=0)

        request = coordinator.request(
            DepthMode.AVOIDANCE,
            robot_stopped=True,
            now_ns=0,
            request_id="req-1",
        )
        coordinator.observe_status(
            new_controller_status(
                DepthMode.AVOIDANCE,
                stream_id="stream-a",
                ack_request_id="old-request",
                updated_monotonic_ns=1,
            )
        )
        self.assertTrue(coordinator.readiness(now_ns=1).pending)

        coordinator.observe_status(
            new_controller_status(
                DepthMode.AVOIDANCE,
                stream_id="stream-a",
                ack_request_id=request["request_id"],
                updated_monotonic_ns=2,
            )
        )
        readiness = coordinator.readiness(now_ns=2)
        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.mode, DepthMode.AVOIDANCE)

    def test_transition_timeout_is_fault_readiness(self):
        coordinator = DepthModeCoordinator(transition_timeout_sec=1.0)
        coordinator.request(
            DepthMode.DISABLED,
            robot_stopped=True,
            now_ns=0,
            request_id="req-2",
        )
        readiness = coordinator.readiness(now_ns=1_000_000_001)
        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.mode, DepthMode.FAULT)


if __name__ == "__main__":
    unittest.main()
