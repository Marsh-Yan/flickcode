from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from flickcode.hooks import HookCatalog, HookEngine, HookEventName
from flickcode.hooks.actions import BoundedExecutor


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class HookEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.user = self.root / "user"
        self.project.mkdir()
        self.user.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def engine(self, yaml_text, runner=None):
        write(self.user / "hooks.yaml", yaml_text)
        engine = HookEngine(
            HookCatalog(self.project, self.user),
            self.project,
            shell_runner=runner,
        )
        engine.start()
        return engine

    def test_prompt_order_once_and_session_reset(self):
        engine = self.engine("""
hooks:
  - name: first
    event: turn.started
    once: true
    action: {type: prompt, content: first}
  - event: turn.started
    action: {type: prompt, content: second}
""")
        engine.begin_session("s1")
        event = engine.make_event(HookEventName.TURN_STARTED)
        engine.dispatch(event)
        engine.dispatch(event)
        self.assertEqual(engine.consume_request_prompts(), ("first", "second", "second"))
        engine.begin_session("s2")
        engine.dispatch(event)
        self.assertEqual(engine.consume_request_prompts(), ("first", "second"))
        engine.close()

    def test_explicit_deny_stops_remaining_rules(self):
        calls = []
        def runner(command, **kwargs):
            calls.append(command)
            output = '{"decision":"deny","reason":"blocked"}' if command == "deny" else ""
            return SimpleNamespace(returncode=0, stdout=output, stderr="")
        engine = self.engine("""
hooks:
  - event: tool.before
    action: {type: shell, command: deny}
  - event: tool.before
    action: {type: shell, command: later}
""", runner)
        engine.begin_session("s")
        result = engine.before_tool("c", "execute_command", {"command": "x"}, {})
        self.assertTrue(result.intercepted)
        self.assertEqual(result.reason, "blocked")
        self.assertEqual(calls, ["deny"])
        engine.close()

    def test_nonzero_and_invalid_output_are_fail_open(self):
        def runner(command, **kwargs):
            if command == "bad-exit":
                return SimpleNamespace(returncode=1, stdout='{"decision":"deny","reason":"x"}', stderr="no")
            return SimpleNamespace(returncode=0, stdout="not-json", stderr="")
        engine = self.engine("""
hooks:
  - event: tool.before
    action: {type: shell, command: bad-exit}
  - event: tool.before
    action: {type: shell, command: bad-json}
""", runner)
        engine.begin_session("s")
        result = engine.before_tool("c", "execute_command", {}, {})
        self.assertFalse(result.intercepted)
        self.assertEqual(len(result.executed_rule_ids), 2)
        engine.close()

    def test_project_trust_and_status(self):
        write(self.project / ".flick" / "hooks.yaml", """
hooks:
  - event: session.started
    action: {type: prompt, content: project}
""")
        engine = HookEngine(HookCatalog(self.project, self.user), self.project)
        seen = []
        engine.start(lambda path, summaries: seen.append((path, summaries)) or False)
        engine.begin_session("s")
        status = engine.status_snapshot()
        self.assertEqual(status.project_trust, "untrusted")
        self.assertEqual(status.active_rules, 0)
        self.assertEqual(len(seen), 1)
        engine.close()

    def test_bounded_executor_is_non_blocking_and_closes(self):
        gate = threading.Event()
        done = []
        executor = BoundedExecutor(workers=1, pending=0)
        self.assertTrue(
            executor.submit(lambda: gate.wait(1), lambda future: done.append(True))
        )
        self.assertFalse(executor.submit(lambda: None, lambda future: None))
        self.assertEqual(executor.active_count, 1)
        gate.set()
        for _ in range(100):
            if done:
                break
            time.sleep(0.001)
        self.assertTrue(done)
        executor.close()
        self.assertFalse(executor.submit(lambda: None, lambda future: None))


if __name__ == "__main__":
    unittest.main()
