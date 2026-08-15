"""Fail-closed velocity gate driven by validated cone scan health."""

from __future__ import annotations

import json
import time

import rclpy
from geometry_msgs.msg import Twist
from rcl_interfaces.srv import GetParameters, SetParameters
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

from nodes.navigation.depth_contract import DepthMode, parse_depth_mode
from nodes.navigation.cone_scan_safety import (
    ZERO_COMMAND,
    ConeLayerAppliedTracker,
    ConeScanHealthTracker,
)

try:
    from rclpy.qos import DurabilityPolicy, HistoryPolicy
except ImportError:
    from rclpy.qos import QoSDurabilityPolicy as DurabilityPolicy
    from rclpy.qos import QoSHistoryPolicy as HistoryPolicy


class ConeScanSafetyGate(Node):
    def __init__(self) -> None:
        super().__init__("cone_scan_safety_gate")
        self.declare_parameter("input_topic", "/cmd_vel_selected")
        self.declare_parameter("output_topic", "/cmd_vel")
        self.declare_parameter("health_topic", "/cone_obstacle/health")
        self.declare_parameter("status_topic", "/cone_obstacle/safety_gate_status")
        self.declare_parameter("mode_status_topic", "/depth/mode_status")
        self.declare_parameter(
            "local_layer_status_topic",
            "/local_costmap/cone_obstacle_layer/applied_status",
        )
        self.declare_parameter(
            "global_layer_status_topic",
            "/global_costmap/cone_obstacle_layer/applied_status",
        )
        self.declare_parameter("enable_mode_control", False)
        self.declare_parameter("mode_status_timeout_sec", 1.0)
        self.declare_parameter("resource_transition_timeout_sec", 8.0)
        self.declare_parameter("output_rate_hz", 40.0)
        self.declare_parameter("status_rate_hz", 5.0)
        self.declare_parameter("command_timeout_sec", 0.35)
        # At 40 Hz, a 0.20 s lease leaves one 25 ms output tick plus
        # scheduling margin inside the externally claimed 250 ms deadline.
        self.declare_parameter("health_timeout_sec", 0.20)
        self.declare_parameter("required_consecutive_frames", 3)

        output_rate = max(5.0, float(self.get_parameter("output_rate_hz").value))
        status_rate = max(1.0, float(self.get_parameter("status_rate_hz").value))
        self._status_divisor = max(1, int(round(output_rate / status_rate)))
        self._tick = 0
        self._command_timeout = max(
            0.05, float(self.get_parameter("command_timeout_sec").value)
        )
        self._command = ZERO_COMMAND
        self._command_time = None
        self._enable_mode_control = bool(
            self.get_parameter("enable_mode_control").value
        )
        self._mode_status_timeout = max(
            0.2, float(self.get_parameter("mode_status_timeout_sec").value)
        )
        self._resource_transition_timeout = max(
            1.0,
            float(self.get_parameter("resource_transition_timeout_sec").value),
        )
        self._requested_mode = DepthMode.AVOIDANCE
        self._controller_mode = DepthMode.AVOIDANCE
        self._mode_acknowledged = not self._enable_mode_control
        self._controller_healthy = not self._enable_mode_control
        self._active_request_id = ""
        self._last_mode_status_time = float("-inf")
        self._resource_generation = None
        self._resource_stage = "ready" if not self._enable_mode_control else "waiting_mode"
        self._resource_started = float("-inf")
        self._resource_futures = []
        self._resource_expected_enabled = True
        self._resource_ready = not self._enable_mode_control
        self._resource_reason = (
            "legacy cone scan mode" if not self._enable_mode_control else "waiting for depth mode"
        )
        self._tracker = ConeScanHealthTracker(
            required_consecutive=int(
                self.get_parameter("required_consecutive_frames").value
            ),
            max_age_sec=float(self.get_parameter("health_timeout_sec").value),
        )
        self._layer_tracker = ConeLayerAppliedTracker()

        self._publisher = self.create_publisher(
            Twist, str(self.get_parameter("output_topic").value), 10
        )
        self._status_publisher = self.create_publisher(
            String, str(self.get_parameter("status_topic").value), 10
        )
        self.create_subscription(
            Twist,
            str(self.get_parameter("input_topic").value),
            self._on_command,
            10,
        )
        health_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
        )
        self.create_subscription(
            String,
            str(self.get_parameter("health_topic").value),
            self._on_health,
            health_qos,
        )
        if self._enable_mode_control:
            self.create_subscription(
                String,
                str(self.get_parameter("mode_status_topic").value),
                self._on_mode_status,
                10,
            )
            costmap_nodes = [
                "/local_costmap/local_costmap",
                "/global_costmap/global_costmap",
            ]
            self._costmap_set_clients = [
                self.create_client(SetParameters, node + "/set_parameters")
                for node in costmap_nodes
            ]
            self._costmap_get_clients = [
                self.create_client(GetParameters, node + "/get_parameters")
                for node in costmap_nodes
            ]
            layer_status_qos = QoSProfile(
                history=HistoryPolicy.KEEP_LAST,
                depth=1,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
            )
            self.create_subscription(
                String,
                str(self.get_parameter("local_layer_status_topic").value),
                lambda msg: self._on_layer_status("local", msg),
                layer_status_qos,
            )
            self.create_subscription(
                String,
                str(self.get_parameter("global_layer_status_topic").value),
                lambda msg: self._on_layer_status("global", msg),
                layer_status_qos,
            )
        else:
            self._costmap_set_clients = []
            self._costmap_get_clients = []
        self.create_timer(1.0 / output_rate, self._publish)
        self.get_logger().info(
            "cone scan safety gate ready | timeout=%.3fs required_frames=%d mode_control=%s"
            % (
                self._tracker.max_age_sec,
                self._tracker.required_consecutive,
                self._enable_mode_control,
            )
        )

    def _on_command(self, msg: Twist) -> None:
        self._command = (
            float(msg.linear.x),
            float(msg.linear.y),
            float(msg.angular.z),
        )
        self._command_time = time.monotonic()

    def _on_health(self, msg: String) -> None:
        now = time.monotonic()
        try:
            data = json.loads(msg.data)
            self._tracker.observe(
                stream_id=str(data.get("stream_id", "")),
                sequence=int(data.get("sequence", 0)),
                healthy=bool(data.get("healthy", False)),
                now=now,
                reason=str(data.get("reason", "")),
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self._tracker.observe("", 0, False, now, "invalid health JSON: %s" % exc)

    def _on_mode_status(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
            requested_mode = parse_depth_mode(
                data.get("requested_mode", data.get("mode"))
            )
            controller_mode = parse_depth_mode(data.get("mode"))
            active_request_id = str(data.get("active_request_id", ""))
            generation = (active_request_id, requested_mode.value)
            self._requested_mode = requested_mode
            self._controller_mode = controller_mode
            self._active_request_id = active_request_id
            self._mode_acknowledged = bool(data.get("acknowledged", False))
            self._controller_healthy = bool(data.get("healthy", False))
            self._last_mode_status_time = time.monotonic()
            if generation != self._resource_generation:
                self._resource_generation = generation
                self._resource_stage = "waiting_ack"
                self._resource_started = time.monotonic()
                self._resource_futures = []
                self._layer_tracker.cancel_transition()
                self._resource_ready = False
                self._resource_reason = "waiting for depth controller acknowledgement"
        except Exception as exc:  # noqa: BLE001
            self._requested_mode = DepthMode.FAULT
            self._controller_mode = DepthMode.FAULT
            self._mode_acknowledged = False
            self._controller_healthy = False
            self._resource_ready = False
            self._resource_reason = "invalid depth mode status: %s" % exc

    def _on_layer_status(self, source: str, msg: String) -> None:
        try:
            data = json.loads(msg.data)
            if not isinstance(data, dict):
                raise ValueError("status JSON must be an object")
            self._layer_tracker.observe(source, data, time.monotonic())
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self._layer_tracker.record_error(source, str(exc))

    @staticmethod
    def _parameter_results_succeeded(response) -> bool:
        results = list(getattr(response, "results", []))
        return bool(results) and all(result.successful for result in results)

    def _advance_resource_transition(self, now: float) -> None:
        if not self._enable_mode_control or self._resource_ready:
            return
        if now - self._resource_started > self._resource_transition_timeout:
            self._resource_stage = "fault"
            self._resource_reason = "cone resource transition timed out"
            return
        mode_status_fresh = (
            0.0 <= now - self._last_mode_status_time <= self._mode_status_timeout
        )
        if self._resource_stage == "waiting_ack":
            if not (
                mode_status_fresh
                and self._mode_acknowledged
                and self._controller_healthy
                and self._controller_mode == self._requested_mode
                and bool(self._active_request_id)
            ):
                return
            enabled = self._requested_mode == DepthMode.AVOIDANCE
            if not self._layer_tracker.begin_transition(enabled):
                self._resource_reason = self._layer_tracker.last_reason
                return
            if not all(
                client.wait_for_service(timeout_sec=0.0)
                for client in self._costmap_set_clients
            ):
                self._resource_reason = "waiting for costmap parameter services"
                return
            parameter = Parameter(
                "cone_obstacle_layer.enabled",
                Parameter.Type.BOOL,
                enabled,
            )
            self._resource_futures = []
            for client in self._costmap_set_clients:
                request = SetParameters.Request()
                request.parameters = [parameter.to_parameter_msg()]
                self._resource_futures.append(client.call_async(request))
            self._resource_expected_enabled = enabled
            self._resource_stage = "setting_layers"
            self._resource_reason = "setting cone costmap layers enabled=%s" % enabled
            return
        if self._resource_stage == "setting_layers":
            if not all(future.done() for future in self._resource_futures):
                return
            try:
                if not all(
                    self._parameter_results_succeeded(future.result())
                    for future in self._resource_futures
                ):
                    raise RuntimeError("costmap layer parameter change was rejected")
            except Exception as exc:  # noqa: BLE001
                self._resource_stage = "fault"
                self._resource_reason = "cone costmap layer transition failed: %s" % exc
                return
            if not all(
                client.wait_for_service(timeout_sec=0.0)
                for client in self._costmap_get_clients
            ):
                self._resource_stage = "waiting_get_services"
                self._resource_reason = "waiting for costmap parameter readback services"
                return
            self._start_costmap_parameter_readback()
            return
        if self._resource_stage == "waiting_get_services":
            if not all(
                client.wait_for_service(timeout_sec=0.0)
                for client in self._costmap_get_clients
            ):
                return
            self._start_costmap_parameter_readback()
            return
        if self._resource_stage == "verifying_layers":
            if not all(future.done() for future in self._resource_futures):
                return
            try:
                for future in self._resource_futures:
                    values = list(getattr(future.result(), "values", []))
                    if (
                        len(values) != 1
                        or bool(values[0].bool_value)
                        != self._resource_expected_enabled
                    ):
                        raise RuntimeError("cone costmap layer readback mismatch")
            except Exception as exc:  # noqa: BLE001
                self._resource_stage = "fault"
                self._resource_reason = "cone costmap layer verification failed: %s" % exc
                return
            self._resource_futures = []
            self._resource_stage = "waiting_layer_apply"
            self._resource_reason = "waiting for local/global cone layer application"
            return
        if self._resource_stage == "waiting_layer_apply":
            ready, reason = self._layer_tracker.readiness()
            if not ready:
                self._resource_reason = reason
                return
            self._resource_stage = "ready"
            self._resource_ready = True
            self._resource_reason = (
                "cone costmap layers enabled and applied"
                if self._resource_expected_enabled
                else "cone costmap layers disabled and stale halo cleared"
            )

    def _start_costmap_parameter_readback(self) -> None:
        self._resource_futures = []
        for client in self._costmap_get_clients:
            request = GetParameters.Request()
            request.names = ["cone_obstacle_layer.enabled"]
            self._resource_futures.append(client.call_async(request))
        self._resource_stage = "verifying_layers"
        self._resource_reason = "verifying live cone costmap layer parameters"

    def _publish(self) -> None:
        now = time.monotonic()
        self._advance_resource_transition(now)
        require_scan_health = True
        mode_ready = True
        if self._enable_mode_control:
            mode_status_fresh = (
                0.0 <= now - self._last_mode_status_time <= self._mode_status_timeout
            )
            mode_ready = bool(
                mode_status_fresh
                and self._mode_acknowledged
                and self._controller_healthy
                and self._controller_mode == self._requested_mode
                and self._resource_ready
                and bool(self._active_request_id)
            )
            require_scan_health = self._requested_mode == DepthMode.AVOIDANCE
        decision = self._tracker.evaluate(
            self._command,
            self._command_time,
            now,
            self._command_timeout,
            require_scan_health=require_scan_health,
        )
        if not mode_ready:
            decision = type(decision)(
                ZERO_COMMAND,
                False,
                self._resource_reason,
            )
        output = Twist()
        output.linear.x, output.linear.y, output.angular.z = decision.command
        self._publisher.publish(output)
        self._tick += 1
        if self._tick % self._status_divisor == 0:
            status = String()
            status.data = json.dumps(
                {
                    "allowed": decision.allowed,
                    "reason": decision.reason,
                    "stream_id": self._tracker.stream_id,
                    "sequence": self._tracker.last_sequence,
                    "consecutive_healthy": self._tracker.consecutive,
                    "required_consecutive": self._tracker.required_consecutive,
                    "mode": self._requested_mode.value,
                    "active_request_id": self._active_request_id,
                    "mode_control_enabled": self._enable_mode_control,
                    "resource_stage": self._resource_stage,
                    "resource_ready": self._resource_ready,
                    "layer_baseline_ready": self._layer_tracker.baseline_ready(),
                    "layer_baseline_reason": self._layer_tracker.last_reason,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            self._status_publisher.publish(status)

    def destroy_node(self) -> bool:
        stop = Twist()
        for _ in range(3):
            self._publisher.publish(stop)
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ConeScanSafetyGate()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
