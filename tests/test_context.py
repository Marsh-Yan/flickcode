"""Tests for FlickCode's local context-management subsystem."""

from __future__ import annotations

import tempfile
import unittest
from unittest import mock
from pathlib import Path

from flickcode.agent import AgentLoop, AgentMode
from flickcode.config import load_config
from flickcode.context import ContextConfig, ContextManager, ContextState, SafetyMode
from flickcode.context.compactor import ContextCompactor
from flickcode.context.estimator import TokenEstimator
from flickcode.context.store import ResultStore
from flickcode.context.summary import (
    SUMMARY_SECTION_HEADINGS,
    SUMMARY_SYSTEM_PROMPT,
    SummaryClient,
    serialize_history,
)
from flickcode.providers.base import Message, StreamEvent
from flickcode.session import Session
from flickcode.tools.base import BaseTool, ToolResult, ToolSpec
from flickcode.tools.registry import ToolRegistry
from flickcode.tui import _run_compact_command


def valid_summary() -> str:
    return "\n".join(f"## {heading}\n内容" for heading in SUMMARY_SECTION_HEADINGS)


class FakeProvider:
    """A deterministic provider used to inspect direct summary calls."""

    class Config:
        protocol = "openai"

    config = Config()

    def __init__(self, responses=None):
        self.responses = list(responses or [valid_summary()])
        self.calls = []

    def stream_chat(self, messages, thinking=False, tools=None, system=None):
        self.calls.append(
            {
                "messages": list(messages),
                "thinking": thinking,
                "tools": tools,
                "system": system,
            }
        )
        response = self.responses.pop(0) if self.responses else valid_summary()
        if isinstance(response, Exception):
            yield StreamEvent("error", str(response))
            return
        if response is None:
            yield StreamEvent("done", "")
            return
        yield StreamEvent("text", response)
        yield StreamEvent("done", '{"usage": {"input_tokens": 42}}')


class ChatProvider(FakeProvider):
    """Provider responses for Session.chat and one or more AgentLoop rounds."""

    def __init__(self, responses):
        super().__init__(responses=[])
        self.chat_responses = list(responses)

    def stream_chat(self, messages, thinking=False, tools=None, system=None):
        self.calls.append(
            {
                "messages": list(messages),
                "thinking": thinking,
                "tools": tools,
                "system": system,
            }
        )
        response = self.chat_responses.pop(0)
        for event in response:
            yield event


class EchoTool(BaseTool):
    spec = ToolSpec(
        name="echo",
        description="Echo a value",
        input_schema={"type": "object", "properties": {"value": {"type": "string"}}},
    )

    def execute(self, params):
        return ToolResult(success=True, output=params["value"])


class ContextConfigTests(unittest.TestCase):
    def test_defaults_and_storage_path(self):
        config = ContextConfig()
        self.assertEqual(config.automatic_safety_margin_tokens, 13_000)
        self.assertEqual(config.manual_safety_margin_tokens, 3_000)
        self.assertIsInstance(config.storage_dir, Path)

    def test_invalid_numeric_values_fail(self):
        with self.assertRaises(ValueError):
            ContextConfig(chars_per_token=0)
        with self.assertRaises(ValueError):
            ContextConfig(summary_max_retries=-1)

    def test_yaml_config_is_optional_and_overridable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.yaml"
            base.write_text(
                """
providers:
  - name: fake
    protocol: openai
    model: fake
    base_url: https://example.invalid
    api_key: key
context:
  context_window_tokens: 64000
  storage_dir: ~/context-test
""",
                encoding="utf-8",
            )
            config = load_config(str(base))
            self.assertEqual(config.context.context_window_tokens, 64_000)
            self.assertEqual(config.context.storage_dir, Path("~/context-test").expanduser())

            old = root / "old.yaml"
            old.write_text(
                """
providers:
  - name: fake
    protocol: openai
    model: fake
    base_url: https://example.invalid
    api_key: key
""",
                encoding="utf-8",
            )
            self.assertEqual(load_config(str(old)).context.context_window_tokens, 128_000)


