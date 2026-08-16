import json
import math
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nodes.navigation.start_prior import load_start_prior


class InitialPoseInstallContractTests(unittest.TestCase):
    def test_accepted_start_prior_matches_formal_start_pose(self):
        prior = ROOT / "configs" / "navigation" / "cuvslam_start_prior.yaml"
        x, y, yaw, source = load_start_prior(prior)

        self.assertEqual((x, y), (4.65, 0.75))
        self.assertAlmostEqual(yaw, math.pi)
        self.assertIn("ROBOT_START_POSE", source)

    def test_non_map_or_non_finite_prior_is_rejected(self):
        for document in (
            {"frame_id": "odom", "x": 4.65, "y": 0.75, "yaw": math.pi},
            {"frame_id": "map", "x": 4.65, "y": 0.75, "yaw": "NaN"},
        ):
            with self.subTest(document=document), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "prior.json"
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_start_prior(path)

    def test_installed_node_uses_package_share_not_source_tree_path(self):
        source = (
            ROOT / "src" / "nodes" / "navigation" / "initial_pose_publisher.py"
        ).read_text(encoding="utf-8")

        self.assertIn("get_package_share_directory", source)
        self.assertIn("cuvslam_start_prior.yaml", source)
        self.assertIn("from .start_prior import load_start_prior", source)
        self.assertNotIn("navi_map_data", source)
        self.assertNotIn("sys.path", source)


if __name__ == "__main__":
    unittest.main()
