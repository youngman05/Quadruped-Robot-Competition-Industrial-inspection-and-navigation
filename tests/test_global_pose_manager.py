import math
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from nodes.navigation.global_pose_manager import (
    GlobalPoseConfig,
    GlobalPoseManagerCore,
    PoseSample,
    SE2,
    fit_se2_alignment,
    load_global_pose_config,
    pair_pose_samples,
    pose_sample_from_payload,
)


def sample(stamp, frame, x, y, yaw=0.0, receive_time=100.0):
    return PoseSample(
        source_stamp=stamp,
        frame_id=frame,
        child_frame_id="base_link",
        x=x,
        y=y,
        z=0.0,
        quaternion=(0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0)),
        receive_time=receive_time,
    )


class GlobalPoseManagerTests(unittest.TestCase):
    def test_se2_composition_and_inverse(self):
        first = SE2(1.0, 2.0, math.pi / 2.0)
        second = SE2(0.5, 0.0, -math.pi / 2.0)
        result = first.compose(second)
        self.assertAlmostEqual(result.x, 1.0)
        self.assertAlmostEqual(result.y, 2.5)
        self.assertAlmostEqual(result.yaw, 0.0)
        identity = result.compose(result.inverse())
        self.assertAlmostEqual(identity.x, 0.0)
        self.assertAlmostEqual(identity.y, 0.0)
        self.assertAlmostEqual(identity.yaw, 0.0)

    def test_pairing_uses_source_stamp_and_rejects_bad_frames(self):
        vo = [sample(1.0, "odom", 0.0, 0.0), sample(2.0, "odom", 1.0, 0.0)]
        slam = [sample(2.015, "vslam_map", 1.0, 0.0), sample(1.40, "vslam_map", 0.0, 0.0)]
        pairs = pair_pose_samples(vo, slam, max_stamp_delta=0.03)
        self.assertEqual(len(pairs), 1)
        self.assertAlmostEqual(pairs[0].vo.source_stamp, 2.0)
        self.assertAlmostEqual(pairs[0].slam.source_stamp, 2.015)

    def test_alignment_fit_requires_multiple_points_for_completion(self):
        transform = SE2(2.0, -1.0, math.radians(30.0))
        source = [(0.0, 0.0), (1.0, 0.0), (0.0, 2.0)]
        target = [(p.x, p.y) for p in (transform.compose(SE2(x, y, 0.0)) for x, y in source)]
        result = fit_se2_alignment(source, target)
        self.assertEqual(result.point_count, 3)
        self.assertLess(result.max_residual, 1e-9)
        self.assertAlmostEqual(result.transform.x, transform.x)
        self.assertAlmostEqual(result.transform.y, transform.y)
        self.assertAlmostEqual(result.transform.yaw, transform.yaw)
        one = fit_se2_alignment([(1.0, 2.0)], [(3.0, 4.0)], yaw_hint=0.0)
        self.assertEqual(one.point_count, 1)
        self.assertTrue(math.isinf(one.max_residual))

    def test_dynamic_manager_is_fail_closed_until_alignment_is_complete(self):
        manager = GlobalPoseManagerCore(GlobalPoseConfig(alignment_status="pending"), mode="legacy_static")
        with self.assertRaisesRegex(ValueError, "complete map alignment"):
            manager.set_mode("cuvslam_global")
        with self.assertRaisesRegex(ValueError, "complete map alignment"):
            GlobalPoseManagerCore(
                GlobalPoseConfig(alignment_status="pending"),
                mode="cuvslam_global",
            )
        self.assertEqual(manager.update(sample(1.0, "odom", 0.0, 0.0), sample(1.0, "vslam_map", 0.0, 0.0)).reason, "mode_legacy_static")

    def test_dynamic_manager_accepts_stable_pairs_and_holds_on_jump(self):
        config = GlobalPoseConfig(
            alignment=SE2(10.0, 20.0, 0.1),
            alignment_status="complete",
            stable_frames=2,
            max_candidate_jump_xy=0.5,
            max_candidate_jump_yaw=0.5,
        )
        manager = GlobalPoseManagerCore(config, mode="cuvslam_global")
        first = manager.update(sample(10.0, "odom", 1.0, 2.0, 0.2, receive_time=100.0), sample(10.0, "vslam_map", 3.0, 4.0, 0.3, receive_time=100.0), now=100.0)
        self.assertFalse(first.accepted)
        self.assertEqual(first.reason, "warming_up")
        second = manager.update(sample(10.01, "odom", 1.0, 2.0, 0.2, receive_time=100.01), sample(10.01, "vslam_map", 3.0, 4.0, 0.3, receive_time=100.01), now=100.01)
        self.assertTrue(second.accepted)
        self.assertIsNotNone(manager.current)
        jump = manager.update(sample(10.02, "odom", 1.0, 2.0, 0.2, receive_time=100.02), sample(10.02, "vslam_map", 5.0, 4.0, 0.3, receive_time=100.02), now=100.02)
        self.assertFalse(jump.accepted)
        self.assertEqual(jump.reason, "candidate_jump")
        self.assertEqual(manager.mode, "fault_hold")

    def test_duplicate_pair_does_not_advance_stability_counter(self):
        config = GlobalPoseConfig(alignment_status="complete", stable_frames=2)
        manager = GlobalPoseManagerCore(config, mode="cuvslam_global")
        vo = sample(1.0, "odom", 0.0, 0.0, receive_time=1.0)
        slam = sample(1.0, "vslam_map", 0.0, 0.0, receive_time=1.0)
        first = manager.update(vo, slam, now=1.0)
        duplicate = manager.update(vo, slam, now=1.0)
        self.assertEqual(first.reason, "warming_up")
        self.assertEqual(duplicate.reason, "duplicate_pair")
        self.assertEqual(duplicate.stable_count, 1)

    def test_medium_correction_requires_external_hold_before_tf_update(self):
        config = GlobalPoseConfig(
            alignment_status="complete",
            stable_frames=1,
            small_correction_xy=0.10,
            medium_correction_xy=0.30,
        )
        manager = GlobalPoseManagerCore(config, mode="cuvslam_global")
        initial = manager.update(
            sample(1.0, "odom", 0.0, 0.0, receive_time=1.0),
            sample(1.0, "vslam_map", 0.0, 0.0, receive_time=1.0),
            now=1.0,
        )
        held = manager.update(
            sample(2.0, "odom", 0.0, 0.0, receive_time=2.0),
            sample(2.0, "vslam_map", 0.20, 0.0, receive_time=2.0),
            now=2.0,
        )
        self.assertTrue(initial.accepted)
        self.assertFalse(held.accepted)
        self.assertEqual(held.reason, "correction_requires_hold")
        self.assertEqual(held.correction_level, "medium")
        self.assertEqual(manager.mode, "relocalize_hold")
        self.assertAlmostEqual(manager.current.x, 0.0)

    def test_stale_and_frame_mismatch_do_not_update(self):
        config = GlobalPoseConfig(alignment_status="complete", stable_frames=1, max_age=0.2)
        manager = GlobalPoseManagerCore(config, mode="cuvslam_global")
        stale = manager.update(sample(1.0, "odom", 0.0, 0.0, receive_time=1.0), sample(1.0, "vslam_map", 0.0, 0.0, receive_time=1.0), now=2.0)
        self.assertEqual(stale.reason, "stale_sample")
        bad = manager.update(sample(1.0, "map", 0.0, 0.0), sample(1.0, "vslam_map", 0.0, 0.0), now=1.0)
        self.assertEqual(bad.reason, "frame_mismatch")

    def test_payload_parser_requires_stamp_pose_and_normalizes_quaternion(self):
        payload = {
            "seq": 7,
            "stamp": {"sec": 10, "nanosec": 500000000},
            "frame_id": "vslam_map",
            "child_frame_id": "base_link",
            "pose": {
                "position": {"x": 1.0, "y": 2.0, "z": 0.0},
                "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 2.0},
            },
        }
        parsed = pose_sample_from_payload(payload)
        self.assertAlmostEqual(parsed.source_stamp, 10.5)
        self.assertAlmostEqual(sum(value * value for value in parsed.quaternion), 1.0)
        with self.assertRaisesRegex(ValueError, "missing field"):
            pose_sample_from_payload({"stamp": payload["stamp"]})

    def test_repository_alignment_config_is_explicitly_pending(self):
        config = load_global_pose_config(REPO_ROOT / "configs" / "navigation" / "global_pose.yaml")
        self.assertEqual(config.alignment_status, "pending")
        self.assertEqual(config.vslam_map_frame, "vslam_map")


if __name__ == "__main__":
    unittest.main()
