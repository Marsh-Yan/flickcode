"""High-level Lead orchestration for durable teams."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Optional

from flickcode.config import TeamsConfig
from flickcode.teams.approval import ApprovalGate
from flickcode.teams.backends import BackendSelector
from flickcode.teams.mailbox import MailboxStore
from flickcode.teams.merge import TeamGitIntegrator
from flickcode.teams.models import MemberBackendKind, MemberState, TeamRecord, TeamStatus, TeamTaskRecord
from flickcode.teams.policy import coordinator_active
from flickcode.teams.protocol import ProtocolCodec
from flickcode.teams.runtime import TeamRuntimeManager
from flickcode.teams.store import TeamStore
from flickcode.teams.tasks import TaskStore
from flickcode.teams.pane import default_pane_adapters


class TeamCoordinator:
    def __init__(self, config: TeamsConfig, project_root: Path, *, diagnostic_callback=None, member_runner=None) -> None:
        storage = Path(config.storage_dir).expanduser()
        if not storage.is_absolute():
            storage = Path(project_root) / storage
        self.config = config
        self.project_root = Path(project_root).resolve()
        self.store = TeamStore(storage, lock_retry_seconds=config.lock_retry_seconds, lock_stale_seconds=config.lock_stale_seconds)
        self.selector = BackendSelector(pane_adapters=default_pane_adapters(config.pane_adapters))
        self.diagnostic_callback = diagnostic_callback
        self.member_runner = member_runner
        self.team: Optional[TeamRecord] = None
        self.tasks: Optional[TaskStore] = None
        self.mailbox: Optional[MailboxStore] = None
        self.runtime: Optional[TeamRuntimeManager] = None
        self.approval: Optional[ApprovalGate] = None
        self.member_id: Optional[str] = None
        self.merge = TeamGitIntegrator(timeout=config.wake_timeout_seconds * 12)
        self._codec = ProtocolCodec()

    def _diagnostic(self, message: str) -> None:
        if self.diagnostic_callback is not None:
            self.diagnostic_callback(message)

    @property
    def active(self) -> bool:
        return self.team is not None and self.team.status is TeamStatus.ACTIVE

    @property
    def coordinator_enabled(self) -> bool:
        return coordinator_active(self.config.coordinator_enabled)

    def activate_lead(self, name: str, *, lead_name: str = "lead", create: bool = False, lead_workdir: Optional[Path] = None) -> TeamRecord:
        if create:
            team = self.store.create(name, lead_name, lead_workdir=lead_workdir or self.project_root)
        else:
            team = self.store.open(name)
        self.team = team
        self.tasks = TaskStore(team, retry_seconds=self.config.lock_retry_seconds, stale_seconds=self.config.lock_stale_seconds)
        layout = self.store.layout_for_name(team.name)
        self.mailbox = MailboxStore(layout, retry_seconds=self.config.lock_retry_seconds, stale_seconds=self.config.lock_stale_seconds)
        self.approval = ApprovalGate(self._codec)
        self.runtime = TeamRuntimeManager(
            team,
            store=self.store,
            mailbox=self.mailbox,
            tasks=self.tasks,
            backends=self.selector,
            approval=self.approval,
            on_diagnostic=self._diagnostic,
            runner=self.member_runner,
        )
        self.member_id = team.lead_member_id
        return team

    def activate_member(self, name: str, member_id: str) -> TeamRecord:
        team = self.store.open(name)
        member = self.store.get_member(team, member_id)
        self.team = team
        self.member_id = member.member_id
        self.tasks = TaskStore(team, retry_seconds=self.config.lock_retry_seconds, stale_seconds=self.config.lock_stale_seconds)
        layout = self.store.layout_for_name(team.name)
        self.mailbox = MailboxStore(layout, retry_seconds=self.config.lock_retry_seconds, stale_seconds=self.config.lock_stale_seconds)
        self.approval = ApprovalGate(self._codec)
        self.runtime = TeamRuntimeManager(
            team,
            store=self.store,
            mailbox=self.mailbox,
            tasks=self.tasks,
            backends=self.selector,
            approval=self.approval,
            on_diagnostic=self._diagnostic,
            runner=self.member_runner,
            execution_backend=MemberBackendKind.IN_PROCESS,
        )
        return team

    def leave(self) -> None:
        if self.runtime is not None:
            self.runtime.stop_all("Lead left team")
        self.team = None
        self.tasks = None
        self.mailbox = None
        self.runtime = None
        self.approval = None
        self.member_id = None

    def _require(self) -> tuple[TeamRecord, TaskStore, MailboxStore, TeamRuntimeManager]:
        if not self.active or self.tasks is None or self.mailbox is None or self.runtime is None:
            raise RuntimeError("no active Lead team")
        return self.team, self.tasks, self.mailbox, self.runtime

    def create_member(
        self,
        *,
        name: str,
        role: str,
        workdir: Optional[Path] = None,
        backend_preference: Optional[Iterable[str]] = None,
        approval_required: bool = False,
    ):
        team, _, _, _ = self._require()
        preference = tuple(backend_preference or self.config.backend_preference)
        selection = self.selector.choose(preference)
        if selection.backend is None:
            raise RuntimeError("member backend unavailable: " + selection.reason)
        member = self.store.add_member(
            team,
            name=name,
            role=role,
            workdir=workdir or self.project_root,
            backend=selection.backend,
            backend_reason=selection.reason,
            approval_required=approval_required,
        )
        return member

    def assign(self, *, title: str, description: str = "", assignee: Optional[str] = None, dependencies: Iterable[str] = ()) -> TeamTaskRecord:
        team, tasks, mailbox, runtime = self._require()
        member_id = None
        member = None
        if assignee:
            route = self.store.layout_for_name(team.name)
            from flickcode.teams.registry import NameRegistry

            found = NameRegistry(route, retry_seconds=self.config.lock_retry_seconds, stale_seconds=self.config.lock_stale_seconds).resolve(assignee)
            member_id = str(found["member_id"])
            member = self.store.get_member(team, member_id)
        task = tasks.create_task(title, description, assignee_id=member_id, dependency_ids=dependencies, created_by=team.lead_member_id)
        if member is not None:
            message = self._codec.encode(
                team_id=team.team_id,
                sender_id=team.lead_member_id,
                recipient_id=member.member_id,
                kind="task.assign",
                payload={"task_id": task.task_id, "title": task.title, "description": task.description, "dependency_ids": list(task.dependency_ids)},
                body=description,
                summary=f"Assigned {task.task_id}: {title}",
            )
            runtime.deliver(member.member_id, message)
        return task

    def terminate(self, member_id: str) -> dict[str, Any]:
        _, _, _, runtime = self._require()
        snapshot = runtime.stop(member_id, "terminated by Lead")
        return snapshot.__dict__.copy()

    def send_message(self, *, recipient: str, kind: str = "member.wakeup", payload: Optional[dict] = None, body: str = "", summary: str = "", sender_id: Optional[str] = None):
        team, _, mailbox, runtime = self._require()
        sender = sender_id or team.lead_member_id
        message = mailbox.send_to_name(team_id=team.team_id, sender_id=sender, recipient_name=recipient, kind=kind, payload=payload or {}, body=body, summary=summary)
        route = self.store.layout_for_name(team.name)
        from flickcode.teams.registry import NameRegistry

        member_id = str(NameRegistry(route, retry_seconds=self.config.lock_retry_seconds, stale_seconds=self.config.lock_stale_seconds).resolve(recipient)["member_id"])
        if member_id == team.lead_member_id and sender != team.lead_member_id:
            wake = {"member_id": member_id, "state": "mailbox_only", "message_id": message.message_id}
        elif kind == "approval.decision":
            wake = self.handle_approval(member_id, message)
        else:
            wake = runtime.deliver(member_id, message, persist=False)
        return {"message_id": message.message_id, "member_id": member_id, "wakeup": wake if isinstance(wake, dict) else wake.__dict__}

    def handle_approval(self, member_id: str, message):
        team, _, _, runtime = self._require()
        if self.approval is None:
            raise RuntimeError("approval gate is not active")
        request_id = str(message.payload.get("request_id", ""))
        state = self.approval.state(request_id)
        if state is None:
            raise ValueError("unknown approval request")
        result = self.approval.apply(
            message,
            request_id=request_id,
            request=state.request,
            lead_member_id=team.lead_member_id,
        )
        if result.decision == "approve":
            return runtime.start_or_resume(member_id, task_id=state.request.task_id, plan=state.request.plan)
        return runtime.status(member_id) if hasattr(runtime, "status") else result

    def broadcast(self, *, kind: str = "member.wakeup", payload: Optional[dict] = None, body: str = "", summary: str = "", sender_id: Optional[str] = None):
        team, _, mailbox, runtime = self._require()
        sender = sender_id or team.lead_member_id
        messages = mailbox.broadcast(team_id=team.team_id, sender_id=sender, kind=kind, payload=payload or {}, body=body, summary=summary)
        wakes = []
        for message in messages:
            if message.recipient_id:
                if message.recipient_id == team.lead_member_id and sender != team.lead_member_id:
                    wakes.append({"member_id": message.recipient_id, "state": "mailbox_only", "message_id": message.message_id})
                else:
                    wakes.append(runtime.deliver(message.recipient_id, message, persist=False).__dict__)
        return {"messages": [item.to_dict() for item in messages], "wakeup": wakes}

    def status(self) -> dict[str, Any]:
        team, tasks, _, _ = self._require()
        return {
            "team": team.to_dict(),
            "coordinator_active": self.coordinator_enabled,
            "members": [item.to_dict() for item in self.store.list_members(team)],
            "tasks": [item.to_dict() for item in tasks.list_tasks()],
        }

    def merge_branches(self, branches: Iterable[str]) -> dict[str, Any]:
        if not self.active:
            raise RuntimeError("no active Lead team")
        result = self.merge.merge_all(self.project_root, branches)
        return result.__dict__.copy()

    def coordinator_state(self) -> dict[str, Any]:
        return {
            "config_enabled": bool(self.config.coordinator_enabled),
            "environment_enabled": __import__("os").environ.get("FLICKCODE_COORDINATOR") == "1",
            "active": self.coordinator_enabled,
        }
