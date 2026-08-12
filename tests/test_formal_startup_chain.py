import importlib.util
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
START_SCRIPT = REPO_ROOT / "scripts" / "start_competition.sh"
HEALTH_PROBE = REPO_ROOT / "scripts" / "cone_startup_health_probe.py"
BASE_PARAMS = REPO_ROOT / "configs" / "navigation" / "nav2_params.yaml"
CONE_PARAMS = REPO_ROOT / "configs" / "navigation" / "nav2_cone_obstacles.yaml"
EXPERIMENTAL_PARAMS = (
    REPO_ROOT / "configs" / "navigation" / "nav2_cone_obstacles_experimental.yaml"
)
SAFETY_GATE = (
    REPO_ROOT / "src" / "nodes" / "navigation" / "cone_scan_safety_gate.py"
)


def load_health_probe():
    spec = importlib.util.spec_from_file_location("cone_startup_health_probe", HEALTH_PROBE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FormalStartupChainContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = START_SCRIPT.read_text(encoding="utf-8")

    def test_formal_environment_source_order_is_explicit(self):
        tokens = (
            'source "$FOXY_SETUP"',
            'source "$CONE_PLUGIN_OVERLAY_SETUP"',
            'source "$NAV2_BT_OVERLAY_SETUP"',
            'source "$FORMAL_DEPLOY_SETUP"',
        )
        positions = [self.script.index(token) for token in tokens]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("CONE_PLUGIN_OVERLAY_SETUP=", self.script)
        self.assertIn("NAV2_BT_OVERLAY_SETUP=", self.script)

    def test_cone_plugin_is_required_before_runtime_mutation(self):
        plugin_guard = self.script.index(
            'pinned cone plugin overlay is missing: $CONE_PLUGIN_OVERLAY_SETUP'
        )
        cleanup = self.script.index("echo '[0/6] 清理旧进程...'")
        docker = self.script.index("echo '[1/6] Docker cuVSLAM...'")
        self.assertLess(plugin_guard, cleanup)
        self.assertLess(plugin_guard, docker)
        guarded_block = self.script.split(
            "if $ENABLE_CONE_AVOIDANCE; then", 3
        )[3].split("fi", 1)[0]
        self.assertIn("CONE_PLUGIN_OVERLAY_SETUP", guarded_block)

    def test_non_cone_mode_does_not_require_plugin_package(self):
        package_lookup = self.script.index(
            "ros2 pkg prefix nonpersistent_voxel_layer"
        )
        enclosing_guard = self.script.rfind(
            "if $ENABLE_CONE_AVOIDANCE; then", 0, package_lookup
        )
        enclosing_end = self.script.index("\nfi", package_lookup)
        self.assertLess(enclosing_guard, package_lookup)
        self.assertGreater(enclosing_end, package_lookup)

    def test_preflight_proves_packages_plugin_xml_and_library(self):
        for token in (
            "ros2 pkg prefix nonpersistent_voxel_layer",
            "ros2 pkg prefix nav2_bt_navigator",
            "ros2 pkg prefix quadruped_robot_competition",
            "nav2_costmap_2d/NonPersistentVoxelLayer",
            "libnonpersistent_voxel_layer_core.so",
            'snapshot_value "plugin_library"',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.script)

    def test_success_banner_is_after_fail_closed_runtime_gate(self):
        banner = self.script.index("GO: 启动完成，运行验收通过!")
        for token in (
            "LIFECYCLE_NODES=(map_server planner_server controller_server recoveries_server bt_navigator)",
            "ros2 lifecycle get",
            "EXPECTED_CMD_VEL_SUBSCRIBERS",
            "Reliability: BEST_EFFORT",
            "Reliability: RELIABLE",
            "cone_startup_health_probe.py",
            "controller_server did not map the pinned",
        ):
            with self.subTest(token=token):
                self.assertLess(self.script.index(token), banner)
        self.assertIn('echo "NO-GO: $*"', self.script)
        self.assertNotIn("✅ 启动完成!", self.script)

    def test_official_parameters_and_gate_defaults_remain_frozen(self):
        base = BASE_PARAMS.read_text(encoding="utf-8")
        cone = CONE_PARAMS.read_text(encoding="utf-8")
        experimental = EXPERIMENTAL_PARAMS.read_text(encoding="utf-8")
        gate = SAFETY_GATE.read_text(encoding="utf-8")
        for token in (
            "observation_persistence: 1.5",
            "inflation_radius: 0.30",
            "cost_scaling_factor: 3.0",
        ):
            self.assertIn(token, cone)
        for token in (
            "PathAlign.scale: 32.0",
            "PathDist.scale: 32.0",
            "ObstacleFootprint.scale: 0.02",
        ):
            self.assertIn(token, base)
        self.assertIn('declare_parameter("required_consecutive_frames", 3)', gate)
        self.assertIn('declare_parameter("health_timeout_sec", 0.20)', gate)
        self.assertNotIn("nav2_cone_obstacles_experimental.yaml", self.script)
        self.assertIn("inflation_radius: 0.45", experimental)


class ConeStartupHealthProbeTests(unittest.TestCase):
    def test_continuously_ready_window_passes_at_minimum_rate(self):
        module = load_health_probe()
        state = module.ProbeState()
        for index in range(81):
            state.record_scan(100.0 + index * 0.1)
        for sequence in range(1, 81):
            state.record_health(
                '{"healthy":true,"reason":"ready","stream_id":"s",'
                '"sequence":%d,"source_age_ms":25.0}' % sequence
            )
        result = state.result(min_scan_rate_hz=8.0, min_health_samples=8)
        self.assertTrue(result["passed"])
        self.assertAlmostEqual(result["scan_rate_hz"], 10.0)

    def test_unhealthy_or_non_advancing_health_fails(self):
        module = load_health_probe()
        state = module.ProbeState()
        state.record_scan(1.0)
        state.record_scan(1.1)
        payload = (
            '{"healthy":true,"reason":"ready","stream_id":"s",'
            '"sequence":1,"source_age_ms":20.0}'
        )
        state.record_health(payload)
        state.record_health(payload)
        result = state.result(min_scan_rate_hz=8.0, min_health_samples=2)
        self.assertFalse(result["passed"])
        self.assertIn("health stream was not continuously ready", result["errors"])


if __name__ == "__main__":
    unittest.main()
