import tempfile
import unittest
from pathlib import Path

from flickcode.teams.models import (
    MemberBackendKind,
    MemberState,
    TeamMessage,
    TeamRecord,
    TeamTaskState,
    utc_now,
)
from flickcode.teams.paths import TeamLayout, safe_team_slug


class TeamModelTests(unittest.TestCase):
    def test_round_trip_models(self):
        with tempfile.TemporaryDirectory() as root:
            now = utc_now()
            team = TeamRecord("team-1", "alpha", "lead-1", Path(root).resolve(), now, now)
            self.assertEqual(team, TeamRecord.from_dict(team.to_dict()))
            message = TeamMessage("msg-1", "team-1", "lead-1", "member-1", "task.assign", "do it", "do it", now, payload={"task_id": "task-1"})
            self.assertEqual(message, TeamMessage.from_dict(message.to_dict()))

    def test_safe_layout_rejects_path_traversal(self):
        self.assertEqual(safe_team_slug("my team"), "my-team")
        with self.assertRaises(ValueError):
            safe_team_slug("../outside")
        with tempfile.TemporaryDirectory() as root:
            layout = TeamLayout.for_name(Path(root), "中文 team")
            member = layout.member("member-1")
            self.assertEqual(member.root.parent, layout.members_root.resolve())
            with self.assertRaises(ValueError):
                layout.member("../escape")


if __name__ == "__main__":
    unittest.main()
