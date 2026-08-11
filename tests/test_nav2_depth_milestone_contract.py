import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE = REPO_ROOT / "scripts" / "nav2_waypoint_sequence_probe.py"
FULL_LAUNCHER = REPO_ROOT / "scripts" / "run_full_navigation.sh"


class Nav2DepthMilestoneContractTests(unittest.TestCase):
    def test_probe_exposes_opt_in_depth_milestones(self):
        source = PROBE.read_text(encoding="utf-8")
        for token in (
            '"--enable-depth-milestones"',
            "MissionDepthPolicy()",
            '"mission_start"',
            '"before:%s"',
            '"after_success:%s"',
            "_acquire_precision_zero_lease()",
            "depth_transition_history",
        ):
            with self.subTest(token=token):
                self.assertIn(token, source)

    def test_validated_full_launcher_does_not_enable_unverified_depth_path(self):
        source = FULL_LAUNCHER.read_text(encoding="utf-8")
        self.assertNotIn("--enable-depth-milestones", source)
        self.assertNotIn("--depth-pipeline", source)


if __name__ == "__main__":
    unittest.main()
