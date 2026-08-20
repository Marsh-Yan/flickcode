"""Isolated SubAgent runtime construction and run-to-completion execution."""

from __future__ import annotations

import copy
import inspect
import json
import platform
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Callable, Mapping, Optional

from flickcode.agent import AgentConfig, AgentLoop, AgentMode, StopReason
from flickcode.config import ContextConfig, ProviderConfig
from flickcode.context import ContextManager
from flickcode.permissions import PermissionEngine
from flickcode.providers.base import Message
from flickcode.subagents.foreground import CancellationToken
from flickcode.subagents.models import (
    AgentInvocationType,
    AgentRoleDefinition,
    AgentUsage,
    ParentRequestSnapshot,
    SubAgentExecutionResult,
    SubAgentLaunchSpec,
    SubAgentTaskState,
)
from flickcode.worktrees.models import (
    AgentIsolationMode,
    WorkspaceContext,
    WorkspaceRequest,
    WorktreeDisposition,
    WorktreeLease,
    WorktreeOutcome,
    WorkspaceStatus,
)
from flickcode.worktrees.lifecycle import WorktreeLifecycle
from flickcode.tools.cache import FileContentCache
from flickcode.worktrees.resources import WorkspacePromptFactory
from flickcode.subagents.policy import ModelResolver, SubAgentPermissionPolicy, SubAgentToolPolicy
from flickcode.subagents.provider_pool import ProviderPool
from flickcode.tools.registry import ToolRegistryView


class FixedPromptBuilder:
    def __init__(self, prompt: str) -> None:
        self.prompt = prompt

    def build(self, context) -> tuple[str, list[Message]]:
        return self.prompt, []


@dataclass
class ChildRuntime:
    spec: SubAgentLaunchSpec
    provider: object
    messages: list[Message]
    context_manager: ContextManager
    permission_engine: PermissionEngine
    cancellation: CancellationToken
    file_read_cache: dict = None
    hook_engine: object = None
    workspace: Optional[WorkspaceContext] = None

    def __post_init__(self) -> None:
        if self.file_read_cache is None:
            self.file_read_cache = {}


