import ast
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
ARM_MOTION_NODE = (
    ROOT / "arm_new" / "arm_new_ros" / "arm_new_ros" / "arm_motion_node.py"
).read_text(encoding="utf-8")
PREFLIGHT = (ROOT / "scripts" / "preflight_l6_pick_place.sh").read_text(
    encoding="utf-8"
)
NO_MOTION_START = (
    ROOT / "scripts" / "start_l6_pick_place_no_motion.sh"
).read_text(encoding="utf-8")
FORMAL_L6_TEST_START = (
    ROOT / "scripts" / "start_l6_pick_place_test_16ad08c.sh"
).read_text(encoding="utf-8")


def task_manager_method(name):
    tree = ast.parse(TASK_MANAGER)
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            source = ast.get_source_segment(TASK_MANAGER, node)
            if source is not None:
                return source
    raise AssertionError(f"TaskManager method not found: {name}")


class PickPlaceIntegrationContractTests(unittest.TestCase):
    def test_inspection_only_l6_entrypoint_is_byte_stable(self):
        digest = hashlib.sha256(
            (ROOT / "scripts" / "start_l6.sh").read_bytes()
        ).hexdigest()
        self.assertEqual(
            digest,
            "2c44515757b962e17778e5b7bdb3189b454dda32b5675c79d94dd563f10919d1",
        )

    def test_full_route_entrypoint_is_separate_and_fixed_preset_gated(self):
        source = (ROOT / "scripts" / "start_l6_pick_place.sh").read_text(
            encoding="utf-8"
        )
        for token in (
            "TASK_MANIPULATION_PARAMS_FILE:?",
            "ARM_MOTION_PARAMS_FILE:?",
            "PICK_PLACE_SOURCE_COMMIT:?",
            "ARM_MOTION_AUTHORIZED:-false",
            "full pick/place requires explicit ARM_MOTION_AUTHORIZED=true",
            "PURE_L6_START=false",
            "TASK_WAYPOINT_ROUTE=full_interleaved",
            "--pick-place-l6",
            "--dog",
            "--cmd-vel-bridge",
            "--prepare-lite3-motion",
        ):
            with self.subTest(token=token):
                self.assertIn(token, source)
        for token in (
            "APRILTAG_TAG_IDS:?",
            "APRILTAG_TAG_SIZE_M:?",
        ):
            with self.subTest(removed_wrapper_token=token):
                self.assertNotIn(token, source + PREFLIGHT)
        for token in (
            "PICK_PLACE_CALIBRATION_BUNDLE",
            "PICK_PLACE_CALIBRATION_APPROVED",
            "TASK_MANIPULATION_CALIBRATED",
            "ARM_STOP_CHAIN",
        ):
            with self.subTest(removed_token=token):
                self.assertNotIn(
                    token,
                    START + source + PREFLIGHT + CALIBRATION_GATE + LAUNCH,
                )

    def test_formal_l6_test_entrypoint_uses_its_current_worktree(self):
        for token in (
            'BASH_SOURCE[0]',
            'SCRIPT_DIR="$(cd -- "$SCRIPT_DIR"; pwd)"',
            'PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.."; pwd)"',
            'SOURCE_COMMIT="$(git rev-parse HEAD)"',
            'cd "$PROJECT_ROOT"',
            "TASK_MANIPULATION_PARAMS_FILE=/home/superwfx666/competition_configs/pick_place_competition_v1.yaml",
            "ARM_MOTION_PARAMS_FILE=/home/superwfx666/competition_configs/arm_motion_competition_v1.yaml",
            'PICK_PLACE_SOURCE_COMMIT="$SOURCE_COMMIT"',
            "IMAGE=isaac_ros_cuvslam_runtime:humble-rs-cone-pick-place",
            "PICK_PLACE_IMAGE_ID=sha256:f7384634ab69256558415a074d4ad53774f2399390ddcdc7135f2c33415fb5a0",
            "ARM_MOTION_AUTHORIZED=true",
            "PURE_L6_START=true",
            "TASK_EXPECTED_MAP_ID=competition_field_phase1",
            'TASK_WAYPOINT_FILE="$PROJECT_ROOT/configs/navigation/waypoints_real.yaml"',
            "TASK_WAYPOINT_ROUTE=full_interleaved",
            "TASK_PASS_OBSTACLE_TIMEOUT_SEC=180.0",
            "TASK_PASS_OBSTACLE_WAYPOINT_TIMEOUT_SEC=120.0",
            "TASK_INSPECTION_TIMEOUT_SEC=300.0",
            "exec env",
            "bash scripts/start_competition.sh",
            "--pick-place-l6",
            "--dog",
            "--cmd-vel-bridge",
            "--prepare-lite3-motion",
        ):
            with self.subTest(token=token):
                self.assertIn(token, FORMAL_L6_TEST_START)

        for stale_pin in (
            "/home/superwfx666/worktrees/quadruped-pick-place-formal-16ad08c",
            "16ad08c6fc4b2368535919b88eed08af2e2f7590",
        ):
            with self.subTest(stale_pin=stale_pin):
                self.assertNotIn(stale_pin, FORMAL_L6_TEST_START)

        for forbidden in (
            "nohup",
            " &",
            "while ",
            "for ",
            "sleep ",
            "timeout ",
            "ros2 ",
            "docker ",
            "pgrep ",
            "wait ",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, FORMAL_L6_TEST_START)

        self.assertEqual(FORMAL_L6_TEST_START.count("exec env"), 1)
        self.assertTrue(
            FORMAL_L6_TEST_START.rstrip().endswith(
                "--prepare-lite3-motion"
            )
        )

    def test_pick_place_preflight_finishes_before_runtime_cleanup(self):
        gate = START.index("pick/place fixed preset gate failed")
        image = START.index("unified pick/place image runtime verification failed")
        preflight_exit = START.index("if $PICK_PLACE_PREFLIGHT_ONLY; then")
        cleanup = START.index("echo '[0/6] 清理旧进程...'")
        self.assertLess(gate, cleanup)
        self.assertLess(image, cleanup)
        self.assertLess(preflight_exit, cleanup)
        for token in (
            "--pick-place-preflight-only",
            "task and arm presets must both be",
            "arm preset YAML must keep enable_motion false",
            "arm parameter {} must be true",
            "arm_service_timeout_sec must be >= max_arm_sequence_sec",
            "3ed76de727a87be8d64cc3b259bf2b0ec39daaaa3fac1f3f97af249824abc648",
        ):
            self.assertIn(token, START + CALIBRATION_GATE)
        self.assertIn("scripts/pick_place_calibration_gate.py", START)
        for token in (
            "PICK_PLACE_SOURCE_COMMIT:?",
            "PICK_PLACE_IMAGE_ID",
            "ARM_MOTION_AUTHORIZED=false",
            "--pick-place-preflight-only",
            "TASK_WAYPOINT_ROUTE=full_interleaved",
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
            '[ "$TASK_ENABLE_PICK_I2_ALIGNMENT" = "true" ] && ENABLE_APRILTAG_BRIDGE=true',
            START,
        )
        self.assertIn(
            'if [ "$TASK_ENABLE_PLACE_VISION_ALIGNMENT" = "true" ]; then',
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
            '"arm_max_sequence_sec": ParameterValue(',
            "enable_manipulation, \"' == 'true')\"",
        ):
            with self.subTest(token=token):
                self.assertIn(token, LAUNCH)

    def test_optional_alignment_falls_back_to_fixed_competition_presets(self):
        find_red_bar = task_manager_method("_tick_find_red_bar")
        place = task_manager_method("_tick_place_to_abnormal_zone")
        depth_fallback = task_manager_method("_disable_optional_alignment")
        for token in (
            "if not self._enable_pick_i2_alignment:",
            "使用抓取区固定偏移继续比赛",
            "I2精对齐失败，降级到固定抓取预设",
        ):
            self.assertIn(token, find_red_bar)
        for token in (
            "if not self._enable_place_vision_alignment:",
            "使用J0固定放置预设",
            "视觉精对齐失败，降级到J0固定放置",
        ):
            self.assertIn(token, place)
        self.assertIn("fail_soft=True", find_red_bar)
        self.assertIn("self._enable_pick_i2_alignment = False", depth_fallback)
        self.assertIn("self._enable_place_vision_alignment = False", depth_fallback)

    def test_fourth_inspection_freezes_exactly_two_distinct_tasks(self):
        inspection = task_manager_method("_tick_inspect_gauges")
        store = task_manager_method("_store_inspection_reading")
        for token in (
            "freeze_two_zone_tasks(",
            "self._abnormal_zone_fallback_order",
            "self._task_queue_frozen = True",
            "self._abnormal_zones[0]",
            "self._abnormal_zones[1]",
        ):
            self.assertIn(token, inspection)
        self.assertIn("reading.agree_frames", store)
        self.assertIn("reading.total_frames", store)
        self.assertIn('"task_queue_frozen": self._task_queue_frozen', TASK_MANAGER)

    def test_inspection_perception_failures_are_uncertain_and_continue(self):
        inspection = task_manager_method("_tick_inspect_gauges")
        uncertain = task_manager_method("_complete_uncertain_inspection")
        for token in (
            'self._complete_uncertain_inspection("service_unavailable")',
            '"service_timeout=%.1fs"',
            '"service_future_error: %s"',
            'self._complete_uncertain_inspection(str(exc))',
        ):
            self.assertIn(token, inspection)
        self.assertIn("inspection_uncertain(reason)", uncertain)
        self.assertIn("self._inspection_route_index += 1", uncertain)

    def test_two_rounds_exclude_the_first_selected_pickup_tag(self):
        find_red_bar = task_manager_method("_tick_find_red_bar")
        self.assertIn("excluded_tag_ids=tuple(self._used_pick_tag_ids)", find_red_bar)
        self.assertIn("self._used_pick_tag_ids.append(selected_tag_id)", find_red_bar)
        self.assertIn('"used_pick_tag_ids": self._used_pick_tag_ids', TASK_MANAGER)

    def test_manipulation_navigation_exhaustion_skips_only_that_task(self):
        find_red_bar = task_manager_method("_tick_find_red_bar")
        place = task_manager_method("_tick_place_to_abnormal_zone")
        retry = task_manager_method("_retry_navigation")
        self.assertIn("self._retry_navigation(retry_key, \"抓取区\")", find_red_bar)
        self.assertIn("place skipped because grab navigation failed", find_red_bar)
        self.assertIn("self._retry_navigation(", place)
        self.assertIn("place skipped after navigation failure", place)
        self.assertNotIn("self._abort(", find_red_bar)
        self.assertNotIn("self._abort(", place)
        self.assertNotIn("self._abort(", retry)
        self.assertIn(
            'TASK_MAX_NAV_RETRIES="${TASK_PICK_PLACE_MAX_NAV_RETRIES:-2}"',
            START,
        )
        self.assertIn(
            'require_exact_parameter /task_manager_node max_nav_retries "$TASK_MAX_NAV_RETRIES"',
            START,
        )

    def test_runtime_localization_and_odometry_faults_remain_hard_abort(self):
        safety = task_manager_method("_runtime_base_safety_ok")
        self.assertIn("runtime odometry became unavailable or stale", safety)
        self.assertIn("runtime visual localization reported tracking loss", safety)
        self.assertIn("self._abort(", safety)

    def test_pick_place_mode_forces_real_full_interleaved_waypoints(self):
        self.assertIn(
            'TASK_WAYPOINT_FILE="$PROJECT_ROOT/configs/navigation/waypoints_real.yaml"',
            START,
        )
        self.assertIn('TASK_WAYPOINT_ROUTE="full_interleaved"', START)
        self.assertIn("TASK_WAYPOINT_ROUTE=full_interleaved", PREFLIGHT)
        self.assertIn("TASK_WAYPOINT_ROUTE=full_interleaved", NO_MOTION_START)

    def test_no_motion_start_exposes_the_graph_without_arming_motion(self):
        for token in (
            "TASK_MISSION_START_ARMED=false",
            "ARM_MOTION_AUTHORIZED=false",
            "--pick-place-no-motion-start",
        ):
            self.assertIn(token, NO_MOTION_START)
        self.assertNotIn("--dog", NO_MOTION_START)
        self.assertNotIn("--cmd-vel-bridge", NO_MOTION_START)
        self.assertNotIn("--prepare-lite3-motion", NO_MOTION_START)
        for token in (
            "PICK_PLACE_NO_MOTION_START=false",
            "if $PICK_PLACE_PREFLIGHT_ONLY || $PICK_PLACE_NO_MOTION_START; then",
            "if $CONE_TO_WHZ_L6 && ! $PICK_PLACE_NO_MOTION_START; then",
            "TaskManager 保持未 armed",
        ):
            self.assertIn(token, START)

    def test_arm_request_starts_a_max_sequence_zero_velocity_guard(self):
        start_guard = task_manager_method("_start_arm_motion_guard")
        state_tick = task_manager_method("_state_machine_tick")
        grasp = task_manager_method("_tick_grasp_bar")
        place = task_manager_method("_tick_place_to_abnormal_zone")
        self.assertIn("time.monotonic() + self._arm_max_sequence_sec", start_guard)
        self.assertIn("if not self._arm_motion_guard_elapsed():", state_tick)
        self.assertIn("self._publish_precision_zero()", state_tick)
        for method in (grasp, place):
            dispatched = method.index("call_async")
            guarded = method.index("self._start_arm_motion_guard()", dispatched)
            self.assertGreater(guarded, dispatched)
            self.assertNotIn("future.cancel()", method)

        grasp_pending = grasp.index(
            'if self._current_grasp_outcome == "sequence_completed_unverified_grasp":'
        )
        grasp_guard = grasp.index(
            "if not self._arm_motion_guard_elapsed():",
            grasp_pending,
        )
        grasp_advance = grasp.index("self._advance_to_next_phase()", grasp_pending)
        self.assertLess(grasp_guard, grasp_advance)
        grasp_response = grasp.index("if response is None or not response.success:")
        grasp_success = grasp[grasp_response:]
        self.assertIn(
            'self._current_grasp_outcome = "sequence_completed_unverified_grasp"',
            grasp_success,
        )
        self.assertNotIn("self._advance_to_next_phase()", grasp_success)

        place_pending = place.index("if self._place_sequence_completed_pending:")
        place_guard = place.index(
            "if not self._arm_motion_guard_elapsed():",
            place_pending,
        )
        place_complete = place.index("self._complete_place_attempt", place_pending)
        self.assertLess(place_guard, place_complete)
        place_response = place.index("if response is None or not response.success:")
        place_success = place[place_response:]
        self.assertIn("self._place_sequence_completed_pending = True", place_success)
        self.assertNotIn("self._complete_place_attempt", place_success)

    def test_arm_failures_are_uncertain_and_continue_after_the_guard(self):
        grasp = task_manager_method("_tick_grasp_bar")
        place = task_manager_method("_tick_place_to_abnormal_zone")
        for token in (
            'self._grasp_uncertain_reason = "grasp dispatch failed: %s" % exc',
            'self._grasp_uncertain_reason = "grasp service timed out"',
            'self._grasp_uncertain_reason = "grasp service failed: %s" % exc',
            'self._grasp_uncertain_reason = "grasp rejected: %s" % message',
            'self._current_grasp_outcome = "uncertain: " + reason',
            "self._advance_to_next_phase()",
        ):
            self.assertIn(token, grasp)
        for token in (
            'self._place_uncertain_reason = "place dispatch failed: %s" % exc',
            'self._place_uncertain_reason = "place service timed out"',
            'self._place_uncertain_reason = "place service failed: %s" % exc',
            'self._place_uncertain_reason = "place rejected: %s" % message',
            "self._complete_place_attempt(current_zone, uncertain_reason=reason)",
        ):
            self.assertIn(token, place)
        self.assertNotIn("self._abort(", grasp)
        self.assertNotIn("self._abort(", place)
        self.assertIn('ExecuteGraspFixed, "/arm/execute_grasp_fixed"', TASK_MANAGER)
        self.assertIn('Trigger, "/arm/execute_place_fixed"', TASK_MANAGER)

    def test_attempted_handled_counts_are_distinct_and_empty_work_finishes(self):
        place = task_manager_method("_tick_place_to_abnormal_zone")
        complete = task_manager_method("_complete_place_attempt")
        self.assertIn(
            "if self._abnormal_attempted >= len(self._abnormal_zones):",
            place,
        )
        self.assertIn("self._advance_to_next_phase()", place)
        self.assertIn("self._abnormal_attempted += 1", complete)
        handled_guard = complete.index("if not uncertain_reason:")
        handled_increment = complete.index("self._abnormal_handled += 1")
        self.assertLess(handled_guard, handled_increment)
        self.assertIn("self._manipulation_outcomes.append", complete)
        self.assertIn("self._enter_phase(Phase.FINISH)", complete)
        for token in (
            '"abnormal_attempted": self._abnormal_attempted',
            '"abnormal_handled": self._abnormal_handled',
            '"manipulation_outcomes": self._manipulation_outcomes',
        ):
            self.assertIn(token, TASK_MANAGER)

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

    def test_startup_preserves_perception_logs_before_cleanup(self):
        no_go = START.split("startup_no_go() {", 1)[1].split(
            "handle_startup_signal() {", 1
        )[0]
        self.assertIn("preserve_docker_perception_logs", no_go)
        self.assertLess(
            no_go.index("preserve_docker_perception_logs"),
            no_go.index("stop_all.sh"),
        )
        self.assertIn('for log_name in apriltag_pose yolo_3d', START)
        self.assertIn('docker cp "$container:$source_path" "$target_path"', START)
        self.assertIn('tail -80 "$target_path"', START)

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
        self.assertIn("AprilTagPoseDetector(0.1, [0, 1])", verify)
        self.assertIn("apriltag=ok", verify)
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
            detector = mock.Mock()
            stack.enter_context(
                mock.patch.dict(
                    "sys.modules",
                    {
                        "cv2": mock.Mock(aruco=object()),
                        "apriltag_pose_core": mock.Mock(
                            AprilTagPoseDetector=detector
                        ),
                    },
                )
            )
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
            detector.assert_called_once_with(0.1, [0, 1])

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
        self.assertIn("arm_preset: unconfigured", params)
        self.assertIn("max_arm_sequence_sec: 20.0", params)
        self.assertIn("transform_calibrated: false", params)
        self.assertIn("require_tf_in_preflight: false", params)
        self.assertIn("grasp_reference_configured: false", params)
        self.assertIn("place_target_configured: false", params)
        self.assertNotIn("static_transform", arm_launch)
        self.assertNotIn("frame_transforms.yaml", arm_launch)

    def test_no_motion_arm_preflight_is_plan_only(self):
        preflight = ARM_MOTION_NODE.index("def _run_preflight")
        servo_guard = ARM_MOTION_NODE.index("if self._enable_motion:", preflight)
        servo_scan = ARM_MOTION_NODE.index("executor.require_servos_online()", servo_guard)
        skipped = ARM_MOTION_NODE.index('checks["servo_scan_skipped"] = True', servo_scan)
        preflight_end = ARM_MOTION_NODE.index("def _configuration_block_reason", preflight)
        self.assertLess(preflight, servo_guard)
        self.assertLess(servo_guard, servo_scan)
        self.assertLess(servo_scan, skipped)
        self.assertLess(skipped, preflight_end)

    def test_pick_place_python_packages_declare_build_tools(self):
        arm_package = (
            ROOT / "arm_new" / "arm_new_ros" / "package.xml"
        ).read_text(encoding="utf-8")
        whz_package = (ROOT / "whz" / "package.xml").read_text(encoding="utf-8")
        self.assertIn("<buildtool_depend>ament_python</buildtool_depend>", arm_package)
        self.assertIn("<buildtool_depend>ament_python</buildtool_depend>", whz_package)


if __name__ == "__main__":
    unittest.main()
