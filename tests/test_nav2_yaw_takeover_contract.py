import ast
import math
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = REPO_ROOT / "scripts" / "nav2_waypoint_sequence_probe.py"
ARBITER_PATH = REPO_ROOT / "src" / "nodes" / "navigation" / "cmd_vel_arbiter.py"


def evaluate(node, values):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return values[node.id]
    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name) and node.value.id == "math":
            return getattr(math, node.attr)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -evaluate(node.operand, values)
    if isinstance(node, ast.BinOp):
        left = evaluate(node.left, values)
        right = evaluate(node.right, values)
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Add):
            return left + right
    if isinstance(node, ast.Subscript):
        value = evaluate(node.value, values)
        if isinstance(node.slice, ast.Slice):
            lower = evaluate(node.slice.lower, values) if node.slice.lower else None
            upper = evaluate(node.slice.upper, values) if node.slice.upper else None
            step = evaluate(node.slice.step, values) if node.slice.step else None
            return value[slice(lower, upper, step)]
        return value[evaluate(node.slice, values)]
    if isinstance(node, ast.List):
        return [evaluate(item, values) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(evaluate(item, values) for item in node.elts)
    if isinstance(node, ast.Dict):
        return {
            evaluate(key, values): evaluate(value, values)
            for key, value in zip(node.keys, node.values)
        }
    raise AssertionError("unsupported route expression: %s" % ast.dump(node))


def load_route_values():
    tree = ast.parse(PROBE_PATH.read_text(encoding="utf-8"), filename=str(PROBE_PATH))
    values = {}
    wanted = {
        "_INSPECTION_PREFIX_LEGACY",
        "_INSPECTION_PREFIX_TAKEOVER",
        "_INSPECTION_PREFIX_STAGED",
        "_INSPECTION_PREFIX_SE2",
        "_INSPECTION_SE2_CORRIDOR_RECOVERY",
        "_INSPECTION_TAIL",
        "_FULL_TAIL",
        "ROUTE_PRESETS",
    }
    for statement in tree.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if isinstance(target, ast.Name) and target.id in wanted:
            values[target.id] = evaluate(statement.value, values)
    return tree, values


def method_call_lines(tree, method_name):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name != method_name:
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
            return calls
    raise AssertionError("method not found: %s" % method_name)


class Nav2YawTakeoverContractTests(unittest.TestCase):
    def test_production_route_uses_proximity_takeover_and_keeps_baseline(self):
        _, values = load_route_values()
        takeover = values["_INSPECTION_PREFIX_TAKEOVER"]
        compound = takeover[1]

        self.assertEqual(takeover[0][0], "obstacle_cross_target")
        self.assertEqual(compound["kind"], "nav2_yaw_takeover")
        self.assertEqual(compound["approach_label"], "pos1_middle")
        self.assertEqual((compound["approach_x"], compound["approach_y"]), (1.5, 3.25))
        self.assertAlmostEqual(compound["approach_yaw"], math.pi / 2.0)
        self.assertEqual(compound["takeover_radius"], 0.22)
        self.assertAlmostEqual(compound["target_yaw"], -math.pi / 2.0)

        routes = values["ROUTE_PRESETS"]
        self.assertEqual(routes["nav-only-full"][:2], takeover)
        self.assertEqual(routes["nav-only-turn-validation"], takeover)
        self.assertEqual(
            routes["nav-only-full-dwb-baseline"][:3],
            values["_INSPECTION_PREFIX_LEGACY"],
        )

    def test_takeover_orders_zero_lease_before_cancel_and_yaw_control(self):
        tree, _ = load_route_values()
        calls = method_call_lines(tree, "run_nav2_yaw_takeover_segment")

        acquire_line = calls["_acquire_precision_zero_lease"][0]
        cancel_line = calls["_cancel_nav2_under_precision_lease"][0]
        yaw_line = calls["YawOnlyController"][0]
        release_line = calls["_wait_for_precision_release"][0]

        self.assertLess(acquire_line, cancel_line)
        self.assertLess(cancel_line, yaw_line)
        self.assertLess(yaw_line, release_line)

    def test_arbiter_exposes_mode_for_lease_confirmation(self):
        source = ARBITER_PATH.read_text(encoding="utf-8")

        self.assertIn('"status_topic", "/cmd_vel_arbiter/mode"', source)
        self.assertIn("status.data = decision.mode", source)
        self.assertIn("self._status_publisher.publish(status)", source)


if __name__ == "__main__":
    unittest.main()
