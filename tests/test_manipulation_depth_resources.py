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


if __name__ == "__main__":
    unittest.main()
