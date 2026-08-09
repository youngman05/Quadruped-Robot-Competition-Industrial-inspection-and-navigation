import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
START_SCRIPT = PROJECT_ROOT / "scripts" / "start_competition.sh"


class StartCompetitionCuvslamDefaultsTest(unittest.TestCase):
    def test_competition_defaults_match_robot_30hz_baseline(self):
        script = START_SCRIPT.read_text(encoding="utf-8")

        expected_defaults = (
            'CUVSLAM_MOUNT_MODE="${CUVSLAM_MOUNT_MODE:-robot}"',
            'CUVSLAM_PROFILE="${CUVSLAM_PROFILE:-custom}"',
            'CUVSLAM_CAMERA_PROFILE="${CUVSLAM_CAMERA_PROFILE:-640x360x30}"',
            'CUVSLAM_IMAGE_JITTER_THRESHOLD_MS="${CUVSLAM_IMAGE_JITTER_THRESHOLD_MS:-40.0}"',
            'ENABLE_SLAM_VISUALIZATION="${ENABLE_SLAM_VISUALIZATION:-false}"',
            'ENABLE_LANDMARKS_VIEW="${ENABLE_LANDMARKS_VIEW:-false}"',
            'ENABLE_OBSERVATIONS_VIEW="${ENABLE_OBSERVATIONS_VIEW:-false}"',
            'ENABLE_SLAM_DIAGNOSTICS="${ENABLE_SLAM_DIAGNOSTICS:-false}"',
            'ENABLE_LOOP_METRICS_RECORDER="${ENABLE_LOOP_METRICS_RECORDER:-false}"',
            'STARTUP_TOPIC_CHECKS="${STARTUP_TOPIC_CHECKS:-false}"',
            'STARTUP_RATE_PROBES="${STARTUP_RATE_PROBES:-false}"',
        )

        for expected in expected_defaults:
            with self.subTest(expected=expected):
                self.assertIn(expected, script)

    def test_cuvslam_defaults_are_exported_to_the_launcher(self):
        script = START_SCRIPT.read_text(encoding="utf-8")

        for name in (
            "CUVSLAM_MOUNT_MODE",
            "CUVSLAM_PROFILE",
            "CUVSLAM_CAMERA_PROFILE",
            "CUVSLAM_IMAGE_JITTER_THRESHOLD_MS",
            "ENABLE_SLAM_VISUALIZATION",
            "ENABLE_LANDMARKS_VIEW",
            "ENABLE_OBSERVATIONS_VIEW",
            "ENABLE_SLAM_DIAGNOSTICS",
            "ENABLE_LOOP_METRICS_RECORDER",
            "STARTUP_TOPIC_CHECKS",
            "STARTUP_RATE_PROBES",
        ):
            with self.subTest(name=name):
                self.assertIn(f"export {name}=", script)


if __name__ == "__main__":
    unittest.main()
