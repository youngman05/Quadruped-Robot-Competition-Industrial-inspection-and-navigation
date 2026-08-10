import ast
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = REPO_ROOT / "scripts" / "nav2_waypoint_sequence_probe.py"
TERMINAL_BT_PATH = (
    REPO_ROOT
    / "configs"
    / "navigation"
    / "navigate_terminal_no_replanning.xml"
)
SETUP_PATH = REPO_ROOT / "setup.py"


def method_calls(tree, method_name):
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != method_name:
            continue
        calls = {}
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            function = child.func
            if isinstance(function, ast.Attribute):
                calls.setdefault(function.attr, []).append(child.lineno)
            elif isinstance(function, ast.Name):
                calls.setdefault(function.id, []).append(child.lineno)
        return {name: sorted(lines) for name, lines in calls.items()}
    raise AssertionError("method not found: %s" % method_name)


class Nav2TerminalReplanningContractTests(unittest.TestCase):
    def test_terminal_tree_computes_once_without_replanning_or_motion_recovery(self):
        root = ET.parse(TERMINAL_BT_PATH).getroot()
        tags = [element.tag for element in root.iter()]

        self.assertEqual(root.attrib["main_tree_to_execute"], "MainTree")
        self.assertEqual(tags.count("ComputePathToPose"), 1)
        self.assertEqual(tags.count("FollowPath"), 1)
        self.assertIn("SequenceStar", tags)
        for forbidden in (
            "RateController",
            "DistanceController",
            "SpeedController",
            "RecoveryNode",
            "Spin",
            "BackUp",
        ):
            self.assertNotIn(forbidden, tags)

    def test_handover_cancels_and_confirms_zero_before_terminal_goal(self):
        tree = ast.parse(PROBE_PATH.read_text(encoding="utf-8"))
        calls = method_calls(tree, "run_nav2_segment")

        send_lines = calls["_send_nav2_goal"]
        self.assertEqual(len(send_lines), 2)
        cancel_line = calls["_cancel_nav2_goal"][0]
        zero_line = calls["_wait_for_output_zero"][0]

        self.assertLess(send_lines[0], cancel_line)
        self.assertLess(cancel_line, zero_line)
        self.assertLess(zero_line, send_lines[1])

    def test_probe_defaults_to_035m_terminal_handover_and_records_evidence(self):
        source = PROBE_PATH.read_text(encoding="utf-8")

        self.assertIn('"--terminal-replan-stop-radius"', source)
        self.assertIn("default=0.35", source)
        self.assertIn('"--terminal-behavior-tree"', source)
        self.assertIn("TERMINAL_NO_REPLANNING_BT", source)
        self.assertIn('"terminal_handover"', source)
        self.assertIn('"zero_confirmed"', source)
        self.assertIn('"trigger_distance"', source)

    def test_terminal_tree_is_included_in_ros_package_data(self):
        setup_source = SETUP_PATH.read_text(encoding="utf-8")
        self.assertIn('glob("configs/navigation/*.xml")', setup_source)


if __name__ == "__main__":
    unittest.main()
