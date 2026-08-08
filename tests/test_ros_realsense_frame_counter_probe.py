import importlib.util
from pathlib import Path
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ros_realsense_frame_counter_probe.py"


def load_script_module():
    spec = importlib.util.spec_from_file_location(
        "ros_realsense_frame_counter_probe", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RosRealSenseFrameCounterProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_script_module()

    def test_parse_metadata_prefers_hardware_frame_counter(self):
        parsed = self.module.parse_metadata_json(
            '{"frame_number": 77, "Frame Counter": "42", "actual_fps": 30}'
        )

        self.assertEqual(parsed["counter"], 42)
        self.assertEqual(parsed["counter_key"], "frame_counter")

    def test_parse_metadata_handles_nested_string_value(self):
        parsed = self.module.parse_metadata_json(
            '{"metadata": {"frame_counter": "frame counter: 1234"}}'
        )

        self.assertEqual(parsed["counter"], 1234)

    def test_frame_counter_gap_reports_missing_frames(self):
        summary = self.module.frame_counter_gap_events(
            [10, 11, 15], [1_000, 2_000, 6_000]
        )

        self.assertEqual(summary["missing_total"], 3)
        self.assertEqual(summary["gap_event_count"], 1)
        self.assertEqual(summary["events"][0]["before"], 11)
        self.assertEqual(summary["events"][0]["after"], 15)

    def test_frame_counter_wrap_is_continuous(self):
        summary = self.module.frame_counter_gap_events(
            [0xFFFFFFFE, 0xFFFFFFFF, 0], [1_000, 2_000, 3_000]
        )

        self.assertEqual(summary["missing_total"], 0)
        self.assertEqual(summary["nonmonotonic_count"], 0)

    def test_image_metadata_pairing_uses_exact_header_stamp(self):
        summary = self.module.summarize_image_metadata_pair(
            [100, 200, 300], [100, 300, 400]
        )

        self.assertEqual(summary["exact_stamp_matches"], 2)
        self.assertEqual(summary["image_without_metadata"], 1)
        self.assertEqual(summary["metadata_without_image"], 1)

    def test_stream_gap_event_preserves_source_and_arrival_times(self):
        events = self.module.stream_gap_events(
            [0, 5_000_000, 20_000_000],
            [1_000_000_000, 1_005_000_000, 1_021_000_000],
            expected_hz=200.0,
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["source_delta_ms"], 15.0)
        self.assertEqual(events[0]["arrival_delta_ms"], 16.0)
        self.assertEqual(events[0]["estimated_missing"], 2)

    def test_read_raw_csv_preserves_messages_and_counters(self):
        content = (
            "category,stream,source_stamp_ns,arrival_monotonic_ns,frame_counter,counter_key\n"
            "message,infra1,100,1000,,\n"
            "metadata_counter,infra1,100,1001,42,frame_counter\n"
            "metadata_counter,infra1,200,2001,,\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.csv"
            path.write_text(content, encoding="utf-8")
            streams, metadata = self.module.read_raw_csv(path)

        self.assertEqual(streams["infra1"]["source_ns"], [100])
        self.assertEqual(metadata["infra1"]["source_ns"], [100, 200])
        self.assertEqual(metadata["infra1"]["counters"], [42])
        self.assertEqual(metadata["infra1"]["counter_keys"], {"frame_counter"})


if __name__ == "__main__":
    unittest.main()
