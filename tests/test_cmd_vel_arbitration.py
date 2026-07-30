import unittest

from nodes.navigation.cmd_vel_arbitration import CmdVelArbitration, ZERO_COMMAND


class CmdVelArbitrationTests(unittest.TestCase):
    def setUp(self):
        self.arbiter = CmdVelArbitration(
            nav_timeout=0.35,
            precision_timeout=0.25,
            release_stop=0.50,
        )

    def test_fresh_nav_command_flows_and_then_times_out(self):
        self.assertTrue(self.arbiter.accept_nav((0.1, 0.0, 0.0), now=1.0))
        self.assertEqual(self.arbiter.select(1.1).command, (0.1, 0.0, 0.0))
        self.assertEqual(self.arbiter.select(1.4).command, ZERO_COMMAND)

    def test_precision_zero_command_still_acquires_priority_lease(self):
        self.arbiter.accept_nav((0.1, 0.0, 0.0), now=1.0)
        acquired = self.arbiter.accept_precision(ZERO_COMMAND, now=1.1)

        decision = self.arbiter.select(1.2)

        self.assertTrue(acquired)
        self.assertEqual(decision.mode, "precision")
        self.assertEqual(decision.command, ZERO_COMMAND)

    def test_stale_precision_forces_release_stop_and_discards_old_nav(self):
        self.arbiter.accept_nav((0.1, 0.0, 0.0), now=1.0)
        self.arbiter.accept_precision((0.0, 0.02, -0.1), now=1.1)

        self.assertFalse(self.arbiter.accept_nav((0.1, 0.0, 0.0), now=1.2))
        self.assertEqual(self.arbiter.select(1.36).mode, "precision_release")
        self.assertEqual(self.arbiter.select(1.70).command, ZERO_COMMAND)
        self.assertEqual(self.arbiter.select(1.87).mode, "idle")
        self.assertEqual(self.arbiter.select(1.88).command, ZERO_COMMAND)

        self.assertTrue(self.arbiter.accept_nav((0.05, 0.0, 0.0), now=1.89))
        self.assertEqual(self.arbiter.select(1.90).command, (0.05, 0.0, 0.0))

    def test_precision_can_reacquire_during_release_stop(self):
        self.arbiter.accept_precision((0.0, 0.0, -0.1), now=1.0)
        self.assertEqual(self.arbiter.select(1.26).mode, "precision_release")

        self.assertTrue(
            self.arbiter.accept_precision((0.0, 0.0, -0.05), now=1.30)
        )
        decision = self.arbiter.select(1.31)
        self.assertEqual(decision.mode, "precision")
        self.assertEqual(decision.command, (0.0, 0.0, -0.05))


if __name__ == "__main__":
    unittest.main()
