import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from nodes.decision.inspection_workflow import (
    InspectionContractError,
    InspectionReading,
    InspectionStage,
    InspectionWorkflow,
)


def trigger_message(
    area="A",
    state_key="middle",
    color="green",
    is_abnormal=False,
    audio_played=True,
):
    return json.dumps({
        "ok": True,
        "area": area,
        "state_key": state_key,
        "is_abnormal": is_abnormal,
        "color": color,
        "audio_played": audio_played,
        "agree_frames": 3,
        "total_frames": 3,
    })


class InspectionReadingTests(unittest.TestCase):
    def test_middle_maps_to_legacy_normal_status(self):
        reading = InspectionReading.from_trigger(True, trigger_message())

        self.assertEqual(reading.area, "A")
        self.assertEqual(reading.state_key, "middle")
        self.assertEqual(reading.status, "normal")
        self.assertFalse(reading.is_abnormal)

    def test_low_maps_to_abnormal_low(self):
        reading = InspectionReading.from_trigger(
            True,
            trigger_message(
                area="D",
                state_key="low",
                color="yellow",
                is_abnormal=True,
            ),
        )

        self.assertEqual(reading.status, "low")
        self.assertTrue(reading.is_abnormal)

    def test_rejects_contradictory_color_or_abnormal_flag(self):
        with self.assertRaisesRegex(InspectionContractError, "color_state_mismatch"):
            InspectionReading.from_trigger(True, trigger_message(color="red"))
        with self.assertRaisesRegex(InspectionContractError, "abnormal_state_mismatch"):
            InspectionReading.from_trigger(
                True,
                trigger_message(is_abnormal=True),
            )

    def test_rejects_unsuccessful_malformed_or_silent_response(self):
        with self.assertRaisesRegex(InspectionContractError, "no_valid_frame"):
            InspectionReading.from_trigger(
                False,
                json.dumps({"ok": False, "error": "no_valid_frame"}),
            )
        with self.assertRaisesRegex(InspectionContractError, "invalid_json"):
            InspectionReading.from_trigger(True, "not-json")
        with self.assertRaisesRegex(InspectionContractError, "audio_not_played"):
            InspectionReading.from_trigger(
                True,
                trigger_message(audio_played=False),
            )


class InspectionWorkflowTests(unittest.TestCase):
    def make_workflow(self, steps=1, nav_retries=3, inspect_retries=3):
        return InspectionWorkflow(
            step_count=steps,
            settle_duration_sec=1.0,
            max_nav_retries=nav_retries,
            max_inspection_retries=inspect_retries,
        )

    def settle_and_start(self, workflow):
        workflow.navigation_succeeded()
        self.assertFalse(workflow.update_stationary(10.0, True))
        self.assertFalse(workflow.update_stationary(10.9, True))
        self.assertTrue(workflow.update_stationary(11.0, True))
        workflow.service_started()

    def test_requires_continuous_stationary_window(self):
        workflow = self.make_workflow()
        workflow.navigation_succeeded()

        self.assertFalse(workflow.update_stationary(1.0, True))
        self.assertFalse(workflow.update_stationary(1.8, False))
        self.assertFalse(workflow.update_stationary(2.0, True))
        self.assertTrue(workflow.update_stationary(3.0, True))
        self.assertEqual(workflow.stage, InspectionStage.WAITING_SERVICE)

    def test_allows_three_nav_retries_then_aborts_fourth_failure(self):
        workflow = self.make_workflow(nav_retries=3)

        self.assertTrue(workflow.navigation_failed("aborted"))
        self.assertTrue(workflow.navigation_failed("rejected"))
        self.assertTrue(workflow.navigation_failed("unavailable"))
        self.assertFalse(workflow.navigation_failed("aborted"))
        self.assertEqual(workflow.stage, InspectionStage.ABORTED)
        self.assertIn("after_4_attempts", workflow.abort_reason)

    def test_explicit_inspection_failures_retry_but_timeout_aborts(self):
        workflow = self.make_workflow(inspect_retries=1)
        self.settle_and_start(workflow)

        self.assertTrue(workflow.inspection_failed("no_valid_frame"))
        self.assertEqual(workflow.stage, InspectionStage.SETTLING)
        self.assertFalse(workflow.update_stationary(20.0, True))
        self.assertTrue(workflow.update_stationary(21.0, True))
        workflow.service_started()
        workflow.inspection_timed_out("20.0s")

        self.assertEqual(workflow.stage, InspectionStage.ABORTED)
        self.assertIn("outcome_unknown", workflow.abort_reason)

    def test_duplicate_success_aborts_without_overwriting(self):
        workflow = self.make_workflow(steps=2)
        reading = InspectionReading.from_trigger(True, trigger_message(area="A"))
        self.settle_and_start(workflow)
        workflow.inspection_succeeded(reading)
        self.assertEqual(workflow.stage, InspectionStage.NAVIGATING)

        self.settle_and_start(workflow)
        workflow.inspection_succeeded(reading)

        self.assertEqual(workflow.stage, InspectionStage.ABORTED)
        self.assertEqual(list(workflow.readings), ["A"])
        self.assertEqual(workflow.abort_reason, "duplicate_area=A")

    def test_full_four_step_workflow_requires_exact_abcd(self):
        workflow = self.make_workflow(steps=4)
        colors = {
            "A": ("middle", "green", False),
            "B": ("low", "yellow", True),
            "C": ("high", "red", True),
            "D": ("middle", "green", False),
        }

        for area in "ABCD":
            state_key, color, abnormal = colors[area]
            self.settle_and_start(workflow)
            workflow.inspection_succeeded(InspectionReading.from_trigger(
                True,
                trigger_message(
                    area=area,
                    state_key=state_key,
                    color=color,
                    is_abnormal=abnormal,
                ),
            ))

        self.assertEqual(workflow.stage, InspectionStage.COMPLETE)
        workflow.require_complete_abcd()
        self.assertEqual(workflow.stage, InspectionStage.COMPLETE)
        self.assertEqual(set(workflow.readings), set("ABCD"))


if __name__ == "__main__":
    unittest.main()
