import hashlib
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_MODEL_SHA256 = "3ed76de727a87be8d64cc3b259bf2b0ec39daaaa3fac1f3f97af249824abc648"


class WHZPackageContractTests(unittest.TestCase):
    def test_formal_model_is_present_with_expected_hash(self):
        model_path = REPO_ROOT / "whz" / "assets" / "models" / "gauge_best.pt"
        digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
        self.assertEqual(digest, EXPECTED_MODEL_SHA256)

    def test_setup_installs_model_resource(self):
        setup_text = (REPO_ROOT / "whz" / "setup.py").read_text(encoding="utf-8")
        self.assertIn('"/assets/models"', setup_text)
        self.assertIn('glob("assets/models/*.pt")', setup_text)

    def test_competition_launch_uses_rtsp_whz_without_color_publisher(self):
        launch_text = (REPO_ROOT / "launch" / "competition.launch.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("color_image_pub_node", launch_text)
        self.assertNotIn('executable="color_image_publisher"', launch_text)
        self.assertIn('"rtsp_url": whz_rtsp_url', launch_text)
        self.assertIn('"model_path": whz_model_path', launch_text)
        self.assertIn('"required_frames": ParameterValue', launch_text)
        self.assertIn('condition=IfCondition(enable_whz)', launch_text)

    def test_inspection_node_declares_required_runtime_parameters(self):
        node_text = (REPO_ROOT / "whz" / "whz" / "inspection_node.py").read_text(
            encoding="utf-8"
        )
        for parameter in (
            "rtsp_url",
            "model_path",
            "device",
            "required_frames",
            "min_agree_frames",
        ):
            with self.subTest(parameter=parameter):
                self.assertIn('"%s"' % parameter, node_text)


if __name__ == "__main__":
    unittest.main()
