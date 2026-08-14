import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from nodes.navigation.navigation_client import NavigationClient


class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warn(self, message):
        self.messages.append(("warn", message))

    def error(self, message):
        self.messages.append(("error", message))


class FakeFuture:
    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error

    def result(self):
        if self.error:
            raise self.error
        return self.value


class FakeGoalHandle:
    def __init__(self, accepted=True):
        self.accepted = accepted
        self.cancel_calls = 0
        self.result_callback = None

    def cancel_goal_async(self):
        self.cancel_calls += 1

    def get_result_async(self):
        handle = self

        class ResultFuture:
            def add_done_callback(self, callback):
                handle.result_callback = callback

        return ResultFuture()


class FakeActionClient:
    def __init__(self, ready):
        self.ready = ready

    def server_is_ready(self):
        return self.ready


class FakeLifecycleFuture:
    def __init__(self, state_id, label):
        self.response = SimpleNamespace(
            current_state=SimpleNamespace(id=state_id, label=label)
        )

    def done(self):
        return True

    def result(self):
        return self.response


class FakeLifecycleClient:
    def __init__(self, state_id=3, label="active", available=True):
        self.state_id = state_id
        self.label = label
        self.available = available

    def wait_for_service(self, timeout_sec):
        return self.available and timeout_sec == 0.0

    def call_async(self, _request):
        return FakeLifecycleFuture(self.state_id, self.label)


class FakeGetState:
    class Request:
        pass


def make_client():
    client = object.__new__(NavigationClient)
    client._logger = FakeLogger()
    client._goal_handle = None
    client._goal_sent = True
    client._goal_result = None
    client._current_waypoint = "test"
    client._result_name = "sending"
    client._failure_reason = ""
    client._generation = 7
    return client


class NavigationClientStateTests(unittest.TestCase):
    def test_server_readiness_is_non_blocking_and_delegated(self):
        client = make_client()
        client._action_client = FakeActionClient(False)
        self.assertFalse(client.server_is_ready())
        client._action_client.ready = True
        self.assertTrue(client.server_is_ready())

    def test_startup_readiness_requires_all_lifecycle_nodes_active(self):
        client = make_client()
        client._action_client = FakeActionClient(True)
        client._lifecycle_get_state = FakeGetState
        client._lifecycle_clients = {
            name: FakeLifecycleClient()
            for name in (
                "map_server",
                "planner_server",
                "controller_server",
                "recoveries_server",
                "bt_navigator",
            )
        }
        client._lifecycle_clients["bt_navigator"].state_id = 2
        client._lifecycle_clients["bt_navigator"].label = "inactive"
        client._lifecycle_futures = {}
        client._lifecycle_states = {}
        client._startup_ready = False
        client._startup_reason = ""

        ready, reason = client.startup_readiness()
        self.assertFalse(ready)
        self.assertIn("bt_navigator=inactive[2]", reason)

        client._lifecycle_clients["bt_navigator"].state_id = 3
        client._lifecycle_clients["bt_navigator"].label = "active"
        ready, reason = client.startup_readiness()
        self.assertTrue(ready)
        self.assertIn("NavigateToPose", reason)

    def test_rejected_goal_is_terminal_failure(self):
        client = make_client()

        client._goal_response_callback(FakeFuture(FakeGoalHandle(False)), 7)

        self.assertTrue(client.is_done())
        self.assertFalse(client.succeeded())
        self.assertEqual(client.result_name, "rejected")
        self.assertIn("rejected", client.failure_reason)

    def test_accepted_goal_transitions_to_success(self):
        client = make_client()
        goal_handle = FakeGoalHandle(True)
        client._goal_response_callback(FakeFuture(goal_handle), 7)

        self.assertTrue(client.goal_sent)
        self.assertEqual(client.result_name, "active")
        goal_handle.result_callback(FakeFuture(SimpleNamespace(status=4)))

        self.assertTrue(client.is_done())
        self.assertTrue(client.succeeded())
        self.assertEqual(client.result_name, "succeeded")

    def test_aborted_result_preserves_failure_reason(self):
        client = make_client()

        client._result_callback(FakeFuture(SimpleNamespace(status=6)), 7)

        self.assertTrue(client.is_done())
        self.assertEqual(client.result_name, "aborted")
        self.assertEqual(client.failure_reason, "action_status=6")

    def test_goal_response_exception_is_terminal(self):
        client = make_client()

        client._goal_response_callback(
            FakeFuture(error=RuntimeError("transport failed")),
            7,
        )

        self.assertEqual(client.result_name, "error")
        self.assertIn("transport failed", client.failure_reason)

    def test_stale_accepted_goal_is_canceled(self):
        client = make_client()
        goal_handle = FakeGoalHandle(True)

        client._goal_response_callback(FakeFuture(goal_handle), 6)

        self.assertEqual(goal_handle.cancel_calls, 1)
        self.assertEqual(client.result_name, "sending")


if __name__ == "__main__":
    unittest.main()
