"""Member lifecycle, mailbox wakeups and durable context recovery."""

from __future__ import annotations

import threading
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Callable, Optional

from flickcode.providers.base import Message
from flickcode.teams.approval import ApprovalGate
from flickcode.teams.backends import BackendHandle, BackendSelector, MemberLaunch
from flickcode.teams.context import MemberContextStore
from flickcode.teams.mailbox import MailboxStore
from flickcode.teams.models import MemberBackendKind, MemberState, RuntimeSnapshot, TeamMemberRecord, TeamMessage, TeamRecord, TeamTaskState
from flickcode.teams.protocol import ApprovalRequest, ProtocolCodec
from flickcode.teams.store import TeamStore
from flickcode.teams.tasks import TaskStore


class TeamMemberRuntime:
    def __init__(
        self,
        team: TeamRecord,
        member: TeamMemberRecord,
        *,
        store: TeamStore,
        mailbox: MailboxStore,
        tasks: TaskStore,
        backends: BackendSelector,
        approval: ApprovalGate,
        on_diagnostic: Optional[Callable[[str], None]] = None,
        launch_command: tuple[str, ...] = (),
        runner: Optional[Callable[[TeamMemberRecord, str], tuple[str, str]]] = None,
        executor: Optional[ThreadPoolExecutor] = None,
        execution_backend: Optional[MemberBackendKind] = None,
    ) -> None:
        self.team = team
        self.member = member
        self.store = store
        self.mailbox = mailbox
        self.tasks = tasks
        self.backends = backends
        self.approval = approval
        self.codec = ProtocolCodec()
        self.on_diagnostic = on_diagnostic
        self.launch_command = launch_command
        self.runner = runner
        self.executor = executor
        self.execution_backend = execution_backend
        self._handle: Optional[BackendHandle] = None
        self._future: Optional[Future] = None
        self._lock = threading.RLock()

    def _diagnostic(self, message: str) -> None:
        if self.on_diagnostic is not None:
            self.on_diagnostic(message)

    def _save_member(self, **changes) -> TeamMemberRecord:
        self.member = self.store.update_member(replace(self.member, **changes))
        return self.member

    def request_approval(self, task_id: str, plan: str) -> TeamMessage:
        request = ApprovalRequest.create(self.member.member_id, task_id, plan)
        self.approval.submit(request)
        message = self.codec.encode(
            team_id=self.team.team_id,
            sender_id=self.member.member_id,
            recipient_id=self.team.lead_member_id,
            kind="approval.request",
            payload={
                "request_id": request.request_id,
                "task_id": task_id,
                "plan": plan,
                "plan_digest": request.plan_digest,
            },
            body=plan,
            summary=f"Approval requested for {task_id}",
        )
        self.mailbox.send(self.team.lead_member_id, message)
        return message

    def start_or_resume(
        self,
        *,
        task_id: Optional[str] = None,
        plan: str = "",
        messages: tuple[Message, ...] = (),
        launch: Optional[MemberLaunch] = None,
    ) -> RuntimeSnapshot:
        with self._lock:
            if self.member.approval_required and task_id and not self.approval.is_approved(task_id):
                self.request_approval(task_id, plan or "No execution plan supplied")
                self._save_member(state=MemberState.IDLE, last_error="waiting for Lead approval")
                return RuntimeSnapshot(self.member.member_id, MemberState.IDLE, self.member.backend, error="waiting for Lead approval")
            try:
                context = MemberContextStore(self._member_layout()).load()
                if messages:
                    context["messages"] = list(context.get("messages", [])) + list(messages)
                if self._handle is None:
                    effective_backend = self.execution_backend or self.member.backend
                    backend = self.backends.backend(effective_backend)
                    default_command = self.launch_command or (
                        sys.executable,
                        "-m",
                        "flickcode",
                        "--team",
                        self.team.name,
                        "--team-member",
                        self.member.member_id,
                    )
                    self._handle = backend.start(
                        self.member,
                        launch or MemberLaunch(default_command, self.member.workdir),
                    )
                if task_id:
                    try:
                        current = self.tasks.get_task(task_id)
                        if current.state is not TeamTaskState.IN_PROGRESS:
                            self.tasks.start_task(task_id)
                    except (KeyError, ValueError):
                        pass
                MemberContextStore(self._member_layout()).save(
                    context.get("messages", []), last_task_id=task_id or context.get("last_task_id"), summary=context.get("summary", "")
                )
                self._save_member(state=MemberState.BUSY, runtime_handle=self._handle.token, last_error="")
                if (
                    self.runner is not None
                    and self.executor is not None
                    and (self.execution_backend is MemberBackendKind.IN_PROCESS or self.member.backend is MemberBackendKind.IN_PROCESS)
                    and task_id
                    and (self._future is None or self._future.done())
                ):
                    self._future = self.executor.submit(self._run_task, task_id)
                return RuntimeSnapshot(self.member.member_id, MemberState.BUSY, self.member.backend, self._handle.token, task_id)
            except Exception as exc:
                self._save_member(state=MemberState.FAILED, last_error=str(exc)[:2048])
                self._diagnostic(f"member {self.member.name} failed to start: {exc}")
                return RuntimeSnapshot(self.member.member_id, MemberState.FAILED, self.member.backend, error=str(exc))

    def deliver(self, message: TeamMessage, *, persist: bool = True) -> RuntimeSnapshot:
        with self._lock:
            if message.team_id != self.team.team_id:
                raise ValueError("message belongs to another team")
            if persist:
                self.mailbox.send(self.member.member_id, message)
            if self._handle is None or self.member.state in {MemberState.IDLE, MemberState.STOPPED, MemberState.REGISTERED}:
                return self.start_or_resume(task_id=message.payload.get("task_id"), plan=str(message.payload.get("plan", "")))
            backend = self.backends.backend(self._handle.backend if self._handle is not None else (self.execution_backend or self.member.backend))
            if not backend.wake(self._handle, "mailbox"):
                self._diagnostic(f"member {self.member.name} wakeup failed; message retained")
                return RuntimeSnapshot(self.member.member_id, self.member.state, self.member.backend, self._handle.token, error="wakeup failed")
            return RuntimeSnapshot(self.member.member_id, self.member.state, self.member.backend, self._handle.token)

    def _run_task(self, task_id: str) -> None:
        try:
            summary, error = self.runner(self.member, task_id)
        except Exception as exc:
            summary, error = "", str(exc)
        self.finish(task_id=task_id, summary=summary, error=error)

    def finish(self, *, task_id: Optional[str] = None, summary: str = "", error: str = "") -> RuntimeSnapshot:
        with self._lock:
            context = MemberContextStore(self._member_layout()).load()
            MemberContextStore(self._member_layout()).save(
                context.get("messages", []), last_task_id=task_id or context.get("last_task_id"), summary=summary
            )
            if task_id:
                try:
                    if error:
                        self.tasks.fail_task(task_id, error)
                    else:
                        self.tasks.complete_task(task_id, summary)
                except (KeyError, ValueError):
                    pass
            state = MemberState.FAILED if error else MemberState.IDLE
            self._save_member(state=state, last_error=error)
            if not error:
                message = self.codec.encode(
                    team_id=self.team.team_id,
                    sender_id=self.member.member_id,
                    recipient_id=self.team.lead_member_id,
                    kind="member.idle",
                    payload={"member_id": self.member.member_id, "task_id": task_id, "summary": summary},
                    body=summary,
                    summary=f"{self.member.name} is idle",
                )
                self.mailbox.send(self.team.lead_member_id, message)
            return RuntimeSnapshot(self.member.member_id, state, self.member.backend, self._handle.token if self._handle else None, task_id, error)

    def stop(self, reason: str = "stopped") -> RuntimeSnapshot:
        with self._lock:
            if self._handle is not None:
                self.backends.backend(self._handle.backend).stop(self._handle)
                self._handle = None
            self._save_member(state=MemberState.STOPPED, runtime_handle=None, last_error=reason)
            return RuntimeSnapshot(self.member.member_id, MemberState.STOPPED, self.member.backend, error=reason)

    def _member_layout(self):
        from flickcode.teams.paths import TeamLayout

        return TeamLayout(self.team.root).member(self.member.member_id)


