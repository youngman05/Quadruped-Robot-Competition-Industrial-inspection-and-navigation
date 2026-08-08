import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
ANALYZER_PATH = REPO_ROOT / "scripts" / "analyze_cuvslam_observer_ab.py"
CXX_PATH = (
    REPO_ROOT
    / "tools"
    / "cuvslam_lightweight_probe"
    / "src"
    / "cuvslam_lightweight_probe.cpp"
)
RUNNER_PATH = REPO_ROOT / "scripts" / "run_cuvslam_observer_ab.sh"
STACK_PATH = REPO_ROOT / "scripts" / "start_cuvslam_observer_stack.sh"
BUILD_PATH = REPO_ROOT / "scripts" / "build_cuvslam_lightweight_probe.sh"
LAUNCHER_PATH = REPO_ROOT / "scripts" / "start_cuvslam_rviz_gui.sh"


def load_analyzer():
    spec = importlib.util.spec_from_file_location("analyze_cuvslam_observer_ab", ANALYZER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def report(mode, aggregate_cpu, self_cpu=0.2, gate=True):
    observer = mode == "observer"
    return {
        "mode": mode,
        "subscribe_topics": observer,
        "duration_s": 120.0,
        "cpu": {
            "aggregate_pct": {"average": aggregate_cpu, "count": 119},
            "probe_self_pct_one_core": {"average": self_cpu},
            "scheduler_delay_ms": {"p95": 0.2, "p99": 0.4, "max": 0.8},
            "per_core_pct": {"cpu0": {"average": aggregate_cpu}},
        },
        "launch_log": {
            "frame_delta_warning_count": 0,
            "tracking_lost_count": 0,
        },
        "status_graph": {"available": False, "compatible": False},
        "measurement_gate_passed": gate if observer else None,
        "gate_checks": {"odometry_continuous": gate} if observer else {},
    }


class CuvslamObserverAbTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_analyzer()

    def test_pair_passes_strict_cpu_and_continuity_gates(self):
        result = self.module.evaluate_pair(
            report("baseline", 60.0), report("observer", 61.5, self_cpu=4.0)
        )

        self.assertTrue(result["passed"])
        self.assertAlmostEqual(result["metrics"]["aggregate_cpu_delta_points"], 1.5)

    def test_pair_fails_on_two_point_delta_or_stream_gap(self):
        result = self.module.evaluate_pair(
            report("baseline", 60.0),
            report("observer", 62.0, self_cpu=4.0, gate=False),
        )

        self.assertFalse(result["passed"])
        self.assertTrue(any("aggregate CPU delta" in item for item in result["errors"]))
        self.assertTrue(any("continuity gate" in item for item in result["errors"]))

    def test_directory_requires_all_three_pairs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index in range(1, 4):
                for label, payload in (
                    (f"A{index}", report("baseline", 50.0)),
                    (f"B{index}", report("observer", 51.0, self_cpu=2.0)),
                ):
                    directory = root / label
                    directory.mkdir()
                    (directory / "report.json").write_text(
                        json.dumps(payload), encoding="utf-8"
                    )

            result = self.module.evaluate_directory(root)

        self.assertEqual(result["decision"], "GO")
        self.assertEqual(len(result["pairs"]), 3)

    def test_tri_signal_correlation_uses_monotonic_window(self):
        base = 10_000_000_000
        correlations = self.module.tri_signal_correlations(
            {
                "anomalies": [
                    {"kind": "counter_gap", "stream": "infra1", "monotonic_ns": base},
                    {
                        "kind": "frame_delta_log",
                        "stream": "launch_log",
                        "monotonic_ns": base + 500_000_000,
                    },
                    {
                        "kind": "stream_gap",
                        "stream": "odometry",
                        "monotonic_ns": base + 700_000_000,
                    },
                ]
            }
        )

        self.assertEqual(len(correlations), 1)
        self.assertTrue(correlations[0]["all_three_in_window"])

    def test_cpp_probe_has_no_large_message_subscriptions(self):
        source = CXX_PATH.read_text(encoding="utf-8")

        self.assertNotIn("sensor_msgs/msg/image", source.lower())
        self.assertNotIn("camera_info", source.lower())
        self.assertNotIn("MultiThreadedExecutor", source)
        self.assertIn("SingleThreadedExecutor", source)
        self.assertIn("realsense2_camera_msgs::msg::Metadata", source)
        self.assertIn("sensor_msgs::msg::Imu", source)
        self.assertIn("nav_msgs::msg::Odometry", source)
        self.assertIn("nlohmann::json::sax_parse", source)
        self.assertNotIn("json::parse(json_data)", source)
        self.assertIn('declare_parameter<int>("qos_depth", 16)', source)
        self.assertIn('"source_ns"', source)
        self.assertIn('"monotonic_ns"', source)
        self.assertIn('"realtime_ns"', source)

    def test_shell_contract_forces_low_load_and_three_round_defaults(self):
        stack = STACK_PATH.read_text(encoding="utf-8")
        runner = RUNNER_PATH.read_text(encoding="utf-8")
        build = BUILD_PATH.read_text(encoding="utf-8")
        launcher = LAUNCHER_PATH.read_text(encoding="utf-8")

        for setting in (
            "ENABLE_SLAM_VISUALIZATION=false",
            "ENABLE_LANDMARKS_VIEW=false",
            "ENABLE_OBSERVATIONS_VIEW=false",
            "ENABLE_LOOP_METRICS_RECORDER=false",
            "STARTUP_TOPIC_CHECKS=false",
            "STARTUP_RATE_PROBES=false",
            "CUVSLAM_MOUNT_MODE=robot",
            "CUVSLAM_PROFILE=custom",
            "CUVSLAM_BASE_FRAME=base_link",
            "CUVSLAM_INPUT_BASE_FRAME=base_link",
            "CUVSLAM_INPUT_LEFT_CAMERA_FRAME=camera_infra1_frame",
            "CUVSLAM_INPUT_IMU_FRAME=camera_gyro_optical_frame",
            "CUVSLAM_CAMERA_PROFILE=640x360x30",
            "CUVSLAM_IMAGE_JITTER_THRESHOLD_MS=40.0",
            "CUVSLAM_FORCE_PLANAR_MODE=true",
            "CUVSLAM_ENABLE_IMU_FUSION=true",
        ):
            self.assertIn(setting, stack)
            self.assertIn(setting, runner)
        self.assertIn('DURATION_S="120.0"', runner)
        self.assertIn('ROUNDS="3"', runner)
        self.assertIn('export PROJECT_DIR=', stack)
        self.assertIn('run_window "A$index" false', runner)
        self.assertIn('run_window "B$index" true', runner)
        self.assertNotIn("command -v tegrastats", runner.lower())
        self.assertNotIn("tegrastats --interval", runner.lower())
        self.assertIn('runtime_config.env', launcher)
        self.assertIn("install_observer_probe", build)
        self.assertIn("install_observer_probe", runner)
        self.assertNotIn("--install-base /workspaces/isaac_ros-dev/install ", build)


if __name__ == "__main__":
    unittest.main()
