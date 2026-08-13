import importlib.util
import socket
import threading
import time
import unittest
import uuid
from pathlib import Path

from nodes.navigation.cone_scan_protocol import ConeScanPacket, encode_packet


REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = REPO_ROOT / "scripts" / "cone_scan_udp_startup_probe.py"


def load_probe():
    spec = importlib.util.spec_from_file_location(
        "cone_scan_udp_startup_probe", PROBE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def packet(depth_healthy=True):
    return ConeScanPacket(
        stream_id=uuid.uuid4().hex,
        sequence=1,
        source_stamp_ns=time.time_ns(),
        sent_wall_time_ns=time.time_ns(),
        angle_min=-0.5,
        angle_max=0.5,
        angle_increment=0.5,
        time_increment=0.0,
        scan_time=0.1,
        range_min=0.2,
        range_max=3.0,
        valid_ratio=0.8,
        left_coverage=0.8,
        center_coverage=0.8,
        right_coverage=0.8,
        ranges=(1.0, 1.1, 1.2),
        depth_healthy=depth_healthy,
    )


class ConeScanUdpStartupProbeTests(unittest.TestCase):
    def test_receives_fresh_healthy_packet_after_rejecting_unhealthy_one(self):
        probe = load_probe()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]

        def send():
            time.sleep(0.05)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(encode_packet(packet(False)), ("127.0.0.1", port))
                time.sleep(0.05)
                sock.sendto(encode_packet(packet(True)), ("127.0.0.1", port))

        sender = threading.Thread(target=send)
        sender.start()
        actual, age_ms = probe.receive_packet("127.0.0.1", port, 1.0)
        sender.join()
        self.assertTrue(actual.depth_healthy)
        self.assertGreaterEqual(age_ms, 0.0)

    def test_timeout_is_fail_closed(self):
        probe = load_probe()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        with self.assertRaisesRegex(TimeoutError, "no datagram received"):
            probe.receive_packet("127.0.0.1", port, 0.1)


if __name__ == "__main__":
    unittest.main()
