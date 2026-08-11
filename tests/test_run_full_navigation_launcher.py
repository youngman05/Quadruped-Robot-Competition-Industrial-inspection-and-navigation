import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "scripts" / "run_full_navigation.sh"
ROUTE_FILE = REPO_ROOT / "configs" / "navigation" / "waypoints_reordered_preview.yaml"


class FullNavigationLauncherContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = LAUNCHER.read_text(encoding="utf-8")

    def test_launcher_targets_the_validated_deploy(self):
        self.assertIn(
            "/home/superwfx666/quadruped-robot-competition-nav2-dwb-deploy",
            self.script,
        )
        self.assertIn("94137ea0bbc10b0e46b684fad5f9c123aced6bfc", self.script)
        self.assertIn('readonly ROUTE_NAME="full_interleaved"', self.script)

    def test_launcher_requires_the_exact_doubled_speed_overlay(self):
        expected_hashes = (
            "20b4e157c2d49ad73f7a74709913037676542ee5bcac68cb2c15290fed27df6b",
            "fe1cc4887d86ff636d698f4fffb9f37e37c1779d247fc6c8b84b32315291daa0",
            "0a70c468e6d4d5687f2bb5d13e6ab160c4099f6dd3bec08f3eead13427bcfe83",
        )
        for expected_hash in expected_hashes:
            with self.subTest(expected_hash=expected_hash):
                self.assertIn(expected_hash, self.script)
        self.assertIn("validate_speed_overlay", self.script)
        self.assertIn('"${#actual_status[@]}" -eq "${#expected_status[@]}"', self.script)

    def test_default_path_has_no_interactive_confirmation(self):
        self.assertNotRegex(self.script, r"(?m)^\s*read\s")
        self.assertNotIn("confirmation phrase", self.script.lower())
        self.assertIn('if [[ "$CHECK_ONLY" == true ]]', self.script)
        self.assertIn("run_route", self.script)

    def test_route_command_keeps_the_validated_contract(self):
        for token in (
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

    def test_exit_trap_stops_and_archives_owned_stack(self):
        self.assertIn("trap on_exit EXIT", self.script)
        self.assertIn('elif [[ "$STACK_OWNED" == true ]]', self.script)
        self.assertIn("stop_and_archive", self.script)
        self.assertIn("bash scripts/stop_all.sh", self.script)
        self.assertIn("docker stop -t 10", self.script)
        self.assertIn("evidence_sha256.txt", self.script)
        self.assertIn("! -name launcher.log", self.script)

    def test_runtime_gates_cover_start_pose_and_command_chain(self):
        for token in (
            "active [3]",
            "Action servers: 1",
            "goal_checker.xy_goal_tolerance 0.3",
            "FollowPath.xy_goal_tolerance 0.3",
            "GridBased.tolerance 0.2",
            "FollowPath.max_vel_x 0.24",
            "FollowPath.max_speed_xy 0.24",
            "FollowPath.max_vel_theta 0.3",
            "max_rotational_vel 0.3",
            "max_vx 0.24",
            "max_wz 0.3",
            "hard_max_vx 0.24",
            "hard_max_speed_xy 0.24",
            "hard_max_az 0.3",
            "oneclick_start_tf_gate",
            "/cmd_vel_nav2",
            "/cmd_vel_precision",
            "last_send=(0.000,0.000,0.000)",
            "done simple=50 complex=48 errors=0",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.script)

    def _run_embedded_nav2_topic_validator(self, topic_text):
        match = re.search(
            r"validate_nav2_input_topic\(\) \{.*?<<'PY_NAV2_TOPIC'\n(.*?)\nPY_NAV2_TOPIC",
            self.script,
            re.S,
        )
        self.assertIsNotNone(match)
        with tempfile.TemporaryDirectory() as directory:
            topic_path = Path(directory) / "cmd_vel_nav2_topic.txt"
            topic_path.write_text(topic_text, encoding="utf-8")
            return subprocess.run(
                [sys.executable, "-c", match.group(1), str(topic_path)],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_nav2_input_gate_accepts_foxy_recovery_publishers(self):
        topic_text = """Type: geometry_msgs/msg/Twist
Publisher count: 4
Node name: controller_server
Endpoint type: PUBLISHER
Node name: recoveries_server
Endpoint type: PUBLISHER
Node name: recoveries_server
Endpoint type: PUBLISHER
Node name: recoveries_server
Endpoint type: PUBLISHER
Subscription count: 1
Node name: cmd_vel_arbiter
Endpoint type: SUBSCRIPTION
"""
        result = self._run_embedded_nav2_topic_validator(topic_text)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_nav2_input_gate_rejects_unknown_publisher(self):
        topic_text = """Type: geometry_msgs/msg/Twist
Publisher count: 2
Node name: controller_server
Endpoint type: PUBLISHER
Node name: rogue_velocity_node
Endpoint type: PUBLISHER
Subscription count: 1
Node name: cmd_vel_arbiter
Endpoint type: SUBSCRIPTION
"""
        result = self._run_embedded_nav2_topic_validator(topic_text)
        self.assertEqual(1, result.returncode)
        self.assertIn("rogue_velocity_node", result.stderr)

    def test_route_file_has_the_expected_14_steps(self):
        document = json.loads(ROUTE_FILE.read_text(encoding="utf-8"))
        route = document["routes"]["full_interleaved"]
        self.assertEqual(14, len(route))
        self.assertEqual("lower_corner_clear", route[7])
        self.assertEqual("placement_C_approach", route[12])

    def test_static_contract_uses_two_point_three_goal_tolerances(self):
        params = (REPO_ROOT / "configs" / "navigation" / "nav2_params.yaml").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            2,
            len(re.findall(r"^\s*xy_goal_tolerance:\s*0\.30\s*$", params, re.M)),
        )

    def test_static_contract_uses_doubled_main_speed_limits(self):
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
