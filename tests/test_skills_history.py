from __future__ import annotations

import unittest

from flickcode.providers.base import Message
from flickcode.skills import CompleteTurnSelector


class CompleteTurnSelectorTests(unittest.TestCase):
    def test_selects_last_complete_turns_and_excludes_system_thinking(self) -> None:
        messages = [
            Message("system", "system"),
            Message("user", "one"),
            Message("assistant", "calling", tool_calls=[{"id": "1", "name": "read_file", "input": {}}]),
            Message("tool", "result", tool_call_id="1"),
            Message("thinking", "secret"),
            Message("assistant", "done one"),
            Message("user", "two"),
            Message("assistant", "done two"),
            Message("user", "incomplete"),
        ]
        selected = CompleteTurnSelector().select(messages, 1)
        self.assertEqual([(item.role, item.content) for item in selected], [("user", "two"), ("assistant", "done two")])
        selected_two = CompleteTurnSelector().select(messages, 2)
        self.assertEqual(selected_two[0].content, "one")
        self.assertNotIn("thinking", [item.role for item in selected_two])
        self.assertNotIn("system", [item.role for item in selected_two])

    def test_incomplete_tool_sequence_is_not_selected(self) -> None:
        messages = [
            Message("user", "one"),
            Message("assistant", "call", tool_calls=[{"id": "x", "name": "read_file", "input": {}}]),
        ]
        self.assertEqual(CompleteTurnSelector().select(messages, 3), [])
        self.assertEqual(CompleteTurnSelector().select(messages, 0), [])


if __name__ == "__main__":
    unittest.main()

