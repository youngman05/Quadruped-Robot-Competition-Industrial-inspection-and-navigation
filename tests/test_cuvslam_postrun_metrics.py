import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "cuvslam_get_all_poses_once.py"


def load_script_module():
    spec = importlib.util.spec_from_file_location("cuvslam_get_all_poses_once", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_pose(x, y, z=0.0, index=0, frame_id="map"):
    return SimpleNamespace(
        header=SimpleNamespace(
            frame_id=frame_id,
            stamp=SimpleNamespace(sec=index, nanosec=0),
        ),
        pose=SimpleNamespace(
            position=SimpleNamespace(x=x, y=y, z=z),
            orientation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
        ),
    )


class CuvslamPostrunMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_script_module()

    def test_summarizes_complete_pose_graph_and_uses_xy_closure(self):
        poses = [
            make_pose(0.0, 0.0, index=0),
            make_pose(3.0, 4.0, z=0.2, index=1),
            make_pose(0.1, 0.0, index=2),
        ]

        summary = self.module.summarize_pose_stamped_list(poses)

        self.assertEqual(summary["poses"], 3)
        self.assertEqual(summary["frame_id"], "map")
        self.assertAlmostEqual(summary["xy_closure_error_m"], 0.1)
        self.assertAlmostEqual(summary["z_span_m"], 0.2)
        self.assertGreater(summary["xy_path_length_m"], 9.0)
        self.assertEqual(
            self.module.interpret(summary, 5.0, 0.2, 0.5),
            "good_optimized_pose_graph_return_to_start",
        )

    def test_rejects_short_or_poor_return(self):
        short = self.module.summarize_pose_stamped_list(
            [make_pose(0.0, 0.0), make_pose(0.1, 0.0, index=1)]
        )
        self.assertTrue(
            self.module.interpret(short, 5.0, 0.2, 0.5).startswith(
                "insufficient_motion"
            )
        )

        poor = self.module.summarize_pose_stamped_list(
            [
                make_pose(0.0, 0.0),
                make_pose(3.0, 4.0, index=1),
                make_pose(1.0, 0.0, index=2),
            ]
        )
        self.assertEqual(
            self.module.interpret(poor, 5.0, 0.2, 0.5),
            "poor_optimized_pose_graph_return_to_start",
        )

    def test_report_records_exactly_one_service_call(self):
        poses = [make_pose(0.0, 0.0), make_pose(0.1, 0.0, index=1)]
        summary = self.module.summarize_pose_stamped_list(poses)
        with tempfile.TemporaryDirectory() as temporary_directory:
            log_dir = Path(temporary_directory)
            self.module.write_report(log_dir, poses, 100000, summary, "test_result")
            payload = json.loads(
                (log_dir / "loop_metrics_latest.json").read_text(encoding="utf-8")
            )
            csv_lines = (log_dir / "slam_all_poses_latest.csv").read_text(
                encoding="utf-8"
            ).splitlines()

        self.assertEqual(payload["service_calls"], 1)
        self.assertEqual(payload["requested_max_count"], 100000)
        self.assertEqual(len(csv_lines), 3)

    def test_online_launcher_disables_get_all_poses_and_checks_process(self):
        launcher = (REPO_ROOT / "scripts" / "start_cuvslam_rviz_gui.sh").read_text(
            encoding="utf-8"
        )
        online_recorder = (
            REPO_ROOT / "scripts" / "cuvslam_loop_metrics_recorder.py"
        ).read_text(encoding="utf-8")

        self.assertIn("--disable-all-poses-service", launcher)
        self.assertIn("cuvslam_get_all_poses_once.py", launcher)
        self.assertIn("kill -0", launcher)
        self.assertIn('"--mount-mode"', online_recorder)
        self.assertIn('"--expected-base-frame"', online_recorder)
        self.assertNotIn("isaac_ros_visual_slam_interfaces", online_recorder)
        self.assertNotIn("create_client(", online_recorder)


if __name__ == "__main__":
    unittest.main()
