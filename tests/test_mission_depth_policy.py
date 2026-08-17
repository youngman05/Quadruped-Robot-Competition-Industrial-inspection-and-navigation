import unittest

from nodes.navigation.depth_contract import DepthContractError, DepthMode
from nodes.navigation.mission_depth_policy import MissionDepthPolicy, StationaryWindow


class MissionDepthPolicyTests(unittest.TestCase):
    def test_default_route_depth_milestones(self):
        policy = MissionDepthPolicy()
        self.assertEqual(policy.mission_start(), DepthMode.AVOIDANCE)
        self.assertIsNone(policy.before_waypoint("obstacle_cross_target"))
        self.assertEqual(
            policy.waypoint_succeeded("obstacle_cross_target"),
            DepthMode.DISABLED,
        )
        self.assertIsNone(policy.waypoint_succeeded("pos1_middle"))
        self.assertIsNone(policy.waypoint_succeeded("pos2b_lower_right"))
        self.assertIsNone(policy.before_waypoint("grab_area_approach"))
        self.assertIsNone(policy.waypoint_succeeded("grab_area_approach"))
        self.assertIsNone(policy.waypoint_succeeded("placement_A_approach"))
        self.assertIsNone(policy.waypoint_succeeded("grab_area_approach"))
        self.assertIsNone(policy.waypoint_succeeded("placement_B_approach"))

    def test_depth_never_reenables_after_obstacle_cross(self):
        policy = MissionDepthPolicy()
        policy.mission_start()
        policy.waypoint_succeeded("obstacle_cross_target")
        self.assertIsNone(policy.before_waypoint("grab_area_approach"))
        self.assertIsNone(policy.waypoint_succeeded("pos2b_lower_right"))
        self.assertIsNone(policy.waypoint_succeeded("grab_area_approach"))
        self.assertIsNone(policy.waypoint_succeeded("placement_A_approach"))

    def test_placement_waypoint_does_not_change_depth(self):
        policy = MissionDepthPolicy()
        policy.mission_start()
        policy.waypoint_succeeded("obstacle_cross_target")
        policy.waypoint_succeeded("pos2b_lower_right")
        self.assertIsNone(policy.before_waypoint("grab_area_approach"))
        self.assertIsNone(policy.waypoint_succeeded("placement_A_approach"))

    def test_depth_transition_requires_continuous_stationary_window(self):
        window = StationaryWindow(1.0)

        self.assertFalse(window.update(10.0, True))
        self.assertFalse(window.update(10.8, False))
        self.assertFalse(window.update(11.0, True))
        self.assertFalse(window.update(11.9, True))
        self.assertTrue(window.update(12.0, True))

        window.reset()
        self.assertFalse(window.update(20.0, True))


if __name__ == "__main__":
    unittest.main()
