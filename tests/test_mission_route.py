import unittest

from nodes.navigation.mission_route import (
    INSPECTION_ROUTE,
    OBSTACLE_ROUTE,
    inspection_route_steps,
    observation_steps,
)
from nodes.navigation.waypoint_calibration import DEFAULT_INSPECTION_ROUTE


class MissionRouteTests(unittest.TestCase):
    def test_task_routes_are_derived_from_calibration_route(self):
        self.assertEqual(OBSTACLE_ROUTE, tuple(DEFAULT_INSPECTION_ROUTE[:3]))
        self.assertEqual(INSPECTION_ROUTE, tuple(DEFAULT_INSPECTION_ROUTE[2:]))
        self.assertEqual(OBSTACLE_ROUTE[-1], INSPECTION_ROUTE[0])

    def test_inspection_route_has_four_observations_and_safe_transits(self):
        steps = inspection_route_steps()
        observations = [step for step in steps if step["kind"] == "observe"]
        transits = [step["waypoint"] for step in steps if step["kind"] == "transit"]
        self.assertEqual(len(observations), 4)
        self.assertEqual(
            [step["waypoint"] for step in observations],
            [step["waypoint"] for step in observation_steps()],
        )
        self.assertEqual(
            transits,
            ["upper_corner_clear", "upper_corner_clear", "lower_corner_clear"],
        )


if __name__ == "__main__":
    unittest.main()
