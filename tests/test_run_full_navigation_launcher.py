import json
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "scripts" / "run_full_navigation.sh"
ROUTE_FILE = REPO_ROOT / "configs" / "navigation" / "waypoints_reordered_preview.yaml"


class FullNavigationLauncherContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = LAUNCHER.read_text(encoding="utf-8")

    def test_launcher_has_no_startup_preflight(self):
        forbidden = (
            "--check-only",
            "preflight",
            "validate_runtime",
            "validate_static_contract",
            "validate_speed_overlay",
            "ros2 lifecycle get",
            "ros2 action info",
            "ros2 param get",
            "ros2 topic info",
            "--describe-route",
            "git status",
            "git rev-parse",
            "lsusb",
            "ping -c",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, self.script)

    def test_default_path_has_no_interactive_confirmation(self):
        self.assertNotRegex(self.script, r"(?m)^\s*read\s")
        self.assertNotIn("confirmation phrase", self.script.lower())

    def test_launcher_starts_the_complete_stack(self):
        for token in (
            "FINAL_BRIDGE_CAMERA_WORLD_REBASE=base_start",
            "CUVSLAM_MOUNT_MODE=robot",
            "CUVSLAM_PROFILE=custom",
            "CUVSLAM_CAMERA_PROFILE=640x360x30",
            "CUVSLAM_ENABLE_LOCALIZATION_N_MAPPING=true",
            "bash scripts/start_competition.sh",
            "--dog",
            "--cmd-vel-bridge",
            "--prepare-lite3-motion",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.script)

    def test_route_command_keeps_the_validated_contract(self):
        for token in (
            'readonly ROUTE_NAME="full_interleaved"',
            "--goal-timeout 130",
            "--map-tf-timeout 30",
            "--inter-goal-pause 2",
            "--stop-on-failure",
            "navigate_w_replanning_time.xml",
            "navigate_terminal_no_replanning.xml",
            "--terminal-replan-stop-radius 0.35",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.script)

    def test_exit_trap_stops_and_archives(self):
        for token in (
            "trap on_exit EXIT",
            "stop_and_archive",
            "bash scripts/stop_all.sh",
            "docker stop -t 10",
            "route_exit_code.txt",
            "evidence_sha256.txt",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.script)

    def test_route_file_has_the_expected_14_steps(self):
        document = json.loads(ROUTE_FILE.read_text(encoding="utf-8"))
        route = document["routes"]["full_interleaved"]
        self.assertEqual(14, len(route))
        self.assertEqual("lower_corner_clear", route[7])
        self.assertEqual("placement_C_approach", route[12])

    def test_doubled_main_speed_config_remains_present(self):
        params = (REPO_ROOT / "configs" / "navigation" / "nav2_params.yaml").read_text(
            encoding="utf-8"
        )
        for parameter, value in (
            ("max_vel_x", "0.24"),
            ("max_speed_xy", "0.24"),
            ("max_vel_theta", "0.30"),
            ("max_rotational_vel", "0.30"),
        ):
            with self.subTest(parameter=parameter):
                self.assertRegex(
                    params,
                    rf"(?m)^\s*{parameter}:\s*{re.escape(value)}\s*$",
                )


if __name__ == "__main__":
    unittest.main()
