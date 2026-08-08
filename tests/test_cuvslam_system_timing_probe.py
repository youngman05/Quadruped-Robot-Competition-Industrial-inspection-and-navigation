import importlib.util
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "cuvslam_system_timing_probe.py"


def load_script_module():
    spec = importlib.util.spec_from_file_location(
        "cuvslam_system_timing_probe", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CuvslamSystemTimingProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_script_module()

    def test_matching_lines_finds_xhci_and_xusb(self):
        text = "10: 1 2 tegra-xusb\n11: 3 4 timer\n12: 5 6 xhci_hcd"

        self.assertEqual(
            self.module.matching_lines(text, r"xhci|xusb"),
            ["10: 1 2 tegra-xusb", "12: 5 6 xhci_hcd"],
        )

    def test_parse_udp_snmp_maps_headers_to_values(self):
        text = "Udp: InDatagrams NoPorts InErrors RcvbufErrors\nUdp: 12 1 2 3\n"

        self.assertEqual(
            self.module.parse_udp_snmp(text),
            {"InDatagrams": 12, "NoPorts": 1, "InErrors": 2, "RcvbufErrors": 3},
        )

    def test_parse_udp_socket_queues_sums_hex_queues_and_drops(self):
        text = (
            "sl local_address rem_address st tx_queue:rx_queue tr tm->when retrnsmt uid timeout inode ref pointer drops\n"
            "1: 00000000:1CE1 00000000:0000 07 00000010:00000020 00:00000000 00000000 1000 0 1 2 3 4\n"
        )

        summary = self.module.parse_udp_socket_queues(text)

        self.assertEqual(summary["total_tx_bytes"], 16)
        self.assertEqual(summary["total_rx_bytes"], 32)
        self.assertEqual(summary["total_drops"], 4)

    def test_default_thread_pattern_covers_realsense_and_visual_slam(self):
        text = "1 2 realsense2_camera_node\n3 4 unrelated\n5 6 visual_slam_node"

        self.assertEqual(
            len(self.module.matching_lines(text, self.module.DEFAULT_THREAD_PATTERN)), 2
        )


if __name__ == "__main__":
    unittest.main()
