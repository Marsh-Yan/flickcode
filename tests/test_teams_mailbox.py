import tempfile
import unittest
from pathlib import Path

from flickcode.teams.mailbox import MailboxStore
from flickcode.teams.models import MemberBackendKind
from flickcode.teams.paths import TeamLayout
from flickcode.teams.store import TeamStore


class TeamMailboxTests(unittest.TestCase):
    def test_direct_broadcast_and_read_state(self):
        with tempfile.TemporaryDirectory() as root:
            store = TeamStore(Path(root))
            team = store.create("alpha", "lead")
            worker = store.add_member(team, name="worker", role="builder", workdir=Path(root), backend=MemberBackendKind.IN_PROCESS)
            mailbox = MailboxStore(TeamLayout(team.root))
            direct = mailbox.send_to_name(team_id=team.team_id, sender_id=team.lead_member_id, recipient_name="worker", kind="task.assign", payload={"task_id": "task-1"}, body="build")
            self.assertFalse(direct.read)
            self.assertEqual(mailbox.count_unread(worker.member_id), 1)
            broadcast = mailbox.broadcast(team_id=team.team_id, sender_id=team.lead_member_id, kind="member.wakeup", payload={})
            self.assertEqual(len(broadcast), 1)
            self.assertEqual(mailbox.mark_read(worker.member_id, [direct.message_id]), 1)
            self.assertEqual(mailbox.count_unread(worker.member_id), 1)


if __name__ == "__main__":
    unittest.main()
