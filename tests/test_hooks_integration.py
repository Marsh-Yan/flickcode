from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from flickcode.agent import AgentLoop
from flickcode.context import ContextManager
from flickcode.hooks import HookCatalog, HookEngine, HookEventName
from flickcode.hooks.prompt import HookPromptSection
from flickcode.prompt import SystemPromptBuilder
from flickcode.providers.base import Message, StreamEvent
from flickcode.tools.base import BaseTool, ToolResult, ToolSpec
from flickcode.tools.registry import ToolRegistry
from flickcode.tools import create_default_registry
from flickcode.session import Session


class FakeProvider:
    config = SimpleNamespace(protocol="openai")
    def __init__(self):
        self.calls = []
        self.round = 0
    def stream_chat(self, messages, thinking=False, tools=None, system=None):
        self.calls.append({"messages": list(messages), "system": system, "tools": tools})
        self.round += 1
        if self.round == 1:
            yield StreamEvent("tool_call", json.dumps({
                "id": "call-1",
                "name": "execute_command",
                "arguments": {"command": "danger"},
            }))
            yield StreamEvent("done", '{"usage":{"input_tokens":1}}')
        else:
            yield StreamEvent("text", "adjusted")
            yield StreamEvent("done", '{"usage":{"input_tokens":1}}')


class CountingTool(BaseTool):
    spec = ToolSpec(
        name="execute_command",
        description="test command",
        input_schema={"type": "object", "properties": {"command": {"type": "string"}}},
    )
    def __init__(self):
        self.calls = 0
    def execute(self, params):
        self.calls += 1
        return ToolResult(success=True, output="ran")


class HookAgentIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.user = self.root / "user"
        self.project.mkdir()
        self.user.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_deny_returns_reason_and_tool_after_prompt_to_next_request(self):
        (self.user / "hooks.yaml").write_text("""
hooks:
  - event: session.started
    action: {type: prompt, content: persistent-rule}
  - event: tool.before
    if:
      all:
        - {field: tool.name, exact: execute_command}
        - {field: tool.arguments.command, exact: danger}
    action: {type: shell, command: decide}
  - event: tool.after
    action: {type: prompt, content: tool-finished}
""", encoding="utf-8")

        def runner(command, **kwargs):
            return SimpleNamespace(
                returncode=0,
                stdout='{"decision":"deny","reason":"safe policy"}',
                stderr="",
            )

        engine = HookEngine(
            HookCatalog(self.project, self.user),
            self.project,
            shell_runner=runner,
        )
        engine.start()
        engine.dispatch(engine.make_event(HookEventName.SYSTEM_STARTED))
        engine.begin_session("s")

        provider = FakeProvider()
        registry = ToolRegistry()
        tool = CountingTool()
        registry.register_instance(tool)
        builder = SystemPromptBuilder()
        builder.add_section(HookPromptSection())
        messages = [Message(role="user", content="run it")]
        loop = AgentLoop(
            provider,
            registry,
            builder=builder,
            context_manager=ContextManager(provider),
            hook_engine=engine,
        )
        events = list(loop.run(messages))

        self.assertEqual(tool.calls, 0)
        self.assertEqual(provider.round, 2)
        self.assertIn("persistent-rule", provider.calls[0]["system"])
        second_contents = [item.content for item in provider.calls[1]["messages"]]
        self.assertTrue(any("[Hook denied] safe policy" in item for item in second_contents))
        self.assertTrue(any("tool-finished" in item for item in second_contents))
        self.assertTrue(any(event.type == "tool_result" for event in events))
        self.assertFalse(any("tool-finished" in item.content for item in messages))
        engine.close()

    def test_session_emits_full_non_tool_lifecycle(self):
        hooks_path = self.project / ".flick" / "hooks.yaml"
        hooks_path.parent.mkdir(parents=True)
        expected = [
            "system.started", "session.started", "turn.started",
            "message.user_accepted", "message.model_request",
            "message.assistant_completed", "turn.ended",
            "session.ending", "system.stopping",
        ]
        hooks_path.write_text(
            "hooks:\n" + "".join(
                "  - event: " + event + "\n"
                "    action: {type: prompt, content: '" + event + "'}\n"
                for event in expected
            ),
            encoding="utf-8",
        )
        config = self.root / "config.yaml"
        config.write_text(
            "providers:\n"
            "  - name: fake\n"
            "    protocol: openai\n"
            "    model: fake\n"
            "    base_url: https://example.invalid\n"
            "    api_key: fake\n",
            encoding="utf-8",
        )

        class FinalProvider:
            config = SimpleNamespace(protocol="openai")
            def stream_chat(self, messages, thinking=False, tools=None, system=None):
                yield StreamEvent("text", "done")
                yield StreamEvent("done", '{"usage":{"input_tokens":1}}')

        with mock.patch("flickcode.session.create_provider", return_value=FinalProvider()), \
             mock.patch("flickcode.session.Path.cwd", return_value=self.project):
            session = Session(
                config_path=str(config),
                tool_registry=create_default_registry(),
            )
            session.memory_scheduler.shutdown()
            session.memory_scheduler = None
            session.start(lambda path, summaries: True)
            list(session.agent_chat("hello"))
            snapshot = session.status_snapshot()
            session.close()

        seen = [item.event for item in session.hook_engine._recent if item.event]
        for event in expected:
            self.assertIn(event, seen)
        self.assertTrue(snapshot.hooks_started)
        self.assertEqual(snapshot.hook_active_rules, len(expected))
        self.assertEqual(snapshot.hook_project_trust, "trusted")


if __name__ == "__main__":
    unittest.main()
