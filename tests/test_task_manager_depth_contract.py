import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TASK_MANAGER = REPO_ROOT / "src" / "nodes" / "decision" / "task_manager.py"
COMPETITION_LAUNCH = REPO_ROOT / "launch" / "competition.launch.py"


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
            "self._host_odom_ready_after_depth_transition(mode)",
            'declare_parameter("verify_host_odom_after_depth_disable", True)',
            'declare_parameter("depth_transition_settle_duration_sec", 1.0)',
            "self._depth_transition_stationary.update(",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.source)
        self.assertNotIn("spin_until_future_complete", self.source)

    def test_phase2_map_switch_is_default_off(self):
        self.assertIn('declare_parameter("enable_phase2_map_switch", False)', self.source)
        launch_source = COMPETITION_LAUNCH.read_text(encoding="utf-8")
        self.assertIn('"enable_phase2_map_switch": False', launch_source)

    def test_task_manager_uses_safe_route_transits_and_approach_names(self):
        for token in (
            "OBSTACLE_ROUTE",
            "inspection_route_steps()",
            '"grab_area_approach"',
            'f"placement_{current_zone}_approach"',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.source)


if __name__ == "__main__":
    unittest.main()
