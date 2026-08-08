#!/usr/bin/env python3
"""Query the optimized cuVSLAM pose graph exactly once after motion stops."""

import argparse
import csv
import json
import math
import time
from pathlib import Path
from types import SimpleNamespace


DEFAULT_POSE_TIMESTAMP_SCALE = 1000.0


def point_distance(a, b):
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def xy_point_distance(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def point_to_list(point):
    return [point.x, point.y, point.z]


def normalize_angle(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def quaternion_to_yaw(orientation):
    values = tuple(
        float(value)
        for value in (
            orientation.x,
            orientation.y,
            orientation.z,
            orientation.w,
        )
    )
    norm = math.sqrt(sum(value * value for value in values))
    if norm < 1.0e-12:
        raise ValueError("pose quaternion norm is zero")
    x, y, z, w = (value / norm for value in values)
    return math.atan2(
        2.0 * (w * z + x * y),
        1.0 - 2.0 * (y * y + z * z),
    )


def raw_pose_stamp_seconds(pose_stamped):
    stamp = pose_stamped.header.stamp
    return float(stamp.sec) + float(stamp.nanosec) / 1.0e9


def normalized_pose_stamp_seconds(pose_stamped, timestamp_scale):
    if not math.isfinite(timestamp_scale) or timestamp_scale <= 0.0:
        raise ValueError("pose timestamp scale must be finite and positive")
    return raw_pose_stamp_seconds(pose_stamped) * timestamp_scale


def load_tracking_window(start_path, end_path):
    start = json.loads(Path(start_path).read_text(encoding="utf-8"))
    end = json.loads(Path(end_path).read_text(encoding="utf-8"))
    start_stamp = float(start["header_stamp_sec"])
    end_stamp = float(end["header_stamp_sec"])
    if not math.isfinite(start_stamp) or not math.isfinite(end_stamp):
        raise ValueError("tracking window timestamps must be finite")
    if end_stamp <= start_stamp:
        raise ValueError("tracking window end must be after start")
    return start_stamp, end_stamp


def select_pose_window(poses, start_stamp_sec, end_stamp_sec, timestamp_scale):
    if end_stamp_sec <= start_stamp_sec:
        raise ValueError("pose window end must be after start")
    return [
        pose
        for pose in poses
        if start_stamp_sec
        <= normalized_pose_stamp_seconds(pose, timestamp_scale)
        <= end_stamp_sec
    ]


def load_pose_csv(path):
    poses = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            raw_stamp = float(row.get("raw_stamp_sec") or row["stamp_sec"])
            sec = math.floor(raw_stamp)
            nanosec = round((raw_stamp - sec) * 1.0e9)
            if nanosec >= 1_000_000_000:
                sec += 1
                nanosec -= 1_000_000_000
            poses.append(
                SimpleNamespace(
                    header=SimpleNamespace(
                        frame_id=row.get("frame_id", ""),
                        stamp=SimpleNamespace(sec=sec, nanosec=nanosec),
                    ),
                    pose=SimpleNamespace(
                        position=SimpleNamespace(
                            x=float(row["x"]),
                            y=float(row["y"]),
                            z=float(row["z"]),
                        ),
                        orientation=SimpleNamespace(
                            x=float(row["qx"]),
                            y=float(row["qy"]),
                            z=float(row["qz"]),
                            w=float(row["qw"]),
                        ),
                    ),
                )
            )
    return poses


def summarize_pose_stamped_list(poses, timestamp_scale=1.0):
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
        "first_stamp_sec": None,
        "last_stamp_sec": None,
        "yaw_closure_rad": None,
        "yaw_closure_deg": None,
        "pose_timestamp_scale": timestamp_scale,
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
    yaw_closure = normalize_angle(
        quaternion_to_yaw(poses[-1].pose.orientation)
        - quaternion_to_yaw(poses[0].pose.orientation)
    )
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
            "first_stamp_sec": normalized_pose_stamp_seconds(
                poses[0], timestamp_scale
            ),
            "last_stamp_sec": normalized_pose_stamp_seconds(
                poses[-1], timestamp_scale
            ),
            "yaw_closure_rad": yaw_closure,
            "yaw_closure_deg": math.degrees(yaw_closure),
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


def write_csv(path, poses, timestamp_scale=1.0):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "index",
                "stamp_sec",
                "raw_stamp_sec",
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
            position = pose_stamped.pose.position
            orientation = pose_stamped.pose.orientation
            raw_stamp = raw_pose_stamp_seconds(pose_stamped)
            writer.writerow(
                [
                    index,
                    f"{raw_stamp * timestamp_scale:.9f}",
                    f"{raw_stamp:.9f}",
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


def write_report(
    log_dir,
    poses,
    max_count,
    summary,
    interpretation,
    timestamp_scale=1.0,
    tracking_window=None,
):
    log_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at_unix": time.time(),
        "service": "/visual_slam/get_all_poses",
        "service_calls": 1,
        "requested_max_count": max_count,
        "service_success": True,
        "pose_timestamp_scale": timestamp_scale,
        "all_poses": summary,
        "tracking_window": tracking_window,
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
        f"pose_timestamp_scale: {timestamp_scale:.9f}",
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
    if tracking_window is not None:
        lines.extend(
            [
                "tracking_window_present: true",
                "tracking_window_start_stamp_sec: "
                + format_optional(tracking_window["requested_start_stamp_sec"]),
                "tracking_window_end_stamp_sec: "
                + format_optional(tracking_window["requested_end_stamp_sec"]),
                f"tracking_window_poses: {tracking_window['poses']}",
                "tracking_window_xy_path_length_m: "
                + format_optional(tracking_window["xy_path_length_m"]),
                "tracking_window_xy_closure_error_m: "
                + format_optional(tracking_window["xy_closure_error_m"]),
                "tracking_window_xy_closure_error_ratio: "
                + format_optional(tracking_window["xy_closure_error_ratio"]),
                "tracking_window_yaw_closure_deg: "
                + format_optional(tracking_window["yaw_closure_deg"]),
            ]
        )
    temporary_text = text_path.with_suffix(".txt.tmp")
    temporary_text.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary_text.replace(text_path)

    write_csv(
        log_dir / "slam_all_poses_latest.csv",
        poses,
        timestamp_scale=timestamp_scale,
    )
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
    parser.add_argument(
        "--pose-timestamp-scale",
        type=float,
        default=DEFAULT_POSE_TIMESTAMP_SCALE,
        help="Scale GetAllPoses pose stamps into tracking UNIX seconds.",
    )
    parser.add_argument("--tracking-start")
    parser.add_argument("--tracking-end")
    return parser


def main():
    args = build_parser().parse_args()
    if args.max_count <= 0:
        raise SystemExit("--max-count must be positive")
    if not 0.0 < args.good_closure < args.usable_closure:
        raise SystemExit("closure thresholds must satisfy 0 < good < usable")
    if not math.isfinite(args.pose_timestamp_scale) or args.pose_timestamp_scale <= 0:
        raise SystemExit("--pose-timestamp-scale must be finite and positive")
    if bool(args.tracking_start) != bool(args.tracking_end):
        raise SystemExit("--tracking-start and --tracking-end must be used together")

    poses = query_all_poses(
        args.max_count, args.service_wait_timeout, args.request_timeout
    )
    summary = summarize_pose_stamped_list(poses, args.pose_timestamp_scale)
    tracking_window = None
    if args.tracking_start:
        start_stamp, end_stamp = load_tracking_window(
            args.tracking_start, args.tracking_end
        )
        window_poses = select_pose_window(
            poses,
            start_stamp,
            end_stamp,
            args.pose_timestamp_scale,
        )
        tracking_window = summarize_pose_stamped_list(
            window_poses, args.pose_timestamp_scale
        )
        tracking_window.update(
            {
                "requested_start_stamp_sec": start_stamp,
                "requested_end_stamp_sec": end_stamp,
            }
        )
    decision_summary = tracking_window or summary
    interpretation = interpret(
        decision_summary,
        args.min_path_length,
        args.good_closure,
        args.usable_closure,
    )
    json_path, text_path = write_report(
        Path(args.log_dir),
        poses,
        args.max_count,
        summary,
        interpretation,
        timestamp_scale=args.pose_timestamp_scale,
        tracking_window=tracking_window,
    )
    print(f"GetAllPoses calls: 1")
    print(f"Optimized poses: {summary['poses']}")
    print(f"XY closure error: {format_optional(summary['xy_closure_error_m'])} m")
    if tracking_window is not None:
        print(
            "Tracking-window XY closure error: "
            f"{format_optional(tracking_window['xy_closure_error_m'])} m"
        )
        print(
            "Tracking-window yaw closure: "
            f"{format_optional(tracking_window['yaw_closure_deg'])} deg"
        )
    print(f"Interpretation: {interpretation}")
    print(f"JSON: {json_path}")
    print(f"Text: {text_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
