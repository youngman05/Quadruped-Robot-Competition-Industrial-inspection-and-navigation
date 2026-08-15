import hashlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
START = (ROOT / "scripts" / "start_competition.sh").read_text(encoding="utf-8")
STOP = (ROOT / "scripts" / "stop_all.sh").read_text(encoding="utf-8")
LAUNCH = (ROOT / "launch" / "competition.launch.py").read_text(encoding="utf-8")
TASK_MANAGER = (ROOT / "src" / "nodes" / "decision" / "task_manager.py").read_text(
    encoding="utf-8"
)
CALIBRATION_GATE = (ROOT / "scripts" / "pick_place_calibration_gate.py").read_text(
    encoding="utf-8"
)


class PickPlaceIntegrationContractTests(unittest.TestCase):
    def test_inspection_only_l6_entrypoint_is_byte_stable(self):
        digest = hashlib.sha256(
            (ROOT / "scripts" / "start_l6.sh").read_bytes()
        ).hexdigest()
        self.assertEqual(
            digest,
            "2c44515757b962e17778e5b7bdb3189b454dda32b5675c79d94dd563f10919d1",
        )

    def test_full_route_entrypoint_is_separate_and_calibration_gated(self):
        source = (ROOT / "scripts" / "start_l6_pick_place.sh").read_text(
            encoding="utf-8"
        )
        for token in (
            "TASK_MANIPULATION_PARAMS_FILE:?",
            "ARM_MOTION_PARAMS_FILE:?",
            "APRILTAG_TAG_IDS:?",
            "APRILTAG_TAG_SIZE_M:?",
            "PICK_PLACE_CALIBRATION_APPROVED",
            "TASK_MANIPULATION_CALIBRATED",
            "PURE_L6_START=false",
            "--pick-place-l6",
            "--dog",
            "--cmd-vel-bridge",
            "--prepare-lite3-motion",
        ):
            with self.subTest(token=token):
                self.assertIn(token, source)

    def test_pick_place_preflight_finishes_before_runtime_cleanup(self):
        gate = START.index("pick/place calibration parameter gate failed")
        image = START.index("unified pick/place image runtime verification failed")
        cleanup = START.index("echo '[0/6] 清理旧进程...'")
        self.assertLess(gate, cleanup)
        self.assertLess(image, cleanup)
        for token in (
            "I2 targets are duplicated",
            "place_target_distance_m is not calibrated",
            "arm parameter {key} must be true",
            "3ed76de727a87be8d64cc3b259bf2b0ec39daaaa3fac1f3f97af249824abc648",
        ):
            self.assertIn(token, START + CALIBRATION_GATE)
        self.assertIn("scripts/pick_place_calibration_gate.py", START)

    def test_single_container_perception_and_unique_udp_ports(self):
        for token in (
            "requires exactly one running cuVSLAM container",
            "isaac_ros_cuvslam_runtime:humble-rs-cone-pick-place",
            "[d]455_apriltag_pose_node.py",
            "[d]455_yolo_3d_node.py",
            'snapshot_value "apriltag_udp_port" "19003"',
            'snapshot_value "yolo_udp_port" "19004"',
        ):
            self.assertIn(token, START)
        self.assertNotIn("docker run.*realsense", START)
        self.assertIn(
            "if $PICK_PLACE_L6; then\n    ENABLE_CAMERA_RELAY=true",
            START,
        )

    def test_pick_place_writes_canonical_depth_but_old_l6_keeps_no_write(self):
        self.assertIn(
            'if $PICK_PLACE_L6; then\n            DEPTH_RELAY_EXTRA_ARGS="--manage-cone-pipeline-parameters"',
            START,
        )
        self.assertIn(
            'DEPTH_RELAY_EXTRA_ARGS="--no-write-frames --manage-cone-pipeline-parameters"',
            START,
        )

    def test_launch_wires_bridges_arm_and_manipulation_only_by_flags(self):
        for token in (
            '"enable_apriltag_bridge", default="false"',
            '"enable_yolo_udp_bridge", default="false"',
            '"enable_arm_motion", default="false"',
            '"enable_manipulation", default="false"',
            'executable="apriltag_udp_bridge"',
            'executable="yolo_udp_bridge"',
            'package="arm_new_ros"',
            '"manipulation_frames_dir": depth_frames_dir',
            "enable_manipulation, \"' == 'true')\"",
        ):
            with self.subTest(token=token):
                self.assertIn(token, LAUNCH)

    def test_arm_feedback_is_fail_closed_and_count_advances_after_place_success(self):
        grasp_success = TASK_MANAGER.index("if response is None or not response.success:")
        grasp_advance = TASK_MANAGER.index("self._advance_to_next_phase()", grasp_success)
        place_success = TASK_MANAGER.index(
            "if response is None or not response.success:", grasp_advance
        )
        handled = TASK_MANAGER.index("self._abnormal_handled += 1", place_success)
        self.assertLess(grasp_success, grasp_advance)
        self.assertLess(place_success, handled)
        self.assertIn('ExecuteGraspFixed, "/arm/execute_grasp_fixed"', TASK_MANAGER)
        self.assertIn('Trigger, "/arm/execute_place_fixed"', TASK_MANAGER)

    def test_manipulation_rejects_stale_cached_perception(self):
        for token in (
            'declare_parameter("manipulation_perception_timeout_sec", 0.5)',
            "_latest_yolo_received_monotonic",
            "_latest_apriltag_received_monotonic",
            "_manipulation_packet_is_fresh",
            "max_frame_age_s=self._manipulation_perception_timeout_sec",
        ):
            self.assertIn(token, TASK_MANAGER)

    def test_cleanup_covers_new_host_and_container_processes(self):
        for token in (
            "apriltag_udp_bridge yolo_udp_bridge arm_motion_node",
            "'[d]455_apriltag_pose_node.py'",
            "'[d]455_yolo_3d_node.py'",
            "/tmp/apriltag_pose.log /tmp/yolo_3d.log",
            "/tmp/apriltag_bridge_probe.txt /tmp/yolo_bridge_probe.txt",
        ):
            self.assertIn(token, STOP)

    def test_unified_image_and_exact_model_are_locked(self):
        dockerfile = (ROOT / "docker" / "Dockerfile.cuvslam-pick-place").read_text(
            encoding="utf-8"
        )
        verify = (ROOT / "docker" / "d455_perception" / "verify_runtime.py").read_text(
            encoding="utf-8"
        )
        model = ROOT / "InstanceSegmentation" / "projects" / "gauge" / "model" / "best.pt"
        self.assertIn("BASE_IMAGE=isaac_ros_cuvslam_runtime:humble-rs-cone", dockerfile)
        self.assertIn("TORCH_WHEEL_SHA256", dockerfile)
        self.assertIn("TORCHVISION_WHEEL_SHA256", dockerfile)
        self.assertIn("pip._internal.models.wheel", dockerfile)
        self.assertNotIn("-o /tmp/torch.whl", dockerfile)
        self.assertNotIn("-o /tmp/torchvision.whl", dockerfile)
        self.assertIn("YOLO_DEVICE=cpu", dockerfile)
        self.assertIn('EXPECTED_TORCH_VERSION = "2.0.0+nv23.5"', verify)
        self.assertIn('EXPECTED_TORCHVISION_VERSION = "0.15.1"', verify)
        self.assertIn('EXPECTED_ULTRALYTICS_VERSION = "8.2.103"', verify)
        self.assertIn("_check_pip_dependencies()", verify)
        self.assertIn("pipeline.warmup((360, 640, 3))", verify)
        self.assertIn("torchvision.ops.nms(boxes, scores, 0.5)", verify)
        self.assertIn("keep.device != boxes.device", verify)
        self.assertIn("PRODUCER_MODEL_ID", verify)
        self.assertIn('"class_name": "A"', verify)
        self.assertIn('"position_valid": True', verify)
        self.assertIn("validate_source_packet", verify)
        self.assertIn("synthetic_udp=ok", verify)
        self.assertIn("--runtime nvidia", START)
        self.assertEqual(
            hashlib.sha256(model.read_bytes()).hexdigest(),
            "3ed76de727a87be8d64cc3b259bf2b0ec39daaaa3fac1f3f97af249824abc648",
        )

    def test_arm_defaults_do_not_claim_unaccepted_calibration(self):
        params = (ROOT / "arm_new" / "config" / "arm_motion_params.yaml").read_text(
            encoding="utf-8"
        )
        arm_launch = (
            ROOT / "arm_new" / "arm_new_ros" / "launch" / "arm_motion.launch.py"
        ).read_text(encoding="utf-8")
        self.assertIn("enable_motion: false", params)
        self.assertIn("transform_calibrated: false", params)
        self.assertIn("grasp_reference_configured: false", params)
        self.assertIn("place_target_configured: false", params)
        self.assertNotIn("static_transform", arm_launch)
        self.assertNotIn("frame_transforms.yaml", arm_launch)

    def test_pick_place_python_packages_declare_build_tools(self):
        arm_package = (
            ROOT / "arm_new" / "arm_new_ros" / "package.xml"
        ).read_text(encoding="utf-8")
        whz_package = (ROOT / "whz" / "package.xml").read_text(encoding="utf-8")
        self.assertIn("<buildtool_depend>ament_python</buildtool_depend>", arm_package)
        self.assertIn("<buildtool_depend>ament_python</buildtool_depend>", whz_package)


if __name__ == "__main__":
    unittest.main()
