#!/usr/bin/env python3
"""Run isolated Foxy cone-scan bridge/gate acceptance and write JSON evidence."""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Callable, Dict, List, Optional

try:
    from nodes.navigation.cone_scan_synthetic import scenario_frame
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from nodes.navigation.cone_scan_synthetic import scenario_frame


PACKAGE = "quadruped_robot_competition"
SCHEMA = "cone_scan_l2_l3_acceptance/v1"
DEFAULT_PORT = 19012
PRODUCTION_PORT = 19002
DEFAULT_ROS_DOMAIN_ID = 93
PRODUCTION_ROS_DOMAIN_ID = 0
TOPICS = {
    "scan": "/cone_l3/scan",
    "health": "/cone_l3/health",
    "cmd_in": "/cone_l3/cmd_in",
    "cmd_out": "/cone_l3/cmd_out",
    "gate_status": "/cone_l3/gate_status",
}
TEST_COMMAND = (0.12, 0.0, -0.04)
ZERO_EPSILON = 1e-6
GRACEFUL_EXIT_CODES = (0, -int(signal.SIGINT), 128 + int(signal.SIGINT))


class AcceptanceFailure(RuntimeError):
    pass


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--startup-timeout-sec", type=float, default=12.0)
    parser.add_argument("--step-timeout-sec", type=float, default=3.0)
    parser.add_argument("--deadline-sec", type=float, default=0.25)
    parser.add_argument("--ros2-command", default="ros2")
    parser.add_argument("--ros-domain-id", type=int, default=DEFAULT_ROS_DOMAIN_ID)
    parser.add_argument("--output")
    parser.add_argument(
        "--confirm-isolated-no-actuator",
        action="store_true",
        help="Confirm that only this probe subscribes to the isolated gate output.",
    )
    return parser.parse_args(argv)


def validate_isolation(args) -> None:
    try:
        address = ipaddress.ip_address(str(args.host))
    except ValueError as exc:
        raise AcceptanceFailure("--host must be a numeric IPv4 loopback address") from exc
    if address.version != 4 or not address.is_loopback:
        raise AcceptanceFailure("L3 probe UDP host must be IPv4 loopback")
    if int(args.port) == PRODUCTION_PORT or not 1024 <= int(args.port) <= 65535:
        raise AcceptanceFailure("L3 probe must use a valid non-production UDP port")
    if (
        int(args.ros_domain_id) == PRODUCTION_ROS_DOMAIN_ID
        or not 1 <= int(args.ros_domain_id) <= 232
    ):
        raise AcceptanceFailure("L3 probe must use a non-production ROS domain in [1, 232]")
    if not args.confirm_isolated_no_actuator:
        raise AcceptanceFailure(
            "pass --confirm-isolated-no-actuator after physically disabling/isolation actuators"
        )
    if any(not topic.startswith("/cone_l3/") for topic in TOPICS.values()):
        raise AcceptanceFailure("all probe topics must remain under /cone_l3/")
    if TOPICS["cmd_out"] == "/cmd_vel":
        raise AcceptanceFailure("probe output must never target production cmd_vel")


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def default_output_path() -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return Path.cwd() / ("cone_l3_acceptance_%s.json" % stamp)


def atomic_write_json(path: Path, value: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def is_nonzero(values) -> bool:
    return any(abs(float(value)) > ZERO_EPSILON for value in values)


def ros_parameter(name: str, value) -> List[str]:
    if isinstance(value, bool):
        rendered = "true" if value else "false"
    else:
        rendered = str(value)
    return ["-p", "%s:=%s" % (name, rendered)]


def process_command(ros2: str, executable: str, parameters: Dict[str, object]):
    command = [ros2, "run", PACKAGE, executable, "--ros-args"]
    for name, value in parameters.items():
        command.extend(ros_parameter(name, value))
    return command


def start_process(command, log_path: Path):
    handle = log_path.open("w", encoding="utf-8")
    try:
        process = subprocess.Popen(
            command,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=(os.name != "nt"),
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            ),
        )
    except Exception:
        handle.close()
        raise
    return process, handle


