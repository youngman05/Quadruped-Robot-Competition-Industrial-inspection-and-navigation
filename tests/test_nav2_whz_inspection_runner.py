import ast
import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from nodes.decision.inspection_workflow import (
    InspectionReading,
    InspectionStage,
    InspectionWorkflow,
)


RUNNER = REPO_ROOT / "scripts" / "nav2_whz_inspection_probe.py"
LAUNCHER = REPO_ROOT / "scripts" / "run_inspection_navigation.sh"
ONE_CLICK_LAUNCHER = REPO_ROOT / "scripts" / "start_inspection_one_click.sh"
ROUTE_FILE = REPO_ROOT / "configs" / "navigation" / "waypoints_reordered_preview.yaml"


class Nav2WhzInspectionRunnerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = RUNNER.read_text(encoding="utf-8")
        cls.launcher = LAUNCHER.read_text(encoding="utf-8")
        cls.one_click_launcher = ONE_CLICK_LAUNCHER.read_text(encoding="utf-8")

    def test_runner_is_valid_python_and_reuses_the_proven_probe(self):
        ast.parse(self.runner)
        self.assertIn(
            "class Nav2WhzInspectionProbe(Nav2WaypointSequenceProbe)",
            self.runner,
        )
        self.assertIn("segment = super().run_segment(index, goal)", self.runner)
        self.assertNotIn("NavigateToPose.Goal()", self.runner)

    def test_runner_requires_stop_before_one_async_whz_call(self):
        required = (
            "self.workflow.navigation_succeeded()",
            "self.workflow.update_stationary",
            "self.latest_odom_received_monotonic",
            "self._output_command_is_zero(output)",
            "self.whz_client.call_async(Trigger.Request())",
            "max_inspection_retries=0",
            "duplicate_whz_request",
            "require_audio=True",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.runner)

    def test_stop_gate_uses_a_dedicated_cmd_vel_executor(self):
        required = (
            "nav2_whz_inspection_cmd_listener",
            "self.safety_cmd_executor = SingleThreadedExecutor()",
            "target=self.safety_cmd_executor.spin",
            "self.latest_safety_output_cmd",
            "output = self.latest_safety_output_cmd",
            "super().shutdown_background_listeners()",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.runner)

    def test_runner_has_explicit_abort_and_finish_states(self):
        self.assertIn('"FINISH"', self.runner)
        self.assertIn('"ABORT"', self.runner)
        self.assertIn("self.workflow.require_complete_abcd()", self.runner)
        self.assertIn("count != 1", self.runner)
        self.assertIn("TaskManager must remain disabled", self.runner)

    def test_route_is_the_validated_nine_step_interleaved_route(self):
        document = json.loads(ROUTE_FILE.read_text(encoding="utf-8"))
        route = document["routes"]["inspection_interleaved"]
        self.assertEqual(
            [
                "obstacle_cross_target",
                "pos1_left_clear",
                "pos1_middle",
                "upper_corner_clear",
                "pos2a_upper_right",
                "upper_corner_clear",
                "pos1_middle_turned",
                "lower_corner_clear",
                "pos2b_lower_right",
            ],
            route,
        )
        actions = [document["waypoints"][name]["action"] for name in route]
        self.assertEqual(4, sum(action.startswith("observe_") for action in actions))

    def test_launcher_requires_explicit_motion_confirmation(self):
        self.assertIn("--confirm-motion", self.launcher)
        self.assertIn("Motion is locked", self.launcher)
        self.assertIn("--single-d", self.launcher)
        self.assertIn("--full", self.launcher)
        self.assertIn("--check-only", self.launcher)

    def test_launcher_enables_whz_but_never_task_manager(self):
        self.assertIn("bash scripts/start_competition.sh", self.launcher)
        self.assertIn("        --whz", self.launcher)
        invocation = self.launcher.split(
            "bash scripts/start_competition.sh",
            1,
        )[1].split("\n\n", 1)[0]
        self.assertNotIn("--task-manager", invocation)
        self.assertNotIn("--mission", invocation)
        self.assertNotIn("--auto-advance", invocation)
        self.assertIn("pos2b_lower_right=D", self.launcher)

    def test_one_click_launcher_starts_full_inspection_directly(self):
        self.assertIn(
            'exec bash "$SCRIPT_DIR/run_inspection_navigation.sh" --full --confirm-motion',
            self.one_click_launcher,
        )
        self.assertNotIn("--check-only", self.one_click_launcher)
        self.assertNotIn("--single-d", self.one_click_launcher)


class DedicatedInspectionWorkflowTests(unittest.TestCase):
    @staticmethod
    def _reading(area):
        return InspectionReading.from_trigger(
            True,
            json.dumps({
                "ok": True,
                "area": area,
                "state_key": "middle",
                "is_abnormal": False,
                "color": "green",
                "audio_played": True,
                "agree_frames": 2,
                "total_frames": 3,
            }),
        )

    @staticmethod
    def _complete_one_step(workflow, reading, start):
        workflow.navigation_succeeded()
        workflow.update_stationary(start, True)
        workflow.update_stationary(start + 1.0, True)
        workflow.service_started()
        workflow.inspection_succeeded(reading)

    def test_single_d_finishes_after_one_audio_backed_result(self):
        workflow = InspectionWorkflow(1, 1.0, 0, 0)
        self._complete_one_step(workflow, self._reading("D"), 10.0)
        self.assertEqual(InspectionStage.COMPLETE, workflow.stage)
        self.assertEqual(["D"], list(workflow.readings))

    def test_full_run_requires_unique_abcd(self):
        workflow = InspectionWorkflow(4, 1.0, 0, 0)
        for index, area in enumerate("ABCD"):
            self._complete_one_step(workflow, self._reading(area), 10.0 * index)
        workflow.require_complete_abcd()
        self.assertEqual(InspectionStage.COMPLETE, workflow.stage)
        self.assertEqual(set("ABCD"), set(workflow.readings))

    def test_duplicate_area_aborts_immediately(self):
        workflow = InspectionWorkflow(2, 1.0, 0, 0)
        self._complete_one_step(workflow, self._reading("A"), 10.0)
        self._complete_one_step(workflow, self._reading("A"), 20.0)
        self.assertEqual(InspectionStage.ABORTED, workflow.stage)
        self.assertEqual("duplicate_area=A", workflow.abort_reason)


if __name__ == "__main__":
    unittest.main()
