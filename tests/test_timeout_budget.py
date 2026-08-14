import unittest

from nodes.decision.timeout_budget import ElapsedTimeoutBudget


class FakeClock:
    def __init__(self, now=0.0):
        self.now = float(now)

    def __call__(self):
        return self.now


class ElapsedTimeoutBudgetTests(unittest.TestCase):
    def test_budget_does_not_expire_at_exact_boundary(self):
        clock = FakeClock(100.0)
        budget = ElapsedTimeoutBudget(120.0, clock=clock)
        budget.start()

        clock.now = 220.0

        self.assertEqual(budget.elapsed(), 120.0)
        self.assertFalse(budget.expired())

    def test_budget_expires_after_boundary(self):
        clock = FakeClock(100.0)
        budget = ElapsedTimeoutBudget(120.0, clock=clock)
        budget.start()

        clock.now = 220.1

        self.assertTrue(budget.expired())

    def test_reset_gives_next_waypoint_an_independent_budget(self):
        clock = FakeClock(100.0)
        budget = ElapsedTimeoutBudget(120.0, clock=clock)
        budget.start()
        clock.now = 185.5
        self.assertFalse(budget.expired())

        budget.reset()
        clock.now = 191.5
        budget.start()
        clock.now = 205.2

        self.assertAlmostEqual(budget.elapsed(), 13.7)
        self.assertFalse(budget.expired())

    def test_inactive_budget_never_expires(self):
        budget = ElapsedTimeoutBudget(120.0, clock=FakeClock())

        self.assertIsNone(budget.elapsed())
        self.assertFalse(budget.expired())


if __name__ == "__main__":
    unittest.main()
