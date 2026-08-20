"""Unified shared and isolated Skill invocation."""

from __future__ import annotations

import json
from pathlib import Path
from dataclasses import replace
from typing import Callable, Optional, Sequence

from flickcode.agent import AgentConfig, AgentEvent, AgentLoop, AgentMode
from flickcode.config import ProviderConfig
from flickcode.context import ContextConfig, ContextManager
from flickcode.permissions import PermissionEngine
from flickcode.prompt import (
    ActiveSkillsSection,
    IsolatedSkillHandoffSection,
    SkillCatalogSection,
    SystemPromptBuilder,
)
from flickcode.providers import BaseProvider, Message, create_provider
from flickcode.sessions import SessionJournal
from flickcode.skills.history import CompleteTurnSelector
from flickcode.skills.load_tool import LoadSkillTool
from flickcode.skills.models import (
    ChildSessionMetadata,
    SkillExecutionResult,
    SkillInvocation,
    SkillInvocationOrigin,
    SkillMode,
)
from flickcode.skills.runtime import SkillRuntime
from flickcode.tools.registry import ToolRegistry


class SkillExecutionError(ValueError):
    pass


class SkillExecutor:
    """Prepares invocations and owns isolated child-agent execution."""

    SUMMARY_LIMIT = 8192

    def __init__(
        self,
        runtime: SkillRuntime,
        tools: ToolRegistry,
        project_root: Path,
        journal: SessionJournal,
        messages_provider: Callable[[], Sequence[Message]],
        session_id_provider: Callable[[], str],
        provider_config_provider: Callable[[], ProviderConfig],
        context_config: ContextConfig,
        agent_config: AgentConfig,
        prompt_builder: SystemPromptBuilder,
        permission_engine: Optional[PermissionEngine] = None,
        prompt_context_provider: Optional[Callable[[AgentMode, int], dict]] = None,
        refresh_callback: Optional[Callable[[], None]] = None,
        provider_factory: Callable[[ProviderConfig], BaseProvider] = create_provider,
        diagnostic_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.runtime = runtime
        self.tools = tools
        self.project_root = Path(project_root).resolve()
        self.journal = journal
        self.messages_provider = messages_provider
        self.session_id_provider = session_id_provider
        self.provider_config_provider = provider_config_provider
        self.context_config = context_config
        self.agent_config = agent_config
        self.prompt_builder = prompt_builder
        self.permission_engine = permission_engine
        self.prompt_context_provider = prompt_context_provider
        self.refresh_callback = refresh_callback
        self.provider_factory = provider_factory
        self.diagnostic_callback = diagnostic_callback
        self.turn_selector = CompleteTurnSelector()
        if self.prompt_builder.get_section("active_skills") is None:
            self.prompt_builder.add_section(ActiveSkillsSection())
        if self.prompt_builder.get_section("skill_catalog") is None:
            self.prompt_builder.add_section(SkillCatalogSection())
        if self.prompt_builder.get_section("isolated_skill_handoff") is None:
            self.prompt_builder.add_section(IsolatedSkillHandoffSection())

    def prepare(
        self,
        name: str,
        user_input: str,
        origin: SkillInvocationOrigin,
        parent_mode: AgentMode,
    ) -> SkillInvocation:
        if self.refresh_callback is not None:
            try:
                self.refresh_callback()
            except Exception as exc:
                if self.diagnostic_callback is not None:
                    self.diagnostic_callback(
                        f"Skill refresh failed; using the previous committed snapshot: {exc}"
                    )
        definition = self.runtime.snapshot.catalog.effective.get(name)
        if definition is None:
            raise SkillExecutionError(f"Skill {name!r} is not available")
        return SkillInvocation(
            definition=definition,
            user_input=user_input,
            origin=origin,
            parent_session_id=self.session_id_provider(),
            parent_agent_mode=parent_mode,
        )

    def invoke(
        self,
        name: str,
        user_input: str = "",
        origin: SkillInvocationOrigin = SkillInvocationOrigin.SLASH,
        parent_mode: AgentMode = AgentMode.FULL,
        cwd: Path | None = None,
    ) -> SkillExecutionResult:
        try:
            invocation = self.prepare(name, user_input, origin, parent_mode)
        except Exception as exc:
            return SkillExecutionResult(
                success=False,
                mode=SkillMode.SHARED,
                summary=f"Skill invocation failed: {exc}",
            )
        if invocation.definition.mode is SkillMode.SHARED:
            return self._activate_shared(invocation)
        return self._run_isolated(invocation, cwd=cwd)

    def _activate_shared(self, invocation: SkillInvocation) -> SkillExecutionResult:
        result = self.runtime.activate_shared(invocation.definition.name, invocation.user_input)
        if not result.success:
            return SkillExecutionResult(
                success=False,
                mode=SkillMode.SHARED,
                summary=f"Could not activate Skill {invocation.definition.name}.",
                diagnostics=result.diagnostics,
            )
        kind = "skill_rebound" if result.rebound else "skill_activated"
        archive_errors = self.journal.append_skill_event(
            invocation.parent_session_id,
            kind,
            {
                "name": invocation.definition.name,
                "input": invocation.user_input,
                "source": invocation.definition.source.value,
                "fingerprint": invocation.definition.fingerprint,
            },
        )
        diagnostics = list(result.diagnostics)
        for error in archive_errors:
            from flickcode.skills.models import SkillDiagnostic

            diagnostics.append(
                SkillDiagnostic("warning", "archive", error.message, error.path, invocation.definition.name)
            )
        verb = "Rebound" if result.rebound else "Activated"
        return SkillExecutionResult(
            success=True,
            mode=SkillMode.SHARED,
            summary=f"{verb} shared Skill `{invocation.definition.name}` for this conversation.",
            diagnostics=tuple(diagnostics),
        )

    def _run_isolated(
        self,
        invocation: SkillInvocation,
        *,
        cwd: Path | None = None,
    ) -> SkillExecutionResult:
        definition = invocation.definition
        execution_root = Path(cwd).expanduser().resolve() if cwd is not None else self.project_root
        child_id = self.journal.new_pending()
        parent_config = self.provider_config_provider()
        child_config = replace(parent_config, model=definition.model or parent_config.model)
        metadata = ChildSessionMetadata(
            child_session_id=child_id,
            parent_session_id=invocation.parent_session_id,
            skill_name=definition.name,
            skill_source=definition.source,
            model=child_config.model,
            status="running",
        )
        self.journal.start_child(metadata)
        child_messages = self.turn_selector.select(
            self.messages_provider(), definition.history or 0
        )
        child_messages.append(Message(role="user", content=invocation.user_input))
        for message in child_messages:
            self.journal.append_child_message(child_id, message)

        try:
            provider = self.provider_factory(child_config)
            child_tools = self._clone_base_registry()
            child_loader = LoadSkillTool()
            child_tools.register_instance(child_loader)
            child_runtime = SkillRuntime(
                self.runtime.snapshot.catalog,
                child_tools,
                execution_root,
            )
            child_runtime.activate_for_child(definition, invocation.user_input)
            child_permission = self._child_permission_engine(execution_root)
            child_context_config = replace(
                self.context_config,
                storage_dir=(
                    execution_root
                    / ".tmp"
                    / "subagents"
                    / "context"
                    / child_id
                ),
            )
            child_executor = SkillExecutor(
                runtime=child_runtime,
                tools=child_tools,
                project_root=execution_root,
                journal=self.journal,
                messages_provider=lambda: child_messages,
                session_id_provider=lambda: child_id,
                provider_config_provider=lambda: child_config,
                context_config=child_context_config,
                agent_config=self.agent_config,
                prompt_builder=self.prompt_builder,
                permission_engine=child_permission,
                prompt_context_provider=self._child_prompt_context(child_runtime),
                provider_factory=self.provider_factory,
                diagnostic_callback=self.diagnostic_callback,
            )
            child_loader.bind(child_executor)
            manager = ContextManager(provider, child_context_config, session_id=child_id)

            def append_messages(additions: list[Message]) -> None:
                child_messages.extend(additions)
                for message in additions:
                    self.journal.append_child_message(child_id, message)

            loop = AgentLoop(
                provider=provider,
                tools=child_tools,
                mode=invocation.parent_agent_mode,
                config=self.agent_config,
                builder=self.prompt_builder,
                engine=child_permission,
                context_manager=manager,
                append_messages=append_messages,
                prompt_context_provider=self._child_prompt_context(child_runtime),
                tool_view_provider=lambda mode, iteration: child_runtime.tool_view(mode),
                cwd=execution_root,
            )
            stop_reason = "error"
            errors = []
            for event in loop.run(child_messages, thinking=child_config.thinking):
                if event.type == "error":
                    errors.append(event.content)
                elif event.type == "done":
                    try:
                        stop_reason = json.loads(event.content).get("stop_reason", "error")
                    except (TypeError, json.JSONDecodeError):
                        stop_reason = "error"
            final_text = next(
                (message.content for message in reversed(child_messages) if message.role == "assistant" and message.content),
                "",
            )
            success = stop_reason == "completed" and bool(final_text)
            if success:
                summary = final_text
            else:
                reason = self._sanitize(errors[-1], child_config) if errors else stop_reason
                summary = f"Isolated Skill `{definition.name}` did not complete: {reason}. Child session: {child_id}."
        except Exception as exc:
            success = False
            stop_reason = "error"
            summary = (
                f"Isolated Skill `{definition.name}` failed: "
                f"{self._sanitize(str(exc), child_config)}. Child session: {child_id}."
            )
        summary = self._limit_summary(summary, child_id)
        self.journal.finish_child(
            child_id,
            "completed" if success else "failed",
            summary,
            stop_reason,
        )
        return SkillExecutionResult(
            success=success,
            mode=SkillMode.ISOLATED,
            summary=summary,
            child_session_id=child_id,
        )

    def _clone_base_registry(self) -> ToolRegistry:
        result = ToolRegistry()
        for name in self.tools.list_tools():
            if name == "load_skill":
                continue
            tool = self.tools.get(name)
            if tool is not None:
                result.register_instance(tool)
        return result

    def _child_prompt_context(self, runtime: SkillRuntime) -> Callable[[AgentMode, int], dict]:
        def provide(mode: AgentMode, iteration: int) -> dict:
            context = (
                dict(self.prompt_context_provider(mode, iteration))
                if self.prompt_context_provider is not None
                else {}
            )
            context.update(runtime.prompt_context())
            context["isolated_skill_handoff"] = (
                "End with a concise handoff covering result, changes, failures, and next steps."
            )
            return context

        return provide

    def _child_permission_engine(self, cwd: Optional[Path] = None) -> Optional[PermissionEngine]:
        if self.permission_engine is None:
            return None
        project_root = Path(cwd).expanduser().resolve() if cwd is not None else self.project_root
        return PermissionEngine(
            mode=self.permission_engine.mode,
            project_root=project_root,
            hitl_callback=getattr(self.permission_engine, "_hitl_callback", None),
        )

    @staticmethod
    def _sanitize(message: str, config: ProviderConfig) -> str:
        result = message
        for secret in (config.api_key, config.base_url):
            if secret:
                result = result.replace(secret, "[redacted]")
        return result[:2048]

    @classmethod
    def _limit_summary(cls, summary: str, child_id: str) -> str:
        if len(summary) <= cls.SUMMARY_LIMIT:
            return summary
        suffix = f"\n[truncated; full child session: {child_id}]"
        return summary[: cls.SUMMARY_LIMIT - len(suffix)] + suffix
