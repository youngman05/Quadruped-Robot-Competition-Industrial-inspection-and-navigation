import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FORWARD_LIMIT = 0.24
EXPECTED_ANGULAR_LIMIT = 0.30


def declared_default(path, parameter_name):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "declare_parameter" or len(node.args) < 2:
            continue
        if not isinstance(node.args[0], ast.Constant):
            continue
        if node.args[0].value == parameter_name:
            return ast.literal_eval(node.args[1])
    raise AssertionError("parameter not declared: %s" % parameter_name)


def yaml_block_scalars(path, block_name):
    values = {}
    block_indent = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip())
        if stripped == block_name + ":":
            block_indent = indent
            continue
        if block_indent is None:
            continue
        if indent <= block_indent:
            break
        key, separator, value = stripped.partition(":")
        if separator and value.strip():
            try:
                values[key] = float(value.strip())
            except ValueError:
                continue
    if block_indent is None:
        raise AssertionError("YAML block not found: %s" % block_name)
    return values


class NavigationSpeedLimitTests(unittest.TestCase):
    def test_navigation_limits_are_consistent(self):
        params_path = REPO_ROOT / "configs" / "navigation" / "nav2_params.yaml"
        follow_path = yaml_block_scalars(params_path, "FollowPath")

        self.assertEqual(follow_path["max_vel_x"], EXPECTED_FORWARD_LIMIT)
        self.assertEqual(follow_path["max_speed_xy"], EXPECTED_FORWARD_LIMIT)
        self.assertEqual(follow_path["max_vel_theta"], EXPECTED_ANGULAR_LIMIT)

        recoveries = yaml_block_scalars(params_path, "recoveries_server")
        self.assertEqual(
            recoveries["max_rotational_vel"],
            EXPECTED_ANGULAR_LIMIT,
        )

        arbiter_path = REPO_ROOT / "src" / "nodes" / "navigation" / "cmd_vel_arbiter.py"
        self.assertEqual(
            declared_default(arbiter_path, "max_vx"),
            EXPECTED_FORWARD_LIMIT,
        )
        self.assertEqual(
            declared_default(arbiter_path, "max_wz"),
            EXPECTED_ANGULAR_LIMIT,
        )

        bridge_path = REPO_ROOT / "src" / "nodes" / "navigation" / "cmd_vel_bridge.py"
        self.assertEqual(
            declared_default(bridge_path, "hard_max_vx"),
            EXPECTED_FORWARD_LIMIT,
        )
        self.assertEqual(
            declared_default(bridge_path, "hard_max_speed_xy"),
            EXPECTED_FORWARD_LIMIT,
        )
        self.assertEqual(
            declared_default(bridge_path, "hard_max_az"),
            EXPECTED_ANGULAR_LIMIT,
        )


if __name__ == "__main__":
    unittest.main()
