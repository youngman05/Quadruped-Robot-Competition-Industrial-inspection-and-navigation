import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ManipulationDepthResourceTests(unittest.TestCase):
    def test_relay_keeps_raw_depth_but_disables_cone_pipeline(self):
        source = (ROOT / "scripts" / "depth_relay_docker.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "self.args.enable_depth_parameter: desired.requires_depth",
            source,
        )
        self.assertIn(
            "cone_pipeline_enabled = desired == DepthMode.AVOIDANCE",
            source,
        )
        self.assertIn(
            "parameter_values[self.args.pointcloud_enable_parameter] = cone_pipeline_enabled",
            source,
        )
        self.assertIn(
            "parameter_values[self.args.decimation_enable_parameter] = cone_pipeline_enabled",
            source,
        )
        for unrelated_stream_parameter in (
            "enable_color_parameter",
            "enable_infra_parameter",
            "enable_gyro_parameter",
            "enable_accel_parameter",
        ):
            self.assertNotIn(unrelated_stream_parameter, source)

    def test_pickup_apriltag_is_rgb_only_while_j1_uses_rgb_and_depth(self):
        apriltag = (
            ROOT / "docker" / "d455_perception" / "d455_apriltag_pose_node.py"
        ).read_text(encoding="utf-8")
        j1 = (
            ROOT / "docker" / "d455_perception" / "d455_yolo_3d_node.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "self.create_subscription(Image, self._color_topic, self._on_image, qos)",
            apriltag,
        )
        self.assertNotIn("_depth_topic", apriltag)
        self.assertIn("self.create_subscription(Image, self._color_topic", j1)
        self.assertIn("self.create_subscription(Image, self._depth_topic", j1)

    def test_cone_layers_and_scan_health_are_avoidance_only(self):
        source = (
            ROOT / "src" / "nodes" / "navigation" / "cone_scan_safety_gate.py"
        ).read_text(encoding="utf-8")
        token = "self._requested_mode == DepthMode.AVOIDANCE"
        self.assertGreaterEqual(source.count(token), 2)
        self.assertNotIn(
            "require_scan_health = self._requested_mode.requires_depth",
            source,
        )
        self.assertIn("current_state_matches", source)


if __name__ == "__main__":
    unittest.main()
