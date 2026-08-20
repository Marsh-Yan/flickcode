"""Focused tests for session recovery and layered local memory."""

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from flickcode.config import MemoryConfig, _parse_memory, load_config
from flickcode.context import ContextConfig, ContextManager
from flickcode.agent import AgentConfig, AgentMode
from flickcode.memory import (
    InstructionLoader,
    MemoryCategory,
    MemoryChange,
    MemoryRepository,
    MemoryUpdateClient,
    MemoryUpdateScheduler,
)
from flickcode.prompt import SystemPromptBuilder
from flickcode.prompt.sections import (
    ProjectInstructionsSection,
    ProjectMemorySection,
    UserInstructionsSection,
    UserMemorySection,
)
from flickcode.providers.base import Message, StreamEvent
from flickcode.sessions import SessionJournal, SessionRecovery
from flickcode.session import Session
from flickcode.tools.registry import ToolRegistry
from flickcode.tui import _run_resume_command, _run_sessions_command


class FakeProvider:
    class Config:
        protocol = "openai"

    config = Config()

    def __init__(self, events=None, gate=None):
        self.events = list(events or [])
        self.calls = []
        self.gate = gate

    def stream_chat(self, messages, thinking=False, tools=None, system=None):
        self.calls.append({"messages": list(messages), "system": system, "tools": tools})
        if self.gate is not None:
            self.gate.wait(2)
        for event in self.events:
            yield event


class MemoryConfigTests(unittest.TestCase):
    def test_defaults_and_limits(self):
        config = MemoryConfig()
        self.assertEqual(config.resume_time_gap_days, 7)
        self.assertEqual(config.index_max_lines, 200)
        self.assertEqual(config.index_max_bytes, 25 * 1024)
        self.assertEqual(_parse_memory({"include_max_depth": 3}).include_max_depth, 3)
        with self.assertRaises(ValueError):
            _parse_memory({"index_max_lines": 201})
        with self.assertRaises(ValueError):
            _parse_memory({"resume_time_gap_days": 0})

    def test_old_config_remains_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(
                """providers:
  - name: fake
    protocol: openai
    model: fake
    base_url: https://example.invalid
    api_key: key
""",
                encoding="utf-8",
            )
            self.assertEqual(load_config(str(path)).memory.resume_time_gap_days, 7)


