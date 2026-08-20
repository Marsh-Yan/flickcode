from __future__ import annotations

import unittest

from flickcode.permissions.rules import Rule, evaluate


class PermissionRuleCompatibilityTests(unittest.TestCase):
    def test_existing_glob_and_first_string_parameter_semantics(self):
        rule = Rule("execute_command", "git *", "allow", "project")
        self.assertTrue(rule.matches("execute_command", {"command": "git status"}))
        self.assertFalse(rule.matches("read_file", {"command": "git status"}))
        self.assertFalse(rule.matches("execute_command", {"count": 1, "path": "src/x"}))

    def test_star_and_reverse_priority_are_unchanged(self):
        user = Rule("read_file", "*", "deny", "user")
        local = Rule("read_file", "*", "allow", "local")
        self.assertTrue(user.matches("read_file", {}))
        self.assertIs(evaluate("read_file", {"path": "x"}, [user, local]), local)


if __name__ == "__main__":
    unittest.main()
