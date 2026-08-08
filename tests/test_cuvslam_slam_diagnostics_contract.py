from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_PATH = REPO_ROOT / "scripts" / "start_cuvslam_rviz_gui.sh"
RUNBOOK_PATH = REPO_ROOT / "docs" / "cuvslam_mapping_runbook_zh.md"


class CuvslamSlamDiagnosticsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.launcher = LAUNCHER_PATH.read_text(encoding="utf-8")
        cls.runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

    def test_diagnostics_are_disabled_by_default(self):
        self.assertIn(
            'ENABLE_SLAM_DIAGNOSTICS="${ENABLE_SLAM_DIAGNOSTICS:-false}"',
            self.launcher,
        )

    def test_generated_launch_has_all_diagnostics_parameters(self):
        for parameter in (
            "enable_slam_diagnostics",
            "slam_diagnostics_path",
            "slam_diagnostics_metrics_period_ms",
            "slam_diagnostics_graph_period_ms",
            "slam_diagnostics_max_items_count",
        ):
            self.assertIn(f"'{parameter}':", self.launcher)

    def test_output_is_fixed_under_persisted_logs_mount(self):
        expected_path = "/logs/cuvslam_slam_diagnostics.jsonl"
        self.assertIn(f"'slam_diagnostics_path': '{expected_path}'", self.launcher)
        self.assertIn(f"SLAM_DIAGNOSTICS_PATH={expected_path}", self.launcher)

    def test_runtime_config_contains_all_diagnostics_settings(self):
        for setting in (
            "ENABLE_SLAM_DIAGNOSTICS=$ENABLE_SLAM_DIAGNOSTICS",
            "SLAM_DIAGNOSTICS_PATH=/logs/cuvslam_slam_diagnostics.jsonl",
            "SLAM_DIAGNOSTICS_METRICS_PERIOD_MS=$SLAM_DIAGNOSTICS_METRICS_PERIOD_MS",
            "SLAM_DIAGNOSTICS_GRAPH_PERIOD_MS=$SLAM_DIAGNOSTICS_GRAPH_PERIOD_MS",
            "SLAM_DIAGNOSTICS_MAX_ITEMS_COUNT=$SLAM_DIAGNOSTICS_MAX_ITEMS_COUNT",
        ):
            self.assertIn(setting, self.launcher)

    def test_integer_parameters_are_range_checked_before_launch_generation(self):
        launch_generation = self.launcher.index("write_cuvslam_launch()")
        for validation in (
            '"SLAM_DIAGNOSTICS_METRICS_PERIOD_MS" '
            '"$SLAM_DIAGNOSTICS_METRICS_PERIOD_MS" 10 1000',
            '"SLAM_DIAGNOSTICS_GRAPH_PERIOD_MS" '
            '"$SLAM_DIAGNOSTICS_GRAPH_PERIOD_MS" 1000 60000',
            '"SLAM_DIAGNOSTICS_MAX_ITEMS_COUNT" '
            '"$SLAM_DIAGNOSTICS_MAX_ITEMS_COUNT" 1 65536',
        ):
            self.assertIn(validation, self.launcher)
            self.assertLess(self.launcher.index(validation), launch_generation)
        self.assertIn(
            "SLAM_DIAGNOSTICS_GRAPH_PERIOD_MS < "
            "SLAM_DIAGNOSTICS_METRICS_PERIOD_MS",
            self.launcher,
        )

    def test_runbook_allows_only_stationary_ab(self):
        for requirement in (
            "第三次短环、半程和完整路线继续冻结",
            "AB_MODE=A",
            "DIAGNOSTICS_ENABLED=false",
            "ENABLE_SLAM_DIAGNOSTICS=\"$DIAGNOSTICS_ENABLED\"",
            "ENABLE_SLAM_VISUALIZATION=false",
            "ENABLE_LANDMARKS_VIEW=false",
            "ENABLE_OBSERVATIONS_VIEW=false",
            "ENABLE_LOOP_METRICS_RECORDER=false",
            "STARTUP_TOPIC_CHECKS=false",
            "STARTUP_RATE_PROBES=false",
            "--skip-input-test --no-rviz",
        ):
            self.assertIn(requirement, self.runbook)

    def test_runbook_documents_diagnostics_evidence_contract(self):
        for requirement in (
            "全图读取硬上限为 `1 Hz`",
            "每个独立 metrics 事件保留两次",
            "`possibly_truncated=true`",
            "`edge_diff_valid=false`",
            "不得更新上一份可靠 edge baseline",
        ):
            self.assertIn(requirement, self.runbook)


if __name__ == "__main__":
    unittest.main()
