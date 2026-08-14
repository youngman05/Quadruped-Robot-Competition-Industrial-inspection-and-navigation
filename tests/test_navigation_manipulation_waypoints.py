"""Regression checks for fixed manipulation waypoints and dynamic end states."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
MODULE_PATH = ROOT / "src" / "navi" / "navigation_client.py"
SPEC = importlib.util.spec_from_file_location("navigation_client", MODULE_PATH)
NAVIGATION = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = NAVIGATION
SPEC.loader.exec_module(NAVIGATION)


class NavigationManipulationWaypointsTest(unittest.TestCase):
    def test_dynamic_i1_j1_are_never_navigation_waypoints(self):
        self.assertNotIn("i1", NAVIGATION.WAYPOINTS)
        self.assertNotIn("j1", NAVIGATION.WAYPOINTS)

    def test_loaded_fixed_manipulation_waypoints_have_explicit_orientation(self):
        for name in ("grasp_i0", "placement_A", "placement_B", "placement_C", "placement_D"):
            waypoint = NAVIGATION.WAYPOINTS.get(name)
            if waypoint is not None:
                self.assertTrue(waypoint["yaw_set"])
                self.assertGreaterEqual(abs(waypoint["qw"]), 0.0)


if __name__ == "__main__":
    unittest.main()
