import math
import unittest

from nodes.navigation.se2_pose_control import (
    DirectedYawTracker,
    Se2ControllerConfig,
    Se2PoseController,
    YawOnlyController,
    YawOnlyControllerConfig,
)


class Se2PoseControlTests(unittest.TestCase):
    def test_clockwise_tracker_keeps_long_clockwise_turn_across_wrap(self):
        tracker = DirectedYawTracker(
            start_yaw=math.radians(105.0),
            target_yaw=-math.pi / 2.0,
            direction="clockwise",
        )

        self.assertAlmostEqual(tracker.error, math.radians(-195.0))
        tracker.update(math.radians(90.0))
        self.assertAlmostEqual(tracker.error, math.radians(-180.0))

    def test_body_error_is_expressed_in_current_robot_frame(self):
        config = Se2ControllerConfig(
            max_linear_accel=100.0,
            max_angular_accel=100.0,
        )
        controller = Se2PoseController(config)
        controller.start(1.0, 0.0, math.pi / 2.0, math.pi / 2.0)

        output = controller.compute(0.0, 0.0, math.pi / 2.0, 0.1)

        self.assertAlmostEqual(output.error_x_body, 0.0)
        self.assertAlmostEqual(output.error_y_body, -1.0)
        self.assertLess(output.vy, 0.0)

    def test_acceleration_limits_are_applied_per_cycle(self):
        config = Se2ControllerConfig(
            coarse_max_vx=1.0,
            coarse_max_vy=1.0,
            coarse_max_wz=1.0,
            max_linear_accel=0.2,
            max_angular_accel=0.4,
        )
        controller = Se2PoseController(config)
        controller.start(1.0, 1.0, 0.0, 1.0)

        output = controller.compute(0.0, 0.0, 0.0, 0.1)

        self.assertLessEqual(abs(output.vx), 0.02 + 1e-12)
        self.assertLessEqual(abs(output.vy), 0.02 + 1e-12)
        self.assertLessEqual(abs(output.wz), 0.04 + 1e-12)

    def test_controller_converges_in_ideal_holonomic_model(self):
        config = Se2ControllerConfig(
            coarse_max_vx=0.08,
            coarse_max_vy=0.08,
            coarse_max_wz=0.20,
            fine_max_vx=0.04,
            fine_max_vy=0.04,
            fine_max_wz=0.08,
        )
        controller = Se2PoseController(config)
        x, y, yaw = 0.14, -0.11, math.radians(105.0)
        controller.start(0.0, 0.0, yaw, -math.pi / 2.0, direction="clockwise")

        dt = 0.05
        output = None
        for _ in range(int(60.0 / dt)):
            output = controller.compute(x, y, yaw, dt)
            x += (math.cos(yaw) * output.vx - math.sin(yaw) * output.vy) * dt
            y += (math.sin(yaw) * output.vx + math.cos(yaw) * output.vy) * dt
            yaw += output.wz * dt
            if output.reached:
                break

        self.assertIsNotNone(output)
        self.assertTrue(output.reached)
        self.assertLessEqual(math.hypot(x, y), config.position_tolerance)
        self.assertLessEqual(abs(output.error_yaw), config.yaw_tolerance)

    def test_controller_outputs_zero_inside_settle_tolerance(self):
        controller = Se2PoseController()
        controller.start(1.0, 2.0, 0.0, 0.0)

        output = controller.compute(1.02, 1.98, 0.03, 0.1)

        self.assertTrue(output.reached)
        self.assertEqual(output.mode, "settle")
        self.assertEqual((output.vx, output.vy, output.wz), (0.0, 0.0, 0.0))


class YawOnlyControlTests(unittest.TestCase):
    def test_clockwise_turn_stays_clockwise_across_wrap(self):
        controller = YawOnlyController(
            YawOnlyControllerConfig(max_angular_accel=100.0)
        )
        controller.start(
            start_yaw=math.radians(105.0),
            target_yaw=-math.pi / 2.0,
            direction="clockwise",
        )

        first = controller.compute(math.radians(105.0), 0.1)
        after_wrap = controller.compute(math.radians(-175.0), 0.1)

        self.assertLess(first.wz, 0.0)
        self.assertLess(after_wrap.wz, 0.0)

    def test_angular_acceleration_limit_is_applied(self):
        controller = YawOnlyController(
            YawOnlyControllerConfig(
                coarse_max_wz=1.0,
                max_angular_accel=0.4,
            )
        )
        controller.start(0.0, 1.0)

        output = controller.compute(0.0, 0.1)

        self.assertLessEqual(abs(output.wz), 0.04 + 1e-12)

    def test_controller_switches_to_fine_speed(self):
        controller = YawOnlyController(
            YawOnlyControllerConfig(
                ktheta=10.0,
                coarse_max_wz=0.12,
                fine_max_wz=0.06,
                fine_yaw_error=0.35,
                max_angular_accel=100.0,
            )
        )
        controller.start(0.0, 0.30)

        output = controller.compute(0.0, 0.1)

        self.assertEqual(output.mode, "fine_yaw")
        self.assertAlmostEqual(output.wz, 0.06)

    def test_controller_outputs_zero_inside_yaw_tolerance(self):
        controller = YawOnlyController()
        controller.start(0.0, 1.0)

        output = controller.compute(0.90, 0.1)

        self.assertTrue(output.reached)
        self.assertEqual(output.mode, "settle")
        self.assertEqual(output.wz, 0.0)

    def test_hold_restarts_acceleration_from_zero(self):
        controller = YawOnlyController(
            YawOnlyControllerConfig(
                coarse_max_wz=1.0,
                max_angular_accel=0.4,
            )
        )
        controller.start(0.0, 1.0)
        controller.compute(0.0, 1.0)
        controller.hold()

        output = controller.compute(0.0, 0.1)

        self.assertLessEqual(abs(output.wz), 0.04 + 1e-12)

    def test_controller_converges_on_competition_clockwise_turn(self):
        controller = YawOnlyController()
        yaw = math.radians(75.0)
        controller.start(yaw, -math.pi / 2.0, direction="clockwise")

        dt = 0.05
        output = None
        for _ in range(int(40.0 / dt)):
            output = controller.compute(yaw, dt)
            yaw += output.wz * dt
            if output.reached:
                break

        self.assertIsNotNone(output)
        self.assertTrue(output.reached)
        self.assertLessEqual(abs(output.error_yaw), controller.config.yaw_tolerance)


if __name__ == "__main__":
    unittest.main()
