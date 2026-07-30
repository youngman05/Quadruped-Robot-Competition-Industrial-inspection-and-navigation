import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import lite3_udp_smoke


class FakeLite3Udp:
    def __init__(self, dog_ip, dog_port, armed):
        self.dog_ip = dog_ip
        self.dog_port = dog_port
        self.armed = armed
        self.initialized = False
        self.closed = False

    def init_motion(self):
        self.initialized = True

    def close(self):
        self.closed = True


def make_args(test_lateral):
    return SimpleNamespace(
        dog_ip="192.168.1.120",
        dog_port=43893,
        rate_hz=40.0,
        forward_vx=0.04,
        lateral_vy=0.03,
        yaw_az=0.12,
        move_sec=1.0,
        stop_sec=1.0,
        combined_axes=False,
        test_lateral=test_lateral,
        armed=False,
    )


class Lite3UdpSmokeSequenceTests(unittest.TestCase):
    def run_sequence(self, test_lateral):
        labels = []

        def record_hold(client, label, cmd, duration, rate_hz, combined_axes):
            labels.append((label, cmd.vx, cmd.vy, cmd.az))

        with patch.object(lite3_udp_smoke, "parse_args", return_value=make_args(test_lateral)):
            with patch.object(lite3_udp_smoke, "Lite3Udp", FakeLite3Udp):
                with patch.object(lite3_udp_smoke, "hold", side_effect=record_hold):
                    self.assertEqual(lite3_udp_smoke.main(), 0)
        return labels

    def test_lateral_calibration_skips_forward_and_yaw_probes(self):
        self.assertEqual(
            self.run_sequence(test_lateral=True),
            [
                ("stop", 0.0, 0.0, 0.0),
                ("slow_lateral_positive", 0.0, 0.03, 0.0),
                ("stop_after_lateral", 0.0, 0.0, 0.0),
            ],
        )

    def test_default_smoke_keeps_forward_and_yaw_probes(self):
        self.assertEqual(
            self.run_sequence(test_lateral=False),
            [
                ("stop", 0.0, 0.0, 0.0),
                ("slow_forward", 0.04, 0.0, 0.0),
                ("stop", 0.0, 0.0, 0.0),
                ("slow_yaw_left", 0.0, 0.0, 0.12),
                ("final_stop", 0.0, 0.0, 0.0),
            ],
        )


if __name__ == "__main__":
    unittest.main()
