from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from flickcode.agent import AgentConfig, AgentMode
from flickcode.config import ProviderConfig
from flickcode.context import ContextConfig
from flickcode.permissions import PermissionEngine, PermissionMode
from flickcode.prompt import ActiveSkillsSection, SkillCatalogSection, SystemPromptBuilder
from flickcode.providers.base import BaseProvider, Message, StreamEvent
from flickcode.sessions import SessionJournal
from flickcode.skills import (
    LoadSkillTool,
    SkillCatalog,
    SkillExecutor,
    SkillInvocationOrigin,
    SkillMode,
    SkillRuntime,
)
from flickcode.tools.base import BaseTool, ToolResult, ToolSpec
from flickcode.tools.registry import ToolRegistry


class FakeTool(BaseTool):
    def __init__(self, name: str) -> None:
        self.spec = ToolSpec(name=name, description=name, input_schema={"type": "object", "properties": {}})

    def execute(self, params: dict) -> ToolResult:
        return ToolResult(True, self.spec.name)


class FakeProvider(BaseProvider):
    def stream_chat(self, messages, thinking=False, tools=None, system=None):
        yield StreamEvent("text", "child handoff")
        yield StreamEvent("done", json.dumps({"usage": {"input_tokens": 1, "output_tokens": 2}}))


def write_skill(root: Path, name: str, mode: str, history: int | None = None, model: str | None = None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    extra = ""
    if history is not None:
        extra += f"history: {history}\n"
    if model is not None:
        extra += f"model: {model}\n"
    (root / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {name} skill\ntools: [read_file]\nmode: {mode}\n{extra}---\nSOP for {{{{input}}}}",
        encoding="utf-8",
    )


class SkillExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.skills = self.root / "skills"
        write_skill(self.skills, "shared-one", "shared")
        write_skill(self.skills, "isolated-one", "isolated", history=1, model="child-model")
        self.catalog = SkillCatalog(self.skills, self.root / "user", self.root / "builtin")
        self.catalog.refresh()
        self.tools = ToolRegistry()
        self.tools.register_instance(FakeTool("read_file"))
        self.loader = LoadSkillTool()
        self.tools.register_instance(self.loader)
        self.runtime = SkillRuntime(self.catalog.snapshot, self.tools, self.root)
        self.messages = [Message("user", "previous"), Message("assistant", "answer")]
        self.session_id = SessionJournal.new_pending()
        self.config = ProviderConfig("fake", "anthropic", "parent-model", "", "", False)
        builder = SystemPromptBuilder()
        builder.add_section(ActiveSkillsSection())
        builder.add_section(SkillCatalogSection())
        self.seen_configs = []

        def provider_factory(config):
            self.seen_configs.append(config)
            return FakeProvider(config)

        self.journal = SessionJournal(self.root)
        self.executor = SkillExecutor(
            runtime=self.runtime,
            tools=self.tools,
            project_root=self.root,
            journal=self.journal,
            messages_provider=lambda: self.messages,
            session_id_provider=lambda: self.session_id,
            provider_config_provider=lambda: self.config,
            context_config=ContextConfig(),
            agent_config=AgentConfig(max_iterations=3),
            prompt_builder=builder,
            permission_engine=PermissionEngine(PermissionMode.PERMISSIVE, self.root),
            provider_factory=provider_factory,
        )
        self.loader.bind(self.executor)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_shared_tool_activation_and_rebind(self) -> None:
        first = self.loader.execute({"name": "shared-one", "input": "one"})
        second = self.loader.execute({"name": "shared-one", "input": "two"})
        self.assertTrue(first.success and second.success)
        self.assertIn("Rebound", second.output)
        self.assertEqual(self.runtime.snapshot.active_skills[0].rendered_instructions, "SOP for two")
        archive = self.journal.path_for(self.session_id).read_text(encoding="utf-8")
        self.assertIn("skill_activated", archive)
        self.assertIn("skill_rebound", archive)

    def test_isolated_clones_model_and_returns_only_summary(self) -> None:
        result = self.executor.invoke(
            "isolated-one", "request", SkillInvocationOrigin.SLASH, AgentMode.FULL
        )
        self.assertTrue(result.success)
        self.assertIs(result.mode, SkillMode.ISOLATED)
        self.assertEqual(result.summary, "child handoff")
        self.assertEqual(self.config.model, "parent-model")
        self.assertEqual(self.seen_configs[0].model, "child-model")
        child_path = self.journal.child_path_for(result.child_session_id or "")
        records = [json.loads(line) for line in child_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(records[0]["parent_session_id"], self.session_id)
        self.assertEqual(records[-1]["kind"], "skill_child_finished")
        child_messages = [record["message"] for record in records if record["kind"] == "message"]
        self.assertEqual([item["content"] for item in child_messages[:3]], ["previous", "answer", "request"])
        self.assertEqual(self.messages, [Message("user", "previous"), Message("assistant", "answer")])

    def test_load_tool_reports_unknown_and_validates_params(self) -> None:
        self.assertFalse(self.loader.execute({}).success)
        self.assertFalse(self.loader.execute({"name": "missing"}).success)


if __name__ == "__main__":
    unittest.main()
