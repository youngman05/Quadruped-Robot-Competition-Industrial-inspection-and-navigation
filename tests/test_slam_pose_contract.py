import importlib.util
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def load_script(name):
    path = REPO_ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Value:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeMessage:
    def __init__(self):
        self.header = Value(stamp=Value(sec=12, nanosec=345), frame_id="map")
        self.child_frame_id = "camera_link"
        self.pose = Value(pose=Value(
            position=Value(x=1.0, y=2.0, z=3.0),
            orientation=Value(x=0.0, y=0.0, z=0.0, w=1.0),
        ), covariance=[0.0] * 36)
        self.twist = Value(twist=Value(
            linear=Value(x=0.1, y=0.0, z=0.0),
            angular=Value(x=0.0, y=0.0, z=0.2),
        ), covariance=[0.0] * 36)


class SlamPoseContractTests(unittest.TestCase):
    def test_exporter_marks_source_and_output_frames_separately(self):
        exporter = load_script("cuvslam_slam_pose_udp_exporter.py")
        payload = exporter.odometry_to_payload(FakeMessage(), sequence=9, receive_time=100.0)
        self.assertEqual(payload["bridge_kind"], "slam_pose")
        self.assertEqual(payload["source_frame_id"], "map")
        self.assertEqual(payload["frame_id"], "vslam_map")
        self.assertEqual(payload["child_frame_id"], "camera_link")
        self.assertEqual(payload["receive_time"], 100.0)
        self.assertEqual(payload["seq"], 9)

    def test_bridge_source_contract_does_not_publish_tf_or_odom(self):
        source = (REPO_ROOT / "scripts" / "cuvslam_slam_pose_bridge.py").read_text(encoding="utf-8")
        self.assertIn("/cuvslam/slam_pose", source)
        self.assertIn("publishing %s without TF", source)
        self.assertNotIn("TransformBroadcaster", source)
        self.assertNotIn('create_publisher(Odometry, "/odom"', source)

    def test_cuvslam_startup_uses_existing_topic_list_helper(self):
        source = (REPO_ROOT / "scripts" / "start_cuvslam_rviz_gui.sh").read_text(encoding="utf-8")
        self.assertNotIn("topic_list_cmd", source)
        self.assertIn("run_in_container \"ros2 topic list", source)


if __name__ == "__main__":
    unittest.main()
