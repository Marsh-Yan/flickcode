from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from flickcode.subagents.models import AgentRoleSource
from flickcode.subagents.roles import AgentRoleCatalog, AgentRoleParser, AgentRoleValidator


ROLE = """---
name: {name}
description: {description}
tools:
  allow: [{allow}]
  deny: [{deny}]
model: inherit
max_turns: 7
permission_mode: inherit
---
{body}
"""


class AgentRoleTests(unittest.TestCase):
    def setUp(self):
        Path(".tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=".tmp")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, tier, filename, **values):
        path = self.root / tier / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(ROLE.format(**values), encoding="utf-8")
        return path

    def test_strict_parser_and_priority_override(self):
        builtin = self.write("builtin", "worker.md", name="worker", description="builtin", allow="read_file", deny="", body="Builtin")
        project = self.write("project", "worker.md", name="worker", description="project", allow="read_file", deny="", body="Project")
        definition = AgentRoleParser().parse_file(project, AgentRoleSource.PROJECT)
        self.assertEqual(definition.system_prompt, "Project")
        catalog = AgentRoleCatalog(self.root / "project", self.root / "user", self.root / "builtin", [self.root / "plugin"])
        snapshot = catalog.refresh()
        self.assertEqual(snapshot.effective["worker"].source_path, project.resolve())
        self.assertEqual(snapshot.shadowed["worker"][0].source_path, builtin.resolve())

    def test_invalid_allow_removes_role_but_unknown_deny_warns(self):
        self.write("project", "bad.md", name="bad", description="bad", allow="missing", deny="", body="Bad")
        self.write("project", "okay.md", name="okay", description="okay", allow="read_file", deny="old_tool", body="Okay")
        catalog = AgentRoleCatalog(self.root / "project", self.root / "user", self.root / "builtin")
        checked = AgentRoleValidator().validate(catalog.prepare_refresh().current, {"read_file"})
        self.assertNotIn("bad", checked.effective)
        self.assertIn("okay", checked.effective)
        self.assertEqual([d.severity for d in checked.diagnostics], ["error", "warning"])

    def test_parser_rejects_unknown_frontmatter(self):
        path = self.write("project", "role.md", name="role", description="role", allow="read_file", deny="", body="Role")
        path.write_text(path.read_text(encoding="utf-8").replace("max_turns: 7", "max_turns: 7\nextra: no"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unknown extra"):
            AgentRoleParser().parse_file(path, AgentRoleSource.PROJECT)


if __name__ == "__main__":
    unittest.main()
