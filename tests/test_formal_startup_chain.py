import importlib.util
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
START_SCRIPT = REPO_ROOT / "scripts" / "start_competition.sh"
HEALTH_PROBE = REPO_ROOT / "scripts" / "cone_startup_health_probe.py"
BASE_PARAMS = REPO_ROOT / "configs" / "navigation" / "nav2_params.yaml"
CONE_PARAMS = REPO_ROOT / "configs" / "navigation" / "nav2_cone_obstacles.yaml"
EXPERIMENTAL_PARAMS = (
    REPO_ROOT / "configs" / "navigation" / "nav2_cone_obstacles_experimental.yaml"
)
SAFETY_GATE = (
    REPO_ROOT / "src" / "nodes" / "navigation" / "cone_scan_safety_gate.py"
)


def load_health_probe():
    spec = importlib.util.spec_from_file_location("cone_startup_health_probe", HEALTH_PROBE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FormalStartupChainContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = START_SCRIPT.read_text(encoding="utf-8")

    def test_formal_environment_source_order_is_explicit(self):
        tokens = (
            'source "$FOXY_SETUP"',
            'source "$CONE_PLUGIN_OVERLAY_SETUP"',
            'source "$NAV2_BT_OVERLAY_SETUP"',
            'source "$FORMAL_DEPLOY_SETUP"',
        )
        positions = [self.script.index(token) for token in tokens]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("CONE_PLUGIN_OVERLAY_SETUP=", self.script)
        self.assertIn("NAV2_BT_OVERLAY_SETUP=", self.script)

    def test_cone_plugin_is_required_before_runtime_mutation(self):
        plugin_guard = self.script.index(
            'pinned cone plugin overlay is missing: $CONE_PLUGIN_OVERLAY_SETUP'
        )
        cleanup = self.script.index("echo '[0/6] 清理旧进程...'")
        docker = self.script.index("echo '[1/6] Docker cuVSLAM...'")
        self.assertLess(plugin_guard, cleanup)
        self.assertLess(plugin_guard, docker)
        guarded_block = self.script.split(
            "if $ENABLE_CONE_AVOIDANCE; then", 3
        )[3].split("fi", 1)[0]
        self.assertIn("CONE_PLUGIN_OVERLAY_SETUP", guarded_block)

    def test_non_cone_mode_does_not_require_plugin_package(self):
        package_lookup = self.script.index(
            "ros2 pkg prefix cone_inflated_voxel_layer"
        )
        enclosing_guard = self.script.rfind(
            "if $ENABLE_CONE_AVOIDANCE; then", 0, package_lookup
        )
        enclosing_end = self.script.index("\nfi", package_lookup)
        self.assertLess(enclosing_guard, package_lookup)
        self.assertGreater(enclosing_end, package_lookup)

    def test_preflight_proves_packages_plugin_xml_and_library(self):
        for token in (
            "ros2 pkg prefix cone_inflated_voxel_layer",
            "ros2 pkg prefix nav2_bt_navigator",
            "ros2 pkg prefix quadruped_robot_competition",
            "cone_inflated_voxel_layer/ConeInflatedVoxelLayer",
            "libcone_inflated_voxel_layer_core.so",
            "NONPERSISTENT_VOXEL_LAYER_SOURCE_INCLUDE",
            "0704666393ef1747562a93d934923fa45a3a8d4b",
            'snapshot_value "plugin_library"',
            'snapshot_value "plugin_library_real"',
            'pkg_resources.load_entry_point(',
            '"cmd_vel_arbiter", "cone_scan_udp_bridge", "cone_scan_safety_gate"',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.script)
        self.assertIn(
            '[ "$PLUGIN_MAP_REAL" = "$PLUGIN_LIBRARY_REAL" ]', self.script
        )
        self.assertIn(
            '[ "$PLANNER_PLUGIN_MAP_REAL" = "$PLUGIN_LIBRARY_REAL" ]', self.script
        )
        self.assertNotIn(
            "export PYTHONPATH=/opt/ros/foxy/lib/python3.8/site-packages",
            self.script,
        )

    def test_success_banner_is_after_fail_closed_runtime_gate(self):
        banner = self.script.index("GO: 启动完成，运行验收通过!")
        for token in (
            "LIFECYCLE_NODES=(map_server planner_server controller_server recoveries_server bt_navigator)",
            "ros2 lifecycle get",
            "EXPECTED_CMD_VEL_SUBSCRIBERS",
            "RMW_QOS_POLICY_RELIABILITY_)?BEST_EFFORT",
            "RMW_QOS_POLICY_RELIABILITY_)?RELIABLE",
            "cone_startup_health_probe.py",
            "controller_server did not map the pinned",
            "planner_server did not map the pinned",
        ):
            with self.subTest(token=token):
                self.assertLess(self.script.index(token), banner)
        self.assertIn('echo "NO-GO: $*"', self.script)
        self.assertIn('docker stop -t 10 "$RUNTIME_CUVSLAM_CONTAINER"', self.script)
        self.assertIn('snapshot_value "runtime_cuvslam_container"', self.script)
        self.assertNotIn("✅ 启动完成!", self.script)

    def test_lifecycle_snapshot_retries_without_weakening_active_gate(self):
        for token in (
            'STARTUP_LIFECYCLE_SNAPSHOT_RETRIES="${STARTUP_LIFECYCLE_SNAPSHOT_RETRIES:-3}"',
            'for attempt in $(seq 1 "$STARTUP_LIFECYCLE_SNAPSHOT_RETRIES")',
            "grep -Fq 'active [3]' && break",
            'kill -0 "$COMP_PID"',
            'cannot confirm active lifecycle state for /$node after ${STARTUP_LIFECYCLE_SNAPSHOT_RETRIES} attempts',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.script)
        snapshot_block = self.script.split(
            'for node in "${LIFECYCLE_NODES[@]}"; do', 2
        )[2].split("CMD_VEL_INFO=", 1)[0]
        self.assertIn("grep -Fq 'active [3]'", snapshot_block)
        self.assertNotIn('state="active [3]"', snapshot_block)

    def test_phase113_preset_is_no_retry_and_calibration_gated(self):
        for token in (
            "--cone-to-whz-l6",
            "CONE_TO_WHZ_L6=true",
            "TASK_MAX_NAV_RETRIES=0",
            "TASK_MAX_INSPECTION_RETRIES=0",
            "TASK_FINISH_AFTER_INSPECTION=true",
            "TASK_ALLOW_PLACEHOLDER_MANIPULATION=false",
            "load_calibrated_waypoints",
            "MISSION_NAV_WAYPOINTS",
            'startup_no_go "Phase 113 requires TASK_EXPECTED_MAP_ID"',
            'startup_no_go "Phase 113 waypoint calibration gate failed"',
            "max_nav_retries:=$TASK_MAX_NAV_RETRIES",
            "finish_after_inspection:=$TASK_FINISH_AFTER_INSPECTION",
            "require_exact_parameter /task_manager_node max_nav_retries 0",
            "require_exact_parameter /task_manager_node finish_after_inspection true",
            "require_exact_parameter /task_manager_node expected_map_id",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.script)

        preset = self.script.split("if $CONE_TO_WHZ_L6; then", 1)[1].split(
            "fi", 1
        )[0]
        self.assertNotIn("ENABLE_DOG=true", preset)
        self.assertNotIn("ENABLE_CMD_VEL_BRIDGE=true", preset)
        self.assertNotIn("PREPARE_LITE3_MOTION=true", preset)
        self.assertLess(
            self.script.index("Phase 113 waypoint calibration gate failed"),
            self.script.index("echo '[0/6] 清理旧进程...'"),
        )
        self.assertIn('"route_goal_count": len(route_goals)', self.script)
        self.assertIn('"unique_waypoint_count": len(waypoints)', self.script)

    def test_empty_optional_waypoint_launch_arguments_are_omitted(self):
        launch_block = self.script.split(
            "COMPETITION_LAUNCH_ARGS=(", 1
        )[1].split("COMP_PID=$!", 1)[0]
        for variable, argument in (
            ("TASK_WAYPOINT_FILE", "waypoint_file"),
            ("TASK_EXPECTED_MAP_ID", "expected_map_id"),
        ):
            with self.subTest(argument=argument):
                self.assertIn(f'[ -n "${variable}" ]', launch_block)
                self.assertIn(
                    f'COMPETITION_LAUNCH_ARGS+=("{argument}:=${variable}")',
                    launch_block,
                )
        declared_args = launch_block.split(")", 1)[0]
        self.assertNotIn('"waypoint_file:=$TASK_WAYPOINT_FILE"', declared_args)
        self.assertNotIn('"expected_map_id:=$TASK_EXPECTED_MAP_ID"', declared_args)
        self.assertIn('"${COMPETITION_LAUNCH_ARGS[@]}"', launch_block)

    def test_mode_control_clears_only_stale_request_and_status_after_cleanup(self):
        cleanup = self.script.index("bash scripts/stop_all.sh 2>&1 | tail -3")
        reset_guard = self.script.index("if $ENABLE_CONE_MODE_CONTROL; then", cleanup)
        docker = self.script.index("echo '[1/6] Docker cuVSLAM...'")
        self.assertLess(cleanup, reset_guard)
        self.assertLess(reset_guard, docker)
        reset_block = self.script[reset_guard:docker]
        for token in (
            "depth_control_request.json",
            "depth_controller_status.json",
            'rm -f -- "$DEPTH_CONTROL_REQUEST_FILE" "$DEPTH_CONTROLLER_STATUS_FILE"',
            'snapshot_value "depth_mode_state_reset_dir"',
        ):
            with self.subTest(token=token):
                self.assertIn(token, reset_block)
        self.assertNotIn("latest_depth.raw", reset_block)
        self.assertNotIn("latest_depth.json", reset_block)

    def test_relay_readiness_logs_are_cleared_before_new_processes_start(self):
        reset = self.script.index(
            'docker exec "$CN" rm -f /tmp/cam.log /tmp/dep.log'
        )
        camera_start = self.script.index("python3 /tmp/camera_relay_docker.py")
        depth_start = self.script.index("python3 /tmp/depth_relay_docker.py")
        self.assertLess(reset, camera_start)
        self.assertLess(reset, depth_start)

    def test_official_cone_parameters_and_gate_defaults_are_enforced(self):
        base = BASE_PARAMS.read_text(encoding="utf-8")
        cone = CONE_PARAMS.read_text(encoding="utf-8")
        experimental = EXPERIMENTAL_PARAMS.read_text(encoding="utf-8")
        gate = SAFETY_GATE.read_text(encoding="utf-8")
        for token in (
            "observation_persistence: 1.5",
            "inflation_radius: 0.60",
            "cost_scaling_factor: 2.0",
        ):
            self.assertIn(token, cone)
        for token in (
            "PathAlign.scale: 32.0",
            "PathDist.scale: 32.0",
            "ObstacleFootprint.scale: 0.02",
        ):
            self.assertIn(token, base)
        for token in (
            "ObstacleFootprint.scale: 1.0",
            "vtheta_samples: 21",
            "global_costmap:",
        ):
            self.assertIn(token, cone)
        for token in (
            "FollowPathCone.ObstacleFootprint.scale 1.0",
            "FollowPathCone.vtheta_samples 21",
            "FollowPathCone.min_vel_x 0.0",
            "FollowPathCone.max_vel_y 0.0",
            "FollowPath.ObstacleFootprint.scale 0.02",
            "FollowPath.vtheta_samples 20",
            "/global_costmap/global_costmap cone_obstacle_layer.cone_scan.observation_persistence 1.5",
        ):
            self.assertIn(token, self.script)
        self.assertIn('declare_parameter("required_consecutive_frames", 3)', gate)
        self.assertIn('declare_parameter("health_timeout_sec", 0.20)', gate)
        self.assertIn('CONE_NAV2_PROFILE="formal"', self.script)
        self.assertIn('CONE_NAV2_PROFILE="experimental"', self.script)
        self.assertIn(
            'cone_obstacle_layer.inflation_radius "$CONE_EXPECTED_INFLATION_RADIUS"',
            self.script,
        )
        self.assertIn("inflation_layer.inflation_radius 0.30", self.script)
        self.assertIn("inflation_layer.cost_scaling_factor 3.0", self.script)
        self.assertIn(
            'FollowPathCone.sim_time "$CONE_EXPECTED_SIM_TIME"',
            self.script,
        )
        self.assertIn("inflation_radius: 0.75", experimental)

    def test_cone_bt_and_dual_controller_provenance_are_checked(self):
        for token in (
            "navigate_cone_w_replanning_and_recovery.xml",
            'controller_id="FollowPathCone"',
            "controller_plugins does not contain FollowPath and FollowPathCone",
            "enable_cone_controller true",
            'cone_behavior_tree "$FORMAL_CONE_BEHAVIOR_TREE"',
        ):
            self.assertIn(token, self.script)

    def test_cone_plugin_build_precedes_runtime_mutation(self):
        build = self.script.index("--packages-select cone_inflated_voxel_layer")
        cleanup = self.script.index("echo '[0/6] 清理旧进程...'")
        docker = self.script.index("echo '[1/6] Docker cuVSLAM...'")
        self.assertLess(build, cleanup)
        self.assertLess(build, docker)


class ConeStartupHealthProbeTests(unittest.TestCase):
    def test_continuously_ready_window_passes_at_minimum_rate(self):
        module = load_health_probe()
        state = module.ProbeState()
        for index in range(81):
            state.record_scan(100.0 + index * 0.1)
        for sequence in range(1, 81):
            state.record_health(
                '{"healthy":true,"reason":"ready","stream_id":"s",'
                '"sequence":%d,"source_age_ms":25.0}' % sequence
            )
        result = state.result(min_scan_rate_hz=8.0, min_health_samples=8)
        self.assertTrue(result["passed"])
        self.assertAlmostEqual(result["scan_rate_hz"], 10.0)

    def test_unhealthy_or_non_advancing_health_fails(self):
        module = load_health_probe()
        state = module.ProbeState()
        state.record_scan(1.0)
        state.record_scan(1.1)
        payload = (
            '{"healthy":true,"reason":"ready","stream_id":"s",'
            '"sequence":1,"source_age_ms":20.0}'
        )
        state.record_health(payload)
        state.record_health(payload)
        result = state.result(min_scan_rate_hz=8.0, min_health_samples=2)
        self.assertFalse(result["passed"])
        self.assertIn("health stream was not continuously ready", result["errors"])


if __name__ == "__main__":
    unittest.main()
