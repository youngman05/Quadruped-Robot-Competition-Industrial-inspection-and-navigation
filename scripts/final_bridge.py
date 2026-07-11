#!/usr/bin/env python3
"""Bridge Docker cuVSLAM UDP odometry to host /odom and odom->base_link TF."""
import argparse
import csv
import json
import math
import os
import socket
import subprocess
import sys
import time

import rclpy
from geometry_msgs.msg import TransformStamped
from nav_msgs.msg import Odometry
from rclpy.qos import QoSProfile, ReliabilityPolicy
from tf2_ros import TransformBroadcaster

try:
    from rclpy.qos import HistoryPolicy
except ImportError:
    from rclpy.qos import QoSHistoryPolicy as HistoryPolicy


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=19001)
    parser.add_argument("--topic", default="/visual_slam/tracking/odometry")
    parser.add_argument("--exporter-path", default="/tmp/cuvslam_odometry_udp_exporter.py")
    parser.add_argument(
        "--local-exporter-path",
        default=os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "cuvslam_odometry_udp_exporter.py",
        ),
    )
    parser.add_argument("--expected-container-substring", default="cuvslam")
    parser.add_argument("--log-every", type=int, default=300)
    parser.add_argument("--startup-timeout", type=float, default=8.0)
    parser.add_argument("--qos-depth", type=int, default=1)
    parser.add_argument("--stale-drop-ms", type=float, default=150.0)
    parser.add_argument("--packet-size", type=int, default=65535)
    parser.add_argument(
        "--no-start-exporter",
        action="store_true",
        help="Only listen on UDP; assume exporter is already running in Docker.",
    )
    parser.add_argument("--camera-frame", default="camera_link")
    parser.add_argument("--base-frame", default="base_link")
    parser.add_argument("--odom-frame", default="odom")
    parser.add_argument(
        "--transform-camera-pose-to-base",
        dest="transform_camera_pose_to_base",
        action="store_true",
        default=True,
        help="Convert camera-frame odometry to the robot base frame.",
    )
    parser.add_argument(
        "--no-transform-camera-pose-to-base",
        dest="transform_camera_pose_to_base",
        action="store_false",
        help="Reject camera-frame odometry instead of converting it.",
    )
    parser.add_argument("--base-to-camera-x", type=float, default=0.080)
    parser.add_argument("--base-to-camera-y", type=float, default=0.000)
    parser.add_argument("--base-to-camera-z", type=float, default=0.493)
    parser.add_argument("--base-to-camera-roll", type=float, default=0.0)
    parser.add_argument("--base-to-camera-pitch", type=float, default=0.523599)
    parser.add_argument("--base-to-camera-yaw", type=float, default=0.0)
    parser.add_argument(
        "--comparison-csv",
        default="/tmp/final_bridge_odom_compare.csv",
        help="Write source and bridged poses from each accepted UDP packet.",
    )
    return parser.parse_args()


def find_container(name_substring):
    output = subprocess.check_output(
        ["docker", "ps", "--format", "{{.Names}}"], text=True
    )
    for line in output.splitlines():
        if name_substring in line:
            return line
    raise RuntimeError(f"No Docker container matching {name_substring!r}")


