#!/usr/bin/env python3
"""Call the Isaac ROS 2.1 cuVSLAM save/load actions inside its container."""

import argparse
import json
import math
from pathlib import Path, PurePosixPath


LOAD_ACTION_NAME = "/visual_slam/load_map_and_localize"
SAVE_ACTION_NAME = "/visual_slam/save_map"


def validate_container_map_url(map_url, *, must_exist):
    path = PurePosixPath(str(map_url))
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("map_url must be an absolute container-local path without '..'")
    if must_exist and not Path(str(path)).exists():
        raise ValueError("saved map does not exist inside container: {}".format(path))
    if not must_exist and not Path(str(path.parent)).is_dir():
        raise ValueError("save_map parent does not exist inside container: {}".format(path.parent))
    return str(path)


def quaternion_to_yaw(quaternion):
    values = tuple(float(value) for value in quaternion)
    if len(values) != 4 or not all(math.isfinite(value) for value in values):
        raise ValueError("localization quaternion must contain four finite values")
    norm = math.sqrt(sum(value * value for value in values))
    if norm < 1.0e-9:
        raise ValueError("localization quaternion norm is zero")
    x, y, z, w = (value / norm for value in values)
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=120.0)
    subparsers = parser.add_subparsers(dest="command", required=True)
    save = subparsers.add_parser("save")
    save.add_argument("--map-url", required=True)
    load = subparsers.add_parser("load")
    load.add_argument("--map-url", required=True)
    load.add_argument("--near-x", required=True, type=float)
    load.add_argument("--near-y", required=True, type=float)
    load.add_argument("--near-z", type=float, default=0.0)
    return parser.parse_args(argv)


def execute(args):
    try:
        import rclpy
        from rclpy.action import ActionClient
        from isaac_ros_visual_slam_interfaces.action import LoadMapAndLocalize, SaveMap
    except ImportError as exc:
        raise RuntimeError(
            "run this client inside the Isaac ROS cuVSLAM container after sourcing its overlay"
        ) from exc

    if args.timeout <= 0.0 or not math.isfinite(args.timeout):
        raise ValueError("timeout must be a finite positive number")
    map_url = validate_container_map_url(
        args.map_url, must_exist=args.command == "load",
    )
    rclpy.init()
    node = rclpy.create_node("cuvslam_map_action_client")
    try:
        if args.command == "save":
            action_type = SaveMap
            action_name = SAVE_ACTION_NAME
            goal = SaveMap.Goal()
            goal.map_url = map_url
        else:
            action_type = LoadMapAndLocalize
            action_name = LOAD_ACTION_NAME
            goal = LoadMapAndLocalize.Goal()
            goal.map_url = map_url
            goal.localize_near_point.x = float(args.near_x)
            goal.localize_near_point.y = float(args.near_y)
            goal.localize_near_point.z = float(args.near_z)
        client = ActionClient(node, action_type, action_name)
        if not client.wait_for_server(timeout_sec=min(args.timeout, 30.0)):
            raise RuntimeError("action server unavailable: {}".format(action_name))
        send_future = client.send_goal_async(goal)
        rclpy.spin_until_future_complete(node, send_future, timeout_sec=args.timeout)
        if not send_future.done():
            raise RuntimeError("timed out while sending {} goal".format(args.command))
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            raise RuntimeError("{} goal was rejected".format(args.command))
        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(node, result_future, timeout_sec=args.timeout)
        if not result_future.done():
            goal_handle.cancel_goal_async()
            raise RuntimeError("timed out waiting for {} result".format(args.command))
        wrapped_result = result_future.result()
        result = wrapped_result.result
        document = {
            "command": args.command,
            "action_name": action_name,
            "status": int(wrapped_result.status),
            "success": bool(result.success),
            "map_url": map_url,
        }
        if args.command == "save":
            document["error"] = str(result.error)
        else:
            pose = result.pose
            document["localized_vslam_pose"] = {
                "x": float(pose.position.x),
                "y": float(pose.position.y),
                "z": float(pose.position.z),
                "yaw": quaternion_to_yaw((
                    pose.orientation.x,
                    pose.orientation.y,
                    pose.orientation.z,
                    pose.orientation.w,
                )),
            }
        print(json.dumps(document, sort_keys=True))
        return 0 if document["success"] else 4
    finally:
        node.destroy_node()
        rclpy.shutdown()


def main(argv=None):
    try:
        return execute(parse_args(argv))
    except (RuntimeError, ValueError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
