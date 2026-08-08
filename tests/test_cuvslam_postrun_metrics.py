import importlib.util
import json
import math
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


def make_pose(x, y, z=0.0, index=0, frame_id="map", yaw_deg=0.0):
    yaw = math.radians(yaw_deg)
    return SimpleNamespace(
        header=SimpleNamespace(
            frame_id=frame_id,
            stamp=SimpleNamespace(sec=index, nanosec=0),
        ),
        pose=SimpleNamespace(
            position=SimpleNamespace(x=x, y=y, z=z),
            orientation=SimpleNamespace(
                x=0.0,
                y=0.0,
                z=math.sin(yaw / 2.0),
                w=math.cos(yaw / 2.0),
            ),
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

    def test_scales_get_all_poses_stamps_and_selects_tracking_window(self):
        poses = [
            make_pose(99.0, 0.0, index=1786202),
            make_pose(0.0, 0.0, index=1786203, yaw_deg=179.0),
            make_pose(1.0, 0.0, index=1786204),
            make_pose(0.1, 0.0, index=1786205, yaw_deg=-179.0),
            make_pose(99.0, 0.0, index=1786206),
        ]

        selected = self.module.select_pose_window(
            poses,
            1786203000.0,
            1786205000.0,
            timestamp_scale=1000.0,
        )
        summary = self.module.summarize_pose_stamped_list(
            selected, timestamp_scale=1000.0
        )

        self.assertEqual(summary["poses"], 3)
        self.assertEqual(summary["first_stamp_sec"], 1786203000.0)
        self.assertEqual(summary["last_stamp_sec"], 1786205000.0)
        self.assertAlmostEqual(summary["xy_closure_error_m"], 0.1)
        self.assertAlmostEqual(summary["yaw_closure_deg"], 2.0)

    def test_report_records_timestamp_scale_and_tracking_window(self):
        poses = [make_pose(0.0, 0.0, index=1), make_pose(0.1, 0.0, index=2)]
        summary = self.module.summarize_pose_stamped_list(
            poses, timestamp_scale=1000.0
        )
        tracking_window = dict(summary)
        tracking_window.update(
            {
                "requested_start_stamp_sec": 1000.0,
                "requested_end_stamp_sec": 2000.0,
            }
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            log_dir = Path(temporary_directory)
            self.module.write_report(
                log_dir,
                poses,
                100000,
                summary,
                "test_result",
                timestamp_scale=1000.0,
                tracking_window=tracking_window,
            )
            payload = json.loads(
                (log_dir / "loop_metrics_latest.json").read_text(encoding="utf-8")
            )
            csv_header = (log_dir / "slam_all_poses_latest.csv").read_text(
                encoding="utf-8"
            ).splitlines()[0]

        self.assertEqual(payload["pose_timestamp_scale"], 1000.0)
        self.assertEqual(payload["tracking_window"]["poses"], 2)
        self.assertEqual(csv_header.split(",")[1:3], ["stamp_sec", "raw_stamp_sec"])

    def test_loads_legacy_raw_timestamp_csv(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "poses.csv"
            path.write_text(
                "index,stamp_sec,frame_id,x,y,z,qx,qy,qz,qw\n"
                "0,1786202.125000000,,1,2,3,0,0,0,1\n",
                encoding="utf-8",
            )
            poses = self.module.load_pose_csv(path)

        self.assertEqual(len(poses), 1)
        self.assertAlmostEqual(
            self.module.normalized_pose_stamp_seconds(poses[0], 1000.0),
            1786202125.0,
            places=6,
        )

    def test_online_launcher_disables_get_all_poses_and_checks_process(self):
        launcher = (REPO_ROOT / "scripts" / "start_cuvslam_rviz_gui.sh").read_text(
            encoding="utf-8"
        )
        online_recorder = (
            REPO_ROOT / "scripts" / "cuvslam_loop_metrics_recorder.py"
        ).read_text(encoding="utf-8")

        self.assertIn("--disable-all-poses-service", launcher)
        self.assertIn("--disable-path-topics", launcher)
        self.assertIn("--odom-csv-hz", launcher)
        self.assertIn("stop_ros2_cli_daemon", launcher)
        self.assertIn("ros2 daemon stop", launcher)
        self.assertIn("cuvslam_get_all_poses_once.py", launcher)
        self.assertIn("kill -0", launcher)
        self.assertIn("scripts/camera/realsense_cuvslam_input_test.py", launcher)
        self.assertIn('PYTHONPATH="$PROJECT_DIR/src', launcher)
        self.assertIn("--skip-color-depth", launcher)
        self.assertIn(
            'ENABLE_LOOP_METRICS_RECORDER="${ENABLE_LOOP_METRICS_RECORDER:-true}"',
            launcher,
        )
        self.assertIn('STARTUP_TOPIC_CHECKS="${STARTUP_TOPIC_CHECKS:-true}"', launcher)
        self.assertIn('STARTUP_RATE_PROBES="${STARTUP_RATE_PROBES:-false}"', launcher)
        self.assertIn('grep -Fx "$topic" "$LOG_DIR/topics.txt"', launcher)
        self.assertNotIn("ros2 topic list | grep -Fx '$topic'", launcher)
        self.assertIn("Skipping startup topic rate probes", launcher)
        self.assertIn('"--mount-mode"', online_recorder)
        self.assertIn('"--expected-base-frame"', online_recorder)
        self.assertIn('"--disable-path-topics"', online_recorder)
        self.assertIn('"--odom-csv-hz"', online_recorder)
        self.assertIn('"path_topics_enabled"', online_recorder)
        self.assertNotIn("isaac_ros_visual_slam_interfaces", online_recorder)
        self.assertNotIn("create_client(", online_recorder)


if __name__ == "__main__":
    unittest.main()
