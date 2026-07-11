#!/usr/bin/env python3
"""Check base passthrough and camera-to-base conversion in final_bridge."""

import argparse
import json
import math

import rclpy
from nav_msgs.msg import Odometry

import final_bridge


def payload(child_frame_id, position):
    return {
        "frame_id": "odom",
        "child_frame_id": child_frame_id,
        "stamp": {"sec": 1, "nanosec": 2},
        "pose": {
            "position": {"x": position[0], "y": position[1], "z": position[2]},
            "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
        },
        "twist": {
            "linear": {"x": 0.0, "y": 0.0, "z": 0.0},
            "angular": {"x": 0.0, "y": 0.0, "z": 0.0},
        },
    }


def assert_close(actual, expected, tolerance=1e-5):
    if not math.isclose(actual, expected, abs_tol=tolerance):
        raise AssertionError(f"actual={actual} expected={expected}")


def pose_dict(msg):
    p = msg.pose.pose.position
    q = msg.pose.pose.orientation
    return {
        "position": [p.x, p.y, p.z],
        "orientation": [q.x, q.y, q.z, q.w],
        "frame_id": msg.header.frame_id,
        "child_frame_id": msg.child_frame_id,
    }


def make_args(camera_world_rebase="camera_start", planarize_output=False):
    return argparse.Namespace(
        camera_frame="camera_link",
        base_frame="base_link",
        odom_frame="odom",
        transform_camera_pose_to_base=True,
        base_to_camera_x=0.080,
        base_to_camera_y=0.000,
        base_to_camera_z=0.493,
        base_to_camera_roll=0.0,
        base_to_camera_pitch=0.523599,
        base_to_camera_yaw=0.0,
        camera_world_rebase=camera_world_rebase,
        planarize_output=planarize_output,
    )


def main():
    legacy_config = final_bridge.make_transform_config(make_args())
    rebased_config = final_bridge.make_transform_config(
        make_args(camera_world_rebase="base_start")
    )
    planar_config = final_bridge.make_transform_config(
        make_args(camera_world_rebase="base_start", planarize_output=True)
    )

    rclpy.init()
    node = rclpy.create_node("final_bridge_transform_probe")
    try:
        base_msg = Odometry()
        _, _, base_mode = final_bridge.fill_odometry(
            base_msg, payload("base_link", (1.0, 2.0, 3.0)), node, legacy_config
        )
        assert base_mode == "base_passthrough"
        assert_close(base_msg.pose.pose.position.x, 1.0)
        assert_close(base_msg.pose.pose.position.y, 2.0)
        assert_close(base_msg.pose.pose.position.z, 3.0)

        legacy_camera_msg = Odometry()
        _, _, camera_mode = final_bridge.fill_odometry(
            legacy_camera_msg,
            payload("camera_link", (1.0, 2.0, 3.0)),
            node,
            legacy_config,
        )
        assert camera_mode == "camera_to_base"
        assert_close(legacy_camera_msg.pose.pose.position.x, 1.1772181)
        assert_close(legacy_camera_msg.pose.pose.position.y, 2.0)
        assert_close(legacy_camera_msg.pose.pose.position.z, 2.5330495)

        rebased_camera_msg = Odometry()
        _, _, rebased_mode = final_bridge.fill_odometry(
            rebased_camera_msg,
            payload("camera_link", (1.0, 2.0, 3.0)),
            node,
            rebased_config,
        )
        assert rebased_mode == "camera_to_base"
        assert_close(rebased_camera_msg.pose.pose.position.x, 2.3660245)
        assert_close(rebased_camera_msg.pose.pose.position.y, 2.0)
        assert_close(rebased_camera_msg.pose.pose.position.z, 2.0980771)

        rebased_origin_msg = Odometry()
        final_bridge.fill_odometry(
            rebased_origin_msg,
            payload("camera_link", (0.0, 0.0, 0.0)),
            node,
            rebased_config,
        )
        assert_close(rebased_origin_msg.pose.pose.position.x, 0.0)
        assert_close(rebased_origin_msg.pose.pose.position.y, 0.0)
        assert_close(rebased_origin_msg.pose.pose.position.z, 0.0)
        assert_close(rebased_origin_msg.pose.pose.orientation.x, 0.0)
        assert_close(rebased_origin_msg.pose.pose.orientation.y, 0.0)
        assert_close(rebased_origin_msg.pose.pose.orientation.z, 0.0)
        assert_close(rebased_origin_msg.pose.pose.orientation.w, 1.0)

        planar_camera_msg = Odometry()
        final_bridge.fill_odometry(
            planar_camera_msg,
            payload("camera_link", (1.0, 2.0, 3.0)),
            node,
            planar_config,
        )
        assert_close(planar_camera_msg.pose.pose.position.x, 2.3660245)
        assert_close(planar_camera_msg.pose.pose.position.y, 2.0)
        assert_close(planar_camera_msg.pose.pose.position.z, 0.0)
        assert_close(planar_camera_msg.pose.pose.orientation.x, 0.0)
        assert_close(planar_camera_msg.pose.pose.orientation.y, 0.0)

        rejected_unknown = False
        try:
            final_bridge.fill_odometry(
                Odometry(),
                payload("unknown_frame", (0.0, 0.0, 0.0)),
                node,
                legacy_config,
            )
        except ValueError:
            rejected_unknown = True
        if not rejected_unknown:
            raise AssertionError("unknown child frame was not rejected")

        print(json.dumps({
            "base": pose_dict(base_msg),
            "base_mode": base_mode,
            "legacy_camera": pose_dict(legacy_camera_msg),
            "rebased_camera": pose_dict(rebased_camera_msg),
            "rebased_origin": pose_dict(rebased_origin_msg),
            "planar_camera": pose_dict(planar_camera_msg),
            "camera_mode": camera_mode,
            "unknown_frame_rejected": rejected_unknown,
        }, indent=2, sort_keys=True))
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
