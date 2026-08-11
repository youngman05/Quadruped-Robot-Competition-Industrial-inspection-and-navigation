import unittest

from nodes.navigation.depth_contract import DepthContractError, DepthMode
from nodes.navigation.mission_depth_policy import MissionDepthPolicy


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
        self.assertEqual(
            policy.before_waypoint("grab_area_approach"),
            DepthMode.MANIPULATION,
        )

    def test_manipulation_cannot_start_before_inspection_exit(self):
        policy = MissionDepthPolicy()
        policy.mission_start()
        policy.waypoint_succeeded("obstacle_cross_target")
        with self.assertRaises(DepthContractError):
            policy.before_waypoint("grab_area_approach")


if __name__ == "__main__":
    unittest.main()
