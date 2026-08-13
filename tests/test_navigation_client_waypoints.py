import tempfile
import unittest
from pathlib import Path

from nodes.navigation.navigation_client import load_calibrated_waypoints
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
