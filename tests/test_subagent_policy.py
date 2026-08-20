from __future__ import annotations

import unittest

from flickcode.permissions.models import PermissionMode
from flickcode.subagents.models import AgentPermissionMode
from flickcode.subagents.policy import SubAgentPermissionPolicy, SubAgentToolPolicy
from flickcode.tools import create_default_registry
from flickcode.subagents.tool import AgentTool


class SubAgentPolicyTests(unittest.TestCase):
    def test_tool_layers_intersect_and_delegation_is_always_removed(self):
        registry = create_default_registry()
        registry.register_instance(AgentTool())
        view = SubAgentToolPolicy.resolve(
            registry.snapshot(),
            role_allow={"read_file", "write_file", "agent"},
            role_deny={"write_file"},
            background_allow={"read_file", "write_file", "agent"},
        )
        self.assertEqual(view.list_tools(), ["read_file"])

    def test_child_permissions_can_only_be_stricter(self):
        self.assertEqual(
            SubAgentPermissionPolicy.resolve(PermissionMode.STRICT, AgentPermissionMode.PERMISSIVE),
            PermissionMode.STRICT,
        )
        self.assertEqual(
            SubAgentPermissionPolicy.resolve(PermissionMode.DEFAULT, AgentPermissionMode.STRICT),
            PermissionMode.STRICT,
        )


if __name__ == "__main__":
    unittest.main()
