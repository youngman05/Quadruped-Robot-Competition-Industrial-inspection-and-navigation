import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CUVSLAM_START = REPO_ROOT / "scripts" / "start_cuvslam_rviz_gui.sh"
COMPETITION_START = REPO_ROOT / "scripts" / "start_competition.sh"
NAV_LAUNCH = REPO_ROOT / "launch" / "navigation.launch.py"
COMP_LAUNCH = REPO_ROOT / "launch" / "competition.launch.py"
CONE_PARAMS = REPO_ROOT / "configs" / "navigation" / "nav2_cone_obstacles.yaml"
BASE_PARAMS = REPO_ROOT / "configs" / "navigation" / "nav2_params.yaml"


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

    def test_overlay_is_local_only_nonpersistent_laserscan(self):
        overlay = CONE_PARAMS.read_text(encoding="utf-8")
        self.assertIn("local_costmap:", overlay)
        self.assertNotIn("global_costmap:", overlay)
        self.assertIn("nav2_costmap_2d/NonPersistentVoxelLayer", overlay)
        self.assertIn('topic: "/cone_obstacle/scan"', overlay)
        self.assertIn('data_type: "LaserScan"', overlay)
        self.assertIn("origin_z: 0.0", overlay)
        self.assertIn("min_obstacle_height: 0.0", overlay)
        self.assertIn("obstacle_range: 2.50", overlay)
        self.assertNotIn("obstacle_max_range", overlay)
        self.assertNotIn("PointCloud2", overlay)

    def test_stable_base_global_costmap_remains_static(self):
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

    def test_package_installs_bridge_gate_and_nonpersistent_dependency(self):
        setup = (REPO_ROOT / "setup.py").read_text(encoding="utf-8")
        package = (REPO_ROOT / "package.xml").read_text(encoding="utf-8")
        self.assertIn("cone_scan_udp_bridge =", setup)
        self.assertIn("cone_scan_safety_gate =", setup)
        self.assertIn("<exec_depend>nonpersistent_voxel_layer</exec_depend>", package)


if __name__ == "__main__":
    unittest.main()
