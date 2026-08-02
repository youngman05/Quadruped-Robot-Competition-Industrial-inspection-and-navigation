import importlib.util
import pathlib
import struct
import unittest


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "lite3_state_recorder.py"
SPEC = importlib.util.spec_from_file_location("lite3_state_recorder", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Lite3StateRecorderTest(unittest.TestCase):
    def test_decode_robot_state_pack4_offsets(self):
        packet = bytearray(MODULE.ROBOT_STATE_PACKET_SIZE)
        struct.pack_into("<iii", packet, 0, MODULE.ROBOT_STATE_CODE, 199, 1)
        struct.pack_into("<ii", packet, 12, 2, 3)
        struct.pack_into("<3d", packet, 20, 1.25, -2.5, 13.75)
        struct.pack_into("<3d", packet, 44, 0.1, 0.2, 0.3)
        struct.pack_into("<3d", packet, 92, 4.0, 5.0, 6.0)
        struct.pack_into("<3d", packet, 116, 0.4, 0.5, 0.6)
        struct.pack_into("<3d", packet, 140, -0.4, -0.5, -0.6)
        struct.pack_into("<i", packet, 176, 9)
        struct.pack_into("<d", packet, 180, 72.5)

        decoded = MODULE.decode_packet(bytes(packet))

        self.assertEqual(decoded["kind"], "robot_state")
        self.assertEqual(decoded["robot_basic_state"], 2)
        self.assertEqual(decoded["robot_gait_state"], 3)
        self.assertAlmostEqual(decoded["rpy_yaw_deg"], 13.75)
        self.assertAlmostEqual(decoded["rpy_vel_z"], 0.3)
        self.assertAlmostEqual(decoded["pos_world_y"], 5.0)
        self.assertAlmostEqual(decoded["vel_world_z"], 0.6)
        self.assertAlmostEqual(decoded["vel_body_x"], -0.4)
        self.assertEqual(decoded["robot_motion_state"], 9)
        self.assertAlmostEqual(decoded["battery_level"], 72.5)

    def test_decode_handle_state_goal_velocities(self):
        packet = struct.pack(
            "<iii6d",
            MODULE.HANDLE_STATE_CODE,
            48,
            1,
            0.1,
            -0.2,
            0.3,
            0.4,
            -0.5,
            0.06,
        )

        decoded = MODULE.decode_packet(packet)

        self.assertEqual(len(packet), MODULE.HANDLE_STATE_PACKET_SIZE)
        self.assertEqual(decoded["kind"], "handle_state")
        self.assertAlmostEqual(decoded["right_axis_yaw"], 0.3)
        self.assertAlmostEqual(decoded["goal_vel_forward"], 0.4)
        self.assertAlmostEqual(decoded["goal_vel_side"], -0.5)
        self.assertAlmostEqual(decoded["goal_vel_yaw"], 0.06)

    def test_unknown_packet_is_not_decoded(self):
        packet = struct.pack("<iii", 9999, 0, 0) + bytes(48)
        self.assertIsNone(MODULE.decode_packet(packet))


if __name__ == "__main__":
    unittest.main()
