import tempfile
import time
import unittest
from pathlib import Path

from flickcode.teams.approval import ApprovalGate
from flickcode.teams.backends import BackendSelector
from flickcode.teams.mailbox import MailboxStore
from flickcode.teams.models import MemberBackendKind, MemberState
from flickcode.teams.paths import TeamLayout
from flickcode.teams.protocol import ProtocolCodec
from flickcode.teams.runtime import TeamRuntimeManager
from flickcode.teams.store import TeamStore
from flickcode.teams.tasks import TaskStore


class TeamRuntimeTests(unittest.TestCase):
    def _setup(self, approval=False):
        root = tempfile.TemporaryDirectory()
        store = TeamStore(Path(root.name))
        team = store.create("alpha", "lead", lead_workdir=Path(root.name))
        member = store.add_member(team, name="worker", role="builder", workdir=Path(root.name), backend=MemberBackendKind.IN_PROCESS, approval_required=approval)
        tasks = TaskStore(team)
        mailbox = MailboxStore(TeamLayout(team.root))
        manager = TeamRuntimeManager(team, store=store, mailbox=mailbox, tasks=tasks, backends=BackendSelector(pane_adapters={}), approval=ApprovalGate())
        return root, store, team, member, tasks, mailbox, manager

    def test_member_finishes_idle_and_can_resume_same_identity(self):
        root, store, team, member, tasks, mailbox, manager = self._setup()
        self.addCleanup(root.cleanup)
        first = tasks.create_task("first", assignee_id=member.member_id)
        started = manager.start_or_resume(member.member_id, task_id=first.task_id)
        self.assertEqual(started.state, MemberState.BUSY)
        finished = manager.finish(member.member_id, task_id=first.task_id, summary="done")
        self.assertEqual(finished.state, MemberState.IDLE)
        self.assertEqual(mailbox.list_messages(team.lead_member_id)[0].kind, "member.idle")
        second = tasks.create_task("second", assignee_id=member.member_id)
        restarted = TeamRuntimeManager(team, store=store, mailbox=mailbox, tasks=tasks, backends=BackendSelector(pane_adapters={}), approval=ApprovalGate()).start_or_resume(member.member_id, task_id=second.task_id)
        self.assertEqual(restarted.state, MemberState.BUSY)
        self.assertEqual(store.get_member(team, member.member_id).member_id, member.member_id)

    def test_approval_blocks_until_matching_decision(self):
        root, store, team, member, tasks, mailbox, manager = self._setup(approval=True)
        self.addCleanup(root.cleanup)
        task = tasks.create_task("sensitive", assignee_id=member.member_id)
        blocked = manager.start_or_resume(member.member_id, task_id=task.task_id, plan="run migration")
        self.assertEqual(blocked.state, MemberState.IDLE)
        request = mailbox.list_messages(team.lead_member_id)[0]
        request_id = request.payload["request_id"]
        digest = request.payload["plan_digest"]
        decision = ProtocolCodec().encode(team_id=team.team_id, sender_id=team.lead_member_id, recipient_id=member.member_id, kind="approval.decision", payload={"request_id": request_id, "decision": "approve", "plan_digest": digest})
        approval_request = next(iter(manager.approval._states.values())).request
        manager.approval.apply(decision, request_id=request_id, request=approval_request, lead_member_id=team.lead_member_id)
        self.assertEqual(manager.start_or_resume(member.member_id, task_id=task.task_id, plan="run migration").state, MemberState.BUSY)

    def test_in_process_backend_runs_member_callback_and_finishes(self):
        root, store, team, member, tasks, mailbox, manager = self._setup()
        self.addCleanup(root.cleanup)
        calls = []
        manager.stop_all()
        manager = TeamRuntimeManager(
            team,
            store=store,
            mailbox=mailbox,
            tasks=tasks,
            backends=BackendSelector(pane_adapters={}),
            approval=ApprovalGate(),
            runner=lambda current, task_id: (calls.append((current.member_id, task_id)) or ("callback complete", "")),
        )
        task = tasks.create_task("run callback", assignee_id=member.member_id)
        manager.start_or_resume(member.member_id, task_id=task.task_id)
        deadline = time.time() + 2
        while time.time() < deadline and store.get_member(team, member.member_id).state is not MemberState.IDLE:
            time.sleep(0.02)
        manager.stop_all()
        self.assertEqual(calls, [(member.member_id, task.task_id)])
        self.assertEqual(tasks.get_task(task.task_id).state.value, "completed")


if __name__ == "__main__":
    unittest.main()
