from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from flickcode.skills import SkillParser, SkillScriptTool, SkillSource


FIXTURE = Path(__file__).parent / "fixtures" / "skills" / "package"


class SkillScriptToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.definition = SkillParser().parse_package(FIXTURE, SkillSource.PROJECT).custom_tools[0]
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_json_protocol_success(self) -> None:
        result = SkillScriptTool(self.definition, self.project).execute({"value": "你好"})
        self.assertTrue(result.success)
        self.assertEqual(result.output, "你好")

    def test_environment_does_not_inherit_secret(self) -> None:
        secret_name = "FLICKCODE_SKILL_TEST_SECRET"
        old = os.environ.get(secret_name)
        os.environ[secret_name] = "secret-value-that-must-not-leak"
        try:
            source = (
                "import json, os, sys\n"
                f"value = os.getenv('{secret_name}', '')\n"
                "json.dump({'success': True, 'output': value, 'error': None}, sys.stdout)\n"
            )
            result = SkillScriptTool(replace(self.definition, script_source=source), self.project).execute({})
        finally:
            if old is None:
                os.environ.pop(secret_name, None)
            else:
                os.environ[secret_name] = old
        self.assertTrue(result.success)
        self.assertEqual(result.output, "")

    def test_timeout_and_invalid_output_are_safe_failures(self) -> None:
        timeout_source = "import time\ntime.sleep(1)\n"
        timeout = SkillScriptTool(
            replace(self.definition, script_source=timeout_source),
            self.project,
            timeout_seconds=0.01,
        ).execute({})
        invalid = SkillScriptTool(
            replace(self.definition, script_source="print('not-json')"),
            self.project,
        ).execute({})
        self.assertFalse(timeout.success)
        self.assertIn("timed out", timeout.error or "")
        self.assertFalse(invalid.success)
        self.assertIn("invalid JSON", invalid.error or "")


if __name__ == "__main__":
    unittest.main()