class ChildRuntimeFactory:
    def __init__(
        self,
        project_root: Path,
        provider_pool: ProviderPool,
        context_config: ContextConfig,
        hook_scope_factory: Optional[Callable[..., object]] = None,
        prompt_factory: Optional[WorkspacePromptFactory] = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.provider_pool = provider_pool
        self.context_config = context_config
        self.hook_scope_factory = hook_scope_factory
        self.prompt_factory = prompt_factory or WorkspacePromptFactory()

    @staticmethod
    def controlled_environment(project_root: Path) -> str:
        return (
            "\n\n[environment]\n"
            f"project_root: {project_root}\n"
            f"platform: {platform.system()}\n"
            f"date: {date.today().isoformat()}\n"
            f"project_type: source repository"
        )

    def create(
        self,
        spec: SubAgentLaunchSpec,
        token: CancellationToken,
        workspace: Optional[WorkspaceContext] = None,
    ) -> ChildRuntime:
        if workspace is None:
            workspace = WorkspaceContext(
                isolation=AgentIsolationMode.SHARED,
                project_root=self.project_root,
                repository_root=self.project_root,
                main_project_root=self.project_root,
                task_id=spec.task_id,
            )
        provider = self.provider_pool.create(spec.provider_config)
        messages = copy.deepcopy(list(spec.messages))
        # Child compaction/results stay project-local instead of inheriting a
        # user-profile (typically C-drive) storage path.
        child_context_config = replace(
            self.context_config,
            storage_dir=(
                workspace.project_root
                / ".tmp"
                / "subagents"
                / "context"
                / spec.task_id
            ),
        )
        manager = ContextManager(provider, child_context_config, session_id=spec.task_id)
        engine = PermissionEngine(
            mode=spec.permission_mode,
            project_root=workspace.project_root,
            hitl_callback=None,
        )
        hook_scope = None
        if self.hook_scope_factory:
            # Keep third-party/test factories written for the original
            # one-argument API while allowing production scopes to receive
            # the explicit workspace context.
            try:
                parameters = inspect.signature(self.hook_scope_factory).parameters.values()
                positional = [
                    item for item in parameters
                    if item.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                ]
                accepts_varargs = any(item.kind is inspect.Parameter.VAR_POSITIONAL for item in parameters)
                if accepts_varargs or len(positional) >= 2:
                    hook_scope = self.hook_scope_factory(spec, workspace)
                else:
                    hook_scope = self.hook_scope_factory(spec)
            except (TypeError, ValueError):
                hook_scope = self.hook_scope_factory(spec, workspace)
        return ChildRuntime(
            spec, provider, messages, manager, engine, token,
            hook_engine=hook_scope, workspace=workspace,
        )

    def prompt_for_workspace(
        self,
        spec: SubAgentLaunchSpec,
        workspace: WorkspaceContext,
    ) -> str:
        if spec.role is None:
            return spec.system_prompt
        return self.prompt_factory.build_defined_prompt(
            role_prompt=spec.role.system_prompt,
            role_fingerprint=spec.role.fingerprint,
            workspace=workspace,
        )

    def defined_spec(
        self,
        *,
        task_id: str,
        parent_session_id: str,
        role: AgentRoleDefinition,
        task: str,
        parent_provider: ProviderConfig,
        providers: Mapping[str, ProviderConfig],
        model_aliases: Mapping[str, str],
        parent_tools: ToolRegistryView,
        parent_permission,
        background: bool,
        background_allow=(),
        additional_deny=(),
        thinking: bool = False,
    ) -> SubAgentLaunchSpec:
        provider = ModelResolver.resolve(role.model, parent_provider, providers, model_aliases)
        permission = SubAgentPermissionPolicy.resolve(parent_permission, role.permission_mode)
        tools = SubAgentToolPolicy.resolve(
            parent_tools,
            role_allow=role.allowed_tools,
            role_deny=role.denied_tools,
            additional_deny=additional_deny,
            background_allow=background_allow if background else None,
        )
        prompt = role.system_prompt + self.controlled_environment(self.project_root)
        return SubAgentLaunchSpec(
            task_id=task_id,
            parent_session_id=parent_session_id,
            invocation_type=AgentInvocationType.DEFINED,
            role=role,
            task=task,
            messages=(Message(role="user", content=task),),
            system_prompt=prompt,
            mode=AgentMode.FULL,
            provider_config=provider,
            tool_view=tools,
            permission_mode=permission,
            max_turns=role.max_turns,
            thinking=provider.thinking if provider is not parent_provider else thinking,
            workspace_request=WorkspaceRequest(
                role.isolation,
                task_id,
                f"agents/{task_id}" if role.isolation is AgentIsolationMode.WORKTREE else "",
            ),
        )

    def fork_spec(
        self,
        *,
        task_id: str,
        snapshot: ParentRequestSnapshot,
        task: str,
        parent_permission,
        max_turns: int,
        background_allow=(),
        additional_deny=(),
    ) -> SubAgentLaunchSpec:
        tools = SubAgentToolPolicy.resolve(
            snapshot.tool_view,
            additional_deny=additional_deny,
            background_allow=background_allow,
        )
        messages = list(copy.deepcopy(snapshot.messages))
        messages.append(Message(role="user", content=task))
        return SubAgentLaunchSpec(
            task_id=task_id,
            parent_session_id=snapshot.session_id,
            invocation_type=AgentInvocationType.FORK,
            role=None,
            task=task,
            messages=tuple(messages),
            system_prompt=snapshot.system_prompt or "",
            mode=snapshot.mode,
            provider_config=snapshot.provider_config,
            tool_view=tools,
            permission_mode=parent_permission,
            max_turns=max_turns,
            thinking=snapshot.thinking,
            forced_background=True,
            workspace_request=WorkspaceRequest(AgentIsolationMode.SHARED, task_id, ""),
        )


class SubAgentRunner:
    SUMMARY_LIMIT = 4096

    def __init__(
        self,
        factory: ChildRuntimeFactory,
        lifecycle: Optional[WorktreeLifecycle] = None,
        workspace_callback: Optional[Callable[[str, WorkspaceStatus], None]] = None,
    ) -> None:
        self.factory = factory
        self.lifecycle = lifecycle
        self.workspace_callback = workspace_callback

    def bind_workspace_callback(
        self, callback: Optional[Callable[[str, WorkspaceStatus], None]]
    ) -> None:
        self.workspace_callback = callback

    def _notify_workspace(self, task_id: str, status: WorkspaceStatus) -> None:
        if self.workspace_callback is None:
            return
        try:
            self.workspace_callback(task_id, status)
        except Exception:
            pass

    def _create_runtime(
        self,
        spec: SubAgentLaunchSpec,
        token: CancellationToken,
        workspace: WorkspaceContext,
    ) -> ChildRuntime:
        creator = self.factory.create
        try:
            parameters = inspect.signature(creator).parameters.values()
            positional = [
                item for item in parameters
                if item.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]
            accepts_varargs = any(item.kind is inspect.Parameter.VAR_POSITIONAL for item in parameters)
            if accepts_varargs or len(positional) >= 3:
                return creator(spec, token, workspace)
            return creator(spec, token)
        except (TypeError, ValueError):
            return creator(spec, token, workspace)

    def run(self, spec: SubAgentLaunchSpec, token: CancellationToken) -> SubAgentExecutionResult:
        if token.is_cancelled():
            return SubAgentExecutionResult(
                SubAgentTaskState.CANCELLED,
                "",
                "SubAgent cancelled before workspace setup.",
                AgentUsage(),
                StopReason.USER_CANCELLED,
            )
        lease: Optional[WorktreeLease] = None
        workspace: Optional[WorkspaceContext] = None
        runtime: Optional[ChildRuntime] = None
        runtime_spec = spec
        workspace_request = spec.workspace_request
        if (
            spec.role is not None
            and spec.role.isolation is AgentIsolationMode.WORKTREE
            and workspace_request.isolation is AgentIsolationMode.SHARED
        ):
            workspace_request = WorkspaceRequest(
                AgentIsolationMode.WORKTREE,
                spec.task_id,
                f"agents/{spec.task_id}",
            )
        if self.lifecycle is not None:
            try:
                lease = self.lifecycle.enter(workspace_request)
            except Exception as exc:
                self._notify_workspace(
                    spec.task_id,
                    WorkspaceStatus(
                        disposition=WorktreeDisposition.RETAINED_CHECK_FAILED,
                        reason=f"Worktree enter failed: {exc}",
                        isolation=workspace_request.isolation,
                    ),
                )
                return SubAgentExecutionResult(
                    SubAgentTaskState.FAILED,
                    "",
                    "SubAgent Worktree setup failed.",
                    AgentUsage(),
                    StopReason.ERROR,
                    str(exc)[:2048],
                )
            workspace = lease.handle.workspace
            self._notify_workspace(
                spec.task_id,
                WorkspaceStatus(
                    path=workspace.project_root,
                    branch=workspace.branch,
                    recovered=lease.handle.recovered,
                    disposition=WorktreeDisposition.NOT_USED,
                    reason="workspace entered",
                    worktree_root=workspace.repository_root,
                    main_project_root=workspace.main_project_root,
                    isolation=workspace.isolation,
                ),
            )
        else:
            factory_root = Path(getattr(self.factory, "project_root", Path.cwd())).resolve()
            workspace = WorkspaceContext(
                isolation=AgentIsolationMode.SHARED,
                project_root=factory_root,
                repository_root=factory_root,
                main_project_root=factory_root,
                task_id=spec.task_id,
            )
            self._notify_workspace(
                spec.task_id,
                WorkspaceStatus(
                    path=workspace.project_root,
                    recovered=False,
                    disposition=WorktreeDisposition.NOT_USED,
                    reason="shared workspace",
                    worktree_root=workspace.repository_root,
                    main_project_root=workspace.main_project_root,
                    isolation=workspace.isolation,
                ),
            )
        stop_reason = StopReason.ERROR
        usage = AgentUsage()
        errors: list[str] = []
        rounds = 0
        try:
            if spec.role is not None and workspace is not None and hasattr(self.factory, "prompt_for_workspace"):
                runtime_spec = replace(
                    spec,
                    system_prompt=self.factory.prompt_for_workspace(spec, workspace),
                    workspace_request=workspace_request,
                )
            elif workspace_request != spec.workspace_request:
                runtime_spec = replace(spec, workspace_request=workspace_request)
            runtime = self._create_runtime(runtime_spec, token, workspace)
            config = AgentConfig(max_iterations=runtime_spec.max_turns)
            loop = AgentLoop(
                provider=runtime.provider,
                tools=runtime_spec.tool_view,
                mode=runtime_spec.mode,
                config=config,
                builder=FixedPromptBuilder(runtime_spec.system_prompt),
                engine=runtime.permission_engine,
                context_manager=runtime.context_manager,
                cancel_check=token.is_cancelled,
                non_interactive_permissions=True,
                hook_engine=runtime.hook_engine,
                cwd=workspace.project_root if workspace is not None else Path.cwd(),
                file_cache=FileContentCache(),
            )
            for event in loop.run(runtime.messages, thinking=spec.thinking):
                if event.type == "progress":
                    rounds += 1
                elif event.type == "error":
                    errors.append(event.content)
                elif event.type == "done":
                    data = json.loads(event.content or "{}")
                    stop_reason = StopReason(data.get("stop_reason", StopReason.ERROR.value))
                    raw = data.get("usage", {})
                    usage = AgentUsage(
                        input_tokens=raw.get("input_tokens", 0),
                        output_tokens=raw.get("output_tokens", 0),
                        thinking_tokens=raw.get("thinking_tokens", 0),
                        cache_creation_input_tokens=raw.get("cache_creation_input_tokens", 0),
                        cache_read_input_tokens=raw.get("cache_read_input_tokens", 0),
                        rounds=rounds,
                    )
        except Exception as exc:
            errors.append(str(exc))
            stop_reason = StopReason.ERROR
        finally:
            close_scope = getattr(runtime.hook_engine, "close_scope", None) if runtime else None
            if close_scope is not None:
                try:
                    close_scope()
                except Exception as exc:
                    errors.append(f"Hook scope cleanup failed: {exc}")
            if lease is not None and self.lifecycle is not None:
                try:
                    outcome = self.lifecycle.exit(lease)
                except Exception as exc:
                    outcome = WorktreeOutcome(
                        WorktreeDisposition.RETAINED_CHECK_FAILED,
                        workspace.project_root if workspace is not None else None,
                        workspace.branch if workspace is not None else "",
                        f"Worktree exit failed: {exc}",
                    )
                # ``WorkspaceStatus.path`` is the explicit tool cwd (the
                # project root); the Worktree top-level path is carried
                # separately for cleanup/inspection.
                terminal_path = workspace.project_root
                self._notify_workspace(
                    spec.task_id,
                    WorkspaceStatus(
                        path=terminal_path,
                        branch=outcome.branch or (workspace.branch if workspace else ""),
                        recovered=lease.handle.recovered,
                        disposition=outcome.disposition,
                        reason=outcome.reason,
                        worktree_root=workspace.repository_root if workspace else None,
                        main_project_root=workspace.main_project_root if workspace else None,
                        isolation=workspace.isolation if workspace else AgentIsolationMode.SHARED,
                    ),
                )
        content = next(
            (m.content for m in reversed(runtime.messages) if m.role == "assistant" and m.content),
            "",
        ) if runtime is not None else ""
        state = {
            StopReason.COMPLETED: SubAgentTaskState.COMPLETED,
            StopReason.MAX_ITERATIONS: SubAgentTaskState.LIMITED,
            StopReason.USER_CANCELLED: SubAgentTaskState.CANCELLED,
        }.get(stop_reason, SubAgentTaskState.FAILED)
        error = errors[-1][:2048] if errors else ""
        summary = (content or error or stop_reason.value)[: self.SUMMARY_LIMIT]
        return SubAgentExecutionResult(state, content, summary, usage, stop_reason, error)
