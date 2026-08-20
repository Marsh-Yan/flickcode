from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from flickcode.agent import AgentMode
from flickcode.commands import CommandRegistry, InMemoryCommandUI, InputRouter
from flickcode.commands.builtin import build_default_registry
from flickcode.skills import SkillCatalog
from flickcode.skills.commands import SkillCommandManager


def write_skill(root: Path, name: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {name} command\ntools: []\nmode: shared\n---\nUse {{{{input}}}}",
        encoding="utf-8",
    )


class SkillCommandManagerTests(unittest.TestCase):
    def test_dynamic_replace_and_raw_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_skill(root, "demo")
            catalog = SkillCatalog(root, root / "user", root / "builtin")
            snapshot = catalog.refresh()
            registry = build_default_registry()
            manager = SkillCommandManager(registry)
            manager.commit(manager.prepare(snapshot))
            ui = InMemoryCommandUI()
            InputRouter(registry).handle("/demo first  line\nsecond", session=object(), ui=ui)
            self.assertEqual(ui.skill_calls, [("demo", "first  line\nsecond", AgentMode.FULL)])
            (root / "demo.md").unlink()
            updated = catalog.refresh()
            manager.commit(manager.prepare(updated))
            self.assertIsNone(registry.resolve("demo"))
            self.assertIsNotNone(registry.resolve("status"))

    def test_dynamic_collision_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_skill(root, "demo")
            catalog = SkillCatalog(root, root / "user", root / "builtin")
            registry = build_default_registry()
            manager = SkillCommandManager(registry)
            manager.commit(manager.prepare(catalog.refresh()))
            write_skill(root, "status")
            with self.assertRaises(Exception):
                manager.prepare(catalog.refresh())
            self.assertIsNotNone(registry.resolve("demo"))


if __name__ == "__main__":
    unittest.main()
