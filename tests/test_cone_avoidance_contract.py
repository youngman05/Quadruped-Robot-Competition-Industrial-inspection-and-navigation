import shutil
import subprocess
import os
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CUVSLAM_START = REPO_ROOT / "scripts" / "start_cuvslam_rviz_gui.sh"
COMPETITION_START = REPO_ROOT / "scripts" / "start_competition.sh"
NAV_LAUNCH = REPO_ROOT / "launch" / "navigation.launch.py"
COMP_LAUNCH = REPO_ROOT / "launch" / "competition.launch.py"
CONE_PARAMS = REPO_ROOT / "configs" / "navigation" / "nav2_cone_obstacles.yaml"
CONE_EXPERIMENT_PARAMS = (
    REPO_ROOT / "configs" / "navigation" / "nav2_cone_obstacles_experimental.yaml"
)
BASE_PARAMS = REPO_ROOT / "configs" / "navigation" / "nav2_params.yaml"
CONE_DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile.cuvslam-cone"


class ConeAvoidanceContractTests(unittest.TestCase):
    def test_single_realsense_owner_generates_decimated_base_link_scan(self):
        source = CUVSLAM_START.read_text(encoding="utf-8")
        self.assertEqual(source.count("realsense_camera_node = Node("), 1)
        for token in (
            "'pointcloud.enable': ${cone_avoidance_enable_py}",
            "'decimation_filter.enable': ${cone_avoidance_enable_py}",
            "'decimation_filter.filter_magnitude': 4",
            "package='pointcloud_to_laserscan'",
            "'target_frame': '${CONE_SCAN_TARGET_FRAME}'",
            "('scan', '/cone_obstacle/scan_humble')",
            "cone_scan_udp_exporter.py",
        ):
            self.assertIn(token, source)

    def test_overlay_buffers_cones_in_both_costmaps(self):
        overlay = CONE_PARAMS.read_text(encoding="utf-8")
        self.assertIn("local_costmap:", overlay)
        self.assertIn("global_costmap:", overlay)
        for token in (
            'plugins: ["static_layer", "cone_obstacle_layer", "inflation_layer"]',
            "nav2_costmap_2d/NonPersistentVoxelLayer",
            'topic: "/cone_obstacle/scan"',
            'data_type: "LaserScan"',
            "origin_z: 0.0",
            "min_obstacle_height: 0.0",
            "obstacle_range: 3.00",
            "observation_persistence: 1.5",
            "cost_scaling_factor: 2.0",
            "inflation_radius: 0.60",
        ):
            self.assertEqual(overlay.count(token), 2, token)
        self.assertIn("ObstacleFootprint.scale: 1.0", overlay)
        self.assertIn("vtheta_samples: 21", overlay)
        self.assertIn("sim_time: 2.5", overlay)
        self.assertIn("PathAlign.scale: 16.0", overlay)
        self.assertIn("PathDist.scale: 16.0", overlay)
        self.assertNotIn("obstacle_max_range", overlay)
        self.assertNotIn("PointCloud2", overlay)

    def test_scan_min_height_is_validated_snapshotted_and_generated(self):
        source = CUVSLAM_START.read_text(encoding="utf-8")
        for token in (
            'CONE_SCAN_MIN_HEIGHT="${CONE_SCAN_MIN_HEIGHT:-0.05}"',
            "require_decimal_in_half_open_range",
            '"CONE_SCAN_MIN_HEIGHT" "$CONE_SCAN_MIN_HEIGHT" 0.0 1.20',
            "'min_height': ${CONE_SCAN_MIN_HEIGHT}",
            "CONE_SCAN_MIN_HEIGHT=$CONE_SCAN_MIN_HEIGHT",
            'validate_generated_python "$CUVSLAM_LAUNCH" "$CUVSLAM_LAUNCH_RUNNER"',
        ):
            self.assertIn(token, source)

    def test_scan_min_height_rejects_invalid_values_before_runtime_checks(self):
        bash = shutil.which("bash")
        if bash is None and os.name == "nt":
            candidate = Path(r"C:\Program Files\Git\bin\bash.exe")
            if candidate.is_file():
                bash = str(candidate)
        if bash is None:
            self.skipTest("bash is required to execute launcher validation")
        env = dict(os.environ)
        for value in (
            "-0.01",
            "1.20",
            "1e-1",
            "0",
            "00.05",
            "0.05;raise SystemExit()",
        ):
            env["CONE_SCAN_MIN_HEIGHT"] = value
            result = subprocess.run(
                [bash, str(CUVSLAM_START), "--no-rviz"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("CONE_SCAN_MIN_HEIGHT must", result.stderr)

    def test_experimental_tuning_is_cone_only_and_never_default(self):
        official = CONE_PARAMS.read_text(encoding="utf-8")
        experiment = CONE_EXPERIMENT_PARAMS.read_text(encoding="utf-8")
        nav_launch = NAV_LAUNCH.read_text(encoding="utf-8")
        competition_launch = COMP_LAUNCH.read_text(encoding="utf-8")
        competition_start = COMPETITION_START.read_text(encoding="utf-8")

        experiment_only_tokens = (
            "inflation_radius: 0.75",
            "cost_scaling_factor: 1.5",
            "PathAlign.scale: 12.0",
            "PathDist.scale: 12.0",
            "sim_time: 3.0",
        )
        for token in experiment_only_tokens:
            self.assertIn(token, experiment)
            self.assertNotIn(token, official)
        self.assertIn("observation_persistence: 1.5", official)
        self.assertIn("observation_persistence: 1.5", experiment)
        self.assertIn("global_costmap:", experiment)
        self.assertIn("ObstacleFootprint.scale: 1.0", experiment)
        self.assertIn("vtheta_samples: 21", experiment)
        self.assertIn('"nav2_cone_obstacles.yaml"', nav_launch)
        self.assertNotIn("nav2_cone_obstacles_experimental.yaml", nav_launch)
        self.assertIn('"cone_params_file": cone_params_file', competition_launch)
        self.assertIn(
            'CONE_NAV2_PARAMS_FILE="${CONE_NAV2_PARAMS_FILE:-$OFFICIAL_CONE_NAV2_PARAMS_FILE}"',
            competition_start,
        )
        self.assertIn('echo " Cone Nav2 params: $CONE_NAV2_PARAMS_FILE"', competition_start)
        self.assertIn('CONE_NAV2_PROFILE="formal"', competition_start)
        self.assertIn('CONE_NAV2_PROFILE="experimental"', competition_start)
        self.assertIn('CONE_EXPECTED_INFLATION_RADIUS="0.75"', competition_start)

    def test_non_cone_base_global_costmap_remains_static(self):
        base = BASE_PARAMS.read_text(encoding="utf-8")
        global_section = base.split("global_costmap:", 1)[1]
        self.assertIn('plugins: ["static_layer", "inflation_layer"]', global_section)
        self.assertNotIn("NonPersistentVoxelLayer", base)

    def test_navigation_uses_one_gated_velocity_owner_in_cone_mode(self):
        nav = NAV_LAUNCH.read_text(encoding="utf-8")
        for token in (
            'enable_cone_avoidance = LaunchConfiguration("enable_cone_avoidance")',
            "parameters=[params_file, cone_params_file]",
            'executable="cone_scan_udp_bridge"',
            'executable="cone_scan_safety_gate"',
            '{"output_topic": "/cmd_vel_selected"}',
            "condition=IfCondition(cone_mode)",
        ):
            self.assertIn(token, nav)
        planner_cone = nav.split("    planner_cone = Node(", 1)[1].split(
            "    controller_static = Node(", 1
        )[0]
        self.assertIn("parameters=[params_file, cone_params_file]", planner_cone)
        self.assertIn("condition=IfCondition(cone_mode)", planner_cone)

    def test_competition_cone_mode_does_not_publish_host_camera_tf(self):
        source = COMP_LAUNCH.read_text(encoding="utf-8")
        self.assertIn('"enable_cone_avoidance": enable_cone_avoidance', source)
        camera_block = source.split("base_to_camera_tf = Node(", 1)[1].split(
            "depth_pub_node = Node(", 1
        )[0]
        self.assertIn("enable_cone_avoidance", camera_block)
        self.assertIn("' != 'true'", camera_block)

    def test_launcher_keeps_new_and_legacy_depth_paths_mutually_exclusive(self):
        source = COMPETITION_START.read_text(encoding="utf-8")
        self.assertIn("--cone-avoidance", source)
        self.assertIn(
            "if $ENABLE_DEPTH_PIPELINE && $ENABLE_CONE_AVOIDANCE; then", source
        )
        self.assertIn('export CONE_AVOIDANCE_ENABLE="$ENABLE_CONE_AVOIDANCE"', source)
        self.assertIn('CONE_DOCKER_ROS_DOMAIN_ID:-42', source)
        self.assertIn("enable_cone_avoidance:=$ENABLE_CONE_AVOIDANCE", source)
        case_line = next(
            line for line in source.splitlines() if "--cone-avoidance)" in line
        )
        self.assertNotIn("ENABLE_DEPTH_RELAY", case_line)

    def test_cone_image_dependency_is_pinned_and_checked_without_devices(self):
        dockerfile = CONE_DOCKERFILE.read_text(encoding="utf-8")
        launcher = CUVSLAM_START.read_text(encoding="utf-8")
        competition = COMPETITION_START.read_text(encoding="utf-8")
        self.assertIn(
            "ros-humble-pointcloud-to-laserscan=${POINTCLOUD_TO_LASERSCAN_VERSION}",
            dockerfile,
        )
        self.assertIn("2.0.1-3focal.20231003.024830", dockerfile)
        self.assertIn("docker run --rm --network none", launcher)
        self.assertIn("check_cone_image_dependencies", launcher)
        self.assertIn(
            'export IMAGE="${IMAGE:-isaac_ros_cuvslam_runtime:humble-rs-cone}"',
            competition,
        )

    def test_cone_pipeline_readiness_retries_topic_and_exporter(self):
        source = COMPETITION_START.read_text(encoding="utf-8")
        self.assertIn("CONE_PIPELINE_READY=false", source)
        self.assertIn("for _ in $(seq 1 20); do", source)
        self.assertIn("timeout 5 ros2 topic list", source)
        self.assertIn("[c]one_scan_udp_exporter.py", source)
        self.assertIn("CONE_PIPELINE_READY=true", source)

    def test_package_installs_bridge_gate_and_nonpersistent_dependency(self):
        setup = (REPO_ROOT / "setup.py").read_text(encoding="utf-8")
        package = (REPO_ROOT / "package.xml").read_text(encoding="utf-8")
        self.assertIn("cone_scan_udp_bridge =", setup)
        self.assertIn("cone_scan_safety_gate =", setup)
        self.assertIn("<exec_depend>nonpersistent_voxel_layer</exec_depend>", package)


if __name__ == "__main__":
    unittest.main()
