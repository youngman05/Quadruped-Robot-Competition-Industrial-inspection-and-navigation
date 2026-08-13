import json
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

try:
    from rclpy.qos import (  # noqa: F401
        DurabilityPolicy,
        HistoryPolicy,
        QoSProfile,
        ReliabilityPolicy,
    )
except ModuleNotFoundError:
    qos_module = types.ModuleType("rclpy.qos")

    class _Policy:
        def __init__(self, name):
            self.name = name

        def __repr__(self):
            return self.name

    qos_module.DurabilityPolicy = SimpleNamespace(TRANSIENT_LOCAL=_Policy("transient_local"))
    qos_module.HistoryPolicy = SimpleNamespace(KEEP_LAST=_Policy("keep_last"))
    qos_module.ReliabilityPolicy = SimpleNamespace(RELIABLE=_Policy("reliable"))

    class QoSProfile:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    qos_module.QoSProfile = QoSProfile
    rclpy_module = types.ModuleType("rclpy")
    rclpy_module.qos = qos_module
    sys.modules["rclpy"] = rclpy_module
    sys.modules["rclpy.qos"] = qos_module

try:
    from std_msgs.msg import String  # noqa: F401
except ModuleNotFoundError:
    std_msgs_module = types.ModuleType("std_msgs")
    msg_module = types.ModuleType("std_msgs.msg")

    class String:
        def __init__(self):
            self.data = ""

    msg_module.String = String
    std_msgs_module.msg = msg_module
    sys.modules["std_msgs"] = std_msgs_module
    sys.modules["std_msgs.msg"] = msg_module

from nodes.navigation.depth_contract import DepthMode, new_controller_status
from nodes.navigation.depth_mode_client import DepthModeClient


class FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message.data)


class FakeNode:
    def __init__(self):
        self.publisher = FakePublisher()
        self.publisher_qos = None

    def create_publisher(self, _msg_type, _topic, qos):
        self.publisher_qos = qos
        return self.publisher

    def create_subscription(self, *_args):
        return SimpleNamespace()


class DepthModeClientTests(unittest.TestCase):
    def test_relay_uses_the_same_latched_request_qos(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "nodes"
            / "navigation"
            / "depth_relay_publisher.py"
        ).read_text(encoding="utf-8")
        for token in (
            "HistoryPolicy.KEEP_LAST",
            "depth=1",
            "ReliabilityPolicy.RELIABLE",
            "DurabilityPolicy.TRANSIENT_LOCAL",
            "mode_request_qos",
        ):
            self.assertIn(token, source)

    def test_client_has_no_blocking_startup_sleep(self):
        source = Path(
            Path(__file__).resolve().parents[1]
            / "src"
            / "nodes"
            / "navigation"
            / "depth_mode_client.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("time.sleep", source)

    def test_request_publisher_uses_latched_reliable_qos(self):
        node = FakeNode()
        DepthModeClient(node)
        self.assertEqual(node.publisher_qos.depth, 1)
        self.assertEqual(node.publisher_qos.history.name, "keep_last")
        self.assertEqual(node.publisher_qos.reliability.name, "reliable")
        self.assertEqual(node.publisher_qos.durability.name, "transient_local")

    def test_request_is_republished_identically_until_end_to_end_ack(self):
        node = FakeNode()
        client = DepthModeClient(node)
        with patch("nodes.navigation.depth_mode_client.time.monotonic", return_value=10.0):
            request = client.begin_transition(DepthMode.AVOIDANCE)
            self.assertTrue(client.republish_active_request(DepthMode.AVOIDANCE, now=10.5))
            payloads = list(node.publisher.messages)
            self.assertEqual(len(payloads), 2)
            self.assertEqual(payloads[0], payloads[1])
            decoded = json.loads(payloads[0])
            self.assertEqual(decoded["version"], 1)
            self.assertEqual(decoded["request_id"], request["request_id"])
            self.assertIn("created_monotonic_ns", decoded)

            client._on_status(
                SimpleNamespace(
                    data=json.dumps(
                        new_controller_status(
                            DepthMode.AVOIDANCE,
                            stream_id="stream-a",
                            ack_request_id=request["request_id"],
                            depth_enabled=True,
                            updated_monotonic_ns=1,
                        )
                    )
                )
            )
            client._on_safety_status(
                SimpleNamespace(
                    data=json.dumps(
                        {
                            "mode": "AVOIDANCE",
                            "active_request_id": request["request_id"],
                            "allowed": True,
                            "reason": "ready",
                        }
                    )
                )
            )
            with patch("nodes.navigation.depth_mode_client.time.monotonic", return_value=10.5):
                self.assertTrue(client.end_to_end_ready(DepthMode.AVOIDANCE))
                self.assertFalse(client.republish_active_request())
                self.assertEqual(len(node.publisher.messages), 2)

    def test_republish_does_not_happen_before_interval(self):
        node = FakeNode()
        client = DepthModeClient(node)
        with patch(
            "nodes.navigation.depth_mode_client.time.monotonic", return_value=20.0
        ):
            client.begin_transition(DepthMode.DISABLED)
        self.assertFalse(client.republish_active_request(DepthMode.DISABLED, now=20.49))
        self.assertTrue(client.republish_active_request(DepthMode.DISABLED, now=20.5))
        self.assertEqual(len(node.publisher.messages), 2)


if __name__ == "__main__":
    unittest.main()