class ResultStoreTests(unittest.TestCase):
    def test_tool_result_and_summary_are_preserved_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResultStore(ContextConfig(storage_dir=Path(directory)))
            first = store.store_tool_result(
                session_id="s/unsafe",
                message_index=3,
                tool_call_id="call/one",
                tool_name="read/file",
                content="full output",
            )
            second = store.store_tool_result(
                session_id="s/unsafe",
                message_index=3,
                tool_call_id="call/one",
                tool_name="read/file",
                content="full output",
            )
            summary_path = store.store_summary(session_id="s", summary="summary")

            self.assertEqual(first.path.read_text(encoding="utf-8"), "full output")
            self.assertEqual(second.path.read_text(encoding="utf-8"), "full output")
            self.assertNotEqual(first.path, second.path)
            self.assertEqual(summary_path.read_text(encoding="utf-8"), "summary")
            self.assertIn("Full result path:", first.preview)
            self.assertNotIn("/unsafe", first.path.name)


class TokenEstimatorTests(unittest.TestCase):
    def test_anchor_uses_only_incremental_messages(self):
        config = ContextConfig(chars_per_token=4)
        estimator = TokenEstimator(config)
        state = ContextState()
        messages = [Message(role="user", content="hello")]
        estimator.record_usage(state, 100, messages)

        before = estimator.estimate(messages, state)
        messages.append(Message(role="assistant", content="x" * 40))
        after = estimator.estimate(messages, state)

        self.assertTrue(before.anchored)
        self.assertTrue(after.anchored)
        self.assertGreater(after.input_tokens, before.input_tokens)

        messages[0].content = "changed old message"
        invalidated = estimator.estimate(messages, state)
        self.assertFalse(invalidated.anchored)

    def test_mode_specific_budget(self):
        config = ContextConfig(
            context_window_tokens=50_000,
            max_output_tokens=8_000,
            automatic_safety_margin_tokens=13_000,
            manual_safety_margin_tokens=3_000,
        )
        estimator = TokenEstimator(config)
        self.assertEqual(estimator.request_budget(SafetyMode.AUTOMATIC), 29_000)
        self.assertEqual(estimator.request_budget(SafetyMode.MANUAL), 39_000)


class SummaryClientTests(unittest.TestCase):
    def test_summary_is_isolated_and_tool_free(self):
        provider = FakeProvider()
        client = SummaryClient(provider)
        original = [
            Message(role="user", content="keep me unchanged"),
            Message(role="assistant", content="working"),
        ]
        result = client.summarize(serialize_history(original))

        self.assertTrue(result.success)
        self.assertEqual(len(provider.calls), 1)
        call = provider.calls[0]
        self.assertIsNone(call["tools"])
        self.assertEqual(len(call["messages"]), 1)
        self.assertEqual(call["messages"][0].role, "user")
        self.assertIn("keep me unchanged", call["messages"][0].content)
        self.assertIn("禁止调用任何工具", call["system"])
        self.assertIn("分析草稿", call["system"])
        self.assertIn("尽量保留原文", call["system"])
        self.assertEqual(original[0].content, "keep me unchanged")

    def test_missing_required_section_is_failure(self):
        provider = FakeProvider(["## 用户目标与明确约束\nonly one section"])
        result = SummaryClient(provider).summarize("history")
        self.assertFalse(result.success)
        self.assertIn("required sections", result.error)