def start_exporter(container, args):
    command = (
        "source /opt/ros/humble/setup.bash && "
        "source /workspaces/isaac_ros-dev/install/setup.bash && "
        f"python3 {args.exporter_path} "
        f"--topic {args.topic} --host {args.host} --port {args.port} "
        f"--qos-depth {args.qos_depth} "
        f"--log-every {args.log_every} "
        ">/tmp/cuvslam_odometry_udp_exporter.log 2>&1"
    )
    return subprocess.Popen(
        ["docker", "exec", container, "bash", "-lc", command],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop_exporter(container):
    subprocess.run(
        [
            "docker",
            "exec",
            container,
            "bash",
            "-lc",
            "pkill -f '[c]uvslam_odometry_udp_exporter.py' 2>/dev/null || true",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def copy_exporter_to_container(container, args):
    if not os.path.exists(args.local_exporter_path):
        raise RuntimeError(f"Local exporter not found: {args.local_exporter_path}")
    subprocess.check_call(
        ["docker", "cp", args.local_exporter_path, f"{container}:{args.exporter_path}"]
    )


def drain_exporter_output(exporter, node):
    return


def set_stamp(stamp_msg, payload):
    stamp = payload.get("stamp") or {}
    if "sec" in stamp:
        stamp_msg.sec = int(stamp["sec"])
        stamp_msg.nanosec = int(stamp.get("nanosec") or 0)
        return "source"
    return "host_now"


def payload_stamp_seconds(payload):
    stamp = payload.get("stamp") or {}
    if "sec" not in stamp:
        return None
    return float(stamp["sec"]) + float(stamp.get("nanosec") or 0) / 1e9


def normalize_quat(q):
    norm = math.sqrt(sum(value * value for value in q))
    if norm == 0.0:
        return (0.0, 0.0, 0.0, 1.0)
    return tuple(value / norm for value in q)


def quat_conjugate(q):
    x, y, z, w = q
    return (-x, -y, -z, w)


def quat_multiply_raw(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def quat_multiply(a, b):
    return normalize_quat(quat_multiply_raw(a, b))


def rotate_vector(q, vector):
    qv = (vector[0], vector[1], vector[2], 0.0)
    rotated = quat_multiply_raw(
        quat_multiply_raw(q, qv),
        quat_conjugate(q),
    )
    return (rotated[0], rotated[1], rotated[2])


def quat_from_rpy(roll, pitch, yaw):
    cr = math.cos(roll * 0.5)
    sr = math.sin(roll * 0.5)
    cp = math.cos(pitch * 0.5)
    sp = math.sin(pitch * 0.5)
    cy = math.cos(yaw * 0.5)
    sy = math.sin(yaw * 0.5)
    return normalize_quat((
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    ))


def cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def make_transform_config(args):
    t_base_camera = (
        args.base_to_camera_x,
        args.base_to_camera_y,
        args.base_to_camera_z,
    )
    q_base_camera = quat_from_rpy(
        args.base_to_camera_roll,
        args.base_to_camera_pitch,
        args.base_to_camera_yaw,
    )
    q_camera_base = quat_conjugate(q_base_camera)
    t_camera_base = rotate_vector(
        q_camera_base,
        tuple(-value for value in t_base_camera),
    )
    return {
        "camera_frame": args.camera_frame,
        "base_frame": args.base_frame,
        "odom_frame": args.odom_frame,
        "transform_camera_pose_to_base": args.transform_camera_pose_to_base,
        "t_base_camera": t_base_camera,
        "q_base_camera": q_base_camera,
        "q_camera_base": q_camera_base,
        "t_camera_base": t_camera_base,
    }


def camera_pose_to_base_pose(position, orientation, config):
    offset_odom = rotate_vector(orientation, config["t_camera_base"])
    position_base = tuple(position[i] + offset_odom[i] for i in range(3))
    orientation_base = quat_multiply(orientation, config["q_camera_base"])
    return position_base, orientation_base


def camera_twist_to_base_twist(linear, angular, config):
    angular_base = rotate_vector(config["q_base_camera"], angular)
    camera_linear_base = rotate_vector(config["q_base_camera"], linear)
    correction = cross(angular_base, config["t_base_camera"])
    linear_base = tuple(camera_linear_base[i] - correction[i] for i in range(3))
    return linear_base, angular_base


def fill_odometry(msg, payload, node, config):
    stamp_source = set_stamp(msg.header.stamp, payload)
    if stamp_source == "host_now":
        msg.header.stamp = node.get_clock().now().to_msg()

    source_child = str(payload.get("child_frame_id") or "").strip()
    if source_child == config["base_frame"]:
        transform_mode = "base_passthrough"
    elif source_child == config["camera_frame"]:
        if not config["transform_camera_pose_to_base"]:
            raise ValueError("camera-frame odometry conversion is disabled")
        transform_mode = "camera_to_base"
    else:
        raise ValueError(
            f"unexpected child_frame_id={source_child!r}; expected "
            f"{config['base_frame']!r} or {config['camera_frame']!r}"
        )

    msg.header.frame_id = config["odom_frame"]
    msg.child_frame_id = config["base_frame"]

    pose = payload.get("pose") or {}
    position = pose.get("position") or {}
    orientation = pose.get("orientation") or {}
    pose_position = (
        float(position.get("x") or 0.0),
        float(position.get("y") or 0.0),
        float(position.get("z") or 0.0),
    )
    pose_orientation = normalize_quat((
        float(orientation.get("x") or 0.0),
        float(orientation.get("y") or 0.0),
        float(orientation.get("z") or 0.0),
        float(orientation.get("w") or 1.0),
    ))

    pose_covariance = payload.get("pose_covariance") or []
    for idx, value in enumerate(pose_covariance[:36]):
        msg.pose.covariance[idx] = float(value)

    twist = payload.get("twist") or {}
    linear = twist.get("linear") or {}
    angular = twist.get("angular") or {}
    twist_linear = (
        float(linear.get("x") or 0.0),
        float(linear.get("y") or 0.0),
        float(linear.get("z") or 0.0),
    )
    twist_angular = (
        float(angular.get("x") or 0.0),
        float(angular.get("y") or 0.0),
        float(angular.get("z") or 0.0),
    )

    if transform_mode == "camera_to_base":
        pose_position, pose_orientation = camera_pose_to_base_pose(
            pose_position, pose_orientation, config
        )
        twist_linear, twist_angular = camera_twist_to_base_twist(
            twist_linear, twist_angular, config
        )

    msg.pose.pose.position.x = pose_position[0]
    msg.pose.pose.position.y = pose_position[1]
    msg.pose.pose.position.z = pose_position[2]
    msg.pose.pose.orientation.x = pose_orientation[0]
    msg.pose.pose.orientation.y = pose_orientation[1]
    msg.pose.pose.orientation.z = pose_orientation[2]
    msg.pose.pose.orientation.w = pose_orientation[3]
    msg.twist.twist.linear.x = twist_linear[0]
    msg.twist.twist.linear.y = twist_linear[1]
    msg.twist.twist.linear.z = twist_linear[2]
    msg.twist.twist.angular.x = twist_angular[0]
    msg.twist.twist.angular.y = twist_angular[1]
    msg.twist.twist.angular.z = twist_angular[2]

    twist_covariance = payload.get("twist_covariance") or []
    for idx, value in enumerate(twist_covariance[:36]):
        msg.twist.covariance[idx] = float(value)

    return stamp_source, source_child, transform_mode


def fill_transform(transform, msg):
    transform.header.stamp = msg.header.stamp
    transform.header.frame_id = msg.header.frame_id
    transform.child_frame_id = msg.child_frame_id
    transform.transform.translation.x = msg.pose.pose.position.x
    transform.transform.translation.y = msg.pose.pose.position.y
    transform.transform.translation.z = msg.pose.pose.position.z
    transform.transform.rotation = msg.pose.pose.orientation


def open_comparison_csv(path):
    if not path:
        return None, None
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    handle = open(path, "w", newline="")
    writer = csv.writer(handle)
    writer.writerow([
        "sequence",
        "source_stamp",
        "source_frame_id",
        "source_child_frame_id",
        "transform_mode",
        "raw_x", "raw_y", "raw_z",
        "raw_qx", "raw_qy", "raw_qz", "raw_qw",
        "host_x", "host_y", "host_z",
        "host_qx", "host_qy", "host_qz", "host_qw",
    ])
    handle.flush()
    return handle, writer


def write_comparison_row(writer, handle, sequence, payload, msg, stamp_source,
                         source_child, transform_mode):
    if writer is None:
        return
    pose = payload.get("pose") or {}
    position = pose.get("position") or {}
    orientation = pose.get("orientation") or {}
    out_position = msg.pose.pose.position
    out_orientation = msg.pose.pose.orientation
    writer.writerow([
        sequence,
        stamp_source,
        payload.get("frame_id") or "",
        source_child,
        transform_mode,
        float(position.get("x") or 0.0),
        float(position.get("y") or 0.0),
        float(position.get("z") or 0.0),
        float(orientation.get("x") or 0.0),
        float(orientation.get("y") or 0.0),
        float(orientation.get("z") or 0.0),
        float(orientation.get("w") or 1.0),
        out_position.x,
        out_position.y,
        out_position.z,
        out_orientation.x,
        out_orientation.y,
        out_orientation.z,
        out_orientation.w,
    ])
    handle.flush()


def recv_latest_datagram(sock, packet_size, timeout_sec):
    sock.settimeout(timeout_sec)
    data, addr = sock.recvfrom(packet_size)
    latest_data = data
    latest_addr = addr
    drained = 0

    sock.setblocking(False)
    try:
        while True:
            try:
                data, addr = sock.recvfrom(packet_size)
            except (BlockingIOError, InterruptedError):
                break
            latest_data = data
            latest_addr = addr
            drained += 1
    finally:
        sock.settimeout(timeout_sec)

    return latest_data, latest_addr, drained


def main():
    args = parse_args()
    rclpy.init()
    qos = QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=args.qos_depth,
        reliability=ReliabilityPolicy.BEST_EFFORT,
    )
    node = rclpy.create_node("final_bridge")
    pub = node.create_publisher(Odometry, "/odom", qos)
    tf_broadcaster = TransformBroadcaster(node)
    transform_config = make_transform_config(args)
    node.get_logger().info(
        "frame policy: "
        f"camera={transform_config['camera_frame']} "
        f"base={transform_config['base_frame']} "
        f"extrinsic_t={transform_config['t_base_camera']} "
        f"extrinsic_q={transform_config['q_base_camera']}"
    )
    verify = [0]

    def self_cb(msg):
        verify[0] += 1

    node.create_subscription(Odometry, "/odom", self_cb, qos)

    exporter = None
    container = None
    if not args.no_start_exporter:
        container = find_container(args.expected_container_substring)
        node.get_logger().info(f"Docker: {container}")
        copy_exporter_to_container(container, args)
        exporter = start_exporter(container, args)
        node.get_logger().info(
            f"started UDP exporter for {args.topic} on {args.host}:{args.port}"
        )

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((args.host, args.port))
    except OSError as exc:
        sock.close()
        raise RuntimeError(
            f"Cannot bind udp://{args.host}:{args.port}. "
            "A stale final_bridge.py may still be running; run scripts/fix_bridge.sh "
            "or pkill -f '[f]inal_bridge.py'."
        ) from exc
    sock.settimeout(0.2)
    node.get_logger().info(f"listening on udp://{args.host}:{args.port}")
    comparison_handle, comparison_writer = open_comparison_csv(args.comparison_csv)
    if comparison_handle is not None:
        node.get_logger().info(f"comparison CSV: {args.comparison_csv}")

    count = 0
    received = 0
    drained_old = 0
    dropped_stale = 0
    dropped_invalid = 0
    first_packet_deadline = time.monotonic() + args.startup_timeout
    try:
        while rclpy.ok():
            try:
                data, _, drained = recv_latest_datagram(
                    sock, args.packet_size, timeout_sec=0.2
                )
            except socket.timeout:
                if exporter is not None and exporter.poll() is not None:
                    drain_exporter_output(exporter, node)
                    raise RuntimeError(f"UDP exporter exited with code {exporter.returncode}")
                rclpy.spin_once(node, timeout_sec=0.0)
                if count == 0 and time.monotonic() > first_packet_deadline:
                    node.get_logger().warn("still waiting for first UDP odometry packet")
                    first_packet_deadline = time.monotonic() + args.startup_timeout
                continue

            received += drained + 1
            drained_old += drained
            try:
                payload = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                dropped_invalid += 1
                node.get_logger().warn(f"dropping invalid UDP packet: {exc}")
                continue

            source_time = payload_stamp_seconds(payload)
            latency_ms = None
            if source_time is not None:
                latency_ms = (time.time() - source_time) * 1000.0
                if args.stale_drop_ms > 0 and latency_ms > args.stale_drop_ms:
                    dropped_stale += 1
                    if args.log_every > 0 and dropped_stale % args.log_every == 1:
                        node.get_logger().warn(
                            f"dropped stale odom packet latency={latency_ms:.2f} ms "
                            f"> {args.stale_drop_ms:.2f} ms | "
                            f"recv={received} drained_old={drained_old} "
                            f"stale_drop={dropped_stale}"
                        )
                    rclpy.spin_once(node, timeout_sec=0.0)
                    continue

            count += 1
            msg = Odometry()
            try:
                stamp_source, source_child, transform_mode = fill_odometry(
                    msg, payload, node, transform_config
                )
            except ValueError as exc:
                dropped_invalid += 1
                node.get_logger().warn(f"dropping odom packet: {exc}")
                rclpy.spin_once(node, timeout_sec=0.0)
                continue
            pub.publish(msg)
            write_comparison_row(
                comparison_writer,
                comparison_handle,
                count,
                payload,
                msg,
                stamp_source,
                source_child,
                transform_mode,
            )
            transform = TransformStamped()
            fill_transform(transform, msg)
            tf_broadcaster.sendTransform(transform)

            # Write latest odom to file (DDS bypass for Navigator on Jetson)
            try:
                with open('/tmp/odom_latest.json', 'w') as f:
                    import json as _json
                    _json.dump({
                        'x': msg.pose.pose.position.x,
                        'y': msg.pose.pose.position.y,
                        'z': msg.pose.pose.position.z,
                        'qx': msg.pose.pose.orientation.x,
                        'qy': msg.pose.pose.orientation.y,
                        'qz': msg.pose.pose.orientation.z,
                        'qw': msg.pose.pose.orientation.w,
                        'stamp': stamp_source if stamp_source else time.time(),
                        'source_child_frame_id': source_child,
                        'transform_mode': transform_mode,
                    }, f)
            except Exception:
                pass

            rclpy.spin_once(node, timeout_sec=0.0)
            if args.log_every > 0 and count % args.log_every == 1:
                stamp = msg.header.stamp
                latency_text = (
                    "nan" if latency_ms is None else f"{latency_ms:.2f} ms"
                )
                node.get_logger().info(
                    f"bridged {count} UDP msgs | stamp={stamp.sec}.{stamp.nanosec:09d} "
                    f"({stamp_source}) | latency={latency_text} | recv={received} "
                    f"drained_old={drained_old} stale_drop={dropped_stale} "
                    f"invalid_drop={dropped_invalid} | self-verify: {verify[0]}"
                    f" | source_child={source_child} mode={transform_mode}"
                )
    finally:
        sock.close()
        if comparison_handle is not None:
            comparison_handle.close()
        if exporter is not None and exporter.poll() is None:
            exporter.terminate()
            try:
                exporter.wait(timeout=3)
            except subprocess.TimeoutExpired:
                exporter.kill()
        if container is not None:
            stop_exporter(container)
        drain_exporter_output(exporter, node)
        node.get_logger().info(
            f"DONE: {count} bridged, {verify[0]} self-verified, "
            f"{received} UDP received, {drained_old} drained_old, "
            f"{dropped_stale} stale_drop, {dropped_invalid} invalid_drop"
        )
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
