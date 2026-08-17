"""Regression tests for the fixed ArmPi posture sequences."""

from __future__ import annotations

import unittest

from arm_api import plan_lie_down, plan_stand_up


class ArmPostureTest(unittest.TestCase):
    def test_lie_down_keeps_gripper_and_uses_calibrated_id6(self) -> None:
        steps = plan_lie_down()

        self.assertEqual([step.servos[0][0] for step in steps], [6, 5, 4, 3, 2])
        self.assertEqual([step.duration_ms for step in steps], [1000, 1200, 1500, 1200, 1200])
        self.assertEqual(dict(step.servos[0] for step in steps)[6], 280)
        self.assertNotIn(1, [step.servos[0][0] for step in steps])

    def test_stand_up_uses_current_initial_position_without_id1(self) -> None:
        steps = plan_stand_up()

        self.assertEqual([step.servos[0][0] for step in steps], [6, 2, 3, 4, 5])
        self.assertEqual(
            dict(step.servos[0] for step in steps),
            {2: 504, 3: 256, 4: 755, 5: 636, 6: 220},
        )
        self.assertNotIn(1, [step.servos[0][0] for step in steps])


if __name__ == "__main__":
    unittest.main()
