import hashlib
import importlib.util
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock


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
PREFLIGHT = (ROOT / "scripts" / "preflight_l6_pick_place.sh").read_text(
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
            "PICK_PLACE_SOURCE_COMMIT:?",
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
        preflight_exit = START.index("if $PICK_PLACE_PREFLIGHT_ONLY; then")
        cleanup = START.index("echo '[0/6] 清理旧进程...'")
        self.assertLess(gate, cleanup)
        self.assertLess(image, cleanup)
        self.assertLess(preflight_exit, cleanup)
        for token in (
            "--pick-place-preflight-only",
            "I2 targets are duplicated",
            "place_target_distance_m is not calibrated",
            "arm parameter {key} must be true",
            "3ed76de727a87be8d64cc3b259bf2b0ec39daaaa3fac1f3f97af249824abc648",
        ):
            self.assertIn(token, START + CALIBRATION_GATE)
        self.assertIn("scripts/pick_place_calibration_gate.py", START)
        for token in (
            "PICK_PLACE_SOURCE_COMMIT:?",
            "PICK_PLACE_IMAGE_ID",
            "--pick-place-preflight-only",
        ):
            with self.subTest(preflight_token=token):
                self.assertIn(token, PREFLIGHT)

    def test_pick_place_preflight_locks_provenance_and_installed_artifacts(self):
        for token in (
            "PICK_PLACE_SOURCE_COMMIT must identify the approved formal source commit",
            'snapshot_value "formal_source_commit"',
            'snapshot_value "task_manipulation_params_sha256"',
            'snapshot_value "arm_motion_params_sha256"',
            "PICK_PLACE_IMAGE_ID must identify the accepted immutable image",
            'snapshot_value "actual_pick_place_image_id"',
            'ros2 pkg prefix arm_new_interfaces',
            'ros2 pkg prefix whz',
            "pick/place package resolved outside formal deploy install",
            'cmp -s "$PROJECT_ROOT/launch/competition.launch.py"',
            'cmp -s "$PROJECT_ROOT/configs/manipulation/pick_place.yaml"',
            'cmp -s "$PROJECT_ROOT/arm_new/config/arm_motion_params.yaml"',
            "installed Host YOLO protocol failed provenance/schema validation",
            'expected_schema = "competition-ad-yellow-red-green-v1"',
            'snapshot_value "installed_host_yolo_protocol"',
        ):
            with self.subTest(provenance_token=token):
                self.assertIn(token, START)

    def test_verifier_is_bounded_named_and_cleaned_on_every_exit_path(self):
        for token in (
            "cleanup_pick_place_verifier()",
            'docker rm -f "$PICK_PLACE_VERIFIER_CONTAINER"',
            "VERIFIER_CONTAINER_NAMES=",
            'timeout -k 10s "${PICK_PLACE_VERIFIER_TIMEOUT_SEC}s"',
            '--name "$PICK_PLACE_VERIFIER_CONTAINER"',
            'snapshot_value "pick_place_verifier_cleanup" "ok"',
        ):
            with self.subTest(verifier_token=token):
                self.assertIn(token, START)

        signal_handler = START.split("handle_startup_signal() {", 1)[1].split(
            "}\ntrap handle_startup_signal", 1
        )[0]
        self.assertIn("cleanup_pick_place_verifier", signal_handler)
        self.assertNotIn("stop_all.sh", signal_handler)

    def test_pick_place_runtime_health_checks_fail_closed_for_reused_container(self):
        reused = START.index('echo "  Docker 已在运行: $CN"')
        tracking = START.index("CUVSLAM_TRACKING_READY=false", reused)
        self.assertLess(reused, tracking)
        for token in (
            "running cuVSLAM image ID is $RUNNING_CUVSLAM_IMAGE_ID; expected $PICK_PLACE_IMAGE_ID",
            "cuVSLAM tracking odometry did not become ready",
            "Host cuVSLAM odometry bridge did not become ready",
            "Lite3 network is unreachable at 192.168.1.120",
        ):
            with self.subTest(runtime_gate=token):
                self.assertIn(token, START)

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
        build_script = (
            ROOT / "scripts" / "build_l6_pick_place_image.sh"
        ).read_text(encoding="utf-8")
        verify = (ROOT / "docker" / "d455_perception" / "verify_runtime.py").read_text(
            encoding="utf-8"
        )
        protocol = (
            ROOT / "docker" / "d455_perception" / "d455_yolo_protocol.py"
        ).read_text(encoding="utf-8")
        model = ROOT / "InstanceSegmentation" / "projects" / "gauge" / "model" / "best.pt"
        self.assertIn("BASE_IMAGE=isaac_ros_cuvslam_runtime:humble-rs-cone", dockerfile)
        self.assertIn("TORCH_WHEEL_SHA256", dockerfile)
        self.assertIn("TORCHVISION_WHEEL_SHA256", dockerfile)
        self.assertIn("pip._internal.models.wheel", dockerfile)
        self.assertNotIn("-o /tmp/torch.whl", dockerfile)
        self.assertNotIn("-o /tmp/torchvision.whl", dockerfile)
        self.assertNotIn("YOLO_DEVICE=cpu", dockerfile)
        self.assertIn("verify_runtime.py --build-stage", dockerfile)
        for cuda_package, cuda_sha256 in (
            ("libcurand-11-4_10.2.5.297-1_arm64.deb", "d4e0025162c0c68d"),
            ("libcufft-11-4_10.6.0.202-1_arm64.deb", "87f2161d58e3766f"),
            ("libcusparse-11-4_11.6.0.299-1_arm64.deb", "b1fedfac989075df"),
            ("libcusolver-11-4_11.2.0.297-1_arm64.deb", "f2e39c718793bfbe"),
            ("cuda-nvtx-11-4_11.4.300-1_arm64.deb", "921de34da9edfbea"),
        ):
            with self.subTest(cuda_package=cuda_package):
                self.assertIn(cuda_package, dockerfile)
                self.assertIn(cuda_sha256, dockerfile)
        self.assertIn("dpkg -i ./*.deb", dockerfile)
        self.assertIn('EXPECTED_TORCH_VERSION = "2.0.0+nv23.5"', verify)
        self.assertIn('EXPECTED_TORCHVISION_VERSION = "0.15.1"', verify)
        self.assertIn('EXPECTED_ULTRALYTICS_VERSION = "8.2.103"', verify)
        self.assertIn("_check_distribution_versions()", verify)
        self.assertNotIn("str(torch.__version__) != EXPECTED_TORCH_VERSION", verify)
        self.assertIn("_check_pip_dependencies()", verify)
        self.assertIn("pipeline.warmup((360, 640, 3))", verify)
        self.assertIn("torchvision.ops.nms(boxes, scores, 0.5)", verify)
        self.assertIn("keep.device != boxes.device", verify)
        self.assertIn("PRODUCER_MODEL_ID", verify)
        self.assertIn("from d455_yolo_protocol import", verify)
        self.assertNotIn("from d455_yolo_3d_node import", verify)
        self.assertIn('MODEL_ID = "gauge-ad-3ed76de7-v1"', protocol)
        self.assertIn('CLASS_SCHEMA = "competition-ad-yellow-red-green-v1"', protocol)
        self.assertIn('6: "yellow"', protocol)
        self.assertIn("pipeline.class_names != PRODUCER_CLASS_MAP", verify)
        self.assertIn('"class_name": "A"', verify)
        self.assertIn('"position_valid": True', verify)
        self.assertIn("validate_source_packet", verify)
        self.assertIn("synthetic_udp=ok", verify)
        self.assertIn("--runtime nvidia", START)
        self.assertIn("docker run --rm --runtime nvidia --network none", build_script)
        self.assertIn("-e YOLO_DEVICE=0", build_script)
        self.assertIn("-e YOLO_DEVICE=0", START)
        self.assertIn("/opt/quadruped/perception/bin/verify_runtime.py", build_script)
        self.assertNotIn("verify_runtime.py --build-stage", build_script)
        self.assertNotIn("verify_runtime.py --build-stage", START)
        self.assertEqual(
            hashlib.sha256(model.read_bytes()).hexdigest(),
            "3ed76de727a87be8d64cc3b259bf2b0ec39daaaa3fac1f3f97af249824abc648",
        )

    def test_runtime_verifier_checks_normalized_distribution_versions(self):
        verifier_path = ROOT / "docker" / "d455_perception" / "verify_runtime.py"
        spec = importlib.util.spec_from_file_location(
            "pick_place_verify_runtime", verifier_path
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)

        accepted = {
            "torch": "2.0.0+nv23.5",
            "torchvision": "0.15.1",
            "ultralytics": "8.2.103",
        }
        with mock.patch.object(
            verifier.metadata, "version", side_effect=lambda name: accepted[name]
        ):
            verifier._check_distribution_versions()

        rejected = dict(accepted, torch="2.0.0")
        with mock.patch.object(
            verifier.metadata, "version", side_effect=lambda name: rejected[name]
        ):
            with self.assertRaisesRegex(
                RuntimeError, "unexpected torch distribution version: 2.0.0"
            ):
                verifier._check_distribution_versions()

    def test_build_stage_verifier_does_not_import_inference_runtime(self):
        verifier_path = ROOT / "docker" / "d455_perception" / "verify_runtime.py"
        spec = importlib.util.spec_from_file_location(
            "pick_place_build_stage_verify_runtime", verifier_path
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)

        original_import = __import__

        def guarded_import(name, *args, **kwargs):
            if name.split(".", 1)[0] in {"torch", "torchvision", "ultralytics"}:
                raise AssertionError(f"build-stage verifier imported {name}")
            return original_import(name, *args, **kwargs)

        accepted = {
            "torch": "2.0.0+nv23.5",
            "torchvision": "0.15.1",
            "ultralytics": "8.2.103",
        }
        model_bytes = b"accepted-model"
        model_path = mock.Mock()
        model_path.read_bytes.return_value = model_bytes

        with ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(
                    verifier.subprocess,
                    "run",
                    return_value=mock.Mock(returncode=0, stdout=""),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    verifier.metadata,
                    "version",
                    side_effect=lambda name: accepted[name],
                )
            )
            stack.enter_context(mock.patch.dict("sys.modules", {"cv2": mock.Mock(aruco=object())}))
            stack.enter_context(mock.patch.object(verifier, "MODEL_PATH", model_path))
            stack.enter_context(
                mock.patch.object(
                    verifier,
                    "EXPECTED_MODEL_SHA256",
                    hashlib.sha256(model_bytes).hexdigest(),
                )
            )
            stack.enter_context(
                mock.patch("builtins.__import__", side_effect=guarded_import)
            )
            verifier.main(build_stage=True)

    def test_image_lock_covers_transitives_and_preserves_system_opencv_exception(self):
        dockerfile = (ROOT / "docker" / "Dockerfile.cuvslam-pick-place").read_text(
            encoding="utf-8"
        )
        lock_path = ROOT / "docker" / "d455_perception" / "requirements.lock"
        locked = {
            line.strip().split("==", 1)[0]
            for line in lock_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        for package in (
            "charset-normalizer",
            "contourpy",
            "cycler",
            "fonttools",
            "importlib-resources",
            "kiwisolver",
            "rospkg",
            "testresources",
        ):
            with self.subTest(package=package):
                self.assertIn(package, locked)
        self.assertNotIn("opencv-python", locked)
        self.assertIn("--no-deps -r /tmp/pick_place_requirements.lock", dockerfile)
        self.assertIn("requires opencv-python", dockerfile)

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
