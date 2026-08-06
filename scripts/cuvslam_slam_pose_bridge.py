#!/usr/bin/env python3
"""Bridge rectified cuVSLAM pose to a diagnostic ``vslam_map`` topic.

This process intentionally publishes no TF and never writes ``/odom``.  It
can run beside the existing VO ``final_bridge.py`` without changing its UDP
port or payload contract.
"""

import argparse
import csv
import json
import math
import os
import socket
import subprocess
import time

import rclpy
from nav_msgs.msg import Odometry
from rclpy.qos import QoSProfile, ReliabilityPolicy

try:
    from rclpy.qos import HistoryPolicy
except ImportError:
    from rclpy.qos import QoSHistoryPolicy as HistoryPolicy

from nodes.navigation.global_pose_manager import normalize_quaternion, pose_sample_from_payload


def quat_from_rpy(roll, pitch, yaw):
    cr, sr = math.cos(roll * 0.5), math.sin(roll * 0.5)
    cp, sp = math.cos(pitch * 0.5), math.sin(pitch * 0.5)
    cy, sy = math.cos(yaw * 0.5), math.sin(yaw * 0.5)
    return normalize_quaternion((
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    ))


def quat_conjugate(quaternion):
    x, y, z, w = quaternion
    return (-x, -y, -z, w)


def quat_multiply_raw(first, second):
    ax, ay, az, aw = first
    bx, by, bz, bw = second
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def quat_multiply(first, second):
    return normalize_quaternion(quat_multiply_raw(first, second))


def rotate_vector(quaternion, vector):
    rotated = quat_multiply_raw(
        quat_multiply_raw(quaternion, (vector[0], vector[1], vector[2], 0.0)),
        quat_conjugate(quaternion),
    )
    return rotated[:3]


def transform_payload_to_base(payload, args):
    """Convert camera child pose to base child while preserving vslam_map."""
    source_child = str(payload.get("child_frame_id") or "").strip()
    if source_child not in (args.base_frame, args.camera_frame):
        raise ValueError("unexpected child_frame_id={!r}".format(source_child))
    pose = payload.get("pose") or {}
    position = pose.get("position") or {}
    orientation = pose.get("orientation") or {}
    source_position = (
        float(position["x"]), float(position["y"]), float(position.get("z", 0.0))
    )
    source_orientation = normalize_quaternion((
        orientation["x"], orientation["y"], orientation["z"], orientation["w"]
    ))
    if source_child == args.camera_frame:
        offset = rotate_vector(source_orientation, args.base_to_camera)
        output_position = tuple(source_position[i] + offset[i] for i in range(3))
        output_orientation = quat_multiply(source_orientation, args.camera_to_base)
    else:
        output_position, output_orientation = source_position, source_orientation
    if args.planarize_output:
        yaw = math.atan2(
            2.0 * (output_orientation[3] * output_orientation[2] + output_orientation[0] * output_orientation[1]),
            1.0 - 2.0 * (output_orientation[1] ** 2 + output_orientation[2] ** 2),
        )
        output_position = (output_position[0], output_position[1], 0.0)
        output_orientation = (0.0, 0.0, math.sin(yaw * 0.5), math.cos(yaw * 0.5))
    result = dict(payload)
    result["source_child_frame_id"] = source_child
    result["frame_id"] = args.output_frame
    result["child_frame_id"] = args.base_frame
    result["pose"] = {
        "position": {"x": output_position[0], "y": output_position[1], "z": output_position[2]},
        "orientation": {"x": output_orientation[0], "y": output_orientation[1], "z": output_orientation[2], "w": output_orientation[3]},
    }
    return result


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=19002)
    parser.add_argument("--topic", default="/cuvslam/slam_pose")
    parser.add_argument("--exporter-path", default="/tmp/cuvslam_slam_pose_udp_exporter.py")
    parser.add_argument("--local-exporter-path", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "cuvslam_slam_pose_udp_exporter.py"))
    parser.add_argument("--expected-container-substring", default="cuvslam")
    parser.add_argument("--no-start-exporter", action="store_true")
    parser.add_argument("--stale-drop-ms", type=float, default=250.0)
    parser.add_argument("--packet-size", type=int, default=65535)
    parser.add_argument("--qos-depth", type=int, default=10)
    parser.add_argument("--camera-frame", default="camera_link")
    parser.add_argument("--base-frame", default="base_link")
    parser.add_argument("--output-frame", default="vslam_map")
    parser.add_argument("--base-to-camera-x", type=float, default=0.080)
    parser.add_argument("--base-to-camera-y", type=float, default=0.000)
    parser.add_argument("--base-to-camera-z", type=float, default=0.493)
    parser.add_argument("--base-to-camera-roll", type=float, default=0.0)
    parser.add_argument("--base-to-camera-pitch", type=float, default=0.523599)
    parser.add_argument("--base-to-camera-yaw", type=float, default=0.0)
    parser.add_argument("--planarize-output", action="store_true")
    parser.add_argument("--comparison-csv", default="/tmp/cuvslam_slam_pose_compare.csv")
    return parser.parse_args()


