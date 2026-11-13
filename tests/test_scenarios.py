"""Scenario coverage and recovery must hold even when a real run fails or stops."""
import contextlib
import io
import unittest
from unittest.mock import patch

from scripts import run_scenarios as runner


class ScenarioRunnerTests(unittest.TestCase):
    def test_every_controller_command_is_covered_once_apart_from_normal(self):
        runner.validate_coverage()
        commands = [s.name for s in runner.SCENARIOS]
        commands += [s.restore for s in runner.SCENARIOS if s.restore]
        self.assertEqual(len(commands), len(set(commands)))
        self.assertEqual(set(commands), set(runner.COMMANDS) - {"normal", "state"})

    def test_new_controller_command_cannot_be_silently_skipped(self):
        with patch.object(runner, "COMMANDS", [*runner.COMMANDS, "new-fault"]):
            with self.assertRaisesRegex(RuntimeError, "new-fault"):
                runner.validate_coverage()

    def exercise(self, failure=None, cleanup_failure=None):
        cases = (runner.Scenario("camera-offline", restore="camera-online"), runner.Scenario("overheat"))
        events = []

        def restore(timeout):
            events.append("normal")
            if cleanup_failure and events.count("normal") == 2:
                raise cleanup_failure

        def verify(scenario, timeout):
            events.append("verify " + scenario.name)
            if failure:
                raise failure

        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(patch.object(runner, "SCENARIOS", cases))
            stack.enter_context(patch.object(runner, "validate_coverage"))
            stack.enter_context(patch.object(runner, "restore_normal", side_effect=restore))
            stack.enter_context(patch.object(runner, "state", return_value={"counts": {"entered": 0, "exited": 0}}))
            stack.enter_context(patch.object(runner, "wait", side_effect=lambda label, check, timeout: events.append(label)))
            stack.enter_context(patch.object(runner, "run", side_effect=events.append))
            stack.enter_context(patch.object(runner, "verify", side_effect=verify))
            if failure or cleanup_failure:
                with self.assertRaises(type(cleanup_failure or failure)):
                    runner.execute(observe_seconds=0)
            else:
                runner.execute(observe_seconds=0)
        return events

    def test_sequential_scenarios_restore_connection_before_normal(self):
        events = self.exercise()
        start = events.index("camera-offline")
        self.assertEqual(events[start:start + 5], ["camera-offline", "verify camera-offline", "camera-online",
                                                 "camera-online: connection recovered", "normal"])
        self.assertEqual(events[-5:], ["overheat", "verify overheat", "normal", "state", "normal"])

    def test_failure_stops_sequence_and_restores_normal(self):
        events = self.exercise(failure=RuntimeError("measured effect absent"))
        self.assertEqual(events[-1], "normal")
        self.assertNotIn("overheat", events)

    def test_ctrl_c_and_sigterm_restore_normal(self):
        for signum in (2, 15):
            with self.subTest(signal=signum):
                with self.assertRaises(KeyboardInterrupt) as caught:
                    runner.interrupted(signum, None)
                events = self.exercise(failure=caught.exception)
                self.assertEqual(events[-1], "normal")
                self.assertNotIn("overheat", events)

    def test_cleanup_failure_is_not_reported_as_success(self):
        events = self.exercise(failure=RuntimeError("scenario failed"), cleanup_failure=OSError("PLC offline"))
        self.assertEqual(events[-1], "normal")

    def test_list_does_not_touch_the_lab(self):
        with patch("sys.argv", ["run_scenarios", "--list"]), patch.object(runner, "run") as run:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(runner.main(), 0)
        run.assert_not_called()
        self.assertEqual(set(output.getvalue().splitlines()), set(runner.COMMANDS))
        self.assertEqual(output.getvalue().splitlines()[-1], "normal")


if __name__ == "__main__":
    unittest.main()
