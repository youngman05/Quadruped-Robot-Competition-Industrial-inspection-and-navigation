#!/usr/bin/env python3
"""Bridge Docker cuVSLAM UDP odometry to host /odom and odom->base_link TF."""
import argparse
import json
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


def fill_odometry(msg, payload, node):
    stamp_source = set_stamp(msg.header.stamp, payload)
    if stamp_source == "host_now":
        msg.header.stamp = node.get_clock().now().to_msg()

    # Keep the host-side frame contract stable for the current Foxy stack.
    msg.header.frame_id = "odom"
    msg.child_frame_id = "base_link"

    pose = payload.get("pose") or {}
    position = pose.get("position") or {}
    orientation = pose.get("orientation") or {}
    msg.pose.pose.position.x = float(position.get("x") or 0.0)
    msg.pose.pose.position.y = float(position.get("y") or 0.0)
    msg.pose.pose.position.z = float(position.get("z") or 0.0)
    msg.pose.pose.orientation.x = float(orientation.get("x") or 0.0)
    msg.pose.pose.orientation.y = float(orientation.get("y") or 0.0)
    msg.pose.pose.orientation.z = float(orientation.get("z") or 0.0)
    msg.pose.pose.orientation.w = float(orientation.get("w") or 1.0)

    pose_covariance = payload.get("pose_covariance") or []
    for idx, value in enumerate(pose_covariance[:36]):
        msg.pose.covariance[idx] = float(value)

    twist = payload.get("twist") or {}
    linear = twist.get("linear") or {}
    angular = twist.get("angular") or {}
    msg.twist.twist.linear.x = float(linear.get("x") or 0.0)
    msg.twist.twist.linear.y = float(linear.get("y") or 0.0)
    msg.twist.twist.linear.z = float(linear.get("z") or 0.0)
    msg.twist.twist.angular.x = float(angular.get("x") or 0.0)
    msg.twist.twist.angular.y = float(angular.get("y") or 0.0)
    msg.twist.twist.angular.z = float(angular.get("z") or 0.0)

    twist_covariance = payload.get("twist_covariance") or []
    for idx, value in enumerate(twist_covariance[:36]):
        msg.twist.covariance[idx] = float(value)

    return stamp_source


def fill_transform(transform, msg):
    transform.header.stamp = msg.header.stamp
    transform.header.frame_id = "odom"
    transform.child_frame_id = "base_link"
    transform.transform.translation.x = msg.pose.pose.position.x
    transform.transform.translation.y = msg.pose.pose.position.y
    transform.transform.translation.z = msg.pose.pose.position.z
    transform.transform.rotation = msg.pose.pose.orientation


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
            stamp_source = fill_odometry(msg, payload, node)
            pub.publish(msg)

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
                )
    finally:
        sock.close()
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
