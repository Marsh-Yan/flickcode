"""Integration coverage for built-in commands and safe Session snapshots."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from prompt_toolkit.document import Document

from flickcode.agent import AgentMode, PlanContext
from flickcode.commands import (
    InMemoryCommandUI,
    InputRouter,
    InteractionMode,
    build_default_registry,
)
from flickcode.context.models import ContextDiagnostic, ContextPreparation, ContextState
from flickcode.session import SessionStatusSnapshot
from flickcode.tui import CommandCompleter


class FakeSession:
    def __init__(self):
        self.plan_context = None
        self.active_session_id = "20260813-120000-a1b2"
        self.compact_calls = 0
        self.sent = []
        self.diagnostics = []
        self.provider_config = SimpleNamespace(name="fake", model="fake-model", protocol="openai")
        self.permission_mode = SimpleNamespace(value="default")
        self.permission_engine = SimpleNamespace(mode=self.permission_mode)
        self.context_manager = SimpleNamespace(
            state=ContextState(last_diagnostic=ContextDiagnostic(message="Context is within the request budget."))
        )
        self.mcp_startup_report = SimpleNamespace(registered_tools=[], failed_servers=[])
        self.mcp_startup_errors = []
        self.instruction_bundle = SimpleNamespace(project_text="", user_text="")
        self.project_memory = None
        self.user_memory = None

    def compact_context(self):
        self.compact_calls += 1
        return ContextPreparation(
            messages=[],
            diagnostic=ContextDiagnostic(
                action="compacted",
                estimated_input_tokens=10,
                request_budget_tokens=100,
                safety_margin_tokens=3,
                message="Context was compacted with a structured summary.",
            ),
        )

    def list_sessions(self):
        return []

    def resume_session(self, session_id):
        raise AssertionError("resume not expected")

    def drain_diagnostics(self):
        diagnostics = list(self.diagnostics)
        self.diagnostics.clear()
        return diagnostics

    def status_snapshot(self):
        return SessionStatusSnapshot(
            provider_name="fake",
            model="fake-model",
            protocol="openai",
            active_session_id=self.active_session_id,
            has_plan_context=self.plan_context is not None,
            permission_mode="default",
            input_tokens=0,
            output_tokens=0,
            thinking_tokens=0,
            estimated_input_tokens=10,
            request_budget_tokens=100,
            safety_margin_tokens=3,
            context_action="unchanged",
            context_diagnostic="Context is within the request budget.",
            summary_path=None,
            result_paths=(),
            mcp_registered_tools=0,
            mcp_failed_servers=0,
            diagnostics=(),
        )


class BuiltinCommandIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.session = FakeSession()
        self.ui = InMemoryCommandUI()
        self.router = InputRouter(build_default_registry())

    def test_local_commands_do_not_send_to_agent(self):
        for command in ("/help", "/clear", "/session", "/permission", "/status"):
            self.router.handle(command, session=self.session, ui=self.ui)
        self.assertEqual(self.ui.sent_messages, [])
        self.assertEqual(self.ui.clear_count, 1)

    def test_compact_reports_result_without_sending_prompt(self):
        self.router.handle("/compact", session=self.session, ui=self.ui)
        self.assertEqual(self.session.compact_calls, 1)
        self.assertEqual(self.ui.sent_messages, [])
        self.assertIn("compacted", "\n".join(self.ui.messages))

    def test_plan_mode_and_do_mode(self):
        self.router.handle("/plan", session=self.session, ui=self.ui)
        self.assertEqual(self.ui.mode, InteractionMode.PLAN)
        self.assertEqual(self.ui.sent_messages, [])
        self.router.handle("next task", session=self.session, ui=self.ui)
        self.assertEqual(self.ui.sent_messages[-1], ("next task", AgentMode.PLAN))

        self.session.plan_context = PlanContext("plan", [], [])
        self.router.handle("/do", session=self.session, ui=self.ui)
        self.assertEqual(self.ui.mode, InteractionMode.DEFAULT)
        self.assertEqual(self.ui.sent_messages[-1], ("Execute the plan.", AgentMode.EXECUTE))

    def test_do_without_plan_does_not_change_mode_or_send(self):
        self.ui.set_mode(InteractionMode.PLAN)
        self.router.handle("/do", session=self.session, ui=self.ui)
        self.assertEqual(self.ui.mode, InteractionMode.PLAN)
        self.assertEqual(self.ui.sent_messages, [])
        self.assertIn("No plan context", self.ui.errors[-1])

    def test_audit_delegates_to_review_skill_with_full_mode_and_focus(self):
        self.router.handle("/audit permissions", session=self.session, ui=self.ui)
        message, mode = self.ui.sent_messages[-1]
        self.assertEqual(mode, AgentMode.FULL)
        self.assertIn("permissions", message)

    def test_aliases_resolve_to_builtin_commands(self):
        self.router.handle("/SESSIONS", session=self.session, ui=self.ui)
        self.router.handle("/? status", session=self.session, ui=self.ui)
        self.assertTrue(any("/status" in message for message in self.ui.messages))

    def test_status_snapshot_is_safe_and_reports_context(self):
        snapshot = self.session.status_snapshot()
        self.assertEqual(snapshot.provider_name, "fake")
        self.assertEqual(snapshot.context_action, "unchanged")
        self.assertNotIn("key", repr(snapshot).lower())

    def test_tui_completer_uses_registry_and_stops_at_arguments(self):
        completer = CommandCompleter(build_default_registry())
        single = list(completer.get_completions(Document("/st"), None))
        self.assertEqual([item.text for item in single], ["/status"])
        self.assertEqual(
            list(completer.get_completions(Document("/status arg"), None)), []
        )


if __name__ == "__main__":
    unittest.main()
