import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "cuvslam_get_odometry_once.py"
RUNBOOK_PATH = REPO_ROOT / "docs" / "cuvslam_mapping_runbook_zh.md"


def load_script_module():
    spec = importlib.util.spec_from_file_location(
        "cuvslam_get_odometry_once", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_odometry(x, y, yaw, stamp_sec=12, stamp_nanosec=500000000):
    return SimpleNamespace(
        header=SimpleNamespace(
            frame_id="odom",
            stamp=SimpleNamespace(sec=stamp_sec, nanosec=stamp_nanosec),
        ),
        child_frame_id="base_link",
        pose=SimpleNamespace(
            pose=SimpleNamespace(
                position=SimpleNamespace(x=x, y=y, z=0.0),
                orientation=SimpleNamespace(
                    x=0.0,
                    y=0.0,
                    z=math.sin(yaw / 2.0),
                    w=math.cos(yaw / 2.0),
                ),
            )
        ),
    )


class CuvslamGetOdometryOnceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_script_module()

    def test_converts_odometry_to_structured_document(self):
        document = self.module.odometry_to_document(
            make_odometry(1.25, -0.5, math.pi / 2.0),
            "/visual_slam/tracking/odometry",
            captured_at_unix=42.0,
        )

        self.assertEqual(document["frame_id"], "odom")
        self.assertEqual(document["child_frame_id"], "base_link")
        self.assertAlmostEqual(document["header_stamp_sec"], 12.5)
        self.assertAlmostEqual(document["position"]["x"], 1.25)
        self.assertAlmostEqual(document["yaw_deg"], 90.0)

    def test_compares_planar_tracking_drift(self):
        topic = "/visual_slam/tracking/odometry"
        start = self.module.odometry_to_document(
            make_odometry(0.0, 0.0, math.radians(179.0), stamp_sec=10), topic
        )
        end = self.module.odometry_to_document(
            make_odometry(0.3, 0.4, math.radians(-179.0), stamp_sec=20), topic
        )

        comparison = self.module.compare_documents(start, end)

        self.assertAlmostEqual(comparison["xy_drift_m"], 0.5)
        self.assertAlmostEqual(comparison["yaw_drift_deg"], 2.0)
        self.assertAlmostEqual(comparison["elapsed_header_sec"], 10.0)

    def test_rejects_mismatched_frames(self):
        topic = "/visual_slam/tracking/odometry"
        start = self.module.odometry_to_document(make_odometry(0, 0, 0), topic)
        end = self.module.odometry_to_document(make_odometry(0, 0, 0), topic)
        end["child_frame_id"] = "camera_link"

        with self.assertRaisesRegex(ValueError, "child_frame_id"):
            self.module.compare_documents(start, end)

    def test_writes_atomic_json(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "nested" / "sample.json"
            self.module.write_json(path, {"value": 3})
            document = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(document, {"value": 3})

    def test_runbook_locks_final_acceptance_load_shedding(self):
        runbook = RUNBOOK_PATH.read_text(encoding="utf-8")
        required = (
            "CUVSLAM_CAMERA_PROFILE=640x360x30",
            "ENABLE_SLAM_VISUALIZATION=false",
            "ENABLE_LANDMARKS_VIEW=false",
            "ENABLE_OBSERVATIONS_VIEW=false",
            "ENABLE_LOOP_METRICS_RECORDER=false",
            "STARTUP_TOPIC_CHECKS=false",
            "STARTUP_RATE_PROBES=false",
            "短闭环",
            "半程路线",
            "完整比赛路线",
            "load_map_and_localize",
        )
        for value in required:
            self.assertIn(value, runbook)


if __name__ == "__main__":
    unittest.main()
