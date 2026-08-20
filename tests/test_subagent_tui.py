from __future__ import annotations

import unittest

from flickcode.subagents.foreground import ForegroundControl


class ForegroundControlTests(unittest.TestCase):
    def test_fake_ctrl_b_poller_detaches_active_task_only(self):
        control = ForegroundControl()
        calls = []
        control.set_poll_callback(lambda: calls.append("ctrl-b") or True)
        control.begin("agent-000000000001")
        self.assertFalse(control.should_detach("agent-000000000002"))
        self.assertTrue(control.should_detach("agent-000000000001"))
        self.assertEqual(calls, ["ctrl-b"])
        control.end("agent-000000000001")


if __name__ == "__main__":
    unittest.main()
