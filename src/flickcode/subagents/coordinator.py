"""Validation and orchestration behind the stable Agent tool."""

from __future__ import annotations

from typing import Mapping

from flickcode.config import ProviderConfig, SubAgentConfig
from flickcode.subagents.models import (
    AgentInvocationType,
    AgentToolOperation,
    AgentToolRequest,
    AgentToolResponse,
)


class SubAgentCoordinator:
    def __init__(
        self,
        *,
        roles,
        snapshots,
        runtime_factory,
        tasks,
        config: SubAgentConfig,
        session_id_provider,
        provider_provider,
        providers: Mapping[str, ProviderConfig],
        tools_provider,
        permission_provider,
        thinking_provider,
        max_turns_provider,
    ) -> None:
        self.roles = roles
        self.snapshots = snapshots
        self.runtime_factory = runtime_factory
        self.tasks = tasks
        self.config = config
        self.session_id_provider = session_id_provider
        self.provider_provider = provider_provider
        self.providers = providers
        self.tools_provider = tools_provider
        self.permission_provider = permission_provider
        self.thinking_provider = thinking_provider
        self.max_turns_provider = max_turns_provider

    def handle(self, request: AgentToolRequest) -> AgentToolResponse:
        try:
            if request.operation is AgentToolOperation.START:
                return self._start(request)
            if not request.task_id:
                raise ValueError(f"{request.operation.value} requires task_id")
            if request.operation is AgentToolOperation.STATUS:
                snap = self.tasks.status(request.task_id)
                return self._from_snapshot(snap)
            if request.operation is AgentToolOperation.RESULT:
                result = self.tasks.result(request.task_id)
                snapshot = self.tasks.status(request.task_id)
                return AgentToolResponse(
                    True, request.task_id, result.state.value,
                    result=result.result,
                    result_path=str(result.result_path) if result.result_path else None,
                    background=snapshot.background,
                    summary=snapshot.summary,
                    usage=snapshot.usage,
                    error=snapshot.error or None,
                    workspace=snapshot.workspace,
                )
            if request.operation is AgentToolOperation.CANCEL:
                return self._from_snapshot(self.tasks.cancel(request.task_id))
            raise ValueError("unsupported Agent operation")
        except (ValueError, KeyError, RuntimeError) as exc:
            return AgentToolResponse(False, task_id=request.task_id, error=str(exc))

    def _start(self, request: AgentToolRequest) -> AgentToolResponse:
        if not request.task or not request.task.strip():
            raise ValueError("start requires a non-empty task")
        if request.invocation_type is None:
            raise ValueError("start requires type=defined or fork")
        task_id = self.tasks.new_task_id()
        if request.invocation_type is AgentInvocationType.DEFINED:
            if not request.role:
                raise ValueError("defined start requires role")
            role = self.roles.resolve(request.role)
            if role is None:
                raise ValueError(f"Unknown Agent role: {request.role}")
            background = bool(request.background)
            spec = self.runtime_factory.defined_spec(
                task_id=task_id,
                parent_session_id=self.session_id_provider(),
                role=role,
                task=request.task,
                parent_provider=self.provider_provider(),
                providers=self.providers,
                model_aliases=self.config.model_aliases,
                parent_tools=self.tools_provider(),
                parent_permission=self.permission_provider(),
                background=background,
                background_allow=self.config.background_allowed_tools,
                additional_deny=self.config.additional_denied_tools,
                thinking=self.thinking_provider(),
            )
            snapshot = self.tasks.submit(spec, background)
            if not background:
                snapshot = self.tasks.wait_or_detach(task_id)
            return self._from_snapshot(snapshot)
        if request.role:
            raise ValueError("fork start must not include role")
        parent = self.snapshots.get()
        if parent is None:
            raise ValueError("Fork requires a completed parent request snapshot")
        spec = self.runtime_factory.fork_spec(
            task_id=task_id,
            snapshot=parent,
            task=request.task,
            parent_permission=self.permission_provider(),
            max_turns=self.max_turns_provider(),
            background_allow=self.config.background_allowed_tools,
            additional_deny=self.config.additional_denied_tools,
        )
        snapshot = self.tasks.submit(spec, True)
        response = self._from_snapshot(snapshot)
        return AgentToolResponse(**{**response.__dict__, "forced_background": request.background is False})

    @staticmethod
    def _from_snapshot(snapshot) -> AgentToolResponse:
        return AgentToolResponse(
            True,
            task_id=snapshot.task_id,
            status=snapshot.state.value,
            background=snapshot.background,
            summary=snapshot.summary,
            usage=snapshot.usage,
            error=snapshot.error or None,
            workspace=snapshot.workspace,
        )
