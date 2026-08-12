import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from scripts.cone_costmap_snapshot import atomic_write_json, summarize_costmap


class ConeCostmapSnapshotTests(unittest.TestCase):
    def test_summary_hashes_only_data_and_counts_cost_classes(self):
        message = SimpleNamespace(
            header=SimpleNamespace(
                frame_id="map",
                stamp=SimpleNamespace(sec=10, nanosec=20),
            ),
            metadata=SimpleNamespace(
                size_x=3,
                size_y=2,
                resolution=0.05,
                origin=SimpleNamespace(
                    position=SimpleNamespace(x=1.0, y=2.0, z=0.0)
                ),
            ),
            data=[0, 1, 253, 254, 255, 254],
        )
        summary = summarize_costmap(message, captured_at_ns=123)
        self.assertEqual(summary["header"]["stamp_ns"], 10_000_000_020)
        self.assertEqual(summary["data_length"], 6)
        self.assertEqual(summary["lethal_count"], 2)
        self.assertEqual(summary["inscribed_count"], 1)
        self.assertEqual(summary["unknown_count"], 1)
        self.assertEqual(summary["nonzero_known_count"], 4)
        self.assertEqual(len(summary["data_sha256"]), 64)

    def test_atomic_write_replaces_complete_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            atomic_write_json(path, {"passed": True})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"passed": True})


if __name__ == "__main__":
    unittest.main()
