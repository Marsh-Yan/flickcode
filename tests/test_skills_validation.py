from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from flickcode.skills import SkillCatalog, SkillStartupError, SkillValidator


def write_skill(root: Path, name: str, tools: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: Validation fixture\ntools: [{tools}]\nmode: shared\n---\nBody",
        encoding="utf-8",
    )


class SkillValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.validator = SkillValidator()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def snapshot(self):
        return SkillCatalog(self.base / "project", self.base / "user", self.base / "builtin").refresh()

    def test_accepts_known_and_system_tools(self) -> None:
        write_skill(self.base / "project", "valid", "read_file, load_skill")
        self.validator.validate_startup(self.snapshot(), {"read_file"}, {"reset", "audit"})

    def test_unknown_whitelist_tool_is_startup_fatal(self) -> None:
        write_skill(self.base / "project", "bad", "missing_tool")
        with self.assertRaisesRegex(SkillStartupError, "unknown tool"):
            self.validator.validate_startup(self.snapshot(), {"read_file"}, set())

    def test_reserved_command_collision_is_fatal(self) -> None:
        write_skill(self.base / "project", "reset", "read_file")
        with self.assertRaisesRegex(SkillStartupError, "reserved command"):
            self.validator.validate_startup(self.snapshot(), {"read_file"}, {"reset"})


if __name__ == "__main__":
    unittest.main()
