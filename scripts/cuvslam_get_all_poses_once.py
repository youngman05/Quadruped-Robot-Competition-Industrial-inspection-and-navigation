#!/usr/bin/env python3
"""Query the optimized cuVSLAM pose graph exactly once after motion stops."""

import argparse
import csv
import json
import math
import time
from pathlib import Path


def point_distance(a, b):
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def xy_point_distance(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def point_to_list(point):
    return [point.x, point.y, point.z]


def summarize_pose_stamped_list(poses):
    frame_id = None
    if poses:
        frame_id = poses[-1].header.frame_id or poses[0].header.frame_id
    summary = {
        "frame_id": frame_id,
        "poses": len(poses),
        "path_length_m": None,
        "xy_path_length_m": None,
        "closure_error_m": None,
        "xy_closure_error_m": None,
        "closure_error_ratio": None,
        "xy_closure_error_ratio": None,
        "max_step_m": None,
        "z_span_m": None,
        "first_position": None,
        "last_position": None,
    }
    if len(poses) < 2:
        return summary

    first = poses[0].pose.position
    last = poses[-1].pose.position
    path_length = 0.0
    xy_path_length = 0.0
    max_step = 0.0
    z_values = []
    for index, pose_stamped in enumerate(poses):
        position = pose_stamped.pose.position
        z_values.append(position.z)
        if index == 0:
            continue
        previous = poses[index - 1].pose.position
        step = point_distance(previous, position)
        path_length += step
        xy_path_length += xy_point_distance(previous, position)
        max_step = max(max_step, step)

    closure = point_distance(first, last)
    xy_closure = xy_point_distance(first, last)
    summary.update(
        {
            "path_length_m": path_length,
            "xy_path_length_m": xy_path_length,
            "closure_error_m": closure,
            "xy_closure_error_m": xy_closure,
            "closure_error_ratio": closure / path_length
            if path_length > 1e-9
            else None,
            "xy_closure_error_ratio": xy_closure / xy_path_length
            if xy_path_length > 1e-9
            else None,
            "max_step_m": max_step,
            "z_span_m": max(z_values) - min(z_values),
            "first_position": point_to_list(first),
            "last_position": point_to_list(last),
        }
    )
    return summary


def interpret(summary, min_path_length_m, good_closure_m, usable_closure_m):
    path_length = summary.get("xy_path_length_m")
    closure = summary.get("xy_closure_error_m")
    if path_length is None or closure is None:
        return "insufficient_data: optimized pose graph has fewer than two poses"
    if path_length < min_path_length_m:
        return (
            "insufficient_motion: optimized XY path is shorter than "
            f"{min_path_length_m:.3f} m"
        )
    if closure < good_closure_m:
        return "good_optimized_pose_graph_return_to_start"
    if closure < usable_closure_m:
        return "usable_optimized_pose_graph_return_to_start"
    return "poor_optimized_pose_graph_return_to_start"


def write_csv(path, poses):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "index",
                "stamp_sec",
                "frame_id",
                "x",
                "y",
                "z",
                "qx",
                "qy",
                "qz",
                "qw",
            ]
        )
        for index, pose_stamped in enumerate(poses):
            stamp = pose_stamped.header.stamp
            position = pose_stamped.pose.position
            orientation = pose_stamped.pose.orientation
            writer.writerow(
                [
                    index,
                    f"{stamp.sec + stamp.nanosec / 1e9:.9f}",
                    pose_stamped.header.frame_id,
                    f"{position.x:.9f}",
                    f"{position.y:.9f}",
                    f"{position.z:.9f}",
                    f"{orientation.x:.9f}",
                    f"{orientation.y:.9f}",
                    f"{orientation.z:.9f}",
                    f"{orientation.w:.9f}",
                ]
            )
    temporary.replace(path)


def format_optional(value):
    return "n/a" if value is None else f"{value:.6f}"


def format_position(value):
    if value is None:
        return "n/a"
    return "(" + ", ".join(f"{item:.6f}" for item in value) + ")"


