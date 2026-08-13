import unittest

from nodes.navigation.mission_route import (
    MISSION_NAV_WAYPOINTS,
    OBSTACLE_TO_INSPECTION_HANDOFF,
    INSPECTION_ROUTE,
    OBSTACLE_ROUTE,
    inspection_route_steps,
    observation_steps,
)
from nodes.navigation.waypoint_calibration import DEFAULT_INSPECTION_ROUTE


class MissionRouteTests(unittest.TestCase):
    def test_task_routes_are_derived_from_calibration_route(self):
        handoff = DEFAULT_INSPECTION_ROUTE.index(OBSTACLE_TO_INSPECTION_HANDOFF)
        self.assertEqual(
            OBSTACLE_ROUTE,
            tuple(DEFAULT_INSPECTION_ROUTE[: handoff + 1]),
        )
        self.assertEqual(
            INSPECTION_ROUTE,
            tuple(DEFAULT_INSPECTION_ROUTE[handoff:]),
        )
        self.assertEqual(OBSTACLE_ROUTE[-1], INSPECTION_ROUTE[0])
        self.assertEqual(
            MISSION_NAV_WAYPOINTS,
            tuple(dict.fromkeys(DEFAULT_INSPECTION_ROUTE)),
        )

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