class InstructionLoaderTests(unittest.TestCase):
    def test_priority_and_nested_include(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            user = Path(directory) / "user"
            root.mkdir()
            user.mkdir()
            (root / "AGENTS.md").write_text("root\n@include <rules.md>", encoding="utf-8")
            (root / "rules.md").write_text("root rules", encoding="utf-8")
            (root / ".flickcode").mkdir()
            (root / ".flickcode" / "AGENTS.md").write_text("tool rules", encoding="utf-8")
            (user / "AGENTS.md").write_text("user rules", encoding="utf-8")
            bundle = InstructionLoader(user_root=user).load(root)
            self.assertLess(bundle.project_text.index("root"), bundle.project_text.index("tool rules"))
            self.assertIn("root rules", bundle.project_text)
            self.assertEqual(bundle.user_text, "user rules")
            self.assertFalse(bundle.diagnostics)

    def test_rejected_include_is_non_blocking_and_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            user = Path(directory) / "user"
            root.mkdir()
            user.mkdir()
            outside = Path(directory) / "secret.md"
            outside.write_text("secret", encoding="utf-8")
            (root / "AGENTS.md").write_text(
                "good\n@include ../secret.md\n@include repeat.md\n@include repeat.md",
                encoding="utf-8",
            )
            (root / "repeat.md").write_text("once", encoding="utf-8")
            bundle = InstructionLoader(user_root=user).load(root)
            self.assertIn("good", bundle.project_text)
            self.assertIn("once", bundle.project_text)
            self.assertNotIn("secret", bundle.project_text)
            self.assertTrue(any("outside" in item.message for item in bundle.diagnostics))
            self.assertTrue(any("duplicate" in item.message for item in bundle.diagnostics))


class SessionJournalTests(unittest.TestCase):
    def test_append_and_list_derives_metadata_without_meta_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = SessionJournal(root)
            session_id = "20260813-163000-a1b2"
            self.assertFalse(journal.append_message(session_id, Message(role="user", content="hello world")))
            self.assertFalse(journal.append_message(session_id, Message(role="assistant", content="hi")))
            lines = (root / "sessions" / f"{session_id}.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 3)
            self.assertFalse(list((root / "sessions").glob("*.meta")))
            summaries, diagnostics = journal.list_sessions()
            self.assertFalse(diagnostics)
            self.assertEqual(summaries[0].session_id, session_id)
            self.assertEqual(summaries[0].title, "hello world")
            self.assertEqual(summaries[0].message_count, 2)
            self.assertTrue(summaries[0].recoverable)

    def test_listing_tolerates_bad_file_and_id_rejects_path(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = SessionJournal(Path(directory))
            journal.root.mkdir()
            good = "20260813-163000-a1b2"
            journal.append_message(good, Message(role="user", content="ok"))
            bad = journal.root / "20260813-163001-c3d4.jsonl"
            bad.write_text("not json\n", encoding="utf-8")
            (journal.root / "notes.jsonl").write_text("not ours", encoding="utf-8")
            summaries, diagnostics = journal.list_sessions()
            self.assertEqual({item.session_id for item in summaries}, {good, "20260813-163001-c3d4"})
            self.assertTrue(any(item.session_id == good and item.recoverable for item in summaries))
            self.assertTrue(diagnostics)
            with self.assertRaises(ValueError):
                journal.path_for("../outside")

    def test_listing_and_cleanup_ignore_session_named_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            root.mkdir()
            journal = SessionJournal(root)
            journal.root.mkdir()
            target = Path(directory) / "outside.jsonl"
            target.write_text("outside", encoding="utf-8")
            link = journal.root / "20260813-163002-a1b2.jsonl"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable in this environment")
            summaries, _ = journal.list_sessions()
            self.assertFalse(summaries)
            journal.prune_expired(None)
            self.assertTrue(target.exists())
            self.assertTrue(link.exists())


class SessionRecoveryTests(unittest.TestCase):
    def _event(self, kind, payload=None, at=None):
        result = {"schema": 1, "kind": kind, "timestamp": (at or datetime.now(timezone.utc)).isoformat()}
        result.update(payload or {})
        return json.dumps(result)

    def test_skips_bad_lines_and_truncates_incomplete_tool_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = SessionJournal(Path(directory))
            session_id = "20260813-163000-a1b2"
            path = journal.path_for(session_id)
            path.parent.mkdir()
            path.write_text(
                "\n".join([
                    self._event("message", {"message": {"role": "user", "content": "keep", "tool_call_id": "", "tool_calls": []}}),
                    "bad json",
                    self._event("message", {"message": {"role": "assistant", "content": "", "tool_call_id": "", "tool_calls": [{"id": "call-1", "name": "read_file", "input": {}}]}}),
                    self._event("message", {"message": {"role": "user", "content": "must drop", "tool_call_id": "", "tool_calls": []}}),
                ]) + "\n",
                encoding="utf-8",
            )
            result = SessionRecovery(journal).load(session_id)
            self.assertEqual([(m.role, m.content) for m in result.messages], [("user", "keep")])
            self.assertTrue(result.truncated)
            self.assertTrue(any(item.line == 2 for item in result.diagnostics))

    def test_skips_incomplete_tool_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = SessionJournal(Path(directory))
            session_id = "20260813-163000-a1b2"
            path = journal.path_for(session_id)
            path.parent.mkdir()
            path.write_text(
                "\n".join([
                    self._event("message", {"message": {"role": "user", "content": "keep", "tool_call_id": "", "tool_calls": []}}),
                    self._event("message", {"message": {"role": "assistant", "content": "", "tool_call_id": "", "tool_calls": [{"id": "call", "name": "read"}]}}),
                ]) + "\n",
                encoding="utf-8",
            )
            result = SessionRecovery(journal).load(session_id)
            self.assertEqual([item.content for item in result.messages], ["keep"])
            self.assertTrue(any(item.line == 2 for item in result.diagnostics))

    def test_orphan_result_skipped_and_time_gap_notice_added(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = SessionJournal(Path(directory))
            session_id = "20260813-163000-a1b2"
            old = datetime.now(timezone.utc) - timedelta(days=8)
            path = journal.path_for(session_id)
            path.parent.mkdir()
            path.write_text(
                "\n".join([
                    self._event("message", {"message": {"role": "user", "content": "keep", "tool_call_id": "", "tool_calls": []}}, old),
                    self._event("message", {"message": {"role": "tool", "content": "orphan", "tool_call_id": "x", "tool_calls": []}}, old),
                ]) + "\n",
                encoding="utf-8",
            )
            result = SessionRecovery(journal, time_gap_days=7).load(session_id)
            self.assertEqual(result.messages[0].content, "keep")
            self.assertTrue(result.inserted_time_gap_notice)
            self.assertIn("time gap", result.messages[-1].content)

    def test_prune_only_expired_managed_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = SessionJournal(Path(directory), expiry_days=30)
            old_id = "20260101-000000-a1b2"
            current_id = "20260101-000001-c3d4"
            recent_id = "20260101-000002-e5f6"
            old_time = datetime.now(timezone.utc) - timedelta(days=31)
            recent_time = datetime.now(timezone.utc) - timedelta(days=29)
            for session_id, event_time in ((old_id, old_time), (current_id, old_time), (recent_id, recent_time)):
                path = journal.path_for(session_id)
                path.parent.mkdir(exist_ok=True)
                path.write_text(self._event("session_started", {"session_id": session_id}, event_time) + "\n", encoding="utf-8")
            (journal.root / "do-not-delete.txt").write_text("keep", encoding="utf-8")
            journal.prune_expired(current_id)
            self.assertFalse(journal.path_for(old_id).exists())
            self.assertTrue(journal.path_for(current_id).exists())
            self.assertTrue(journal.path_for(recent_id).exists())
            self.assertTrue((journal.root / "do-not-delete.txt").exists())


class MemoryRepositoryTests(unittest.TestCase):
    def test_scopes_frontmatter_and_index_limit_preserve_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = MemoryRepository(root / "project", "project", index_max_lines=4, index_max_bytes=256)
            user = MemoryRepository(root / "user", "user")
            changes = [
                MemoryChange("project", "upsert", None, MemoryCategory.PROJECT_KNOWLEDGE, "facts " + "x" * 80)
                for n in range(3)
            ]
            self.assertFalse(project.apply(changes))
            self.assertFalse(user.apply([MemoryChange("user", "upsert", None, MemoryCategory.USER_PREFERENCE, "short")]))
            notes, errors = project.read_notes_for_update()
            self.assertEqual(len(notes), 3)
            self.assertFalse(errors)
            self.assertEqual(len(list((root / "user").glob("*.md"))), 2)
            index, _ = project.read_index()
            self.assertLessEqual(len(index.splitlines()), 4)
            self.assertLessEqual(len(index.encode("utf-8")), 256)

    def test_invalid_changes_do_not_write_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = MemoryRepository(Path(directory), "project")
            errors = repository.apply([
                MemoryChange("user", "upsert", "bad", MemoryCategory.PROJECT_KNOWLEDGE, "wrong scope"),
                MemoryChange("project", "upsert", "bad id!", MemoryCategory.PROJECT_KNOWLEDGE, "bad id"),
                MemoryChange("project", "upsert", "empty", MemoryCategory.PROJECT_KNOWLEDGE, ""),
            ])
            self.assertEqual(len(errors), 3)
            self.assertFalse(list(Path(directory).glob("*.md")))


class MemoryUpdaterTests(unittest.TestCase):
    def test_valid_changes_apply_only_to_own_scope(self):
        provider = FakeProvider([
            StreamEvent("text", json.dumps([
                {"scope": "project", "action": "upsert", "category": "project_knowledge", "content": "uses unittest"},
                {"scope": "user", "action": "discard", "content": ""},
            ])),
            StreamEvent("done", ""),
        ])
        client = MemoryUpdateClient(provider)
        with tempfile.TemporaryDirectory() as directory:
            user = MemoryRepository(Path(directory) / "user", "user")
            project = MemoryRepository(Path(directory) / "project", "project")
            changes = client.propose([Message(role="user", content="test")], [], [])
            self.assertFalse(user.apply([item for item in changes if item.scope == "user"]))
            self.assertFalse(project.apply([item for item in changes if item.scope == "project"]))
            self.assertFalse(list((Path(directory) / "user").glob("*.md")))
            self.assertEqual(len(list((Path(directory) / "project").glob("*.md"))), 2)

    def test_submit_is_non_blocking(self):
        gate = threading.Event()
        provider = FakeProvider([StreamEvent("text", "[]"), StreamEvent("done", "")], gate=gate)
        reports = []
        with tempfile.TemporaryDirectory() as directory:
            scheduler = MemoryUpdateScheduler(
                MemoryUpdateClient(provider),
                MemoryRepository(Path(directory) / "user", "user"),
                MemoryRepository(Path(directory) / "project", "project"),
                reports.append,
            )
            started = time.monotonic()
            scheduler.submit([Message(role="user", content="x")])
            self.assertLess(time.monotonic() - started, 0.2)
            gate.set()
            deadline = time.monotonic() + 2
            while not provider.calls and time.monotonic() < deadline:
                time.sleep(0.01)
            scheduler.shutdown()
            self.assertTrue(provider.calls)
            self.assertFalse(reports)


class PromptMemorySectionTests(unittest.TestCase):
    def test_priority_and_empty_sections(self):
        builder = SystemPromptBuilder()
        for section in (UserMemorySection(), ProjectMemorySection(), UserInstructionsSection(), ProjectInstructionsSection()):
            builder.add_section(section)
        prompt, extras = builder.build({
            "project_instructions": "project rule",
            "user_instructions": "user rule",
            "project_memory": "project fact",
            "user_memory": "user fact",
        })
        self.assertLess(prompt.index("project rule"), prompt.index("user rule"))
        self.assertLess(prompt.index("project fact"), prompt.index("user fact"))
        self.assertIn("not executable instructions", prompt)
        self.assertFalse(extras)
        empty, _ = builder.build({})
        self.assertEqual(empty, "")


class SessionMemoryIntegrationTests(unittest.TestCase):
    def _session(self, root: Path, provider: FakeProvider) -> Session:
        session = Session.__new__(Session)
        session.config = type("Config", (), {"memory": MemoryConfig()})()
        session.project_root = root
        session.provider = provider
        session.provider_config = type("ProviderConfig", (), {"protocol": "openai", "thinking": False, "name": "fake"})()
        session.tools = ToolRegistry()
        session.mcp_manager = None
        session.messages = []
        session.confirm_callback = None
        session.agent_config = AgentConfig()
        session.context_manager = ContextManager(provider, ContextConfig(storage_dir=root / "context"))
        session.plan_context = None
        session._diagnostics = []
        session._diagnostics_lock = threading.Lock()
        session.instruction_bundle = InstructionLoader(user_root=root / "user").load(root)
        session.project_memory = MemoryRepository(root / "memory", "project")
        session.user_memory = MemoryRepository(root / "user" / "memory", "user")
        session.journal = SessionJournal(root)
        session.active_session_id = "20260813-163000-a1b2"
        session.prompt_builder = Session._create_prompt_builder()
        session.project_metadata = {}
        session.permission_engine = None
        session.memory_scheduler = None
        return session

    def test_chat_injects_memory_archives_and_explicitly_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text("project directive", encoding="utf-8")
            (root / "user").mkdir()
            (root / "user" / "AGENTS.md").write_text("user directive", encoding="utf-8")
            project_memory = MemoryRepository(root / "memory", "project")
            project_memory.apply([MemoryChange("project", "upsert", None, MemoryCategory.PROJECT_KNOWLEDGE, "project fact")])
            user_memory = MemoryRepository(root / "user" / "memory", "user")
            user_memory.apply([MemoryChange("user", "upsert", None, MemoryCategory.USER_PREFERENCE, "user fact")])
            provider = FakeProvider([StreamEvent("text", "answer"), StreamEvent("done", "")])
            session = self._session(root, provider)

            self.assertEqual(session.messages, [])  # no automatic resume
            list(session.chat("hello"))
            self.assertIn("project directive", provider.calls[0]["system"])
            self.assertIn("user directive", provider.calls[0]["system"])
            self.assertLess(provider.calls[0]["system"].index("project fact"), provider.calls[0]["system"].index("user fact"))
            archive = session.journal.path_for(session.active_session_id)
            self.assertTrue(archive.exists())
            self.assertEqual(len(session.list_sessions()), 1)

            old_messages = list(session.messages)
            failed = session.resume_session("not-a-session")
            self.assertFalse(failed.success)
            self.assertEqual(session.messages, old_messages)
            resumed = session.resume_session(session.active_session_id)
            self.assertTrue(resumed.success)
            self.assertEqual([message.content for message in session.messages[:2]], ["hello", "answer"])

    def test_completed_agent_schedules_only_after_done(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = FakeProvider([StreamEvent("text", "done"), StreamEvent("done", "")])
            session = self._session(root, provider)

            class RecordingScheduler:
                def __init__(self):
                    self.calls = []

                def submit(self, messages):
                    self.calls.append(list(messages))

            scheduler = RecordingScheduler()
            session.memory_scheduler = scheduler
            events = list(session.agent_chat("finish", mode=AgentMode.FULL))
            self.assertEqual(events[-1].type, "done")
            self.assertEqual(len(scheduler.calls), 1)

    def test_unsuccessful_agent_does_not_schedule_memory_update(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = FakeProvider([StreamEvent("error", "nope")])
            session = self._session(root, provider)

            class RecordingScheduler:
                def __init__(self):
                    self.calls = []

                def submit(self, messages):
                    self.calls.append(list(messages))

            scheduler = RecordingScheduler()
            session.memory_scheduler = scheduler
            list(session.agent_chat("fail", mode=AgentMode.FULL))
            self.assertFalse(scheduler.calls)

    def test_agent_loop_injects_same_memory_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text("agent project rule", encoding="utf-8")
            provider = FakeProvider([StreamEvent("text", "complete"), StreamEvent("done", "")])
            session = self._session(root, provider)
            session.instruction_bundle = InstructionLoader(user_root=root / "user").load(root)
            session.project_memory.apply([
                MemoryChange("project", "upsert", None, MemoryCategory.PROJECT_KNOWLEDGE, "agent fact")
            ])
            list(session.agent_chat("do work", mode=AgentMode.FULL))
            self.assertIn("agent project rule", provider.calls[0]["system"])
            self.assertIn("agent fact", provider.calls[0]["system"])

    def test_failed_resume_keeps_current_history_when_context_is_unsafe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = FakeProvider()
            session = self._session(root, provider)
            session.context_manager = ContextManager(
                provider,
                ContextConfig(
                    storage_dir=root / "context",
                    context_window_tokens=100,
                    max_output_tokens=50,
                    automatic_safety_margin_tokens=40,
                ),
            )
            session.messages = [Message(role="user", content="keep current")]
            restore_id = "20260813-163001-c3d4"
            session.journal.append_message(restore_id, Message(role="user", content="x" * 4_000))
            outcome = session.resume_session(restore_id)
            self.assertFalse(outcome.success)
            self.assertEqual(session.messages[0].content, "keep current")

    def test_archive_write_failure_does_not_rollback_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = self._session(root, FakeProvider())
            with mock.patch.object(session.journal, "append_message") as append:
                from flickcode.sessions import ArchiveDiagnostic
                append.return_value = [ArchiveDiagnostic(None, "disk full")]
                session._append_history_messages([Message(role="user", content="keep")])
            self.assertEqual(session.messages[-1].content, "keep")
            self.assertIn("disk full", session.drain_diagnostics())


class TUIMemoryCommandTests(unittest.TestCase):
    class Renderer:
        def __init__(self):
            self.progress = []
            self.errors = []

        def render_progress(self, text):
            self.progress.append(text)

        def render_error(self, text):
            self.errors.append(text)

    def test_sessions_and_resume_commands_do_not_call_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = FakeProvider([StreamEvent("text", "unused"), StreamEvent("done", "")])
            session = SessionMemoryIntegrationTests()._session(root, provider)
            session._append_history_messages([Message(role="user", content="saved")])
            renderer = self.Renderer()
            _run_sessions_command(session, renderer)
            self.assertTrue(renderer.progress)
            _run_resume_command(session, renderer, session.active_session_id)
            self.assertTrue(any("Restored" in item for item in renderer.progress))
            self.assertFalse(provider.calls)


if __name__ == "__main__":
    unittest.main()
