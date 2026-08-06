import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from nodes.navigation.apriltag_global_observation import (
    AprilTagObservation,
    validate_apriltag_observation,
)
from nodes.navigation.global_pose_manager import load_global_pose_config


def load_script(name):
    path = REPO_ROOT / "scripts" / name
    module_name = "test_{}".format(path.stem)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


CALIBRATOR = load_script("cuvslam_map_alignment_calibrator.py")
LIFECYCLE = load_script("cuvslam_map_lifecycle_guard.py")
ACTION_CLIENT = load_script("cuvslam_map_action_client.py")


class MapLifecycleTests(unittest.TestCase):
    def make_bundle(self, directory, *, nav_points=None):
        directory = Path(directory)
        nav_yaml = directory / "field.yaml"
        nav_image = directory / "field.pgm"
        vslam_map = directory / "visual_map"
        points = directory / "points.json"
        alignment = directory / "alignment.json"
        extrinsics = directory / "extrinsics.json"
        start_prior = directory / "start_prior.json"
        nav_image.write_bytes(b"P5\n1 1\n255\n\x00")
        nav_yaml.write_text(
            "image: field.pgm\nresolution: 0.05\norigin: [0, 0, 0]\n",
            encoding="utf-8",
        )
        vslam_map.mkdir()
        (vslam_map / "map.bin").write_bytes(b"visual-map-v1")
        extrinsics.write_text(json.dumps({
            "parent_frame": "base_link",
            "child_frame": "camera_link",
            "translation_m": {"x": 0.08, "y": 0.0, "z": 0.493},
            "rotation_rpy_rad": {"roll": 0.0, "pitch": 0.523599, "yaw": 0.0},
        }), encoding="utf-8")
        start_prior.write_text(json.dumps({
            "frame_id": "map",
            "map_id": "field-v1",
            "x": 4.65,
            "y": 0.75,
            "yaw": math.pi,
        }), encoding="utf-8")
        vslam_points = [(0.0, 0.0), (2.0, 0.0), (0.0, 2.0)]
        if nav_points is None:
            nav_points = [(4.0, 1.0), (6.0, 1.0), (4.0, 3.0)]
        points.write_text(
            json.dumps({
                "control_points": [
                    {
                        "vslam_map": {"x": source[0], "y": source[1]},
                        "nav_map": {"x": target[0], "y": target[1]},
                    }
                    for source, target in zip(vslam_points, nav_points)
                ]
            }),
            encoding="utf-8",
        )
        document = CALIBRATOR.build_alignment_document(
            points,
            nav_map_yaml=nav_yaml,
            nav_map_id="field-v1",
            vslam_map=vslam_map,
            vslam_map_id="visual-v1",
            extrinsics_file=extrinsics,
            start_prior_file=start_prior,
        )
        alignment.write_text(json.dumps(document), encoding="utf-8")
        bundle = LIFECYCLE.MapBundle(
            "field-v1", "visual-v1", nav_yaml, vslam_map,
            extrinsics, start_prior, alignment,
        )
        return document, bundle, nav_image, vslam_map

    def test_multi_point_bundle_records_all_map_hashes_and_passes_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            document, bundle, _, _ = self.make_bundle(directory)
            result = LIFECYCLE.validate_bundle(bundle)
            self.assertEqual(document["status"], "complete")
            self.assertEqual(document["alignment"]["control_points"], 3)
            self.assertAlmostEqual(document["alignment"]["scale_ratio"], 1.0)
            self.assertTrue(document["nav_map_image_sha256"])
            self.assertTrue(document["vslam_map_sha256"])
            self.assertTrue(document["extrinsics_sha256"])
            self.assertTrue(document["start_prior_sha256"])
            self.assertTrue(result["ok"], result["errors"])
            self.assertEqual(
                load_global_pose_config(bundle.alignment_config).alignment_status,
                "complete",
            )

            goal = LIFECYCLE.load_map_and_localize_goal(
                bundle,
                LIFECYCLE.LocalizationPrior(4.65, 0.75, math.pi),
            )
            self.assertTrue(goal["fail_closed"])
            self.assertEqual(
                goal["action_type"],
                "isaac_ros_visual_slam_interfaces/action/LoadMapAndLocalize",
            )
            self.assertAlmostEqual(
                goal["goal"]["localize_near_point"]["x"], 0.65,
            )
            self.assertAlmostEqual(
                goal["goal"]["localize_near_point"]["y"], -0.25,
            )
            self.assertNotIn("yaw", goal["goal"]["localize_near_point"])

            validation = LIFECYCLE.validate_localization_result(
                bundle,
                LIFECYCLE.LocalizationPrior(4.65, 0.75, math.pi),
                action_success=True,
                localized_vslam_pose={"x": 0.65, "y": -0.25, "yaw": math.pi},
            )
            self.assertTrue(validation["ok"], validation["errors"])

    def test_action_payloads_match_installed_isaac_ros_2_1_interfaces(self):
        save = LIFECYCLE.save_map_goal("/maps/competition.cuvslam")
        self.assertEqual(save["action_name"], "/visual_slam/save_map")
        self.assertEqual(
            save["action_type"],
            "isaac_ros_visual_slam_interfaces/action/SaveMap",
        )
        self.assertEqual(set(save["goal"]), {"map_url"})
        self.assertEqual(
            ACTION_CLIENT.parse_args([
                "load", "--map-url", "/tmp/map.db", "--near-x", "1", "--near-y", "2",
            ]).near_z,
            0.0,
        )
        self.assertAlmostEqual(
            ACTION_CLIENT.quaternion_to_yaw((0.0, 0.0, math.sin(0.25), math.cos(0.25))),
            0.5,
        )

    def test_localization_result_must_match_nav_prior_after_alignment(self):
        with tempfile.TemporaryDirectory() as directory:
            _, bundle, _, _ = self.make_bundle(directory)
            result = LIFECYCLE.validate_localization_result(
                bundle,
                LIFECYCLE.LocalizationPrior(4.0, 1.0, 0.0),
                action_success=True,
                localized_vslam_pose={"x": 1.0, "y": 1.0, "yaw": 0.5},
                max_xy_error_m=0.10,
                max_yaw_error_rad=0.10,
            )
            self.assertFalse(result["ok"])
            self.assertIn(
                "localized XY residual exceeds threshold", result["errors"],
            )
            self.assertIn(
                "localized yaw residual exceeds threshold", result["errors"],
            )

    def test_scale_mismatch_stays_pending_even_when_point_residual_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            nav_points = [(4.0, 1.0), (6.12, 1.0), (4.0, 3.12)]
            document, _, _, _ = self.make_bundle(directory, nav_points=nav_points)
            self.assertLess(document["alignment"]["max_residual_m"], 0.10)
            self.assertGreater(document["alignment"]["scale_ratio"], 1.05)
            self.assertEqual(document["status"], "pending")

    def test_map_content_changes_invalidate_the_approved_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            _, bundle, nav_image, vslam_map = self.make_bundle(directory)
            nav_image.write_bytes(nav_image.read_bytes() + b"tampered")
            (vslam_map / "map.bin").write_bytes(b"visual-map-v2")
            result = LIFECYCLE.validate_bundle(bundle)
            self.assertFalse(result["ok"])
            self.assertIn("nav_map_image SHA-256 mismatch", result["errors"])
            self.assertIn("vslam_map SHA-256 mismatch", result["errors"])
            with self.assertRaisesRegex(ValueError, "bundle rejected"):
                load_global_pose_config(bundle.alignment_config)

    def test_top_level_and_alignment_status_must_agree(self):
        with tempfile.TemporaryDirectory() as directory:
            document, bundle, _, _ = self.make_bundle(directory)
            document["status"] = "pending"
            bundle.alignment_config.write_text(json.dumps(document), encoding="utf-8")
            result = LIFECYCLE.validate_bundle(bundle)
            self.assertFalse(result["ok"])
            self.assertIn("bundle status is 'pending', expected 'complete'", result["errors"])
            with self.assertRaisesRegex(ValueError, "status must match"):
                load_global_pose_config(bundle.alignment_config)

    def test_empty_saved_map_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            _, bundle, _, vslam_map = self.make_bundle(directory)
            (vslam_map / "map.bin").unlink()
            result = LIFECYCLE.validate_bundle(bundle)
            self.assertFalse(result["ok"])
            self.assertIn(
                "vslam_map is missing or empty: {}".format(vslam_map),
                result["errors"],
            )

    def test_wrong_prior_frame_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            _, bundle, _, _ = self.make_bundle(directory)
            with self.assertRaisesRegex(ValueError, "Nav2 map frame"):
                LIFECYCLE.load_map_and_localize_goal(
                    bundle,
                    LIFECYCLE.LocalizationPrior(0.0, 0.0, 0.0, "vslam_map"),
                )


