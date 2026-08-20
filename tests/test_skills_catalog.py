from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from flickcode.skills import SkillCatalog, SkillSource


def write_skill(root: Path, filename: str, name: str, description: str = "Skill") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / filename
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\ntools: [read_file]\nmode: shared\n---\nDo {{{{input}}}}",
        encoding="utf-8",
    )
    return path


class SkillCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.project = base / "project"
        self.user = base / "user"
        self.builtin = base / "builtin"
        self.catalog = SkillCatalog(self.project, self.user, self.builtin)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_priority_and_shadowed_sources(self) -> None:
        write_skill(self.builtin, "demo.md", "demo", "Built in")
        write_skill(self.user, "demo.md", "demo", "User")
        write_skill(self.project, "demo.md", "demo", "Project")
        snapshot = self.catalog.refresh()
        self.assertIs(snapshot.effective["demo"].source, SkillSource.PROJECT)
        self.assertEqual(
            [item.source for item in snapshot.shadowed["demo"]],
            [SkillSource.USER, SkillSource.BUILTIN],
        )

    def test_invalid_higher_tier_falls_back_without_blocking_others(self) -> None:
        write_skill(self.builtin, "demo.md", "demo", "Built in")
        write_skill(self.user, "other.md", "other", "Other")
        self.project.mkdir(parents=True)
        (self.project / "demo.md").write_text(
            "---\nname: demo\ndescription: Broken\ntools: nope\nmode: shared\n---\nBody",
            encoding="utf-8",
        )
        candidate = self.catalog.prepare_refresh()
        self.assertIs(candidate.current.effective["demo"].source, SkillSource.BUILTIN)
        self.assertIn("other", candidate.current.effective)
        self.assertIn("demo", candidate.retained_invalid)
        self.assertEqual(len(candidate.current.diagnostics), 1)

    def test_same_tier_duplicate_excludes_tier_and_uses_fallback(self) -> None:
        write_skill(self.builtin, "demo.md", "demo", "Built in")
        write_skill(self.project, "one.md", "demo", "One")
        write_skill(self.project, "two.md", "demo", "Two")
        snapshot = self.catalog.refresh()
        self.assertIs(snapshot.effective["demo"].source, SkillSource.BUILTIN)
        self.assertTrue(any("duplicate skill name" in item.message for item in snapshot.diagnostics))

    def test_prepare_is_non_mutating_and_stale_commit_fails(self) -> None:
        write_skill(self.project, "demo.md", "demo")
        first = self.catalog.prepare_refresh()
        self.assertNotIn("demo", self.catalog.snapshot.effective)
        self.catalog.commit(first)
        second = self.catalog.prepare_refresh()
        with self.assertRaisesRegex(RuntimeError, "stale"):
            self.catalog.commit(first)
        self.assertIs(self.catalog.commit(second), self.catalog.snapshot)

    def test_deletion_reveals_lower_tier(self) -> None:
        write_skill(self.builtin, "demo.md", "demo", "Built in")
        project_path = write_skill(self.project, "demo.md", "demo", "Project")
        self.catalog.refresh()
        project_path.unlink()
        candidate = self.catalog.prepare_refresh()
        self.assertIn("demo", candidate.changed)
        self.assertIs(candidate.current.effective["demo"].source, SkillSource.BUILTIN)


if __name__ == "__main__":
    unittest.main()

