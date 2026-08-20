from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from flickcode.hooks import HookCatalog, ProjectTrust


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class HookLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.user = self.root / "user"
        self.project.mkdir()
        self.user.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_minimal_rule_and_invalid_rule_isolation(self):
        write(self.user / "hooks.yaml", """
hooks:
  - event: turn.started
    action:
      type: prompt
      content: hello
  - event: missing.event
    action:
      type: prompt
      content: bad
""")
        catalog = HookCatalog(self.project, self.user)
        snapshot = catalog.commit(catalog.prepare_refresh(ProjectTrust.TRUSTED))
        self.assertEqual(len(snapshot.rules), 1)
        self.assertEqual(snapshot.skipped_rules, 1)
        self.assertIn("unsupported event", snapshot.diagnostics[0].message)

    def test_trust_filter_happens_before_named_override(self):
        write(self.user / "hooks.yaml", """
hooks:
  - name: shared
    event: turn.started
    action: {type: prompt, content: user}
  - event: turn.started
    action: {type: prompt, content: anonymous-user}
""")
        write(self.project / ".flick" / "hooks.yaml", """
hooks:
  - name: shared
    event: turn.started
    action: {type: prompt, content: project}
  - event: turn.started
    action: {type: prompt, content: anonymous-project}
""")
        write(self.project / ".flick" / "hooks.local.yaml", """
hooks:
  - event: turn.started
    action: {type: prompt, content: anonymous-local}
""")
        catalog = HookCatalog(self.project, self.user)
        denied = catalog.commit(catalog.prepare_refresh(ProjectTrust.UNTRUSTED))
        self.assertEqual([r.action.content for r in denied.rules], ["user", "anonymous-user", "anonymous-local"])
        trusted = catalog.commit(catalog.prepare_refresh(ProjectTrust.TRUSTED))
        self.assertEqual(
            [r.action.content for r in trusted.rules],
            ["anonymous-user", "project", "anonymous-project", "anonymous-local"],
        )
        self.assertEqual(trusted.overrides[0].name, "shared")

    def test_fatal_reload_keeps_previous_snapshot(self):
        path = self.user / "hooks.yaml"
        write(path, "hooks: []\n")
        catalog = HookCatalog(self.project, self.user)
        first = catalog.commit(catalog.prepare_refresh(ProjectTrust.TRUSTED))
        write(path, "hooks: [")
        refresh = catalog.prepare_refresh(ProjectTrust.TRUSTED)
        self.assertIsNone(refresh.candidate)
        self.assertIs(catalog.commit(refresh), first)

    def test_tool_before_cannot_be_async(self):
        write(self.user / "hooks.yaml", """
hooks:
  - event: tool.before
    async: true
    action: {type: prompt, content: "no"}
""")
        catalog = HookCatalog(self.project, self.user)
        snapshot = catalog.commit(catalog.prepare_refresh(ProjectTrust.TRUSTED))
        self.assertFalse(snapshot.rules)
        self.assertIn("cannot be async", snapshot.diagnostics[0].message)


if __name__ == "__main__":
    unittest.main()
