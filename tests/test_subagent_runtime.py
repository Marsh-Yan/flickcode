from __future__ import annotations

import unittest
from pathlib import Path

from flickcode.agent import AgentMode
from flickcode.config import ContextConfig, ProviderConfig
from flickcode.permissions.models import PermissionMode
from flickcode.providers.base import Message
from flickcode.subagents.models import AgentModelAlias, AgentPermissionMode, AgentRoleDefinition, AgentRoleSource, ParentRequestSnapshot
from flickcode.subagents.runtime import ChildRuntimeFactory
from flickcode.tools import create_default_registry
from flickcode.subagents.tool import AgentTool


class _Pool:
    pass


class SubAgentRuntimeSpecTests(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd()
        self.factory = ChildRuntimeFactory(self.root, _Pool(), ContextConfig(storage_dir=self.root / ".tmp" / "context"))
        self.provider = ProviderConfig("main", "openai", "model", "http://localhost", "key", False)
        self.registry = create_default_registry()
        self.registry.register_instance(AgentTool())

    def role(self):
        return AgentRoleDefinition(
            "explore", "Explore", frozenset({"read_file", "agent"}), frozenset(),
            AgentModelAlias.INHERIT, 4, AgentPermissionMode.STRICT, "Role prompt",
            AgentRoleSource.BUILTIN, self.root / "role.md", "hash",
        )

    def test_defined_starts_from_clean_history_and_fixed_role(self):
        launch = self.factory.defined_spec(
            task_id="agent-000000000001", parent_session_id="parent", role=self.role(), task="inspect",
            parent_provider=self.provider, providers={"main": self.provider}, model_aliases={},
            parent_tools=self.registry.snapshot(), parent_permission=PermissionMode.DEFAULT,
            background=False,
        )
        self.assertEqual([(m.role, m.content) for m in launch.messages], [("user", "inspect")])
        self.assertIn("Role prompt", launch.system_prompt)
        self.assertEqual(launch.tool_view.list_tools(), ["read_file"])
        self.assertEqual(launch.permission_mode, PermissionMode.STRICT)

    def test_fork_inherits_snapshot_and_is_forced_background(self):
        snapshot = ParentRequestSnapshot(
            "parent", 2, AgentMode.PLAN,
            (Message(role="user", content="original"), Message(role="assistant", content="prefix")),
            "stable prompt", self.registry.snapshot(), self.provider, False,
        )
        launch = self.factory.fork_spec(
            task_id="agent-000000000002", snapshot=snapshot, task="branch",
            parent_permission=PermissionMode.DEFAULT, max_turns=5,
        )
        self.assertEqual([m.content for m in launch.messages], ["original", "prefix", "branch"])
        self.assertEqual(launch.system_prompt, "stable prompt")
        self.assertEqual(launch.mode, AgentMode.PLAN)
        self.assertTrue(launch.forced_background)
        self.assertNotIn("agent", launch.tool_view.list_tools())


if __name__ == "__main__":
    unittest.main()
