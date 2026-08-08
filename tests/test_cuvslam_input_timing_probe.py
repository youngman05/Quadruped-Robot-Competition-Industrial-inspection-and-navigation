import importlib.util
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "cuvslam_input_timing_probe.py"
RAW_SCRIPT_PATH = REPO_ROOT / "scripts" / "camera" / "realsense_imu_timing_probe.py"


def load_script_module():
    spec = importlib.util.spec_from_file_location("cuvslam_input_timing_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_raw_script_module():
    spec = importlib.util.spec_from_file_location(
        "realsense_imu_timing_probe", RAW_SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CuvslamInputTimingProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_script_module()
        cls.raw_module = load_raw_script_module()

    def test_stream_summary_detects_clustered_gap(self):
        stamps = [0.0, 1.0 / 60.0, 2.0 / 60.0, 5.0 / 60.0]
        summary = self.module.summarize_stream(stamps, stamps, 60.0)

        self.assertEqual(summary["gap_over_2_5x_count"], 1)
        self.assertEqual(summary["estimated_missing_samples"], 2)
        self.assertEqual(summary["status"], "clustered_gaps")

    def test_stereo_sync_reports_exact_pairing(self):
        stamps = [1.0, 1.016, 1.033]
        summary = self.module.summarize_stereo_sync(stamps, stamps)

        self.assertEqual(summary["within_0_5ms_ratio"], 1.0)
        self.assertEqual(summary["nearest_delta_ms"]["max"], 0.0)

    def test_imu_samples_are_counted_between_image_frames(self):
        images = [0.0, 0.02, 0.04]
        imu = [0.005, 0.010, 0.015, 0.025, 0.030, 0.035]
        summary = self.module.summarize_imu_per_frame(images, imu)

        self.assertEqual(summary["frame_intervals"], 2)
        self.assertEqual(summary["samples_per_frame"]["median"], 3.0)
        self.assertEqual(summary["zero_sample_intervals"], 0)

    def test_raw_probe_discards_startup_timestamp_domain_reset(self):
        stream = {
            "source": [0.0, 1_786_000_000.0, 1_786_000_000.005],
            "arrival": [1.0, 1.005, 1.010],
            "frame_numbers": [1, 2, 3],
        }

        cleaned, resets, discarded = self.raw_module.trim_startup_timestamp_resets(
            stream
        )

        self.assertEqual(resets, 1)
        self.assertEqual(discarded, 1)
        self.assertEqual(cleaned["frame_numbers"], [2, 3])


if __name__ == "__main__":
    unittest.main()
