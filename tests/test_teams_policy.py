import os
import unittest

from flickcode.teams.policy import (
    TEAM_LEAD_TOOL,
    TEAM_MESSAGE_TOOL,
    TEAM_TASK_TOOL,
    TeamToolPolicy,
    coordinator_active,
)


class TeamPolicyTests(unittest.TestCase):
    def test_coordinator_requires_two_locks(self):
        self.assertFalse(coordinator_active(False, {"FLICKCODE_COORDINATOR": "1"}))
        self.assertFalse(coordinator_active(True, {}))
        self.assertTrue(coordinator_active(True, {"FLICKCODE_COORDINATOR": "1"}))

    def test_views_are_identity_scoped(self):
        policy = TeamToolPolicy()
        base = {"read_file", "write_file", "edit_file", "execute_command", "agent", "load_skill"}
        lead = policy.lead_names(base)
        member = policy.member_names(base)
        coordinator = policy.lead_names(base, coordinator=True)
        self.assertIn(TEAM_LEAD_TOOL, lead)
        self.assertIn(TEAM_TASK_TOOL, member)
        self.assertIn(TEAM_MESSAGE_TOOL, member)
        self.assertNotIn(TEAM_LEAD_TOOL, member)
        self.assertNotIn("write_file", coordinator)
        self.assertNotIn("edit_file", coordinator)
        self.assertNotIn(TEAM_TASK_TOOL, policy.lead_names(base) - {TEAM_TASK_TOOL})


if __name__ == "__main__":
    unittest.main()