def write_report(log_dir, poses, max_count, summary, interpretation):
    log_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at_unix": time.time(),
        "service": "/visual_slam/get_all_poses",
        "service_calls": 1,
        "requested_max_count": max_count,
        "service_success": True,
        "all_poses": summary,
        "interpretation": interpretation,
    }

    json_path = log_dir / "loop_metrics_latest.json"
    temporary_json = json_path.with_suffix(".json.tmp")
    temporary_json.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    temporary_json.replace(json_path)

    text_path = log_dir / "loop_metrics_latest.txt"
    lines = [
        "cuVSLAM post-run optimized pose graph",
        "service: /visual_slam/get_all_poses",
        "service_calls: 1",
        f"requested_max_count: {max_count}",
        "service_success: true",
        f"interpretation: {interpretation}",
        f"poses: {summary['poses']}",
        f"frame_id: {summary['frame_id']}",
        f"path_length_m: {format_optional(summary['path_length_m'])}",
        f"xy_path_length_m: {format_optional(summary['xy_path_length_m'])}",
        f"closure_error_m: {format_optional(summary['closure_error_m'])}",
        f"xy_closure_error_m: {format_optional(summary['xy_closure_error_m'])}",
        f"closure_error_ratio: {format_optional(summary['closure_error_ratio'])}",
        f"xy_closure_error_ratio: {format_optional(summary['xy_closure_error_ratio'])}",
        f"max_step_m: {format_optional(summary['max_step_m'])}",
        f"z_span_m: {format_optional(summary['z_span_m'])}",
        f"first_position: {format_position(summary['first_position'])}",
        f"last_position: {format_position(summary['last_position'])}",
    ]
    temporary_text = text_path.with_suffix(".txt.tmp")
    temporary_text.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary_text.replace(text_path)

    write_csv(log_dir / "slam_all_poses_latest.csv", poses)
    return json_path, text_path


def query_all_poses(max_count, service_wait_timeout, request_timeout):
    import rclpy
    from isaac_ros_visual_slam_interfaces.srv import GetAllPoses

    rclpy.init()
    node = rclpy.create_node("cuvslam_get_all_poses_once")
    try:
        client = node.create_client(GetAllPoses, "/visual_slam/get_all_poses")
        if not client.wait_for_service(timeout_sec=service_wait_timeout):
            raise RuntimeError("GetAllPoses service is unavailable")
        request = GetAllPoses.Request()
        request.max_count = max_count
        future = client.call_async(request)
        deadline = time.monotonic() + request_timeout
        while rclpy.ok() and not future.done():
            if time.monotonic() >= deadline:
                raise RuntimeError("GetAllPoses request timed out")
            rclpy.spin_once(node, timeout_sec=0.1)
        if not future.done():
            raise RuntimeError("ROS shutdown before GetAllPoses completed")
        response = future.result()
        if response is None:
            raise RuntimeError("GetAllPoses returned no response")
        if not response.success:
            raise RuntimeError("GetAllPoses returned success=false")
        return list(response.poses)
    finally:
        node.destroy_node()
        rclpy.shutdown()


def build_parser():
    parser = argparse.ArgumentParser(
        description="Query the complete optimized cuVSLAM pose graph once."
    )
    parser.add_argument("--log-dir", default="/logs/postrun_metrics_full")
    parser.add_argument("--max-count", type=int, default=100000)
    parser.add_argument("--service-wait-timeout", type=float, default=10.0)
    parser.add_argument("--request-timeout", type=float, default=60.0)
    parser.add_argument("--min-path-length", type=float, default=5.0)
    parser.add_argument("--good-closure", type=float, default=0.2)
    parser.add_argument("--usable-closure", type=float, default=0.5)
    return parser


def main():
    args = build_parser().parse_args()
    if args.max_count <= 0:
        raise SystemExit("--max-count must be positive")
    if not 0.0 < args.good_closure < args.usable_closure:
        raise SystemExit("closure thresholds must satisfy 0 < good < usable")

    poses = query_all_poses(
        args.max_count, args.service_wait_timeout, args.request_timeout
    )
    summary = summarize_pose_stamped_list(poses)
    interpretation = interpret(
        summary, args.min_path_length, args.good_closure, args.usable_closure
    )
    json_path, text_path = write_report(
        Path(args.log_dir), poses, args.max_count, summary, interpretation
    )
    print(f"GetAllPoses calls: 1")
    print(f"Optimized poses: {summary['poses']}")
    print(f"XY closure error: {format_optional(summary['xy_closure_error_m'])} m")
    print(f"Interpretation: {interpretation}")
    print(f"JSON: {json_path}")
    print(f"Text: {text_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
