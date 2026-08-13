import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TASK_MANAGER = REPO_ROOT / "src" / "nodes" / "decision" / "task_manager.py"
COMPETITION_LAUNCH = REPO_ROOT / "launch" / "competition.launch.py"
COMPETITION_PARAMS = REPO_ROOT / "configs" / "ros" / "competition_params.yaml"


class TaskManagerDepthContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = TASK_MANAGER.read_text(encoding="utf-8")

    def test_task_manager_owns_depth_milestones_non_blockingly(self):
        for token in (
            "MissionDepthPolicy()",
            "DepthModeClient(",
            '"mission_start"',
            '"after_success:obstacle_cross_target"',
            '"before:grab_area_approach"',
            "self._depth_mode_client.readiness()",
            "self._depth_mode_client.end_to_end_ready(mode)",
            "self._depth_mode_client.republish_active_request(mode)",
            "self._host_odom_ready_after_depth_transition(mode)",
            'declare_parameter("verify_host_odom_after_depth_disable", True)',
            'declare_parameter("depth_transition_settle_duration_sec", 1.0)',
            "self._depth_transition_stationary.update(",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.source)
        self.assertNotIn("spin_until_future_complete", self.source)
        self.assertNotIn("time.sleep", self.source)

    def test_phase2_map_switch_is_default_off(self):
        self.assertIn('declare_parameter("enable_phase2_map_switch", False)', self.source)
        launch_source = COMPETITION_LAUNCH.read_text(encoding="utf-8")
        self.assertIn('"enable_phase2_map_switch": False', launch_source)

    def test_launch_owned_task_parameters_are_not_shadowed_by_node_yaml(self):
        launch_source = COMPETITION_LAUNCH.read_text(encoding="utf-8")
        params = COMPETITION_PARAMS.read_text(encoding="utf-8")
        for parameter in (
            "auto_advance",
            "max_nav_retries",
            "max_inspection_retries",
            "finish_after_inspection",
            "allow_placeholder_manipulation",
            "pass_obstacle_timeout_sec",
            "inspection_timeout_sec",
            "waypoint_file",
            "waypoint_route",
            "expected_map_id",
            "enable_phase2_map_switch",
            "enable_depth_milestones",
            "depth_safety_status_topic",
            "verify_host_odom_after_depth_disable",
        ):
            with self.subTest(parameter=parameter):
                self.assertIn('"' + parameter + '"', launch_source)
                self.assertNotIn("    " + parameter + ":", params)

    def test_task_manager_uses_safe_route_transits_and_approach_names(self):
        for token in (
            "OBSTACLE_ROUTE",
            "inspection_route_steps()",
            '"grab_area_approach"',
            'f"placement_{current_zone}_approach"',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.source)

    def test_phase113_stops_after_inspection_and_rejects_placeholders(self):
        for token in (
            'declare_parameter("finish_after_inspection", False)',
            'declare_parameter("allow_placeholder_manipulation", False)',
            "if self._inspection_only or self._finish_after_inspection:",
            "elif not self._allow_placeholder_manipulation:",
            'self._abort("mechanical arm feedback is not implemented")',
            'declare_parameter("pass_obstacle_timeout_sec", 120.0)',
            'declare_parameter("inspection_timeout_sec", 300.0)',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.source)

    def test_slam_tracking_and_odom_readiness_are_separate(self):
        self.assertIn("self._slam_tracking_ok", self.source)
        self.assertIn('"slam_tracking_ok": self._slam_tracking_ok', self.source)
        self.assertIn('"odom_ok": (', self.source)
        odom_block = self.source.split("def _on_odom", 1)[1].split(
            "# ═══════════════════════════════════════════════════════════", 1
        )[0]
        self.assertNotIn("_slam_tracking_ok", odom_block)


if __name__ == "__main__":
    unittest.main()
