import json
import math
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = REPO_ROOT / "navi" / "map" / "competition_field_phase1.pgm"
PARAMS_PATH = REPO_ROOT / "configs" / "navigation" / "nav2_params.yaml"
WAYPOINTS_PATH = (
    REPO_ROOT / "configs" / "navigation" / "waypoints_reordered_preview.yaml"
)
MAP_RESOLUTION = 0.025
FOOTPRINT_HALF_LENGTH = 0.35 + 0.02
FOOTPRINT_HALF_WIDTH = 0.25 + 0.02


def read_pgm(path):
    data = path.read_bytes()
    offset = 0

    def next_token():
        nonlocal offset
        while offset < len(data):
            if data[offset] == ord("#"):
                offset = data.index(b"\n", offset) + 1
            elif chr(data[offset]).isspace():
                offset += 1
            else:
                break
        start = offset
        while offset < len(data) and not chr(data[offset]).isspace():
            offset += 1
        return data[start:offset]

    magic = next_token()
    width = int(next_token())
    height = int(next_token())
    max_value = int(next_token())
    while offset < len(data) and chr(data[offset]).isspace():
        offset += 1
    pixels = data[offset:]

    if magic != b"P5" or max_value != 255:
        raise AssertionError("expected an 8-bit binary PGM")
    if len(pixels) != width * height:
        raise AssertionError("PGM payload size does not match its dimensions")
    return width, height, pixels


def occupied_cell_centers():
    width, height, pixels = read_pgm(MAP_PATH)
    centers = []
    for row in range(height):
        for column in range(width):
            if pixels[row * width + column] != 0:
                continue
            centers.append(
                (
                    (column + 0.5) * MAP_RESOLUTION,
                    (height - row - 0.5) * MAP_RESOLUTION,
                )
            )
    return centers


def footprint_polygon(x, y, yaw):
    cosine = math.cos(yaw)
    sine = math.sin(yaw)
    polygon = []
    for body_x, body_y in (
        (FOOTPRINT_HALF_LENGTH, FOOTPRINT_HALF_WIDTH),
        (FOOTPRINT_HALF_LENGTH, -FOOTPRINT_HALF_WIDTH),
        (-FOOTPRINT_HALF_LENGTH, -FOOTPRINT_HALF_WIDTH),
        (-FOOTPRINT_HALF_LENGTH, FOOTPRINT_HALF_WIDTH),
    ):
        polygon.append(
            (
                x + cosine * body_x - sine * body_y,
                y + sine * body_x + cosine * body_y,
            )
        )
    return polygon


def point_in_polygon(x, y, polygon):
    inside = False
    previous = len(polygon) - 1
    for current, (current_x, current_y) in enumerate(polygon):
        previous_x, previous_y = polygon[previous]
        if (current_y > y) != (previous_y > y):
            crossing_x = (
                (previous_x - current_x)
                * (y - current_y)
                / (previous_y - current_y)
                + current_x
            )
            if x < crossing_x:
                inside = not inside
        previous = current
    return inside


def footprint_hits_occupied(x, y, yaw, occupied_centers):
    polygon = footprint_polygon(x, y, yaw)
    min_x = min(point[0] for point in polygon)
    max_x = max(point[0] for point in polygon)
    min_y = min(point[1] for point in polygon)
    max_y = max(point[1] for point in polygon)
    return any(
        min_x <= cell_x <= max_x
        and min_y <= cell_y <= max_y
        and point_in_polygon(cell_x, cell_y, polygon)
        for cell_x, cell_y in occupied_centers
    )


class NavigationStaticClearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.occupied_centers = occupied_cell_centers()

    def test_local_costmap_loads_static_map_before_inflation(self):
        params = PARAMS_PATH.read_text(encoding="utf-8")
        local_block = params.split("local_costmap:", 1)[1].split(
            "global_costmap:", 1
        )[0]

        self.assertIn('plugins: ["static_layer", "inflation_layer"]', local_block)
        self.assertIn('plugin: "nav2_costmap_2d::StaticLayer"', local_block)
        self.assertIn("map_subscribe_transient_local: true", local_block)

    def test_dwb_scores_the_rectangular_footprint(self):
        params = PARAMS_PATH.read_text(encoding="utf-8")
        follow_path_block = params.split("    FollowPath:", 1)[1].split(
            "controller_server_rclcpp_node:", 1
        )[0]

        self.assertIn('- "ObstacleFootprint"', follow_path_block)
        self.assertIn("ObstacleFootprint.scale: 0.02", follow_path_block)
        self.assertNotIn('"BaseObstacle"', follow_path_block)
        self.assertNotIn("BaseObstacle.scale", follow_path_block)

    def test_corner_clear_route_has_safe_swept_footprint(self):
        document = json.loads(WAYPOINTS_PATH.read_text(encoding="utf-8"))
        route = document["routes"]["inspection_interleaved"]
        upper_route = route[2:7]
        self.assertEqual(
            upper_route,
            [
                "pos1_middle",
                "upper_corner_clear",
                "pos2a_upper_right",
                "upper_corner_clear",
                "pos1_middle_turned",
            ],
        )

        corner = document["waypoints"]["upper_corner_clear"]
        self.assertEqual(
            (corner["x"], corner["y"], corner["yaw"], corner["action"]),
            (2.6, 3.25, math.pi, "transit"),
        )

        segments = []
        for start_name, end_name in zip(upper_route, upper_route[1:]):
            start_waypoint = document["waypoints"][start_name]
            end_waypoint = document["waypoints"][end_name]
            segments.append(
                (
                    (start_waypoint["x"], start_waypoint["y"]),
                    (end_waypoint["x"], end_waypoint["y"]),
                )
            )
        sampled_yaws = [index * math.pi / 12.0 for index in range(24)]
        for start, end in segments:
            for step in range(51):
                fraction = step / 50.0
                x = start[0] + (end[0] - start[0]) * fraction
                y = start[1] + (end[1] - start[1]) * fraction
                for yaw in sampled_yaws:
                    self.assertFalse(
                        footprint_hits_occupied(
                            x,
                            y,
                            yaw,
                            self.occupied_centers,
                        ),
                        "swept footprint collides at x=%.3f y=%.3f yaw=%.3f"
                        % (x, y, yaw),
                    )

    def test_regression_pose_from_failed_run_collides(self):
        failed_poses = (
            (2.441901, 4.245238, -2.444062),
            (1.755, 3.780, 0.616),
        )
        for pose in failed_poses:
            with self.subTest(pose=pose):
                self.assertTrue(
                    footprint_hits_occupied(*pose, self.occupied_centers)
                )


if __name__ == "__main__":
    unittest.main()
