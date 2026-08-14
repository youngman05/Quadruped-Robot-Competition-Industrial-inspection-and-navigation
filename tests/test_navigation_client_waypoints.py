import tempfile
import unittest
from pathlib import Path

from nodes.navigation.navigation_client import (
    NavigationClient,
    _behavior_tree_for_waypoint,
    load_calibrated_waypoints,
)
from nodes.navigation.waypoint_calibration import (
    DEFAULT_INSPECTION_ROUTE,
    WaypointCalibrationError,
    new_waypoint_document,
    write_waypoint_document,
)


def completed_document(map_id="field-v1"):
    document = new_waypoint_document(map_id=map_id)
    document["calibration"]["status"] = "complete"
    for index, name in enumerate(DEFAULT_INSPECTION_ROUTE):
        document["waypoints"][name] = {
            "x": 0.25 * index,
            "y": 0.10 * index,
            "yaw": 0.05 * index,
            "action": "transit",
        }
    return document


class NavigationClientWaypointTests(unittest.TestCase):
    def test_only_configured_waypoint_selects_cone_behavior_tree(self):
        mapping = {
            "obstacle_cross_target": "/tmp/navigate_cone.xml",
        }
        self.assertEqual(
            _behavior_tree_for_waypoint("obstacle_cross_target", mapping),
            "/tmp/navigate_cone.xml",
        )
        self.assertEqual(
            _behavior_tree_for_waypoint("pos1_left_clear", mapping),
            "",
        )

    def test_navigation_goal_routing_restores_default_after_cone_goal(self):
        client = object.__new__(NavigationClient)
        client._waypoints = {
            "obstacle_cross_target": {
                "x": 1.0, "y": 0.5,
                "qx": 0.0, "qy": 0.0, "qz": 0.0, "qw": 1.0,
                "label": "cone",
            },
            "pos1_left_clear": {
                "x": 0.6, "y": 2.9,
                "qx": 0.0, "qy": 0.0, "qz": 0.0, "qw": 1.0,
                "label": "clear",
            },
        }
        client._behavior_tree_by_waypoint = {
            "obstacle_cross_target": "/tmp/navigate_cone.xml",
        }
        calls = []
        client.navigate_to_pose = lambda **kwargs: calls.append(kwargs) or True

        self.assertTrue(client.navigate_to_waypoint("obstacle_cross_target"))
        self.assertTrue(client.navigate_to_waypoint("pos1_left_clear"))
        self.assertEqual(calls[0]["behavior_tree"], "/tmp/navigate_cone.xml")
        self.assertEqual(calls[1]["behavior_tree"], "")

    def write_document(self, document):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "waypoints_real.yaml"
        write_waypoint_document(path, document)
        self.addCleanup(directory.cleanup)
        return path

    def test_completed_route_loads_with_map_provenance(self):
        path = self.write_document(completed_document())
        waypoints = load_calibrated_waypoints(
            path,
            "inspection_interleaved",
            expected_map_id="field-v1",
        )
        self.assertEqual(
            list(waypoints),
            list(dict.fromkeys(DEFAULT_INSPECTION_ROUTE)),
        )
        self.assertEqual(waypoints["obstacle_cross_target"]["map_id"], "field-v1")
        self.assertEqual(
            waypoints["obstacle_cross_target"]["source"],
            "waypoint_file",
        )

    def test_incomplete_calibration_is_rejected(self):
        document = completed_document()
        document["calibration"]["status"] = "in_progress"
        path = self.write_document(document)
        with self.assertRaisesRegex(
            WaypointCalibrationError,
            "calibration must be complete",
        ):
            load_calibrated_waypoints(path, "inspection_interleaved")

    def test_map_id_mismatch_is_rejected(self):
        path = self.write_document(completed_document())
        with self.assertRaisesRegex(
            WaypointCalibrationError,
            "does not match expected map_id",
        ):
            load_calibrated_waypoints(
                path,
                "inspection_interleaved",
                expected_map_id="field-v2",
            )


if __name__ == "__main__":
    unittest.main()
