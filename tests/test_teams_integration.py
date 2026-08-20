import json
import os
import tempfile
import unittest
from pathlib import Path

from flickcode.config import TeamsConfig
from flickcode.agent import AgentMode
from flickcode.session import Session
from flickcode.teams.coordinator import TeamCoordinator
from flickcode.teams.models import MemberState, TeamTaskState
from flickcode.teams.paths import TeamLayout


class TeamLeadFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = TeamsConfig(
            storage_dir=str(Path(self.temp.name) / "teams"),
            backend_preference=("in_process", "pane"),
            pane_adapters=("tmux",),
        )
        self.coordinator = TeamCoordinator(self.config, Path(self.temp.name))
        self.team = self.coordinator.activate_lead("backend", create=True, lead_name="lead", lead_workdir=Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_lead_creates_member_assigns_and_resumes(self):
        member = self.coordinator.create_member(name="builder", role="implementer", workdir=Path(self.temp.name))
        task = self.coordinator.assign(title="Implement feature", description="write code", assignee="builder")
        self.assertEqual(task.assignee_id, member.member_id)
        self.assertEqual(self.coordinator.store.get_member(self.team, member.member_id).state, MemberState.BUSY)
        mailbox = self.coordinator.mailbox
        self.assertEqual(len(mailbox.list_messages(member.member_id)), 1)
        self.coordinator.runtime.finish(member.member_id, task_id=task.task_id, summary="implemented")
        self.assertEqual(self.coordinator.store.get_member(self.team, member.member_id).state, MemberState.IDLE)
        self.assertEqual(len(mailbox.list_messages(self.team.lead_member_id)), 1)
        status = self.coordinator.status()
        self.assertEqual(status["tasks"][0]["state"], TeamTaskState.COMPLETED.value)

    def test_broadcast_and_status_are_durable(self):
        self.coordinator.create_member(name="one", role="worker", workdir=Path(self.temp.name))
        self.coordinator.create_member(name="two", role="worker", workdir=Path(self.temp.name))
        result = self.coordinator.broadcast(kind="member.wakeup", payload={"reason": "new work"})
        self.assertEqual(len(result["messages"]), 2)
        reopened = TeamCoordinator(self.config, Path(self.temp.name))
        reopened.activate_lead("backend")
        self.assertEqual(len(reopened.status()["members"]), 3)

    def test_session_tool_view_is_empty_until_lead_activation(self):
        session = Session(config_path=str(Path(__file__).parent / "fixtures" / "minimal_config.yaml"))
        self.addCleanup(session.close)
        session.team_coordinator = TeamCoordinator(
            self.config,
            Path(self.temp.name),
            member_runner=session._run_team_member,
        )
        before = set(session._tool_view_for_mode(AgentMode.FULL).list_tools())
        self.assertFalse({"team_lead", "team_tasks", "team_message"} & before)
        session.activate_team("session-team", create=True)
        after = set(session._tool_view_for_mode(AgentMode.FULL).list_tools())
        self.assertTrue({"team_lead", "team_tasks", "team_message"} <= after)


class TeamApprovalRecoveryTests(TeamLeadFlowTests):
    def test_approval_required_member_does_not_execute_without_approval(self):
        member = self.coordinator.create_member(name="reviewer", role="review", workdir=Path(self.temp.name), approval_required=True)
        task = self.coordinator.assign(title="Review change", assignee="reviewer")
        self.assertEqual(self.coordinator.store.get_member(self.team, member.member_id).state, MemberState.IDLE)
        self.assertEqual(self.coordinator.mailbox.list_messages(self.team.lead_member_id)[0].kind, "approval.request")

    def test_lead_approval_message_resumes_original_member(self):
        member = self.coordinator.create_member(name="reviewer", role="review", workdir=Path(self.temp.name), approval_required=True)
        task = self.coordinator.assign(title="Review change", assignee="reviewer")
        request = self.coordinator.mailbox.list_messages(self.team.lead_member_id)[0]
        result = self.coordinator.send_message(
            recipient="reviewer",
            kind="approval.decision",
            payload={
                "request_id": request.payload["request_id"],
                "decision": "approve",
                "plan_digest": request.payload["plan_digest"],
            },
        )
        self.assertEqual(result["wakeup"]["state"].value, MemberState.BUSY.value)
        self.assertEqual(self.coordinator.store.get_member(self.team, member.member_id).member_id, member.member_id)


if __name__ == "__main__":
    unittest.main()
