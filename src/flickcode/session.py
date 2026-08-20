"""Session management for FlickCode conversations."""

from __future__ import annotations

import json
import threading
from dataclasses import replace
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Generator, List, Optional

from flickcode.agent import (
    AgentConfig,
    AgentEvent,
    AgentLoop,
    AgentMode,
    PlanContext,
)
from flickcode.context import ContextManager, ContextPreparation
from flickcode.permissions import PermissionEngine
from flickcode.permissions.models import PermissionMode
from flickcode.config import DEFAULT_CONFIG_DIR, load_config, ProviderConfig
from flickcode.memory import (
    InstructionLoader,
    MemoryRepository,
    MemoryUpdateClient,
    MemoryUpdateScheduler,
)
from flickcode.providers import (
    BaseProvider,
    Message,
    StreamEvent,
    create_provider,
)
from flickcode.prompt import SystemPromptBuilder
from flickcode.hooks import HookCatalog, HookEngine, HookEventName
from flickcode.hooks.prompt import HookPromptSection
from flickcode.prompt.sections import (
    ActionExecutionSection,
    ActiveSkillsSection,
    IdentitySection,
    ProjectInstructionsSection,
    ProjectMemorySection,
    SkillCatalogSection,
    IsolatedSkillHandoffSection,
    SystemConstraintsSection,
    TaskModeSection,
    TextOutputSection,
    ToneStyleSection,
    ToolUseSection,
    UserInstructionsSection,
    UserMemorySection,
)
from flickcode.sessions import ResumeResult, SessionJournal, SessionRecovery, SessionSummary
from flickcode.tools import ToolRegistry, create_default_registry
from flickcode.tools.cache import FileContentCache
from flickcode.mcp import MCPClientManager, MCPStartupReport
from flickcode.commands.builtin import build_default_registry
from flickcode.skills import (
    LoadSkillTool,
    SkillCatalog,
    SkillExecutor,
    SkillInvocationOrigin,
    SkillMode,
    SkillRuntime,
    SkillValidator,
)
from flickcode.skills.commands import SkillCommandManager
from flickcode.subagents import (
    AgentRoleCatalog,
    AgentRoleValidator,
    AgentTool,
    ChildRuntimeFactory,
    ForegroundControl,
    NotificationInbox,
    ParentRequestSnapshotStore,
    ProviderPool,
    SubAgentCoordinator,
    SubAgentResultStore,
    SubAgentRunner,
    SubAgentTaskManager,
)
from flickcode.subagents.models import ParentRequestSnapshot
from flickcode.subagents.notifications import serialize_notification
from flickcode.subagents.hooks import SubAgentHookScope
from flickcode.worktrees import WorktreeJanitor, WorktreeLifecycle
from flickcode.worktrees.config import WorktreeConfigLoader
from flickcode.worktrees.resources import WorkspacePromptFactory
from flickcode.teams.coordinator import TeamCoordinator
from flickcode.teams.policy import TeamToolPolicy
from flickcode.teams.tools import TeamLeadTool, TeamMessageTool, TeamTaskTool


@dataclass
class ResumeOutcome:
    """The observable result of one explicit resume attempt."""

    success: bool
    result: ResumeResult
    reason: str = ""
    compacted: bool = False
    diagnostics: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SessionStatusSnapshot:
    """Safe, read-only session state for local status commands."""

    provider_name: str
    model: str
    protocol: str
    active_session_id: str
    has_plan_context: bool
    permission_mode: str
    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    estimated_input_tokens: int
    request_budget_tokens: int
    safety_margin_tokens: int
    context_action: str
    context_diagnostic: str
    summary_path: Optional[str]
    result_paths: tuple[str, ...]
    mcp_registered_tools: int
    mcp_failed_servers: int
    diagnostics: tuple[str, ...]
    effective_skills: tuple[str, ...] = ()
    active_skills: tuple[str, ...] = ()
    skill_tools: tuple[str, ...] = ()
    skill_details: tuple[str, ...] = ()
    skill_generation: int = 0
    hooks_started: bool = False
    hook_active_rules: int = 0
    hook_skipped_rules: int = 0
    hook_project_trust: str = "pending"
    hook_once_count: int = 0
    hook_background_count: int = 0
    hook_overrides: tuple[str, ...] = ()
    hook_diagnostics: tuple[str, ...] = ()


