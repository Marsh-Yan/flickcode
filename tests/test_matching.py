from __future__ import annotations

import unittest

from flickcode.matching import (
    MatchOperator,
    compile_condition,
    match_value,
    matches,
    resolve_field,
)


class MatchingTests(unittest.TestCase):
    def test_field_resolution_distinguishes_null_and_missing(self):
        self.assertIsNone(resolve_field({"a": {"b": None}}, "a.b"))
        with self.assertRaises(KeyError):
            resolve_field({"a": {}}, "a.b")

    def test_four_operators_preserve_exact_types(self):
        self.assertTrue(match_value("x", MatchOperator.EXACT, "x"))
        self.assertFalse(match_value(1, MatchOperator.EXACT, True))
        self.assertTrue(match_value("x", MatchOperator.NOT, "y"))
        self.assertTrue(match_value("git status", MatchOperator.GLOB, "git *"))
        self.assertTrue(match_value("rm -rf x", MatchOperator.REGEX, r"^rm\s+-rf"))

    def test_all_any_and_invalid_shape(self):
        all_group = compile_condition(
            {"all": [
                {"field": "tool.name", "exact": "execute_command"},
                {"field": "tool.arguments.command", "glob": "git *"},
            ]},
            {"tool.name", "tool.arguments"},
        )
        context = {"tool": {"name": "execute_command", "arguments": {"command": "git status"}}}
        self.assertTrue(matches(all_group, context))
        any_group = compile_condition(
            {"any": [
                {"field": "tool.name", "exact": "read_file"},
                {"field": "tool.arguments.command", "regex": "status$"},
            ]},
            {"tool.name", "tool.arguments"},
        )
        self.assertTrue(matches(any_group, context))
        with self.assertRaises(ValueError):
            compile_condition({"all": [], "any": []})
        with self.assertRaises(ValueError):
            compile_condition({"all": [{"field": "bad", "exact": 1}]}, {"tool.name"})


if __name__ == "__main__":
    unittest.main()
