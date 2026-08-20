from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from flickcode.skills import SkillMode, SkillParseError, SkillParser, SkillSource


FIXTURES = Path(__file__).parent / "fixtures" / "skills"


class SkillParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = SkillParser()

    def test_parses_shared_frontmatter_and_replaces_all_inputs(self) -> None:
        skill = self.parser.parse_file(FIXTURES / "valid_shared.md", SkillSource.PROJECT)
        self.assertEqual(skill.name, "fixture-shared")
        self.assertIs(skill.mode, SkillMode.SHARED)
        self.assertEqual(skill.tool_names, ("read_file",))
        self.assertNotIn("{{input}}", skill.render("hello"))
        self.assertIn("hello", skill.render("hello"))
        with self.assertRaises(FrozenInstanceError):
            skill.name = "changed"  # type: ignore[misc]

    def test_parses_isolated_history_and_model(self) -> None:
        skill = self.parser.parse_file(FIXTURES / "valid_isolated.md", SkillSource.USER)
        self.assertIs(skill.mode, SkillMode.ISOLATED)
        self.assertEqual(skill.history, 2)
        self.assertEqual(skill.model, "fixture-model")

    def test_rejects_invalid_metadata(self) -> None:
        with self.assertRaises(SkillParseError):
            self.parser.parse_file(FIXTURES / "invalid.md", SkillSource.PROJECT)

    def test_parses_directory_tool_and_snapshots_script(self) -> None:
        skill = self.parser.parse_package(FIXTURES / "package", SkillSource.BUILTIN)
        self.assertEqual(skill.name, "fixture-package")
        self.assertEqual(len(skill.custom_tools), 1)
        tool = skill.custom_tools[0]
        self.assertEqual(tool.name, "fixture-echo")
        self.assertIn("json.load", tool.script_source)

    def test_shared_rejects_isolated_only_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.md"
            path.write_text(
                "---\nname: bad\ndescription: Bad\ntools: []\nmode: shared\nhistory: 0\n---\nBody",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(SkillParseError, "must not declare"):
                self.parser.parse_file(path, SkillSource.PROJECT)

    def test_package_rejects_escape_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skill"
            (root / "tools").mkdir(parents=True)
            (root / "SKILL.md").write_text(
                "---\nname: bad-package\ndescription: Bad package\ntools: [bad-tool]\nmode: shared\n---\nBody",
                encoding="utf-8",
            )
            (Path(tmp) / "outside.py").write_text("pass", encoding="utf-8")
            (root / "tools" / "bad.json").write_text(
                json.dumps(
                    {
                        "name": "bad-tool",
                        "description": "Bad tool",
                        "input_schema": {"type": "object", "properties": {}},
                        "entrypoint": "../outside.py",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(SkillParseError):
                self.parser.parse_package(root, SkillSource.PROJECT)


if __name__ == "__main__":
    unittest.main()

