import json
import hashlib
import math
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from nodes.navigation.waypoint_calibration import (
    DEFAULT_CALIBRATION_ORDER,
    DEFAULT_FULL_ROUTE,
    DEFAULT_INSPECTION_ROUTE,
    WaypointCalibrationError,
    estimate_stable_pose,
    load_waypoint_document,
    new_waypoint_document,
    resolve_waypoint_route,
    upsert_waypoint,
    write_waypoint_document,
)


def stable_samples(x=1.5, y=3.25, yaw=0.0, count=30):
    samples = []
    for index in range(count):
        offset = (index % 5 - 2) * 0.001
        samples.append({"x": x + offset, "y": y - offset, "yaw": yaw + offset})
    return samples


class WaypointCalibrationTests(unittest.TestCase):
    def test_circular_yaw_mean_stays_near_pi_across_wrap(self):
        samples = []
        for index in range(30):
            yaw = math.pi - 0.01 if index % 2 == 0 else -math.pi + 0.01
            samples.append({"x": 1.0, "y": 2.0, "yaw": yaw})

        estimate = estimate_stable_pose(
            samples,
            min_samples=20,
            max_xy_deviation=0.01,
            max_yaw_deviation=0.02,
        )

        self.assertLess(abs(abs(estimate["yaw"]) - math.pi), 1e-9)
        self.assertEqual(estimate["sample_count"], 30)

    def test_unstable_xy_window_is_rejected(self):
        samples = stable_samples()
        samples[-1]["x"] += 0.20

        with self.assertRaisesRegex(WaypointCalibrationError, "XY is unstable"):
            estimate_stable_pose(samples, max_xy_deviation=0.04)

    def test_document_round_trip_and_interleaved_route_resolution(self):
        document = new_waypoint_document(frame_id="map", map_id="field-test")
        all_names = set(DEFAULT_FULL_ROUTE)
        for index, name in enumerate(sorted(all_names)):
            estimate = estimate_stable_pose(
                stable_samples(x=1.0 + index * 0.1, yaw=index * 0.05)
            )
            upsert_waypoint(document, name, estimate)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "waypoints_real.yaml"
            write_waypoint_document(path, document)
            loaded = load_waypoint_document(path)

        goals = resolve_waypoint_route(loaded, "inspection_interleaved")
        self.assertEqual(
            [goal["label"] for goal in goals],
            list(DEFAULT_INSPECTION_ROUTE),
        )
        self.assertEqual(goals[0]["source"], "waypoint_file")
        self.assertEqual(loaded["map_id"], "field-test")
        self.assertEqual(loaded["calibration"]["status"], "in_progress")

    def test_route_with_uncalibrated_waypoint_is_rejected(self):
        document = new_waypoint_document()

        with self.assertRaisesRegex(
            WaypointCalibrationError, "uncalibrated waypoint obstacle_cross_target"
        ):
            resolve_waypoint_route(document, "inspection_interleaved")

    def test_repository_real_waypoints_track_pending_grab_approach(self):
        path = REPO_ROOT / "configs" / "navigation" / "waypoints_real.yaml"
        document = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(document["version"], 1)
        self.assertEqual(document["frame_id"], "map")
        self.assertEqual(document["map_id"], "competition_field_phase1")
        self.assertEqual(document["calibration"]["status"], "in_progress")
        self.assertEqual(
            document["calibration"]["map_yaml_sha256"],
            "6993e41e4d057f204fa7d229e25906cf1ccfd4f2cc7c9bee9881851d69ff8ec0",
        )
        self.assertEqual(
            document["calibration"]["map_image_sha256"],
            "3540f2abaac8903dd61da70c8ff43ee5c0abf3b33036df1c3576466739692fff",
        )
        map_dir = REPO_ROOT / "navi" / "map"
        for metadata_key, filename in (
            ("map_yaml_sha256", "competition_field_phase1.yaml"),
            ("map_image_sha256", "competition_field_phase1.pgm"),
        ):
            actual_hash = hashlib.sha256((map_dir / filename).read_bytes()).hexdigest()
            self.assertEqual(document["calibration"][metadata_key], actual_hash)
        self.assertEqual(
            document["routes"]["full_interleaved"],
            list(DEFAULT_FULL_ROUTE),
        )
        self.assertEqual(len(document["routes"]["full_interleaved"]), 14)
        self.assertEqual(set(document["waypoints"]), set(DEFAULT_FULL_ROUTE))

        grab = document["waypoints"]["grab_area_approach"]
        self.assertEqual(
            (grab["x"], grab["y"], grab["yaw"], grab["yaw_deg"], grab["action"]),
            (4.25, 3.05, -math.pi / 2.0, -90.0, "grab"),
        )

        goals = resolve_waypoint_route(document, "full_interleaved")
        self.assertEqual([goal["label"] for goal in goals], list(DEFAULT_FULL_ROUTE))

        preview_path = (
            REPO_ROOT
            / "configs"
            / "navigation"
            / "waypoints_reordered_preview.yaml"
        )
        preview = load_waypoint_document(preview_path)
        self.assertEqual(document["waypoints"], preview["waypoints"])
        self.assertEqual(document["routes"], preview["routes"])

    def test_reordered_preview_separates_the_same_xy_opposite_yaw_poses(self):
        path = (
            REPO_ROOT
            / "configs"
            / "navigation"
            / "waypoints_reordered_preview.yaml"
        )
        document = load_waypoint_document(path)
        goals = resolve_waypoint_route(document, "inspection_interleaved")

        self.assertEqual(document["calibration"]["status"], "preview")
        self.assertEqual(
            [goal["label"] for goal in goals],
            list(DEFAULT_INSPECTION_ROUTE),
        )
        self.assertEqual(
            [goal["action"] for goal in goals if goal["action"].startswith("observe")],
            [
                "observe_upper_gauge",
                "observe_upper_side",
                "observe_lower_gauge",
                "observe_lower_side",
            ],
        )

        goals_by_label = {goal["label"]: goal for goal in goals}
        middle = goals_by_label["pos1_middle"]
        corner_clear = goals_by_label["upper_corner_clear"]
        middle_turned = goals_by_label["pos1_middle_turned"]
        lower_corner_clear = goals_by_label["lower_corner_clear"]
        self.assertEqual((middle["x"], middle["y"]), (middle_turned["x"], middle_turned["y"]))
        self.assertAlmostEqual(abs(middle["yaw"] - middle_turned["yaw"]), math.pi)
        self.assertEqual(
            (corner_clear["x"], corner_clear["y"], corner_clear["yaw"]),
            (2.6, 3.25, math.pi),
        )
        self.assertEqual(
            (
                lower_corner_clear["x"],
                lower_corner_clear["y"],
                lower_corner_clear["yaw"],
            ),
            (2.6, 3.25, math.pi),
        )
        self.assertEqual(len(goals), 9)
        calibration_order = list(DEFAULT_CALIBRATION_ORDER)
        lower_calibration_index = calibration_order.index("lower_corner_clear")
        self.assertEqual(
            calibration_order[
                lower_calibration_index - 1 : lower_calibration_index + 2
            ],
            ["pos1_middle_turned", "lower_corner_clear", "pos2b_lower_right"],
        )
        labels = [goal["label"] for goal in goals]
        corner_indices = [
            index
            for index, label in enumerate(labels)
            if label == "upper_corner_clear"
        ]
        self.assertEqual(len(corner_indices), 2)
        self.assertEqual(
            labels[corner_indices[0] - 1 : corner_indices[0] + 2],
            ["pos1_middle", "upper_corner_clear", "pos2a_upper_right"],
        )
        self.assertEqual(
            labels[corner_indices[1] - 1 : corner_indices[1] + 2],
            ["pos2a_upper_right", "upper_corner_clear", "pos1_middle_turned"],
        )
        lower_corner_indices = [
            index
            for index, label in enumerate(labels)
            if label == "lower_corner_clear"
        ]
        self.assertEqual(len(lower_corner_indices), 1)
        self.assertEqual(
            labels[
                lower_corner_indices[0] - 1 : lower_corner_indices[0] + 2
            ],
            ["pos1_middle_turned", "lower_corner_clear", "pos2b_lower_right"],
        )

        for previous, current in zip(goals, goals[1:]):
            distance = math.hypot(
                current["x"] - previous["x"],
                current["y"] - previous["y"],
            )
            yaw_change = abs(
                math.atan2(
                    math.sin(current["yaw"] - previous["yaw"]),
                    math.cos(current["yaw"] - previous["yaw"]),
                )
            )
            self.assertFalse(
                distance <= 0.05 and yaw_change >= math.radians(150.0),
                "%s -> %s reintroduces a same-position reversal"
                % (previous["label"], current["label"]),
            )

    def test_probe_exposes_explicit_calibrated_route_arguments(self):
        source = (
            REPO_ROOT / "scripts" / "nav2_waypoint_sequence_probe.py"
        ).read_text(encoding="utf-8")

        self.assertIn('"--waypoint-file"', source)
        self.assertIn('"--waypoint-route"', source)
        self.assertIn("resolve_waypoint_route(", source)
        self.assertIn(
            '"--waypoint-file and --waypoint-route must be provided together"',
            source,
        )
        self.assertIn('raise WaypointCalibrationError("map_id is empty")', source)
        self.assertIn('calibration_status != "complete"', source)
        self.assertIn('"--allow-preview-route"', source)
        self.assertIn('preview_source == "legacy_pgm_route_presets"', source)
        self.assertIn(
            '("absolute", "route_preset", "waypoint_file")',
            source,
        )


if __name__ == "__main__":
    unittest.main()
