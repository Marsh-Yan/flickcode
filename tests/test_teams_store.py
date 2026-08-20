import tempfile
import unittest
from pathlib import Path

from flickcode.teams.models import MemberBackendKind, MemberState
from flickcode.teams.store import TeamStore


class TeamStoreTests(unittest.TestCase):
    def test_team_and_member_survive_store_reopen(self):
        with tempfile.TemporaryDirectory() as root:
            store = TeamStore(Path(root))
            team = store.create("alpha", "lead", lead_workdir=Path(root))
            member = store.add_member(
                team,
                name="worker",
                role="builder",
                workdir=Path(root) / "worker",
                backend=MemberBackendKind.IN_PROCESS,
            )
            member = store.update_member(member.__class__(**{**member.__dict__, "state": MemberState.IDLE}))
            reopened = TeamStore(Path(root)).open("alpha")
            self.assertEqual(team.team_id, reopened.team_id)
            self.assertEqual([item.name for item in store.list_members(reopened)], ["lead", "worker"])
            self.assertEqual(store.get_member(reopened, member.member_id).state, MemberState.IDLE)

    def test_duplicate_member_name_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            store = TeamStore(Path(root))
            team = store.create("alpha", "lead")
            with self.assertRaises(ValueError):
                store.add_member(team, name="lead", role="worker", workdir=Path(root), backend=MemberBackendKind.PANE)


if __name__ == "__main__":
    unittest.main()
