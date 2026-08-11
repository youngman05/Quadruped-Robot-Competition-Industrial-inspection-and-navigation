import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TASK_MANAGER = REPO_ROOT / "src" / "nodes" / "decision" / "task_manager.py"
SETUP = REPO_ROOT / "setup.py"
PACKAGE_XML = REPO_ROOT / "package.xml"
LEGACY_SERVER = (
    REPO_ROOT / "src" / "nodes" / "perception" / "whz_standalone_inspect.py"
)


class TaskManagerWhzContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = TASK_MANAGER.read_text(encoding="utf-8")

    def test_task_manager_uses_async_trigger_client(self):
        self.assertIn("from std_srvs.srv import Trigger", self.source)
        self.assertIn("self.create_client(Trigger, whz_service)", self.source)
        self.assertIn("self._whz_client.call_async(Trigger.Request())", self.source)
        self.assertNotIn("spin_until_future_complete", self.source)
        self.assertNotIn("self._whz_client.wait_for_service", self.source)

    def test_inline_opencv_and_relay_pipeline_are_removed(self):
        forbidden = (
            "_run_whz_inline",
            "import cv2",
            "import numpy",
            "latest_color.jpg",
            "latest_depth.raw",
            "LetterDetector",
            "detect_gauge",
        )
        for text in forbidden:
            self.assertNotIn(text, self.source)
        self.assertNotIn("_on_gauge_status", self.source)

    def test_arrival_settling_retry_and_completeness_contracts_are_present(self):
        required = (
            "InspectionStage.NAVIGATING",
            "self._nav.succeeded()",
            "InspectionStage.SETTLING",
            "self._last_odom_linear_speed",
            "max_nav_retries",
            "max_inspection_retries",
            "require_complete_abcd",
            "self._abort(workflow.abort_reason)",
        )
        for text in required:
            self.assertIn(text, self.source)

    def test_legacy_duplicate_service_entrypoint_is_retired(self):
        self.assertFalse(LEGACY_SERVER.exists())
        self.assertNotIn(
            "whz_standalone",
            SETUP.read_text(encoding="utf-8"),
        )

    def test_main_package_declares_std_srvs(self):
        self.assertIn(
            "<exec_depend>std_srvs</exec_depend>",
            PACKAGE_XML.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
