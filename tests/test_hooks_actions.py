from __future__ import annotations

import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from flickcode.hooks.actions import ActionExecutor, parse_intercept, prepare_action
from flickcode.hooks.events import build_event
from flickcode.hooks.models import (
    HookEventName,
    HttpAction,
    InterceptDecision,
    PromptAction,
    ShellAction,
    SubAgentAction,
)
from flickcode.hooks.prompt_state import PromptState
from flickcode.hooks.template import HookTemplateError


class FakeResponse:
    def __init__(self, body=b"", status=200):
        self.body = body
        self.status = status
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, size=-1):
        return self.body[:size]
    def getcode(self):
        return self.status


class FakeOpener:
    def __init__(self, response):
        self.response = response
        self.calls = []
    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class HookActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temp.name)
        self.event = build_event(
            HookEventName.TOOL_BEFORE,
            cwd=self.root,
            session_id="s1",
            tool_call_id="c1",
            tool_name="execute_command",
            tool_arguments={"command": "git status"},
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_template_expansion_and_unknown_variable(self):
        action = prepare_action(
            ShellAction("check {{tool.arguments.command}}"),
            self.event,
        )
        self.assertEqual(action.command, "check git status")
        with self.assertRaises(HookTemplateError):
            prepare_action(PromptAction("{{tool.missing}}"), self.event)

    def test_shell_failure_does_not_become_deny(self):
        def runner(*args, **kwargs):
            return SimpleNamespace(returncode=3, stdout='{"decision":"deny","reason":"x"}', stderr="bad")
        executor = ActionExecutor(self.root, PromptState(), shell_runner=runner)
        result = executor.execute("r", ShellAction("x"), self.event)
        self.assertFalse(result.success)
        self.assertIsNone(parse_intercept(result).decision)

    def test_shell_timeout_is_safe_failure(self):
        def runner(*args, **kwargs):
            raise subprocess.TimeoutExpired("x", 1)
        result = ActionExecutor(self.root, PromptState(), shell_runner=runner).execute(
            "r", ShellAction("x", timeout_seconds=1), self.event
        )
        self.assertFalse(result.success)
        self.assertIn("timed out", result.error)

    def test_http_request_and_explicit_deny(self):
        opener = FakeOpener(FakeResponse(b'{"decision":"deny","reason":"policy"}'))
        executor = ActionExecutor(self.root, PromptState(), http_opener=opener)
        action = HttpAction("https://example.test", headers={"X": "{{tool.name}}"}, body={"call": "{{tool.call_id}}"})
        result = executor.execute("r", prepare_action(action, self.event), self.event)
        self.assertTrue(result.success)
        self.assertEqual(parse_intercept(result).decision, InterceptDecision.DENY)
        request, timeout = opener.calls[0]
        self.assertEqual(request.headers["X"], "execute_command")
        self.assertIn(b'"call":"c1"', request.data)
        self.assertEqual(timeout, 10)

    def test_prompt_scopes_and_subagent_placeholder(self):
        state = PromptState()
        executor = ActionExecutor(self.root, state)
        session_event = build_event(HookEventName.SESSION_STARTED, cwd=self.root, session_id="s")
        self.assertTrue(executor.execute("p", PromptAction("persistent"), session_event).success)
        self.assertEqual(state.persistent(), ("persistent",))
        executor.execute("p2", PromptAction("next"), self.event)
        self.assertEqual(state.consume_pending(), ("next",))
        child = executor.execute("child", SubAgentAction("do work"), self.event)
        self.assertFalse(child.success)
        self.assertIn("not executable", child.error)


if __name__ == "__main__":
    unittest.main()