def find_container(substring):
    output = subprocess.check_output(["docker", "ps", "--format", "{{.Names}}"], text=True)
    for name in output.splitlines():
        if substring in name:
            return name
    raise RuntimeError("no Docker container matching {!r}".format(substring))


def start_exporter(container, args):
    command = (
        "source /opt/ros/humble/setup.bash && "
        "source /workspaces/isaac_ros-dev/install/setup.bash && "
        "python3 %s --topic /visual_slam/vis/slam_odometry --host %s --port %d "
        ">/tmp/cuvslam_slam_pose_udp_exporter.log 2>&1" %
        (args.exporter_path, args.host, args.port)
    )
    return subprocess.Popen(["docker", "exec", container, "bash", "-lc", command])


def stop_exporter(container):
    subprocess.run(["docker", "exec", container, "bash", "-lc", "pkill -f '[c]uvslam_slam_pose_udp_exporter.py'"], check=False)


def make_args_transform(args):
    args.base_to_camera = (args.base_to_camera_x, args.base_to_camera_y, args.base_to_camera_z)
    args.camera_to_base = quat_conjugate(quat_from_rpy(args.base_to_camera_roll, args.base_to_camera_pitch, args.base_to_camera_yaw))
    return args


def main():
    args = make_args_transform(parse_args())
    rclpy.init()
    node = rclpy.create_node("cuvslam_slam_pose_bridge")
    qos = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=args.qos_depth, reliability=ReliabilityPolicy.BEST_EFFORT)
    publisher = node.create_publisher(Odometry, args.topic, qos)
    container = None
    exporter = None
    if not args.no_start_exporter:
        container = find_container(args.expected_container_substring)
        subprocess.check_call(["docker", "cp", args.local_exporter_path, "%s:%s" % (container, args.exporter_path)])
        exporter = start_exporter(container, args)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    csv_handle = open(args.comparison_csv, "w", newline="", encoding="utf-8") if args.comparison_csv else None
    writer = csv.writer(csv_handle) if csv_handle else None
    if writer:
        writer.writerow(["seq", "source_stamp", "received_at", "source_frame", "source_child", "output_frame", "output_child", "x", "y", "z", "yaw"])
    received = dropped_stale = dropped_invalid = published = 0
    try:
        node.get_logger().info("listening on udp://%s:%d; publishing %s without TF" % (args.host, args.port, args.topic))
        while rclpy.ok():
            sock.settimeout(0.5)
            try:
                data, _ = sock.recvfrom(args.packet_size)
            except socket.timeout:
                if exporter is not None and exporter.poll() is not None:
                    raise RuntimeError("SLAM exporter exited with code %s" % exporter.returncode)
                rclpy.spin_once(node, timeout_sec=0.0)
                continue
            received += 1
            received_at = time.time()
            try:
                payload = json.loads(data.decode("utf-8"))
                sample = pose_sample_from_payload(payload, frame_override=args.output_frame, child_override=args.base_frame)
                payload = transform_payload_to_base(payload, args)
                if payload.get("receive_time") is not None and received_at - float(payload["receive_time"]) > args.stale_drop_ms / 1000.0:
                    dropped_stale += 1
                    continue
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                dropped_invalid += 1
                node.get_logger().warning("dropping invalid SLAM packet: %s" % exc)
                continue
            message = Odometry()
            stamp = payload.get("stamp") or {}
            message.header.stamp.sec = int(stamp["sec"])
            message.header.stamp.nanosec = int(stamp.get("nanosec", 0))
            message.header.frame_id = args.output_frame
            message.child_frame_id = args.base_frame
            position = payload["pose"]["position"]
            orientation = payload["pose"]["orientation"]
            message.pose.pose.position.x = float(position["x"])
            message.pose.pose.position.y = float(position["y"])
            message.pose.pose.position.z = float(position["z"])
            message.pose.pose.orientation.x = float(orientation["x"])
            message.pose.pose.orientation.y = float(orientation["y"])
            message.pose.pose.orientation.z = float(orientation["z"])
            message.pose.pose.orientation.w = float(orientation["w"])
            publisher.publish(message)
            published += 1
            if writer:
                writer.writerow([sample.sequence, sample.source_stamp, received_at, payload.get("source_frame_id", payload.get("frame_id", "")), payload.get("source_child_frame_id", ""), args.output_frame, args.base_frame, message.pose.pose.position.x, message.pose.pose.position.y, message.pose.pose.position.z, sample.yaw])
                csv_handle.flush()
    finally:
        sock.close()
        if csv_handle:
            csv_handle.close()
        if exporter is not None and exporter.poll() is None:
            exporter.terminate()
            try:
                exporter.wait(timeout=3)
            except subprocess.TimeoutExpired:
                exporter.kill()
        if container:
            stop_exporter(container)
        node.get_logger().info("DONE received=%d published=%d stale_drop=%d invalid_drop=%d" % (received, published, dropped_stale, dropped_invalid))
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