class CompactorTests(unittest.TestCase):
    def test_batch_storage_prefers_largest_result_and_keeps_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ContextConfig(
                storage_dir=Path(directory),
                single_tool_result_chars=10_000,
                message_tool_result_chars=1_000,
            )
            estimator = TokenEstimator(config)
            compactor = ContextCompactor(config, ResultStore(config), estimator)
            messages = [
                Message(role="user", content="original request"),
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[
                        {"id": "large", "name": "read_file", "input": {}},
                        {"id": "small", "name": "grep", "input": {}},
                    ],
                ),
                Message(role="tool", tool_call_id="large", content="A" * 800),
                Message(role="tool", tool_call_id="small", content="B" * 500),
            ]
            outcome = compactor.lighten_tool_results(messages, session_id="session")

            self.assertTrue(outcome.changed)
            self.assertEqual(len(outcome.stored_paths), 1)
            self.assertTrue(messages[2].content.startswith("[FlickCode stored"))
            self.assertEqual(messages[2].tool_call_id, "large")
            self.assertEqual(messages[3].content, "B" * 500)
            self.assertEqual(messages[0].content, "original request")

    def test_recent_selection_does_not_split_tool_batch(self):
        config = ContextConfig(recent_target_tokens=1, recent_min_messages=1)
        compactor = ContextCompactor(config, ResultStore(config), TokenEstimator(config))
        messages = [
            Message(role="user", content="old"),
            Message(
                role="assistant",
                tool_calls=[{"id": "one", "name": "read_file", "input": {}}],
            ),
            Message(role="tool", tool_call_id="one", content="tool result"),
        ]
        older, recent = compactor.select_recent_messages(messages)
        self.assertEqual(older, [messages[0]])
        self.assertEqual(recent, messages[1:])

    def test_compacted_history_converts_for_both_provider_formats(self):
        from flickcode.providers.anthropic import AnthropicProvider
        from flickcode.providers.openai import OpenAIProvider

        messages = ContextCompactor.build_compacted_messages(
            valid_summary(),
            [
                Message(
                    role="assistant",
                    tool_calls=[
                        {"id": "read-1", "name": "read_file", "input": {"path": "a.py"}}
                    ],
                ),
                Message(role="tool", tool_call_id="read-1", content="contents"),
                Message(role="assistant", content="recent answer"),
            ],
        )
        anthropic_messages = AnthropicProvider.__new__(AnthropicProvider)._to_anthropic_messages(messages)
        openai_messages = OpenAIProvider.__new__(OpenAIProvider)._to_openai_messages(messages)

        self.assertEqual(openai_messages[0]["role"], "assistant")
        self.assertEqual(openai_messages[1]["role"], "user")
        self.assertEqual(openai_messages[3]["role"], "tool")
        self.assertEqual(openai_messages[3]["tool_call_id"], "read-1")
        self.assertEqual(anthropic_messages[0]["role"], "assistant")
        self.assertEqual(anthropic_messages[1]["role"], "user")
        self.assertEqual(anthropic_messages[3]["content"][0]["tool_use_id"], "read-1")

    def test_storage_failure_leaves_tool_content_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ContextConfig(
                storage_dir=Path(directory),
                single_tool_result_chars=10,
            )
            store = ResultStore(config)
            compactor = ContextCompactor(config, store, TokenEstimator(config))
            messages = [
                Message(
                    role="assistant",
                    tool_calls=[{"id": "read-1", "name": "read_file", "input": {}}],
                ),
                Message(role="tool", tool_call_id="read-1", content="X" * 100),
            ]
            with mock.patch.object(
                store,
                "store_tool_result",
                side_effect=__import__("flickcode.context.store", fromlist=["ContextStorageError"]).ContextStorageError("disk full"),
            ):
                outcome = compactor.lighten_tool_results(messages, session_id="test")

            self.assertFalse(outcome.changed)
            self.assertEqual(messages[1].content, "X" * 100)
            self.assertIn("disk full", outcome.errors[0])


