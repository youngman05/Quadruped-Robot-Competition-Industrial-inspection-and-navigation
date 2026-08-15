"""Tests for the fixed two-round competition task queue."""

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nodes.decision.competition_task_core import (  # noqa: E402
    ZoneAssessment,
    freeze_two_zone_tasks,
)


def assessment(letter, abnormal=False, confidence=0.0):
    return ZoneAssessment(letter, abnormal, confidence)


class CompetitionTaskCoreTests(unittest.TestCase):
    def test_zero_abnormal_uses_two_configured_fallback_zones(self):
        result = freeze_two_zone_tasks([], ("D", "B", "A", "C"))
        self.assertEqual(("D", "B"), result)

    def test_one_abnormal_is_kept_and_completed_from_fallback_order(self):
        result = freeze_two_zone_tasks(
            [assessment("C", True, 0.8)],
            ("A", "B", "C", "D"),
        )
        self.assertEqual(("C", "A"), result)

    def test_two_abnormal_are_used_directly(self):
        result = freeze_two_zone_tasks(
            [assessment("D", True, 0.55), assessment("B", True, 0.99)],
        )
        self.assertEqual(("D", "B"), result)

    def test_three_abnormal_selects_the_two_highest_confidences(self):
        result = freeze_two_zone_tasks(
            [
                assessment("A", True, 0.61),
                assessment("B", True, 0.94),
                assessment("C", True, 0.82),
            ]
        )
        self.assertEqual(("B", "C"), result)

    def test_four_abnormal_breaks_confidence_ties_by_configured_order(self):
        result = freeze_two_zone_tasks(
            [
                assessment("A", True, 0.75),
                assessment("B", True, 0.75),
                assessment("C", True, 0.75),
                assessment("D", True, 0.70),
            ],
            ("C", "B", "A", "D"),
        )
        self.assertEqual(("C", "B"), result)

    def test_result_is_an_immutable_two_item_snapshot(self):
        source = [assessment("A", True, 0.9)]
        result = freeze_two_zone_tasks(source, ("B", "C", "D", "A"))
        source.append(assessment("D", True, 1.0))
        self.assertEqual(("A", "B"), result)
        self.assertIsInstance(result, tuple)


if __name__ == "__main__":
    unittest.main()
