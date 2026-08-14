"""Unit tests for the hardware-independent competition route framework."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "nodes" / "decision" / "competition_route.py"
SPEC = importlib.util.spec_from_file_location("competition_route", MODULE_PATH)
ROUTE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = ROUTE
SPEC.loader.exec_module(ROUTE)


class CompetitionRouteTest(unittest.TestCase):
    def test_fixed_route_keeps_navigation_and_local_steps_explicit(self) -> None:
        steps = ROUTE.build_competition_route()
        self.assertEqual(steps[0].step_id, "nav_obstacle_exit")
        self.assertEqual(steps[0].kind, ROUTE.StepKind.NAV)
        self.assertEqual(steps[2].step_id, "inspect_p1a")
        self.assertEqual(steps[2].kind, ROUTE.StepKind.LOCAL)
        self.assertEqual(steps[-1].step_id, "prepare_jobs")

    def test_job_decision_expands_two_sorted_pick_place_cycles(self) -> None:
        runner = ROUTE.RouteRunner(ROUTE.build_competition_route())
        runner.start()
        while runner.current_step.step_id != "prepare_jobs":
            runner.complete_current()

        next_step = runner.prepare_jobs(["D", "B"])
        self.assertEqual(next_step.step_id, "nav_i0_1")
        self.assertEqual(runner.context.abnormal_zones, ("B", "D"))
        self.assertEqual(
            [step.step_id for step in runner.steps[-8:]],
            ["nav_i0_1", "pick_one_1", "nav_j0_B", "place_one_B",
             "nav_i0_2", "pick_one_2", "nav_j0_D", "place_one_D"],
        )
        self.assertFalse(any(step.kind == ROUTE.StepKind.NAV and step.end_checkpoint in {"i1", "j1"} for step in runner.steps))

    def test_place_only_advances_after_explicit_service_success(self) -> None:
        context = ROUTE.CompetitionContext(abnormal_zones=("A", "C"))
        runner = ROUTE.RouteRunner(ROUTE.build_manipulation_steps(["A", "C"]), context)
        runner.start()
        runner.complete_current()
        runner.complete_current({"grasp_success": True})
        runner.complete_current()
        self.assertEqual(runner.current_step.step_id, "place_one_A")

        with self.assertRaises(ROUTE.RouteContractError):
            runner.complete_current({"place_success": False})
        self.assertEqual(runner.context.job_index, 0)
        self.assertTrue(runner.context.carrying_block)

        runner.complete_current({"place_success": True})
        self.assertEqual(runner.context.job_index, 1)
        self.assertFalse(runner.context.carrying_block)

    def test_inspection_segment_routes_never_contain_navigation(self) -> None:
        for name in ("inspect_p1a", "inspect_p1b", "inspect_p2a", "inspect_p2b"):
            steps = ROUTE.build_segment_route(name)
            self.assertEqual(len(steps), 1)
            self.assertEqual(steps[0].kind, ROUTE.StepKind.LOCAL)
        self.assertEqual(ROUTE.build_segment_route("place_one", "C")[0].zone, "C")

    def test_pick_acceptance_routes_are_cumulative_from_nav_i0(self) -> None:
        self.assertEqual(len(ROUTE.build_segment_route("pick_until_i0")), 1)
        for name in (
            "pick_until_i2",
            "pick_align_only",
            "pick_one",
        ):
            steps = ROUTE.build_segment_route(name)
            self.assertEqual([step.kind for step in steps], [ROUTE.StepKind.NAV, ROUTE.StepKind.LOCAL])
            self.assertEqual(steps[0].end_checkpoint, "grasp_i0")

        align_step = ROUTE.build_segment_route("pick_align_only")[1]
        self.assertEqual(align_step.executor, "pick_align_only")
        self.assertEqual(align_step.completion_flag, "alignment_success")
        self.assertEqual(
            ROUTE.build_segment_route("pick_one")[1].completion_flag,
            "grasp_success",
        )

    def test_i0_to_i2_route_is_local_only(self) -> None:
        steps = ROUTE.build_segment_route("pick_i0_to_i2")
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].kind, ROUTE.StepKind.LOCAL)
        self.assertEqual(steps[0].executor, "pick_i0_to_i2")
        self.assertEqual(steps[0].start_checkpoint, "grasp_i0")
        self.assertEqual(steps[0].end_checkpoint, "i2")
        self.assertEqual(steps[0].completion_flag, "alignment_success")


if __name__ == "__main__":
    unittest.main()
