import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
NAV_LAUNCH = REPO_ROOT / "launch" / "navigation.launch.py"
COMP_LAUNCH = REPO_ROOT / "launch" / "competition.launch.py"
BASE_PARAMS = REPO_ROOT / "configs" / "navigation" / "nav2_params.yaml"
DEPTH_PARAMS = REPO_ROOT / "configs" / "navigation" / "nav2_depth_obstacles.yaml"
START = REPO_ROOT / "scripts" / "start_competition.sh"
FULL = REPO_ROOT / "scripts" / "run_full_navigation.sh"


class DepthPipelineLaunchContractTests(unittest.TestCase):
    def test_default_navigation_stays_static_only_and_phase1(self):
        nav = NAV_LAUNCH.read_text(encoding="utf-8")
        base = BASE_PARAMS.read_text(encoding="utf-8")
        self.assertIn('default_value="false"', nav)
        self.assertIn("competition_field_phase1.yaml", nav)
        self.assertNotIn("competition_field_phase2.yaml", nav)
        self.assertIn('plugins: ["static_layer", "inflation_layer"]', base)

    def test_opt_in_pipeline_has_dynamic_layers_and_single_velocity_gate(self):
        nav = NAV_LAUNCH.read_text(encoding="utf-8")
        overlay = DEPTH_PARAMS.read_text(encoding="utf-8")
        for token in (
            '"output_topic": "/cmd_vel_selected"',
            'executable="depth_safety_gate"',
            'executable="depth_relay_publisher"',
            "camera_depth_optical_frame",
        ):
            self.assertIn(token, nav)
        self.assertIn("nav2_costmap_2d::VoxelLayer", overlay)
        self.assertIn("nav2_costmap_2d::ObstacleLayer", overlay)

    def test_launcher_copies_contract_and_defaults_to_consumer_only(self):
        start = START.read_text(encoding="utf-8")
        self.assertIn("--depth-pipeline", start)
        self.assertIn("depth_contract.py", start)
        self.assertIn("consumer_only", start)
        self.assertIn("enable_depth_pipeline:=$ENABLE_DEPTH_PIPELINE", start)

    def test_relay_uses_sensor_qos_and_generation_freshness_guards(self):
        docker_relay = (REPO_ROOT / "scripts" / "depth_relay_docker.py").read_text(
            encoding="utf-8"
        )
        host_relay = (
            REPO_ROOT
            / "src"
            / "nodes"
            / "navigation"
            / "depth_relay_publisher.py"
        ).read_text(encoding="utf-8")
        gate = (
            REPO_ROOT
            / "src"
            / "nodes"
            / "navigation"
            / "depth_safety_gate.py"
        ).read_text(encoding="utf-8")
        self.assertIn("qos_profile_sensor_data", docker_relay)
        self.assertIn("stream_id=self.stream_id", docker_relay)
        self.assertIn('label="depth frame"', host_relay)
        self.assertIn("frame stream does not match controller stream", host_relay)
        self.assertIn("costmap_confirms_depth_generation", gate)
        self.assertIn('"active_request_id": self._active_request_id', gate)

    def test_existing_full_route_does_not_enable_unvalidated_pipeline(self):
        full = FULL.read_text(encoding="utf-8")
        self.assertNotIn("--depth-pipeline", full)
        self.assertNotIn("--enable-depth-milestones", full)

    def test_competition_launch_keeps_legacy_depth_owner_off_by_default(self):
        competition = COMP_LAUNCH.read_text(encoding="utf-8")
        self.assertIn('enable_depth_publisher = LaunchConfiguration(', competition)
        self.assertIn('default="false"', competition)
        self.assertIn('enable_depth_pipeline = LaunchConfiguration(', competition)


if __name__ == "__main__":
    unittest.main()
