import unittest

from nodes.navigation.cmd_vel_bridge_core import (
    CODE_FWD,
    CODE_LAT,
    CODE_YAW,
    STOP_MOTION_COMMAND,
    select_motion_command,
)


class CmdVelBridgeTest(unittest.TestCase):
    def test_only_yaw_is_emitted_when_multiple_axes_are_set(self):
        self.assertEqual(select_motion_command(0.2, 0.1, 0.3), (CODE_YAW, -0.3))

    def test_forward_precedes_lateral(self):
        self.assertEqual(select_motion_command(0.2, 0.1, 0.0), (CODE_FWD, 0.2))

    def test_lateral_command_preserves_established_sign(self):
        self.assertEqual(select_motion_command(0.0, 0.025, 0.0), (CODE_LAT, 0.025))

    def test_zero_twist_emits_one_forward_zero_stop(self):
        self.assertEqual(select_motion_command(0.0, 0.0, 0.0), STOP_MOTION_COMMAND)
