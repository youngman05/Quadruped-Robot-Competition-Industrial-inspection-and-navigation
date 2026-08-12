import importlib.util
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = REPO_ROOT / "scripts" / "cone_scan_l2_l3_probe.py"
SENDER_PATH = REPO_ROOT / "scripts" / "cone_scan_synthetic_sender.py"
GATE_PATH = REPO_ROOT / "src" / "nodes" / "navigation" / "cone_scan_safety_gate.py"
EXPORTER_PATH = REPO_ROOT / "scripts" / "cone_scan_udp_exporter.py"
BRIDGE_PATH = REPO_ROOT / "src" / "nodes" / "navigation" / "cone_scan_udp_bridge.py"
RUNBOOK_PATH = REPO_ROOT / "docs" / "cone_avoidance_l2_l3_runbook_zh.md"


def load_probe():
    spec = importlib.util.spec_from_file_location("cone_scan_l2_l3_probe", PROBE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_sender():
    spec = importlib.util.spec_from_file_location("cone_scan_synthetic_sender", SENDER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConeL2L3ContractTests(unittest.TestCase):
    def test_probe_defaults_are_loopback_test_only_and_explicitly_confirmed(self):
        probe = load_probe()
        args = SimpleNamespace(
            host="127.0.0.1",
            port=19012,
            ros_domain_id=93,
            confirm_isolated_no_actuator=True,
        )
        probe.validate_isolation(args)
        self.assertNotEqual(probe.DEFAULT_PORT, probe.PRODUCTION_PORT)
        self.assertTrue(all(topic.startswith("/cone_l3/") for topic in probe.TOPICS.values()))
        self.assertNotEqual(probe.TOPICS["cmd_out"], "/cmd_vel")
        args.confirm_isolated_no_actuator = False
        with self.assertRaisesRegex(probe.AcceptanceFailure, "confirm"):
            probe.validate_isolation(args)

    def test_probe_rejects_non_loopback_and_production_port(self):
        probe = load_probe()
        for host, port, domain_id in (
            ("192.168.1.10", 19012, 93),
            ("::1", 19012, 93),
            ("127.0.0.1", 19002, 93),
            ("127.0.0.1", 19012, 0),
        ):
            args = SimpleNamespace(
                host=host,
                port=port,
                ros_domain_id=domain_id,
                confirm_isolated_no_actuator=True,
            )
            with self.assertRaises(probe.AcceptanceFailure):
                probe.validate_isolation(args)

    def test_probe_covers_required_runtime_faults_and_machine_readable_output(self):
        source = PROBE_PATH.read_text(encoding="utf-8")
        for token in (
            '"three_frame_warmup"',
            '"healthy_clear_scan"',
            '"isolated-point"',
            '"short-run"',
            '"unhealthy-depth"',
            '"stale"',
            '"future"',
            '"bad-crc"',
            '"sequence-regression"',
            '"latest_only_backlog"',
            '"stream_restart_warmup"',
            '"silence_deadline"',
            "atomic_write_json(output_path, evidence)",
            '"verification_level": "L3"',
            'counts["cmd_out"]["subscribers"] != 1',
        ):
            self.assertIn(token, source)

    def test_probe_starts_installed_bridge_and_gate_with_isolated_parameters(self):
        probe = load_probe()
        command = probe.process_command(
            "ros2",
            "cone_scan_udp_bridge",
            {"port": 19012, "scan_topic": "/cone_l3/scan"},
        )
        self.assertEqual(command[:4], ["ros2", "run", probe.PACKAGE, "cone_scan_udp_bridge"])
        self.assertIn("port:=19012", command)
        self.assertIn("scan_topic:=/cone_l3/scan", command)

    def test_gate_has_deadline_margin_and_three_frame_warmup(self):
        source = GATE_PATH.read_text(encoding="utf-8")
        self.assertIn('declare_parameter("health_timeout_sec", 0.20)', source)
        self.assertIn('declare_parameter("required_consecutive_frames", 3)', source)
        self.assertIn('declare_parameter("output_rate_hz", 40.0)', source)

    def test_clear_scene_semantics_are_used_on_both_sides(self):
        exporter = EXPORTER_PATH.read_text(encoding="utf-8")
        bridge = BRIDGE_PATH.read_text(encoding="utf-8")
        self.assertIn("scan_observation_is_healthy", exporter)
        self.assertIn("scan_observation_is_healthy", bridge)
        self.assertNotIn('self._reject("scan has no contiguous obstacle returns"', bridge)

    def test_sender_defaults_to_nonproduction_port_and_all_scenarios(self):
        sender = load_sender()
        args = sender.parse_args([])
        self.assertEqual(args.port, 19012)
        self.assertNotEqual(args.port, sender.PRODUCTION_PORT)
        sender.validate_target(args)
        source = SENDER_PATH.read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--port", type=int, default=DEFAULT_PORT)', source)
        self.assertIn('choices=SCENARIOS', source)

    def test_sender_rejects_nonloopback_ipv6_and_production_port(self):
        sender = load_sender()
        for host, port in (
            ("192.168.1.10", 19012),
            ("::1", 19012),
            ("127.0.0.1", 19002),
        ):
            with self.assertRaises(SystemExit):
                sender.validate_target(SimpleNamespace(host=host, port=port))

    def test_failed_process_start_closes_its_log(self):
        probe = load_probe()
        handle = mock.MagicMock()
        with mock.patch.object(probe.Path, "open", return_value=handle), mock.patch.object(
            probe.subprocess, "Popen", side_effect=OSError("cannot start")
        ):
            with self.assertRaisesRegex(OSError, "cannot start"):
                probe.start_process(["ros2", "run"], Path("bridge.log"))
        handle.close.assert_called_once_with()

    def test_failed_step_is_preserved_in_machine_readable_evidence(self):
        probe = load_probe()
        runner = object.__new__(probe.AcceptanceRunner)
        runner.steps = []

        def fail():
            raise probe.AcceptanceFailure("expected failure")

        with self.assertRaisesRegex(probe.AcceptanceFailure, "expected failure"):
            runner.run_step("failing_step", fail)
        self.assertEqual(runner.steps[0]["name"], "failing_step")
        self.assertFalse(runner.steps[0]["passed"])
        self.assertIn("AcceptanceFailure", runner.steps[0]["error"])

    def test_probe_cleanup_escalates_the_whole_process_group(self):
        source = PROBE_PATH.read_text(encoding="utf-8")
        self.assertIn("start_new_session=(os.name != \"nt\")", source)
        self.assertIn("os.killpg(process.pid, signum)", source)
        self.assertIn('signal_process_group(process, signal.SIGTERM)', source)
        self.assertIn('getattr(signal, "SIGKILL", 9)', source)

    def test_probe_forces_localhost_only_nonproduction_ros_domain(self):
        probe = load_probe()
        args = probe.parse_args(["--confirm-isolated-no-actuator"])
        self.assertEqual(args.ros_domain_id, 93)
        self.assertNotEqual(args.ros_domain_id, probe.PRODUCTION_ROS_DOMAIN_ID)
        source = PROBE_PATH.read_text(encoding="utf-8")
        self.assertIn('os.environ["ROS_LOCALHOST_ONLY"] = "1"', source)
        self.assertIn('os.environ["ROS_DOMAIN_ID"] = str(int(args.ros_domain_id))', source)

    def test_probe_rejects_forced_or_crashed_cleanup(self):
        probe = load_probe()
        self.assertEqual(probe.GRACEFUL_EXIT_CODES, (0, -2, 130))
        source = PROBE_PATH.read_text(encoding="utf-8")
        self.assertIn('evidence["cleanup_error"]', source)
        self.assertIn('evidence["passed"] = False', source)

    def test_runbook_covers_the_complete_no_actuator_acceptance_path(self):
        source = RUNBOOK_PATH.read_text(encoding="utf-8")
        for token in (
            "configure-only",
            "NonPersistentVoxelLayer",
            "ROS_DOMAIN_ID=93",
            "--confirm-isolated-no-actuator",
            "three_frame_warmup",
            "/cone_l3/cmd_out",
            "ros2 topic hz /cone_obstacle/scan",
            "/local_costmap/costmap_raw",
            "/global_costmap/costmap_raw",
            "首次 local 标记",
            "tegrastats",
            "250 ms",
            "Go/No-Go",
        ):
            self.assertIn(token, source)

    def test_runbook_production_start_is_no_actuator_and_no_goal(self):
        source = RUNBOOK_PATH.read_text(encoding="utf-8")
        command_lines = [
            line.strip()
            for line in source.splitlines()
            if line.strip().startswith("bash scripts/start_competition.sh")
        ]
        self.assertIn(
            "bash scripts/start_competition.sh --cone-avoidance", command_lines
        )
        self.assertNotIn("--dog", "\n".join(command_lines))
        self.assertNotIn("--cmd-vel-bridge", "\n".join(command_lines))
        self.assertIn("不调用 `/navigate_to_pose`", source)


if __name__ == "__main__":
    unittest.main()