class TeamRuntimeManager:
    def __init__(
        self,
        team: TeamRecord,
        *,
        store: TeamStore,
        mailbox: MailboxStore,
        tasks: TaskStore,
        backends: BackendSelector,
        approval: ApprovalGate,
        on_diagnostic: Optional[Callable[[str], None]] = None,
        runner: Optional[Callable[[TeamMemberRecord, str], tuple[str, str]]] = None,
        max_workers: int = 4,
        execution_backend: Optional[MemberBackendKind] = None,
    ) -> None:
        self.team = team
        self.store = store
        self.mailbox = mailbox
        self.tasks = tasks
        self.backends = backends
        self.approval = approval
        self.on_diagnostic = on_diagnostic
        self.runner = runner
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="flick-team")
        self.execution_backend = execution_backend
        self._runtimes: dict[str, TeamMemberRuntime] = {}

    def runtime(self, member_id: str) -> TeamMemberRuntime:
        current = self._runtimes.get(member_id)
        member = self.store.get_member(self.team, member_id)
        if current is None:
            current = TeamMemberRuntime(
                self.team,
                member,
                store=self.store,
                mailbox=self.mailbox,
                tasks=self.tasks,
                backends=self.backends,
                approval=self.approval,
                on_diagnostic=self.on_diagnostic,
                runner=self.runner,
                executor=self._executor,
                execution_backend=self.execution_backend,
            )
            self._runtimes[member_id] = current
        else:
            current.member = member
        return current

    def start_or_resume(self, member_id: str, **kwargs) -> RuntimeSnapshot:
        return self.runtime(member_id).start_or_resume(**kwargs)

    def deliver(self, member_id: str, message: TeamMessage, *, persist: bool = True) -> RuntimeSnapshot:
        return self.runtime(member_id).deliver(message, persist=persist)

    def finish(self, member_id: str, **kwargs) -> RuntimeSnapshot:
        return self.runtime(member_id).finish(**kwargs)

    def stop(self, member_id: str, reason: str = "stopped") -> RuntimeSnapshot:
        return self.runtime(member_id).stop(reason)

    def status(self, member_id: str) -> RuntimeSnapshot:
        member = self.store.get_member(self.team, member_id)
        return RuntimeSnapshot(member.member_id, member.state, member.backend, member.runtime_handle, error=member.last_error)

    def stop_all(self, reason: str = "team closed") -> None:
        for member_id in tuple(self._runtimes):
            self.stop(member_id, reason)
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            self._executor.shutdown(wait=False)