class Session:
    """Manages a conversation session with an LLM provider.

    Maintains conversation history and orchestrates the flow
    between user input and provider responses — including
    tool-call interception, execution, and result re-integration.
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        provider_name: Optional[str] = None,
        tool_registry: Optional[ToolRegistry] = None,
        confirm_callback: Optional[Callable[[str, dict], bool]] = None,
        agent_config: Optional[AgentConfig] = None,
        context_manager: Optional[ContextManager] = None,
        permission_mode: PermissionMode = PermissionMode.DEFAULT,
        permission_callback: Optional[Callable[[str, dict], str]] = None,
    ):
        self.config = load_config(config_path)
        self.project_root = Path.cwd().resolve()
        self.provider_config = self._resolve_provider(provider_name)
        self.provider = create_provider(self.provider_config)
        self.tools = tool_registry or create_default_registry()
        self.mcp_manager = MCPClientManager(self.config.mcp_servers)
        self.mcp_startup_report = self.mcp_manager.start_all(self.tools)
        self.mcp_startup_errors = list(self.config.mcp_errors)
        self.messages: List[Message] = []
        self.confirm_callback = confirm_callback
        self.agent_config = agent_config or AgentConfig()
        self.context_manager = context_manager or ContextManager(
            self.provider,
            self.config.context,
        )
        self.plan_context: Optional[PlanContext] = None
        self._diagnostics: list[str] = []
        self._diagnostics_lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._started = False
        self._closed = False
        self._turn_counter = 0
        self.file_read_cache = FileContentCache()

        # Worktree services are deliberately lazy with respect to Git: a
        # normal non-Git project can still use shared SubAgents, while a
        # declared isolated role receives a clear lifecycle error at launch.
        self.worktree_config, worktree_diagnostics = WorktreeConfigLoader().load(
            self.project_root
        )
        for diagnostic in worktree_diagnostics:
            self._record_diagnostic(diagnostic.message)
        self.worktree_lifecycle = WorktreeLifecycle(
            self.project_root,
            config=self.worktree_config,
        )
        self.worktree_janitor = WorktreeJanitor(
            self.worktree_lifecycle,
            config=self.worktree_config,
        )

        self.instruction_bundle = InstructionLoader(self.config.memory).load(
            self.project_root
        )
        for diagnostic in self.instruction_bundle.diagnostics:
            self._record_diagnostic(diagnostic.message)
        self.project_memory = MemoryRepository(
            self.project_root / "memory",
            "project",
            index_max_lines=self.config.memory.index_max_lines,
            index_max_bytes=self.config.memory.index_max_bytes,
        )
        self.user_memory = MemoryRepository(
            DEFAULT_CONFIG_DIR / "memory",
            "user",
            index_max_lines=self.config.memory.index_max_lines,
            index_max_bytes=self.config.memory.index_max_bytes,
        )
        self.journal = SessionJournal(
            self.project_root,
            expiry_days=self.config.memory.session_expiry_days,
        )
        self.active_session_id = self.journal.new_pending()
        for diagnostic in self.journal.prune_expired(self.active_session_id):
            self._record_diagnostic(diagnostic.message)
        self.memory_scheduler = MemoryUpdateScheduler(
            MemoryUpdateClient(self.provider),
            self.user_memory,
            self.project_memory,
            self._record_diagnostic,
        )

        # Hook configuration is prepared during construction but actions do
        # not run until start(), after an interactive trust callback exists.
        self.hook_catalog = HookCatalog(self.project_root, DEFAULT_CONFIG_DIR)
        self.hook_engine = HookEngine(
            self.hook_catalog,
            self.project_root,
            diagnostic_callback=self._record_diagnostic,
        )

        # ── Permission Engine ─────────────────────────────────────────────
        self.permission_mode = permission_mode
        self.permission_engine = PermissionEngine(
            mode=permission_mode,
            project_root=self.project_root,
            hitl_callback=permission_callback,
        )

        # ── System Prompt Builder ─────────────────────────────────────────
        self.prompt_builder = self._create_prompt_builder()
        self.project_metadata = self._collect_project_metadata()

        # ── Skill system ────────────────────────────────────────────────
        self.command_registry = build_default_registry()
        self.load_skill_tool = LoadSkillTool()
        self.tools.register_instance(self.load_skill_tool)
        self.agent_tool = AgentTool()
        self.tools.register_instance(self.agent_tool)
        self.skill_catalog = SkillCatalog(
            self.project_root / ".flickcode" / "skills",
            DEFAULT_CONFIG_DIR / "skills",
            Path(__file__).parent / "skills" / "builtins",
        )
        initial_catalog = self.skill_catalog.prepare_refresh()
        SkillValidator().validate_startup(
            initial_catalog.current,
            self.tools.list_tools(),
            self.command_registry.stable_names(),
        )
        self.skill_catalog.commit(initial_catalog)
        for diagnostic in self.skill_catalog.snapshot.diagnostics:
            self._record_diagnostic(diagnostic.message)
        self.skill_runtime = SkillRuntime(
            self.skill_catalog.snapshot,
            self.tools,
            self.project_root,
            system_tool_names=("load_skill", "agent"),
        )
        self.skill_executor = SkillExecutor(
            runtime=self.skill_runtime,
            tools=self.tools,
            project_root=self.project_root,
            journal=self.journal,
            messages_provider=lambda: self.messages,
            session_id_provider=lambda: self.active_session_id,
            provider_config_provider=lambda: self.provider_config,
            context_config=self.config.context,
            agent_config=self.agent_config,
            prompt_builder=self.prompt_builder,
            permission_engine=self.permission_engine,
            prompt_context_provider=self._prompt_context,
            refresh_callback=self.refresh_skills,
            diagnostic_callback=self._record_diagnostic,
        )
        self.load_skill_tool.bind(self.skill_executor)
        self.skill_command_manager = SkillCommandManager(self.command_registry)
        self.skill_command_manager.commit(
            self.skill_command_manager.prepare(self.skill_catalog.snapshot)
        )

        # ── SubAgent delegation ───────────────────────────────────────
        subagent_config = self.config.subagents
        self.subagent_provider_pool = ProviderPool(provider_factory=create_provider)
        self.subagent_provider_pool.seed(self.provider_config, self.provider)
        self.subagent_snapshots = ParentRequestSnapshotStore()
        self.subagent_notifications = NotificationInbox()
        result_root = Path(subagent_config.result_storage_dir)
        if not result_root.is_absolute():
            result_root = self.project_root / result_root
        self.subagent_result_store = SubAgentResultStore(
            inline_chars=subagent_config.result_inline_chars,
            max_chars=subagent_config.result_max_chars,
            base_dir=result_root,
        )
        self.subagent_foreground = ForegroundControl()
        plugin_roots = tuple(
            p if p.is_absolute() else self.project_root / p
            for p in map(Path, subagent_config.plugin_role_dirs)
        )
        self.agent_role_catalog = AgentRoleCatalog(
            self.project_root / ".flickcode" / "agents",
            DEFAULT_CONFIG_DIR / "agents",
            Path(__file__).parent / "subagents" / "builtins",
            plugin_roots,
        )
        role_candidate = self.agent_role_catalog.prepare_refresh()
        validated_roles = AgentRoleValidator().validate(
            role_candidate.current,
            self.tools.list_tools(),
        )
        self.agent_role_catalog.commit(role_candidate, validated_roles)
        for diagnostic in validated_roles.diagnostics:
            self._record_diagnostic(diagnostic.message)
        runtime_factory = ChildRuntimeFactory(
            self.project_root,
            self.subagent_provider_pool,
            self.config.context,
            hook_scope_factory=lambda spec, workspace: SubAgentHookScope(
                self.hook_engine, spec, workspace
            ),
            prompt_factory=WorkspacePromptFactory(
                memory_config=self.config.memory,
                user_root=DEFAULT_CONFIG_DIR,
            ),
        )
        runner = SubAgentRunner(runtime_factory, lifecycle=self.worktree_lifecycle)
        self.subagent_tasks = SubAgentTaskManager(
            runner.run,
            self.subagent_notifications,
            self.subagent_result_store,
            self.subagent_foreground,
            max_workers=subagent_config.max_workers,
            max_pending=subagent_config.max_pending,
            foreground_timeout=subagent_config.foreground_timeout_seconds,
            event_callback=self._dispatch_subagent_event,
        )
        runner.bind_workspace_callback(self.subagent_tasks.record_workspace)
        self.subagent_runner = runner
        self.subagent_coordinator = SubAgentCoordinator(
            roles=self.agent_role_catalog,
            snapshots=self.subagent_snapshots,
            runtime_factory=runtime_factory,
            tasks=self.subagent_tasks,
            config=subagent_config,
            session_id_provider=lambda: self.active_session_id,
            provider_provider=lambda: self.provider_config,
            providers={provider.name: provider for provider in self.config.providers},
            tools_provider=lambda: self.skill_runtime.tool_view(AgentMode.FULL),
            permission_provider=lambda: self.permission_mode,
            thinking_provider=lambda: self.thinking_enabled,
            max_turns_provider=lambda: self.agent_config.max_iterations,
        )
        self.agent_tool.bind(self.subagent_coordinator, self.refresh_agent_roles)

        # ── Durable team collaboration ──────────────────────────────
        # Team tools are deliberately not registered in the global ToolRegistry:
        # they are added as extras only after an explicit Lead activation.
        self.team_coordinator = TeamCoordinator(
            self.config.teams,
            self.project_root,
            diagnostic_callback=self._record_diagnostic,
            member_runner=self._run_team_member,
        )
        self.team_policy = TeamToolPolicy()
        self.team_lead_tool = TeamLeadTool(self.team_coordinator)
        self.team_tasks_tool = TeamTaskTool(self.team_coordinator)
        self.team_message_tool = TeamMessageTool(self.team_coordinator)

    def close(self) -> None:
        """Close lifecycle Hooks and external resources; idempotent."""
        with getattr(self, "_lifecycle_lock", threading.RLock()):
            if getattr(self, "_closed", False):
                return
            self._closed = True
        team_coordinator = getattr(self, "team_coordinator", None)
        if team_coordinator is not None:
            try:
                team_coordinator.leave()
            except Exception as exc:
                self._record_diagnostic(f"Team shutdown failed: {exc}")
        hook_engine = getattr(self, "hook_engine", None)
        if hook_engine is not None and getattr(self, "_started", False):
            hook_engine.end_session(self.active_session_id, "close")
            hook_engine.dispatch(
                hook_engine.make_event(HookEventName.SYSTEM_STOPPING)
            )
        if hook_engine is not None:
            hook_engine.close()
        janitor = getattr(self, "worktree_janitor", None)
        if janitor is not None:
            janitor.close()
        manager = getattr(self, "mcp_manager", None)
        if manager is not None:
            manager.close()
        scheduler = getattr(self, "memory_scheduler", None)
        if scheduler is not None:
            scheduler.shutdown()
        subagent_tasks = getattr(self, "subagent_tasks", None)
        if subagent_tasks is not None:
            timeout = getattr(getattr(self, "config", None), "subagents", None)
            subagent_tasks.close(getattr(timeout, "shutdown_timeout_seconds", 5.0))
        inbox = getattr(self, "subagent_notifications", None)
        if inbox is not None:
            inbox.close()
        result_store = getattr(self, "subagent_result_store", None)
        if result_store is not None:
            result_store.close()
        provider_pool = getattr(self, "subagent_provider_pool", None)
        if provider_pool is not None:
            provider_pool.close()

    def start(self, hook_trust_callback=None) -> None:
        """Activate Hooks after UI callbacks are available."""
        lifecycle_lock = getattr(self, "_lifecycle_lock", None)
        if lifecycle_lock is None:
            lifecycle_lock = threading.RLock()
            self._lifecycle_lock = lifecycle_lock
        with lifecycle_lock:
            if getattr(self, "_started", False) or getattr(self, "_closed", False):
                return
            hook_engine = getattr(self, "hook_engine", None)
            if hook_engine is None:
                self._started = True
                return
            hook_engine.start(hook_trust_callback)
            janitor = getattr(self, "worktree_janitor", None)
            if janitor is not None:
                janitor.start()
            self._started = True
        hook_engine.dispatch(
            hook_engine.make_event(HookEventName.SYSTEM_STARTED)
        )
        hook_engine.begin_session(self.active_session_id, resumed=False)

    @staticmethod
    def _create_prompt_builder() -> SystemPromptBuilder:
        """Create the default SystemPromptBuilder with all standard sections."""
        builder = SystemPromptBuilder()
        for sec in [
            ProjectInstructionsSection(),
            UserInstructionsSection(),
            ActiveSkillsSection(),
            SkillCatalogSection(),
            IsolatedSkillHandoffSection(),
            IdentitySection(),
            SystemConstraintsSection(),
            TaskModeSection(),
            ActionExecutionSection(),
            ToolUseSection(),
            ToneStyleSection(),
            TextOutputSection(),
            ProjectMemorySection(),
            UserMemorySection(),
            HookPromptSection(),
        ]:
            builder.add_section(sec)
        return builder

    def _record_diagnostic(self, message: str) -> None:
        lock = getattr(self, "_diagnostics_lock", None)
        if lock is None:
            self._diagnostics = getattr(self, "_diagnostics", [])
            self._diagnostics.append(message)
            return
        with lock:
            self._diagnostics.append(message)

    def drain_diagnostics(self) -> list[str]:
        """Return non-fatal archive, memory, and instruction diagnostics."""
        lock = getattr(self, "_diagnostics_lock", None)
        if lock is None:
            items = list(getattr(self, "_diagnostics", []))
            self._diagnostics = []
            return items
        with lock:
            items = list(self._diagnostics)
            self._diagnostics.clear()
            return items

    def _capture_parent_request_snapshot(
        self,
        *,
        messages: list[Message],
        system_prompt: Optional[str],
        tool_view,
        mode: AgentMode,
        iteration: int,
    ) -> None:
        """Publish the exact stable request prefix available to Fork agents."""
        store = getattr(self, "subagent_snapshots", None)
        if store is None:
            return
        store.put(ParentRequestSnapshot(
            session_id=self.active_session_id,
            turn_number=getattr(self, "_turn_counter", 0),
            mode=mode,
            messages=tuple(messages),
            system_prompt=system_prompt,
            tool_view=tool_view,
            provider_config=self.provider_config,
            thinking=self.thinking_enabled,
        ))

    def _dispatch_subagent_event(self, event: str, snapshot) -> None:
        hook_engine = getattr(self, "hook_engine", None)
        if hook_engine is None:
            return
        names = {
            "started": HookEventName.AGENT_STARTED,
            "backgrounded": HookEventName.AGENT_BACKGROUNDED,
            "completed": HookEventName.AGENT_COMPLETED,
            "limited": HookEventName.AGENT_LIMITED,
            "failed": HookEventName.AGENT_FAILED,
            "cancelled": HookEventName.AGENT_CANCELLED,
        }
        name = names.get(event)
        if name is None:
            return
        hook_engine.dispatch(hook_engine.make_event(
            name,
            session_id=snapshot.parent_session_id,
            session_state="active",
            agent_task_id=snapshot.task_id,
            agent_parent_task_id=snapshot.parent_session_id,
            agent_kind="subagent",
            agent_invocation_type=snapshot.invocation_type.value,
            agent_role_name=snapshot.role_name or "",
            agent_state=snapshot.state.value,
            agent_background=snapshot.background,
            agent_stop_reason=snapshot.stop_reason.value if snapshot.stop_reason else "",
            agent_isolation=snapshot.workspace.isolation.value,
            agent_project_root=str(snapshot.workspace.path) if snapshot.workspace.path else str(self.project_root),
            agent_worktree_root=(
                str(snapshot.workspace.worktree_root)
                if snapshot.workspace.worktree_root
                else str(self.project_root)
            ),
            agent_branch=snapshot.workspace.branch,
        ))

    def refresh_agent_roles(self):
        """Atomically refresh and validate all role definition sources."""
        catalog = self.agent_role_catalog
        candidate = catalog.prepare_refresh()
        checked = AgentRoleValidator().validate(candidate.current, self.tools.list_tools())
        snapshot = catalog.commit(candidate, checked)
        for diagnostic in snapshot.diagnostics:
            self._record_diagnostic(diagnostic.message)
        return snapshot

    def status_snapshot(self) -> SessionStatusSnapshot:
        """Return safe session/context state without mutating the session."""
        state = self.context_manager.state
        diagnostic = state.last_diagnostic
        provider = self.provider_config
        report = getattr(self, "mcp_startup_report", None)
        diagnostics_lock = getattr(self, "_diagnostics_lock", None)
        if diagnostics_lock is None:
            diagnostics = tuple(getattr(self, "_diagnostics", []))
        else:
            with diagnostics_lock:
                diagnostics = tuple(self._diagnostics)
        permission_mode = getattr(self.permission_mode, "value", str(self.permission_mode))
        hook_status = getattr(self, "hook_engine", None)
        hook_status = hook_status.status_snapshot() if hook_status is not None else None
        return SessionStatusSnapshot(
            provider_name=provider.name,
            model=provider.model,
            protocol=provider.protocol,
            active_session_id=self.active_session_id,
            has_plan_context=self.plan_context is not None,
            permission_mode=permission_mode,
            input_tokens=state.last_input_tokens or 0,
            output_tokens=state.last_output_tokens,
            thinking_tokens=state.last_thinking_tokens,
            estimated_input_tokens=diagnostic.estimated_input_tokens,
            request_budget_tokens=diagnostic.request_budget_tokens,
            safety_margin_tokens=diagnostic.safety_margin_tokens,
            context_action=diagnostic.action,
            context_diagnostic=diagnostic.message,
            summary_path=str(diagnostic.summary_path) if diagnostic.summary_path else None,
            result_paths=tuple(str(path) for path in diagnostic.stored_paths),
            mcp_registered_tools=len(getattr(report, "registered_tools", [])) if report else 0,
            mcp_failed_servers=(len(getattr(report, "failed_servers", [])) if report else 0)
            + len(getattr(self, "mcp_startup_errors", [])),
            diagnostics=diagnostics,
            effective_skills=tuple(sorted(getattr(self, "skill_runtime", None).snapshot.catalog.effective))
            if getattr(self, "skill_runtime", None) is not None else (),
            active_skills=tuple(
                item.definition.name for item in getattr(self, "skill_runtime", None).snapshot.active_skills
            ) if getattr(self, "skill_runtime", None) is not None else (),
            skill_tools=tuple(sorted(getattr(self, "skill_runtime", None).snapshot.allowed_tool_names))
            if getattr(self, "skill_runtime", None) is not None else (),
            skill_details=tuple(
                f"{name}:{definition.source.value}"
                for name, definition in sorted(getattr(self, "skill_runtime", None).snapshot.catalog.effective.items())
            ) if getattr(self, "skill_runtime", None) is not None else (),
            skill_generation=getattr(self, "skill_runtime", None).snapshot.catalog.generation
            if getattr(self, "skill_runtime", None) is not None else 0,
            hooks_started=hook_status.started if hook_status else False,
            hook_active_rules=hook_status.active_rules if hook_status else 0,
            hook_skipped_rules=hook_status.skipped_rules if hook_status else 0,
            hook_project_trust=hook_status.project_trust if hook_status else "pending",
            hook_once_count=hook_status.once_count if hook_status else 0,
            hook_background_count=hook_status.background_count if hook_status else 0,
            hook_overrides=hook_status.overrides if hook_status else (),
            hook_diagnostics=hook_status.diagnostics if hook_status else (),
        )

    def _prompt_context(self, mode=None, iteration=None) -> dict:
        """Read bounded indexes for every request without persisting them."""
        bundle = getattr(self, "instruction_bundle", None)
        project_text = bundle.project_text if bundle is not None else ""
        user_text = bundle.user_text if bundle is not None else ""
        project_index = ""
        user_index = ""
        project_repository = getattr(self, "project_memory", None)
        if project_repository is not None:
            project_index, errors = project_repository.read_index()
            for diagnostic in errors:
                self._record_diagnostic(diagnostic.message)
        user_repository = getattr(self, "user_memory", None)
        if user_repository is not None:
            user_index, errors = user_repository.read_index()
            for diagnostic in errors:
                self._record_diagnostic(diagnostic.message)
        context = {
            "project_instructions": project_text,
            "user_instructions": user_text,
            "project_memory": project_index,
            "user_memory": user_index,
            "hook_prompts": (
                self.hook_engine.persistent_prompts()
                if getattr(self, "hook_engine", None) is not None else ()
            ),
        }
        runtime = getattr(self, "skill_runtime", None)
        previous_runtime_snapshot = runtime.snapshot if runtime is not None else None
        if runtime is not None:
            context.update(runtime.prompt_context())
        return context

    def _build_prompt(self) -> tuple[Optional[str], list[Message]]:
        builder = getattr(self, "prompt_builder", None)
        if builder is None:
            return None, []
        context = self._prompt_context()
        context["project_metadata"] = getattr(self, "project_metadata", {})
        return builder.build(context)

    def _append_history_messages(self, additions: list[Message]) -> None:
        """Keep memory history even when append-only archive writes fail."""
        if not additions:
            return
        self.messages.extend(additions)
        journal = getattr(self, "journal", None)
        active_session_id = getattr(self, "active_session_id", None)
        if journal is None or not active_session_id:
            return
        for message in additions:
            for diagnostic in journal.append_message(active_session_id, message):
                self._record_diagnostic(diagnostic.message)

    def list_sessions(self) -> list[SessionSummary]:
        journal = getattr(self, "journal", None)
        if journal is None:
            return []
        summaries, diagnostics = journal.list_sessions()
        for diagnostic in diagnostics:
            self._record_diagnostic(diagnostic.message)
        return summaries

    def refresh_skills(self) -> None:
        """Prepare and commit Catalog, Runtime, and dynamic commands together."""
        catalog_candidate = self.skill_catalog.prepare_refresh()
        validation = SkillValidator().diagnostics(
            catalog_candidate.current,
            self.tools.list_tools(),
            self.command_registry.stable_names(),
        )
        if validation:
            from flickcode.skills.validation import SkillStartupError

            raise SkillStartupError(validation)
        runtime_candidate = self.skill_runtime.prepare_reconcile(catalog_candidate)
        command_candidate = self.skill_command_manager.prepare(catalog_candidate.current)
        before = {item.definition.name for item in self.skill_runtime.snapshot.active_skills}
        after = {item.definition.name for item in runtime_candidate.active_skills}
        self.skill_catalog.commit(catalog_candidate)
        self.skill_runtime.commit(runtime_candidate)
        self.skill_command_manager.commit(command_candidate)
        for diagnostic in runtime_candidate.diagnostics:
            self._record_diagnostic(diagnostic.message)
        for name in sorted(before - after):
            for diagnostic in self.journal.append_skill_event(
                self.active_session_id,
                "skill_deactivated",
                {"name": name},
            ):
                self._record_diagnostic(diagnostic.message)

    def refresh_skills_safely(self) -> None:
        try:
            self.refresh_skills()
        except Exception as exc:
            self._record_diagnostic(f"Skill refresh failed; using previous snapshot: {exc}")

    def invoke_skill(
        self,
        name: str,
        user_input: str = "",
        mode: AgentMode = AgentMode.FULL,
    ) -> Generator[AgentEvent, None, None]:
        """Run one dynamic slash command through the same Skill executor."""
        result = self.skill_executor.invoke(
            name,
            user_input,
            origin=SkillInvocationOrigin.SLASH,
            parent_mode=mode,
        )
        for diagnostic in result.diagnostics:
            self._record_diagnostic(diagnostic.message)
        if not result.success:
            yield AgentEvent("error", result.summary)
            yield AgentEvent(
                "done",
                json.dumps({"stop_reason": "error", "usage": {}}),
            )
            return
        if result.mode is SkillMode.SHARED:
            yield AgentEvent("progress", result.summary)
            yield from self.agent_chat(user_input, mode=mode)
            return

        invocation_text = f"/{name}" + (f" {user_input}" if user_input else "")
        self._append_history_messages(
            [
                Message(role="user", content=invocation_text),
                Message(role="assistant", content=result.summary),
            ]
        )
        yield AgentEvent("text", result.summary)
        yield AgentEvent(
            "done",
            json.dumps({
                "stop_reason": "completed",
                "child_session_id": result.child_session_id,
                "usage": {},
            }),
        )

    def reset_session(self) -> None:
        """Archive the reset boundary and start a clean conversation identity."""
        old_session_id = self.active_session_id
        hook_engine = getattr(self, "hook_engine", None)
        if getattr(self, "_started", False) and hook_engine is not None:
            hook_engine.end_session(old_session_id, "reset")
        next_session_id = self.journal.new_pending()
        for diagnostic in self.journal.append_skill_event(
            old_session_id,
            "session_reset",
            {"next_session": next_session_id},
        ):
            self._record_diagnostic(diagnostic.message)
        self.messages = []
        self.plan_context = None
        snapshots = getattr(self, "subagent_snapshots", None)
        if snapshots is not None:
            snapshots.reset()
        self.skill_runtime.clear_active()
        self.active_session_id = next_session_id
        self.context_manager = ContextManager(
            self.provider,
            self.config.context,
            session_id=self.active_session_id,
        )
        if getattr(self, "_started", False) and hook_engine is not None:
            hook_engine.begin_session(self.active_session_id, resumed=False)

    def resume_session(self, session_id: str) -> ResumeOutcome:
        """Restore exactly one explicit managed archive without partial mutation."""
        journal = getattr(self, "journal", None)
        if journal is None:
            return ResumeOutcome(False, ResumeResult(), "Session archives are unavailable")
        memory_config = getattr(getattr(self, "config", None), "memory", None)
        gap_days = getattr(memory_config, "resume_time_gap_days", 7)
        result = SessionRecovery(journal, time_gap_days=gap_days).load(session_id)
        if not result.messages:
            reason = "No recoverable messages were found"
            if result.diagnostics:
                reason = result.diagnostics[-1].message
            return ResumeOutcome(False, result, reason)

        if hasattr(self, "skill_catalog"):
            try:
                self.refresh_skills()
            except Exception as exc:
                return ResumeOutcome(False, result, f"Skill refresh failed: {exc}")
        runtime = getattr(self, "skill_runtime", None)
        if runtime is not None:
            runtime.clear_active()
            for archived in result.skill_activations:
                activation = runtime.activate_shared(archived.name, archived.user_input)
                if not activation.success:
                    self._record_diagnostic(
                        f"Could not restore Skill {archived.name!r}; its current definition is unavailable or isolated."
                    )
                elif (
                    activation.active_skill is not None
                    and activation.active_skill.definition.source.value != archived.recorded_source
                ):
                    self._record_diagnostic(
                        f"Restored Skill {archived.name!r} from current "
                        f"{activation.active_skill.definition.source.value} source instead of archived "
                        f"{archived.recorded_source} source."
                    )
        stable_prompt, extra_messages = self._build_prompt()
        if runtime is not None:
            tools = runtime.tool_view(AgentMode.FULL).to_api_tools(api_format=self._api_format)
        else:
            tools = self.tools.to_api_tools(api_format=self._api_format)
        temporary_messages = list(result.messages)
        temporary_manager = ContextManager(
            self.provider,
            self.context_manager.config,
            session_id=session_id,
        )
        preparation = temporary_manager.prepare_before_request(
            temporary_messages,
            tools=tools,
            system_prompt=stable_prompt,
            transient_messages=extra_messages,
        )
        if preparation.blocked:
            if runtime is not None and previous_runtime_snapshot is not None:
                runtime.restore_snapshot(previous_runtime_snapshot)
            message = "Restored history exceeds the context budget"
            return ResumeOutcome(
                False,
                result,
                message,
                compacted=preparation.changed,
                diagnostics=list(preparation.diagnostic.errors),
            )
        self.messages = temporary_messages
        hook_engine = getattr(self, "hook_engine", None)
        if getattr(self, "_started", False) and hook_engine is not None:
            hook_engine.end_session(self.active_session_id, "resume_switch")
        self.context_manager = temporary_manager
        self.active_session_id = session_id
        self.plan_context = None
        for diagnostic in journal.mark_resumed(session_id):
            self._record_diagnostic(diagnostic.message)
        if getattr(self, "_started", False) and hook_engine is not None:
            hook_engine.begin_session(self.active_session_id, resumed=True)
        return ResumeOutcome(
            True,
            result,
            compacted=preparation.changed,
            diagnostics=list(preparation.diagnostic.errors),
        )

    @staticmethod
    def _collect_project_metadata() -> dict:
        """Read lightweight project metadata from the current directory.

        Returns a dict with ``name``, ``version``, ``python`` when the
        project file exists, or an empty dict otherwise.
        """
        meta: dict[str, str] = {}
        cwd = Path.cwd()

        # Try pyproject.toml
        pyproject = cwd / "pyproject.toml"
        if pyproject.exists():
            try:
                text = pyproject.read_text(encoding="utf-8")
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("name = "):
                        meta["name"] = stripped.strip("name = ").strip("\"'")
                    elif stripped.startswith("version = "):
                        meta["version"] = stripped.strip("version = ").strip("\"'")
                    elif stripped.startswith("requires-python = "):
                        meta["python"] = stripped.strip("requires-python = ").strip("\"'")
            except Exception:
                pass

        # Try package.json if no name found yet
        if "name" not in meta:
            pkg_json = cwd / "package.json"
            if pkg_json.exists():
                try:
                    data = json.loads(pkg_json.read_text(encoding="utf-8"))
                    if "name" in data:
                        meta["name"] = data["name"]
                    if "version" in data:
                        meta["version"] = data["version"]
                except Exception:
                    pass

        return meta

    def _resolve_provider(
        self, provider_name: Optional[str]
    ) -> ProviderConfig:
        """Find the provider config matching the given name or use the first."""
        if provider_name:
            for p in self.config.providers:
                if p.name == provider_name:
                    return p
            available = [p.name for p in self.config.providers]
            raise ValueError(
                f"Provider '{provider_name}' not found. "
                f"Available providers: {', '.join(available)}"
            )
        return self.config.providers[0]

    @property
    def current_provider_name(self) -> str:
        """Get the name of the currently active provider."""
        return self.provider_config.name

    @property
    def thinking_enabled(self) -> bool:
        """Check if extended thinking is enabled for this session."""
        return (
            self.provider_config.thinking
            and self.provider_config.protocol == "anthropic"
        )

    @property
    def _api_format(self) -> str:
        """Return the tool-definition format expected by the active provider."""
        return self.provider_config.protocol  # "anthropic" | "openai"

    def activate_team(self, name: str, *, create: bool = False) -> dict:
        """Explicitly bind this Session as the Lead of a durable team."""
        lead_name = "lead-" + self.active_session_id[:8]
        team = self.team_coordinator.activate_lead(
            name,
            lead_name=lead_name,
            create=create,
            lead_workdir=self.project_root,
        )
        return team.to_dict()

    def leave_team(self) -> None:
        self.team_coordinator.leave()

    def team_status(self) -> dict:
        return self.team_coordinator.status()

    def team_coordinator_state(self) -> dict:
        return self.team_coordinator.coordinator_state()

    def _run_team_member(self, member, task_id: str):
        """Run one member task with a fresh AgentLoop and member identity."""
        task = self.team_coordinator.tasks.get_task(task_id)
        provider = create_provider(self.provider_config)
        context_config = replace(
            self.config.context,
            storage_dir=Path(member.context_path).parent / "agent-context",
        )
        context_manager = ContextManager(provider, context_config, session_id=member.member_id + "-" + task_id)
        member_tasks = TeamTaskTool(self.team_coordinator, actor_id=member.member_id)
        member_messages = TeamMessageTool(self.team_coordinator, actor_id=member.member_id)
        base_names = set(self.tools.list_tools()) - {"agent", "load_skill"}
        view = self.tools.snapshot(base_names, extras=(member_tasks, member_messages))
        messages = [Message(role="user", content=task.description or task.title)]
        from flickcode.subagents.runtime import FixedPromptBuilder
        role_prompt = (
            f"You are the durable FlickCode team member {member.name!r}.\n"
            f"Your team role is {member.role!r}.\n"
            "Work only on the assigned task, use team_tasks and team_message for coordination, "
            "and report a concise handoff when finished."
        )
        loop = AgentLoop(
            provider=provider,
            tools=view,
            mode=AgentMode.FULL,
            config=self.agent_config,
            builder=FixedPromptBuilder(role_prompt),
            project_metadata=self.project_metadata,
            engine=PermissionEngine(mode=self.permission_mode, project_root=member.workdir, hitl_callback=None),
            context_manager=context_manager,
            cwd=member.workdir,
            file_cache=FileContentCache(),
            non_interactive_permissions=True,
        )
        parts = []
        error = ""
        for event in loop.run(messages, thinking=self.thinking_enabled):
            if event.type == "text":
                parts.append(event.content)
            elif event.type == "error":
                error = event.content
        return "".join(parts)[-4096:], error

    def run_team_member(self, team_name: str, member_id: str) -> None:
        """Run the mailbox loop used by an isolated terminal member process."""
        self.team_coordinator.activate_member(team_name, member_id)
        mailbox = self.team_coordinator.mailbox
        runtime = self.team_coordinator.runtime
        try:
            while not getattr(self, "_closed", False):
                for message in mailbox.list_messages(member_id, unread_only=True):
                    mailbox.mark_read(member_id, [message.message_id])
                    if message.kind == "approval.decision":
                        self.team_coordinator.handle_approval(member_id, message)
                        continue
                    task_id = message.payload.get("task_id")
                    if task_id:
                        runtime.start_or_resume(member_id, task_id=task_id, plan=str(message.payload.get("plan", "")))
                import time
                time.sleep(0.2)
        except KeyboardInterrupt:
            self._record_diagnostic(f"Team member {member_id} stopped by user")

    def _tool_view_for_mode(self, mode: AgentMode):
        runtime = getattr(self, "skill_runtime", None)
        if runtime is not None:
            base = runtime.tool_view(mode)
        else:
            base = self.tools.snapshot() if hasattr(self, "tools") else None
            if base is None:
                raise RuntimeError("Session has no tool registry")
        coordinator = getattr(self, "team_coordinator", None)
        if coordinator is None or not coordinator.active:
            return base
        names = set(base.list_tools())
        if coordinator.coordinator_enabled:
            names -= {"write_file", "edit_file"}
        selected = base.snapshot(names)
        return selected.snapshot(
            selected.list_tools(),
            extras=(self.team_lead_tool, self.team_tasks_tool, self.team_message_tool),
        )

    # ── Agent Loop ───────────────────────────────────────────────────

    def agent_chat(
        self,
        user_input: str,
        mode: AgentMode = AgentMode.FULL,
    ) -> Generator[AgentEvent, None, None]:
        """Run an Agent Loop for the given user input.

        Unlike ``chat()`` which handles a single round, this method
        gives the model full ReAct autonomy: it can call tools, receive
        results, and iterate until the task is done.

        Args:
            user_input: The user's message.
            mode: Agent mode (FULL, PLAN, or EXECUTE).

        Yields:
            AgentEvent — text, tool_call, tool_result, usage, progress,
                         done, or error.
        """
        if not getattr(self, "_started", False):
            self.start()
        hook_engine = getattr(self, "hook_engine", None)
        self._turn_counter = getattr(self, "_turn_counter", 0) + 1
        if hook_engine is not None:
            hook_engine.set_turn(self._turn_counter, mode.value)
            hook_engine.dispatch(
                hook_engine.make_event(
                HookEventName.TURN_STARTED,
                session_state="active",
            )
            )
            hook_engine.dispatch(
                hook_engine.make_event(
                HookEventName.MESSAGE_USER_ACCEPTED,
                message_role="user",
                message_content=user_input,
                message_stage="accepted",
            )
            )

        if hasattr(self, "skill_catalog"):
            try:
                self.refresh_skills()
            except Exception as exc:
                self._record_diagnostic(f"Skill refresh failed; using previous snapshot: {exc}")

        # Completed background work is injected only at a parent request
        # boundary, so it cannot mutate an in-flight provider request.
        inbox = getattr(self, "subagent_notifications", None)
        if inbox is not None:
            self._append_history_messages([
                Message(role="user", content=serialize_notification(item))
                for item in inbox.drain()
            ])

        # Add user message to history
        self._append_history_messages([Message(role="user", content=user_input)])

        loop = AgentLoop(
            provider=self.provider,
            tools=self.tools,
            mode=mode,
            config=getattr(self, "agent_config", AgentConfig()),
            builder=getattr(self, "prompt_builder", None),
            project_metadata=getattr(self, "project_metadata", {}),
            engine=getattr(self, "permission_engine", None),
            context_manager=self.context_manager,
            append_messages=self._append_history_messages,
            prompt_context_provider=self._prompt_context if hasattr(self, "instruction_bundle") else None,
            tool_view_provider=(
                lambda current_mode, iteration: self._tool_view_for_mode(current_mode)
            ) if hasattr(self, "skill_runtime") else None,
            hook_engine=hook_engine,
            request_snapshot_callback=self._capture_parent_request_snapshot,
            # A few lightweight embedding/tests construct Session via
            # ``__new__``; retain their legacy behavior while normal
            # production sessions always provide these explicit values.
            cwd=getattr(self, "project_root", Path.cwd()),
            file_cache=getattr(self, "file_read_cache", None),
        )

        # Track the messages snapshot before /plan for PlanContext
        messages_before_plan: list[Message] = []
        if mode == AgentMode.PLAN:
            messages_before_plan = list(self.messages[:-1])  # exclude current user msg

        completed = False
        final_stop_reason = "error"
        for event in loop.run(self.messages, thinking=self.thinking_enabled):
            yield event
            if event.type == "done":
                try:
                    final_stop_reason = json.loads(event.content).get("stop_reason", "error")
                    completed = final_stop_reason == "completed"
                except (TypeError, json.JSONDecodeError):
                    completed = False
        if hook_engine is not None:
            hook_engine.dispatch(
                hook_engine.make_event(
                HookEventName.TURN_ENDED,
                turn_stop_reason=final_stop_reason,
            )
            )
        if completed:
            scheduler = getattr(self, "memory_scheduler", None)
            if scheduler is not None:
                scheduler.submit(self.messages)

        # After /plan completes, capture PlanContext
        if mode == AgentMode.PLAN:
            # The last assistant message should contain the plan
            plan_content = ""
            for msg in reversed(self.messages):
                if msg.role == "assistant" and msg.content:
                    plan_content = msg.content
                    break
            # Exclude the tool-call messages for the clean plan context
            plan_msgs = list(self.messages[len(messages_before_plan):])
            self.plan_context = PlanContext(
                plan_content=plan_content,
                messages_before_plan=messages_before_plan,
                plan_messages=plan_msgs,
            )

    def set_plan_context(self, context: Optional[PlanContext]) -> None:
        """Set or clear the Plan Context."""
        self.plan_context = context

    def compact_context(self) -> ContextPreparation:
        """Manually compact persisted conversation history for ``/compact``."""
        runtime = getattr(self, "skill_runtime", None)
        api_tools = self._tool_view_for_mode(AgentMode.FULL).to_api_tools(api_format=self._api_format)
        stable_prompt, _ = self._build_prompt()
        return self.context_manager.compact(
            self.messages,
            tools=api_tools,
            system_prompt=stable_prompt,
        )

    # ── Chat loop ───────────────────────────────────────────────────

    def chat(
        self, user_input: str
    ) -> Generator[StreamEvent, None, None]:
        """Process user input and yield streaming response events.

        When the model issues a tool call the session intercepts it,
        executes the requested tool, yields the result event, and
        re-integrates everything into the conversation history in the
        correct order (assistant message *with* tool_calls, then tool
        result messages).

        Yields:
            StreamEvent — text, thinking, tool_call, tool_result, done, or error.
        """
        # Compatibility adapter: all request paths now share the same
        # per-iteration prompt/tool snapshot and autonomous Agent Loop.
        for event in self.agent_chat(user_input, mode=AgentMode.FULL):
            if event.type in ("progress", "usage"):
                continue
            yield StreamEvent(event.type, event.content)
        return

        # Add user message to history
        self._append_history_messages([Message(role="user", content=user_input)])

        # Accumulators
        response_parts: List[str] = []
        thinking_parts: List[str] = []
        tool_calls_executed: list[tuple[dict, "ToolResult"]] = []
        in_error = False

        # Resolve tool definitions for the active provider
        api_tools = self.tools.to_api_tools(api_format=self._api_format)
        stable_prompt, extra_messages = self._build_prompt()
        preparation = self.context_manager.prepare_before_request(
            self.messages,
            tools=api_tools,
            system_prompt=stable_prompt,
            transient_messages=extra_messages,
        )
        if preparation.blocked:
            yield StreamEvent("error", preparation.diagnostic.message)
            return

        sent_messages = list(preparation.messages)
        call_messages = list(extra_messages) + sent_messages

        try:
            for event in self.provider.stream_chat(
                call_messages,
                thinking=self.thinking_enabled,
                tools=api_tools,
                system=stable_prompt,
            ):
                # ── Error ────────────────────────────────────────────
                if event.type == "error":
                    in_error = True
                    yield event
                    break

                # ── Text / thinking — pass through ───────────────────
                if event.type == "text":
                    response_parts.append(event.content)
                    yield event
                elif event.type in ("thinking", "thinking_delta"):
                    thinking_parts.append(event.content)
                    yield event
                elif event.type == "done":
                    usage = self._usage_from_done_event(event.content)
                    if usage is not None:
                        self.context_manager.record_usage(
                            usage.get("input_tokens", 0),
                            usage.get("output_tokens", 0),
                            usage.get("thinking_tokens", 0),
                            sent_messages,
                            tools=api_tools,
                            system_prompt=stable_prompt,
                            transient_messages=extra_messages,
                        )
                    yield event  # pass through to TUI

                # ── Tool call — intercept & execute ──────────────────
                elif event.type == "tool_call":
                    yield event  # let TUI show "🔧 …"

                    data = json.loads(event.content)
                    tool_call_id: str = data["id"]
                    tool_name: str = data["name"]
                    arguments: dict = data["arguments"]

                    # ── High-risk command confirmation ────────────
                    if (
                        tool_name == "execute_command"
                        and self.confirm_callback is not None
                    ):
                        from flickcode.tools.execute_command import (
                            is_high_risk,
                        )

                        command = arguments.get("command", "")
                        if is_high_risk(command):
                            confirmed = self.confirm_callback(
                                tool_name, arguments
                            )
                            if not confirmed:
                                from flickcode.tools.base import (
                                    ToolResult,
                                )

                                result = ToolResult(
                                    success=False,
                                    output="",
                                    error=(
                                        "Execution cancelled by user. "
                                        "Ask the user if they want to "
                                        "proceed."
                                    ),
                                )
                                tool_calls_executed.append(
                                    (data, result)
                                )
                                yield StreamEvent(
                                    "tool_result",
                                    json.dumps({
                                        "tool_call_id": tool_call_id,
                                        "result": result.to_dict(),
                                    }),
                                )
                                continue  # skip execution

                    # ── Execute tool ──────────────────────────────
                    tool = self.tools.get(tool_name)
                    if tool:
                        result = tool.execute(
                            arguments,
                            cwd=getattr(self, "project_root", Path.cwd()),
                            file_cache=getattr(self, "file_read_cache", None),
                        )
                    else:
                        from flickcode.tools.base import ToolResult

                        result = ToolResult(
                            success=False,
                            error=(
                                f"Unknown tool: {tool_name}. "
                                f"Available: {', '.join(self.tools.list_tools())}."
                            ),
                        )

                    tool_calls_executed.append((data, result))

                    yield StreamEvent(
                        "tool_result",
                        json.dumps({
                            "tool_call_id": tool_call_id,
                            "result": result.to_dict(),
                        }),
                    )

        except Exception as e:
            in_error = True
            yield StreamEvent("error", f"Session error: {e}")

        # ── Re-integrate into conversation history ───────────────────
        if not in_error:
            pending_messages: list[Message] = []
            # 1. Assistant message (text + tool_calls metadata)
            if response_parts or tool_calls_executed:
                assistant_msg = Message(
                    role="assistant",
                    content="".join(response_parts),
                )
                if tool_calls_executed:
                    assistant_msg.tool_calls = [
                        {
                            "id": tc_data["id"],
                            "name": tc_data["name"],
                            "input": tc_data["arguments"],
                        }
                        for tc_data, _ in tool_calls_executed
                    ]
                pending_messages.append(assistant_msg)

            # 2. Tool result messages (belong after the assistant message)
            for tc_data, result in tool_calls_executed:
                pending_messages.append(
                    Message(
                        role="tool",
                        content=result.output,
                        tool_call_id=tc_data["id"],
                    )
                )

            # 3. Thinking (Claude only)
            if thinking_parts and self.thinking_enabled:
                full_thinking = "".join(thinking_parts)
                pending_messages.append(
                    Message(role="thinking", content=full_thinking)
                )

            if pending_messages:
                # Process the combined sequence before the new tool results
                # become part of the persisted history. Existing messages are
                # still scanned as a safe fallback for older sessions.
                self.context_manager.store_oversized_tool_results(
                    list(self.messages) + pending_messages
                )
                self._append_history_messages(pending_messages)

    @staticmethod
    def _usage_from_done_event(content: str) -> Optional[dict]:
        """Extract provider usage safely without changing existing events."""
        if not content:
            return None
        try:
            data = json.loads(content)
        except (TypeError, json.JSONDecodeError):
            return None
        usage = data.get("usage")
        return usage if isinstance(usage, dict) else None