def signal_process_group(process: subprocess.Popen, signum: int) -> None:
    if os.name == "nt":
        if signum == signal.SIGINT:
            process.send_signal(signal.CTRL_BREAK_EVENT)
        elif signum == signal.SIGTERM:
            process.terminate()
        else:
            process.kill()
        return
    os.killpg(process.pid, signum)


def stop_process(process: subprocess.Popen) -> int:
    if process.poll() is not None:
        if os.name != "nt":
            try:
                signal_process_group(process, signal.SIGINT)
            except ProcessLookupError:
                pass
        return int(process.returncode)
    try:
        signal_process_group(process, signal.SIGINT)
        process.wait(timeout=4.0)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            try:
                signal_process_group(process, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                try:
                    signal_process_group(process, getattr(signal, "SIGKILL", 9))
                except ProcessLookupError:
                    pass
                process.wait(timeout=2.0)
    return int(process.returncode)


def load_ros():
    try:
        import rclpy
        from geometry_msgs.msg import Twist
        from rclpy.node import Node
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        from sensor_msgs.msg import LaserScan
        from std_msgs.msg import String
    except ImportError as exc:
        raise AcceptanceFailure(
            "Foxy rclpy messages are unavailable; source the installed workspace first"
        ) from exc
    try:
        from rclpy.qos import HistoryPolicy
    except ImportError:
        from rclpy.qos import QoSHistoryPolicy as HistoryPolicy
    return rclpy, Node, Twist, LaserScan, String, QoSProfile, ReliabilityPolicy, HistoryPolicy


def make_probe_node(ros):
    rclpy, Node, Twist, LaserScan, String, QoSProfile, ReliabilityPolicy, HistoryPolicy = ros

    class ConeL3ProbeNode(Node):
        def __init__(self):
            super().__init__("cone_scan_l3_acceptance_probe")
            self.scan_events = []
            self.health_events = []
            self.gate_events = []
            self.output_events = []
            self.command_enabled = False
            sensor_qos = QoSProfile(
                history=HistoryPolicy.KEEP_LAST,
                depth=10,
                reliability=ReliabilityPolicy.BEST_EFFORT,
            )
            reliable_qos = QoSProfile(
                history=HistoryPolicy.KEEP_LAST,
                depth=20,
                reliability=ReliabilityPolicy.RELIABLE,
            )
            self.command_publisher = self.create_publisher(
                Twist, TOPICS["cmd_in"], reliable_qos
            )
            self.create_subscription(
                LaserScan, TOPICS["scan"], self._on_scan, sensor_qos
            )
            self.create_subscription(
                String, TOPICS["health"], self._on_health, reliable_qos
            )
            self.create_subscription(
                String, TOPICS["gate_status"], self._on_gate, reliable_qos
            )
            self.create_subscription(
                Twist, TOPICS["cmd_out"], self._on_output, reliable_qos
            )
            self.create_timer(0.05, self._publish_command)

        def _publish_command(self):
            message = Twist()
            if self.command_enabled:
                message.linear.x = TEST_COMMAND[0]
                message.linear.y = TEST_COMMAND[1]
                message.angular.z = TEST_COMMAND[2]
            self.command_publisher.publish(message)

        def _on_scan(self, message):
            finite = [float(value) for value in message.ranges if math.isfinite(float(value))]
            self.scan_events.append(
                {
                    "at": time.monotonic(),
                    "stamp_ns": int(message.header.stamp.sec) * 1_000_000_000
                    + int(message.header.stamp.nanosec),
                    "frame_id": str(message.header.frame_id),
                    "beam_count": len(message.ranges),
                    "finite_count": len(finite),
                    "minimum_range": min(finite) if finite else None,
                }
            )

        def _json_event(self, target, message):
            try:
                data = json.loads(message.data)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                data = {"decode_error": str(exc), "raw": str(message.data)}
            target.append({"at": time.monotonic(), "data": data})

        def _on_health(self, message):
            self._json_event(self.health_events, message)

        def _on_gate(self, message):
            self._json_event(self.gate_events, message)

        def _on_output(self, message):
            values = (
                float(message.linear.x),
                float(message.linear.y),
                float(message.angular.z),
            )
            self.output_events.append(
                {"at": time.monotonic(), "values": values, "nonzero": is_nonzero(values)}
            )

    return ConeL3ProbeNode()


class AcceptanceRunner:
    def __init__(self, rclpy, node, args):
        self.rclpy = rclpy
        self.node = node
        self.args = args
        self.target = (str(args.host), int(args.port))
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.steps = []

    def close(self):
        self.socket.close()

    def spin_for(self, duration: float) -> None:
        deadline = time.monotonic() + max(0.0, float(duration))
        while time.monotonic() < deadline:
            self.rclpy.spin_once(
                self.node,
                timeout_sec=min(0.02, max(0.0, deadline - time.monotonic())),
            )

    def wait_for(self, predicate: Callable[[], object], label: str, timeout=None):
        deadline = time.monotonic() + float(
            timeout if timeout is not None else self.args.step_timeout_sec
        )
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            self.rclpy.spin_once(self.node, timeout_sec=0.02)
        raise AcceptanceFailure("timed out waiting for %s" % label)

    @staticmethod
    def latest(events, start_index: int, predicate):
        for event in reversed(events[start_index:]):
            if predicate(event):
                return event
        return None

    def send(self, scenario: str, stream_id: str, sequence: int):
        frame = scenario_frame(
            scenario,
            stream_id=stream_id,
            sequence=sequence,
        )
        if frame.payload is None:
            raise AcceptanceFailure("cannot send silence frame")
        sent_at = time.monotonic()
        self.socket.sendto(frame.payload, self.target)
        return sent_at, frame

    def health_after(self, start_index: int, predicate, label: str):
        return self.wait_for(
            lambda: self.latest(
                self.node.health_events,
                start_index,
                lambda event: predicate(event.get("data", {})),
            ),
            label,
        )

    def output_after(self, start_index: int, nonzero: bool, label: str, timeout=None):
        return self.wait_for(
            lambda: self.latest(
                self.node.output_events,
                start_index,
                lambda event: bool(event["nonzero"]) is bool(nonzero),
            ),
            label,
            timeout,
        )

    def run_step(self, name: str, operation):
        started = time.monotonic()
        try:
            evidence = operation()
        except Exception as exc:
            self.steps.append(
                {
                    "name": name,
                    "passed": False,
                    "duration_ms": round(
                        (time.monotonic() - started) * 1000.0, 3
                    ),
                    "error": "%s: %s" % (type(exc).__name__, exc),
                }
            )
            raise
        self.steps.append({
            "name": name,
            "passed": True,
            "duration_ms": round((time.monotonic() - started) * 1000.0, 3),
            "evidence": evidence,
        })
        return evidence

    def graph_isolation(self):
        def graph_ready():
            return bool(
                self.node.count_subscribers(TOPICS["cmd_in"]) == 1
                and self.node.count_publishers(TOPICS["cmd_out"]) == 1
                and self.node.count_publishers(TOPICS["scan"]) == 1
                and self.node.count_publishers(TOPICS["health"]) == 1
                and self.node.count_publishers(TOPICS["gate_status"]) == 1
            )

        self.wait_for(graph_ready, "isolated ROS graph", self.args.startup_timeout_sec)
        counts = {
            key: {
                "publishers": self.node.count_publishers(topic),
                "subscribers": self.node.count_subscribers(topic),
            }
            for key, topic in TOPICS.items()
        }
        if counts["cmd_out"]["subscribers"] != 1:
            raise AcceptanceFailure(
                "isolated gate output has %d subscribers; expected only this probe"
                % counts["cmd_out"]["subscribers"]
            )
        if counts["cmd_in"]["publishers"] != 1:
            raise AcceptanceFailure("isolated gate input has an unexpected publisher")
        self.node.command_enabled = True
        return {"topics": TOPICS, "counts": counts, "nonzero_command_armed": True}

    def warm_stream(self, label: str):
        stream_id = uuid.uuid5(uuid.NAMESPACE_DNS, "cone-l3-%s" % label).hex
        observations = []
        for sequence in (1, 2, 3):
            health_index = len(self.node.health_events)
            output_index = len(self.node.output_events)
            sent_at, _ = self.send("healthy-cone", stream_id, sequence)
            health = self.health_after(
                health_index,
                lambda data, seq=sequence: bool(data.get("healthy"))
                and data.get("stream_id") == stream_id
                and int(data.get("sequence", 0)) == seq,
                "healthy sequence %d" % sequence,
            )
            if sequence < 3:
                zero = self.output_after(
                    output_index, False, "zero output during warmup %d" % sequence
                )
                observations.append(
                    {"sequence": sequence, "health": health["data"], "output": zero["values"]}
                )
            else:
                passed = self.output_after(
                    output_index, True, "nonzero output after third healthy frame"
                )
                observations.append(
                    {
                        "sequence": sequence,
                        "health": health["data"],
                        "output": passed["values"],
                        "latency_ms": round((passed["at"] - sent_at) * 1000.0, 3),
                    }
                )
        return stream_id, observations

    def initial_warmup(self):
        stream_id, observations = self.warm_stream("initial")
        return {"stream_id": stream_id, "frames": observations}

    def clear_scan(self):
        stream_id = uuid.uuid5(uuid.NAMESPACE_DNS, "cone-l3-initial").hex
        health_index = len(self.node.health_events)
        scan_index = len(self.node.scan_events)
        self.send("clear", stream_id, 4)
        health = self.health_after(
            health_index,
            lambda data: bool(data.get("healthy")) and int(data.get("sequence", 0)) == 4,
            "healthy clear scan",
        )
        scan = self.wait_for(
            lambda: self.latest(
                self.node.scan_events,
                scan_index,
                lambda event: event["beam_count"] == 180 and event["finite_count"] == 0,
            ),
            "published clear LaserScan",
        )
        return {"health": health["data"], "scan": scan}

    def fault_case(self, scenario: str):
        stream_id, _ = self.warm_stream("fault-%s" % scenario)
        health_index = len(self.node.health_events)
        output_index = len(self.node.output_events)
        sequence = 2 if scenario == "sequence-regression" else 4
        sent_at, _ = self.send(scenario, stream_id, sequence)
        health = self.health_after(
            health_index,
            lambda data: data.get("healthy") is False,
            "%s unhealthy status" % scenario,
        )
        zero = self.output_after(
            output_index, False, "%s fail-closed zero" % scenario
        )
        latency = zero["at"] - sent_at
        if latency > float(self.args.deadline_sec):
            raise AcceptanceFailure(
                "%s fail-closed latency %.3f ms exceeds %.3f ms"
                % (scenario, latency * 1000.0, self.args.deadline_sec * 1000.0)
            )
        return {
            "scenario": scenario,
            "health": health["data"],
            "zero_output": zero["values"],
            "fail_closed_latency_ms": round(latency * 1000.0, 3),
            "deadline_ms": round(float(self.args.deadline_sec) * 1000.0, 3),
        }

    def backlog(self):
        stream_id = uuid.uuid5(uuid.NAMESPACE_DNS, "cone-l3-backlog").hex
        health_index = len(self.node.health_events)
        previous_drained = max(
            [int(event.get("data", {}).get("drained_old", 0)) for event in self.node.health_events]
            or [0]
        )
        for sequence in range(1, 33):
            self.send("backlog", stream_id, sequence)
        health = self.health_after(
            health_index,
            lambda data: bool(data.get("healthy"))
            and data.get("stream_id") == stream_id
            and int(data.get("sequence", 0)) == 32,
            "latest backlog sequence",
        )
        drained = int(health["data"].get("drained_old", 0)) - previous_drained
        if drained < 1:
            raise AcceptanceFailure("bridge did not report draining an older backlog packet")
        return {
            "sent_sequences": [1, 32],
            "accepted_sequence": int(health["data"]["sequence"]),
            "drained_old_delta": drained,
            "health": health["data"],
        }

    def stream_restart(self):
        old_stream, _ = self.warm_stream("restart-old")
        new_stream = uuid.uuid5(uuid.NAMESPACE_DNS, "cone-l3-restart-new").hex
        frames = []
        for sequence in (1, 2, 3):
            health_index = len(self.node.health_events)
            output_index = len(self.node.output_events)
            self.send("stream-restart", new_stream, sequence)
            health = self.health_after(
                health_index,
                lambda data, seq=sequence: bool(data.get("healthy"))
                and data.get("stream_id") == new_stream
                and int(data.get("sequence", 0)) == seq,
                "new stream sequence %d" % sequence,
            )
            output = self.output_after(
                output_index,
                sequence == 3,
                "new stream warmup output %d" % sequence,
            )
            frames.append(
                {
                    "sequence": sequence,
                    "health": health["data"],
                    "output": output["values"],
                }
            )
        return {"old_stream": old_stream, "new_stream": new_stream, "frames": frames}

    def silence(self):
        stream_id, _ = self.warm_stream("silence")
        health_index = len(self.node.health_events)
        sent_at, _ = self.send("healthy-cone", stream_id, 4)
        self.health_after(
            health_index,
            lambda data: bool(data.get("healthy")) and int(data.get("sequence", 0)) == 4,
            "final healthy frame before silence",
        )
        last_packet_at = sent_at
        health_index = len(self.node.health_events)
        output_index = len(self.node.output_events)
        zero = self.output_after(output_index, False, "silence fail-closed zero", timeout=1.0)
        latency = zero["at"] - last_packet_at
        if latency > float(self.args.deadline_sec):
            raise AcceptanceFailure(
                "silence fail-closed latency %.3f ms exceeds %.3f ms"
                % (latency * 1000.0, self.args.deadline_sec * 1000.0)
            )
        health = self.health_after(
            health_index,
            lambda data: data.get("healthy") is False,
            "bridge stale health",
        )
        return {
            "stream_id": stream_id,
            "zero_output": zero["values"],
            "fail_closed_latency_ms": round(latency * 1000.0, 3),
            "deadline_ms": round(float(self.args.deadline_sec) * 1000.0, 3),
            "health": health["data"],
        }

    def run(self):
        self.run_step("graph_isolation", self.graph_isolation)
        self.run_step("three_frame_warmup", self.initial_warmup)
        self.run_step("healthy_clear_scan", self.clear_scan)
        for scenario in (
            "isolated-point",
            "short-run",
            "unhealthy-depth",
            "stale",
            "future",
            "bad-crc",
            "sequence-regression",
        ):
            self.run_step("fail_closed_%s" % scenario.replace("-", "_"), lambda s=scenario: self.fault_case(s))
        self.run_step("latest_only_backlog", self.backlog)
        self.run_step("stream_restart_warmup", self.stream_restart)
        self.run_step("silence_deadline", self.silence)
        return self.steps


def main(argv=None) -> int:
    args = parse_args(argv)
    output_path = Path(args.output).expanduser().resolve() if args.output else default_output_path().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    evidence = {
        "schema": SCHEMA,
        "started_at": now_iso(),
        "verification_level": "L3",
        "robot_connected": False,
        "actuator_output": False,
        "passed": False,
        "udp": {"host": args.host, "port": int(args.port)},
        "ros_domain_id": int(args.ros_domain_id),
        "ros_localhost_only": True,
        "topics": TOPICS,
        "test_command": TEST_COMMAND,
        "steps": [],
        "processes": {},
    }
    processes = []
    log_handles = []
    node = None
    rclpy = None
    rclpy_initialized = False
    runner = None
    try:
        validate_isolation(args)
        os.environ["ROS_LOCALHOST_ONLY"] = "1"
        os.environ["ROS_DOMAIN_ID"] = str(int(args.ros_domain_id))
        ros = load_ros()
        rclpy = ros[0]
        rclpy.init(args=None)
        rclpy_initialized = True
        node = make_probe_node(ros)
        bridge_log = output_path.with_suffix(".bridge.log")
        gate_log = output_path.with_suffix(".gate.log")
        bridge_command = process_command(
            args.ros2_command,
            "cone_scan_udp_bridge",
            {
                "bind_host": args.host,
                "port": int(args.port),
                "scan_topic": TOPICS["scan"],
                "health_topic": TOPICS["health"],
                "frame_id": "base_link",
                "poll_rate_hz": 20.0,
                "packet_timeout_sec": 0.25,
                "source_max_age_sec": 0.25,
                "expected_beams": 180,
            },
        )
        gate_command = process_command(
            args.ros2_command,
            "cone_scan_safety_gate",
            {
                "input_topic": TOPICS["cmd_in"],
                "output_topic": TOPICS["cmd_out"],
                "health_topic": TOPICS["health"],
                "status_topic": TOPICS["gate_status"],
                "output_rate_hz": 40.0,
                "health_timeout_sec": 0.20,
                "required_consecutive_frames": 3,
            },
        )
        for name, command, log_path in (
            ("bridge", bridge_command, bridge_log),
            ("gate", gate_command, gate_log),
        ):
            process, handle = start_process(command, log_path)
            processes.append((name, process))
            log_handles.append(handle)
            evidence["processes"][name] = {
                "pid": process.pid,
                "command": command,
                "log": str(log_path),
            }
        runner = AcceptanceRunner(rclpy, node, args)
        evidence["steps"] = runner.run()
        evidence["passed"] = True
    except Exception as exc:
        evidence["error"] = "%s: %s" % (type(exc).__name__, exc)
        if runner is not None:
            evidence["steps"] = runner.steps
    finally:
        cleanup_errors = []
        if runner is not None:
            try:
                runner.close()
            except Exception as exc:
                cleanup_errors.append("probe socket: %s" % exc)
        if node is not None:
            try:
                node.command_enabled = False
                for _ in range(3):
                    node._publish_command()
                    rclpy.spin_once(node, timeout_sec=0.02)
            except Exception as exc:
                cleanup_errors.append("final zero command: %s" % exc)
        for name, process in reversed(processes):
            try:
                exit_code = stop_process(process)
                evidence["processes"][name]["exit_code"] = exit_code
                if exit_code not in GRACEFUL_EXIT_CODES:
                    cleanup_errors.append("%s exit code %d" % (name, exit_code))
            except Exception as exc:
                evidence["processes"][name]["exit_code"] = None
                cleanup_errors.append("%s cleanup: %s" % (name, exc))
        for handle in log_handles:
            try:
                handle.close()
            except Exception as exc:
                cleanup_errors.append("log close: %s" % exc)
        if node is not None:
            try:
                node.destroy_node()
            except Exception as exc:
                cleanup_errors.append("probe node: %s" % exc)
        if rclpy_initialized:
            try:
                rclpy.shutdown()
            except Exception as exc:
                cleanup_errors.append("rclpy shutdown: %s" % exc)
        if cleanup_errors:
            evidence["cleanup_error"] = "; ".join(cleanup_errors)
            evidence["passed"] = False
        evidence["finished_at"] = now_iso()
        atomic_write_json(output_path, evidence)
        print(json.dumps({"passed": evidence["passed"], "evidence": str(output_path)}))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
