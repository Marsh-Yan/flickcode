from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flickcode.agent import AgentMode
from flickcode.providers.base import BaseProvider, StreamEvent
from flickcode.providers.base import Message
from flickcode.session import Session
from flickcode.skills import SkillStartupError


class FakeProvider(BaseProvider):
    def stream_chat(self, messages, thinking=False, tools=None, system=None):
        yield StreamEvent("text", "done")
        yield StreamEvent("done", "")


class SkillSessionIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.user = self.root / "user"
        self.project.mkdir()
        self.user.mkdir()
        self.config = self.root / "config.yaml"
        self.config.write_text(
            "providers:\n"
            "  - name: fake\n"
            "    protocol: anthropic\n"
            "    model: fake-model\n"
            "    base_url: https://example.invalid\n"
            "    api_key: fake\n",
            encoding="utf-8",
        )
        self.old_cwd = Path.cwd()
        os.chdir(self.project)

    def tearDown(self) -> None:
        os.chdir(self.old_cwd)
        self.temp.cleanup()

    def make_session(self) -> Session:
        patches = (
            patch("flickcode.session.DEFAULT_CONFIG_DIR", self.user),
            patch("flickcode.session.create_provider", lambda config: FakeProvider(config)),
        )
        with patches[0], patches[1]:
            session = Session(config_path=str(self.config))
        session.skill_executor.provider_factory = lambda config: FakeProvider(config)
        return session

    def test_startup_two_phase_prompt_dynamic_commands_and_shared_activation(self) -> None:
        session = self.make_session()
        try:
            self.assertIsNotNone(session.command_registry.resolve("commit"))
            self.assertIsNotNone(session.command_registry.resolve("review"))
            shallow, _ = session._build_prompt()
            self.assertIn("Inspect changes and create a focused Git commit", shallow or "")
            self.assertNotIn("Stage only files", shallow or "")
            result = session.skill_executor.invoke("commit", "focus")
            self.assertTrue(result.success)
            full, _ = session._build_prompt()
            self.assertIn("Stage only files", full or "")
            self.assertEqual(
                set(session.skill_runtime.tool_view().list_tools()),
                {"read_file", "glob", "grep", "execute_command", "load_skill", "agent"},
            )
        finally:
            session.close()

    def test_hot_override_and_invalid_refresh_rollback(self) -> None:
        session = self.make_session()
        try:
            project_skills = self.project / ".flickcode" / "skills"
            project_skills.mkdir(parents=True)
            override = project_skills / "commit.md"
            override.write_text(
                "---\nname: commit\ndescription: Project commit\ntools: [read_file]\nmode: shared\n---\nPROJECT {{{{input}}}}",
                encoding="utf-8",
            )
            session.refresh_skills()
            self.assertEqual(session.skill_catalog.resolve("commit").description, "Project commit")
            generation = session.skill_catalog.snapshot.generation
            bad = project_skills / "bad.md"
            bad.write_text(
                "---\nname: bad\ndescription: Bad\ntools: [missing_tool]\nmode: shared\n---\nBody",
                encoding="utf-8",
            )
            with self.assertRaises(SkillStartupError):
                session.refresh_skills()
            self.assertEqual(session.skill_catalog.snapshot.generation, generation)
            self.assertIsNone(session.command_registry.resolve("bad"))
        finally:
            session.close()

    def test_reset_clears_history_plan_and_active_skills(self) -> None:
        session = self.make_session()
        try:
            session.skill_executor.invoke("commit", "focus")
            list(session.agent_chat("hello", AgentMode.FULL))
            old_id = session.active_session_id
            session.reset_session()
            self.assertNotEqual(session.active_session_id, old_id)
            self.assertEqual(session.messages, [])
            self.assertEqual(session.skill_runtime.snapshot.active_skills, ())
            self.assertIsNone(session.plan_context)
            self.assertTrue(session.journal.path_for(old_id).exists())
        finally:
            session.close()

    def test_builtin_review_package_tool_is_read_only_and_executable(self) -> None:
        session = self.make_session()
        try:
            review = session.skill_catalog.resolve("review")
            self.assertIsNotNone(review)
            self.assertEqual(len(review.custom_tools), 1)
            before = sorted(path.relative_to(self.project) for path in self.project.rglob("*") if path.is_file())
            from flickcode.skills import SkillScriptTool

            result = SkillScriptTool(review.custom_tools[0], self.project).execute({})
            after = sorted(path.relative_to(self.project) for path in self.project.rglob("*") if path.is_file())
            self.assertTrue(result.success, result.error)
            self.assertIn("extensions", result.output)
            self.assertEqual(before, after)
        finally:
            session.close()

    def test_isolated_slash_returns_summary_without_child_messages_in_parent(self) -> None:
        session = self.make_session()
        try:
            session._append_history_messages(
                [Message("user", "previous"), Message("assistant", "previous answer")]
            )
            events = list(session.invoke_skill("review", "permissions", AgentMode.FULL))
            self.assertEqual(events[0].type, "text")
            self.assertEqual(
                [(message.role, message.content) for message in session.messages[-2:]],
                [("user", "/review permissions"), ("assistant", "done")],
            )
            self.assertFalse(any(message.role == "tool" for message in session.messages))
            children = list(session.journal.children_root.glob("*.jsonl"))
            self.assertEqual(len(children), 1)
            self.assertIn("skill_child_finished", children[0].read_text(encoding="utf-8"))
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