class ContextManagerTests(unittest.TestCase):
    def _config(self, directory: str) -> ContextConfig:
        return ContextConfig(
            storage_dir=Path(directory),
            context_window_tokens=2_000,
            max_output_tokens=100,
            automatic_safety_margin_tokens=100,
            manual_safety_margin_tokens=100,
            recent_target_tokens=600,
            recent_min_messages=5,
            summary_max_retries=3,
        )

    def _long_history(self):
        return [Message(role="user", content="old " + "x" * 8_000)] + [
            Message(role="assistant", content=f"recent {index} " + "y" * 100)
            for index in range(5)
        ]

    def test_summary_rewrites_old_history_and_appends_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = FakeProvider([valid_summary()])
            manager = ContextManager(provider, self._config(directory))
            messages = self._long_history()
            preparation = manager.prepare_before_request(messages)

            self.assertTrue(preparation.changed)
            self.assertFalse(preparation.blocked)
            self.assertEqual(messages[0].role, "assistant")
            self.assertTrue(messages[0].content.startswith("[FlickCode context summary]"))
            self.assertEqual(messages[1].role, "user")
            self.assertIn("context boundary", messages[1].content)
            self.assertEqual(len(messages), 7)
            self.assertIsNotNone(preparation.diagnostic.summary_path)
            self.assertTrue(preparation.diagnostic.summary_path.exists())

    def test_three_summary_failures_open_circuit_without_history_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = FakeProvider([RuntimeError("bad"), RuntimeError("bad"), RuntimeError("bad")])
            manager = ContextManager(provider, self._config(directory))
            messages = self._long_history()
            original = [message.content for message in messages]

            preparation = manager.prepare_before_request(messages)
            self.assertTrue(preparation.blocked)
            self.assertTrue(manager.state.summary_circuit_open)
            self.assertEqual(manager.state.summary_failure_count, 3)
            self.assertEqual([message.content for message in messages], original)
            calls_after_failure = len(provider.calls)

            manager.prepare_before_request(messages)
            self.assertEqual(len(provider.calls), calls_after_failure)

            manager.reset_summary_circuit()
            self.assertFalse(manager.state.summary_circuit_open)
            self.assertEqual(manager.state.summary_failure_count, 0)

    def test_successful_summary_resets_existing_failure_count(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = FakeProvider([valid_summary()])
            manager = ContextManager(provider, self._config(directory))
            manager.state.summary_failure_count = 2
            messages = self._long_history()

            preparation = manager.prepare_before_request(messages)

            self.assertTrue(preparation.changed)
            self.assertEqual(manager.state.summary_failure_count, 0)
            self.assertFalse(manager.state.summary_circuit_open)

    def test_manual_compact_respects_open_circuit(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = FakeProvider([])
            manager = ContextManager(provider, self._config(directory))
            manager.state.summary_circuit_open = True
            messages = self._long_history()

            preparation = manager.compact(messages)

            self.assertEqual(len(provider.calls), 0)
            self.assertIn(preparation.diagnostic.action, ("blocked", "circuit_open"))

    def test_second_compaction_pass_keeps_only_recent_minimum_when_needed(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = FakeProvider([valid_summary(), valid_summary()])
            config = ContextConfig(
                storage_dir=Path(directory),
                context_window_tokens=630,
                max_output_tokens=100,
                automatic_safety_margin_tokens=100,
                recent_target_tokens=1_000,
                recent_min_messages=5,
            )
            manager = ContextManager(provider, config)
            messages = [
                Message(role="user", content="old " + "x" * 2_000),
                Message(role="assistant", content="middle " + "z" * 1_000),
            ] + [
                Message(role="assistant", content=f"recent {index} " + "y" * 100)
                for index in range(5)
            ]

            preparation = manager.prepare_before_request(messages)

            self.assertFalse(preparation.blocked)
            self.assertEqual(len(provider.calls), 2)
            self.assertEqual(len(messages), 7)
            self.assertIn("recent 0", messages[2].content)


class RequestPathIntegrationTests(unittest.TestCase):
    @staticmethod
    def _session_with(provider, config):
        """Build a focused Session object without loading real credentials/MCP."""
        session = Session.__new__(Session)
        session.provider = provider
        session.provider_config = type(
            "ProviderConfig",
            (), {"protocol": "openai", "thinking": False},
        )()
        session.messages = []
        session.tools = ToolRegistry()
        session.tools.register_instance(EchoTool())
        session.confirm_callback = None
        session.context_manager = ContextManager(provider, config)
        return session

    def test_session_chat_prepares_request_and_records_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = ChatProvider(
                [[
                    StreamEvent("text", "hello"),
                    StreamEvent("done", '{"usage":{"input_tokens":77,"output_tokens":3}}'),
                ]]
            )
            config = ContextConfig(storage_dir=Path(directory))
            session = self._session_with(provider, config)

            events = list(session.chat("hello"))

            self.assertEqual([event.type for event in events], ["text", "done"])
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(provider.calls[0]["messages"][0].content, "hello")
            self.assertEqual(session.context_manager.state.last_input_tokens, 77)
            self.assertEqual(session.messages[-1].role, "assistant")

    def test_session_chat_externalizes_tool_output_before_next_request(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = ChatProvider(
                [[
                    StreamEvent(
                        "tool_call",
                        '{"id":"echo-1","name":"echo","arguments":{"value":"' + "Z" * 100 + '"}}',
                    ),
                    StreamEvent("done", '{"usage":{"input_tokens":77}}'),
                ]]
            )
            config = ContextConfig(
                storage_dir=Path(directory),
                single_tool_result_chars=10,
            )
            session = self._session_with(provider, config)

            list(session.chat("get result"))

            tool_message = next(message for message in session.messages if message.role == "tool")
            self.assertTrue(tool_message.content.startswith("[FlickCode stored"))
            self.assertEqual(len(session.context_manager.state.last_result_paths), 1)
            self.assertEqual(
                session.context_manager.state.last_result_paths[0].read_text(encoding="utf-8"),
                "Z" * 100,
            )

    def test_session_chat_blocks_before_provider_when_context_is_unsafe(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = ChatProvider([])
            config = ContextConfig(
                storage_dir=Path(directory),
                context_window_tokens=120,
                max_output_tokens=50,
                automatic_safety_margin_tokens=50,
            )
            session = self._session_with(provider, config)
            events = list(session.chat("x" * 1_000))

            self.assertEqual(len(provider.calls), 0)
            self.assertEqual(events[0].type, "error")
            self.assertEqual(session.messages[0].content, "x" * 1_000)

    def test_agent_loop_prepares_every_round_and_records_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = ChatProvider(
                [
                    [
                        StreamEvent(
                            "tool_call",
                            '{"id":"echo-1","name":"echo","arguments":{"value":"' + "Z" * 100 + '"}}',
                        ),
                        StreamEvent("done", '{"usage":{"input_tokens":41}}'),
                    ],
                    [
                        StreamEvent("text", "completed"),
                        StreamEvent("done", '{"usage":{"input_tokens":59}}'),
                    ],
                ]
            )
            config = ContextConfig(
                storage_dir=Path(directory),
                single_tool_result_chars=10,
            )
            registry = ToolRegistry()
            registry.register_instance(EchoTool())
            manager = ContextManager(provider, config)
            messages = [Message(role="user", content="do work")]

            events = list(
                AgentLoop(
                    provider,
                    registry,
                    AgentMode.FULL,
                    context_manager=manager,
                ).run(messages)
            )

            self.assertEqual(len(provider.calls), 2)
            tool_message = next(
                message
                for message in provider.calls[1]["messages"]
                if message.role == "tool"
            )
            self.assertTrue(tool_message.content.startswith("[FlickCode stored"))
            self.assertEqual(manager.state.last_input_tokens, 59)
            self.assertEqual(messages[-1].content, "completed")
            self.assertEqual([event.type for event in events].count("tool_result"), 1)

    def test_session_manual_compact_forces_summary_and_uses_manual_margin(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = FakeProvider([valid_summary()])
            config = ContextConfig(
                storage_dir=Path(directory),
                context_window_tokens=20_000,
                max_output_tokens=1_000,
                automatic_safety_margin_tokens=13_000,
                manual_safety_margin_tokens=3_000,
                recent_min_messages=1,
            )
            session = self._session_with(provider, config)
            session.messages = [
                Message(role="user", content="old context"),
                Message(role="assistant", content="recent context"),
            ]

            preparation = session.compact_context()

            self.assertTrue(preparation.changed)
            self.assertEqual(preparation.diagnostic.safety_margin_tokens, 3_000)
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(session.messages[0].role, "assistant")


class TUICompactTests(unittest.TestCase):
    def test_compact_command_calls_session_and_renders_diagnostic(self):
        diagnostic = type(
            "Diagnostic",
            (), {
                "message": "Context was compacted.",
                "estimated_input_tokens": 10,
                "request_budget_tokens": 20,
                "safety_margin_tokens": 3_000,
                "action": "compacted",
                "stored_paths": [],
                "summary_path": None,
                "errors": [],
            },
        )()
        preparation = type("Preparation", (), {"diagnostic": diagnostic})()

        class FakeSession:
            def __init__(self):
                self.calls = 0

            def compact_context(self):
                self.calls += 1
                return preparation

        class FakeRenderer:
            def __init__(self):
                self.progress = []
                self.errors = []

            def render_progress(self, text):
                self.progress.append(text)

            def render_error(self, text):
                self.errors.append(text)

        session = FakeSession()
        renderer = FakeRenderer()
        result = _run_compact_command(session, renderer)

        self.assertIs(result, preparation)
        self.assertEqual(session.calls, 1)
        self.assertTrue(renderer.progress)
        self.assertFalse(renderer.errors)


if __name__ == "__main__":
    unittest.main()