class AprilTagObservationTests(unittest.TestCase):
    def observation(self, **overrides):
        values = {
            "tag_id": 11,
            "region": "grab",
            "map_x": 3.1,
            "map_y": 2.0,
            "map_yaw": 0.1,
            "reprojection_error_px": 1.0,
            "depth_residual_m": 0.02,
            "vio_residual_m": 0.10,
            "stable_frames": 6,
            "stationary": True,
        }
        values.update(overrides)
        return AprilTagObservation(**values)

    def test_grab_tag_passes_every_gate(self):
        result = validate_apriltag_observation(
            self.observation(),
            tag_map={11: {
                "region": "grab",
                "map_frame": "map",
                "pose": {"x": 3.2, "y": 2.1, "yaw": 0.0},
            }},
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.pose[:2], (3.1, 2.0))
        self.assertAlmostEqual(result.pose[2], 0.1)

    def test_instrument_region_and_tag_region_mismatch_are_rejected(self):
        instrument = validate_apriltag_observation(
            self.observation(region="instrument"),
            tag_map={11: {
                "region": "instrument",
                "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
            }},
        )
        mismatch = validate_apriltag_observation(
            self.observation(),
            tag_map={11: {
                "region": "drop",
                "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
            }},
        )
        self.assertEqual(instrument.reason, "region_not_allowed")
        self.assertEqual(mismatch.reason, "tag_region_mismatch")

    def test_motion_and_quality_fail_closed(self):
        tag_map = {11: {
            "region": "grab",
            "pose": {"x": 3.2, "y": 2.1, "yaw": 0.0},
        }}
        self.assertEqual(
            validate_apriltag_observation(
                self.observation(stationary=False), tag_map=tag_map,
            ).reason,
            "robot_not_stationary",
        )
        self.assertEqual(
            validate_apriltag_observation(
                self.observation(reprojection_error_px=3.0), tag_map=tag_map,
            ).reason,
            "reprojection_error",
        )

    def test_nan_and_negative_quality_values_are_invalid(self):
        with self.assertRaisesRegex(ValueError, "must be finite"):
            self.observation(vio_residual_m=float("nan"))
        with self.assertRaisesRegex(ValueError, "must be non-negative"):
            self.observation(depth_residual_m=-0.01)


if __name__ == "__main__":
    unittest.main()
