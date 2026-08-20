"""Built-in FlickCode slash commands."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from flickcode.agent import AgentMode
from flickcode.commands.models import (
    CommandContext,
    CommandResult,
    CommandSpec,
    CommandType,
    InteractionMode,
)
from flickcode.commands.registry import CommandRegistry
from flickcode.permissions.rules import load as load_permission_rules


def build_default_registry() -> CommandRegistry:
    """Build and validate the complete built-in command registry."""
    registry = CommandRegistry()
    for spec in _builtin_specs():
        registry.register(spec)
    registry.validate()
    return registry


def _builtin_specs() -> Iterable[CommandSpec]:
    yield CommandSpec(
        name="help",
        aliases=("?",),
        description="Show available slash commands or detailed help.",
        usage="/help [command]",
        argument_hint="optional command name or alias",
        command_type=CommandType.LOCAL,
        handler=_help,
    )
    yield CommandSpec(
        name="compact",
        description="Compact the current conversation context.",
        usage="/compact",
        command_type=CommandType.LOCAL,
        handler=_compact,
    )
    yield CommandSpec(
        name="clear",
        description="Clear visible UI output without deleting session data.",
        usage="/clear",
        command_type=CommandType.UI_STATE,
        handler=_clear,
    )
    yield CommandSpec(
        name="reset",
        description="Archive and reset conversation history, plan state, and active Skills.",
        usage="/reset",
        command_type=CommandType.UI_STATE,
        handler=_reset,
    )
    yield CommandSpec(
        name="plan",
        description="Enter plan mode or plan a task immediately.",
        usage="/plan [task description]",
        argument_hint="optional task description",
        command_type=CommandType.PROMPT,
        handler=_plan,
    )
    yield CommandSpec(
        name="do",
        aliases=("execute",),
        description="Execute the current plan and return to default mode.",
        usage="/do",
        command_type=CommandType.PROMPT,
        handler=_do,
    )
    yield CommandSpec(
        name="session",
        aliases=("sessions",),
        description="List the current and recoverable project sessions.",
        usage="/session",
        command_type=CommandType.LOCAL,
        handler=_session,
    )
    yield CommandSpec(
        name="memory",
        description="Show loaded project and user memory indexes.",
        usage="/memory",
        command_type=CommandType.LOCAL,
        handler=_memory,
    )
    yield CommandSpec(
        name="permission",
        aliases=("permissions",),
        description="Show the current permission mode and rule summary.",
        usage="/permission",
        command_type=CommandType.LOCAL,
        handler=_permission,
    )
    yield CommandSpec(
        name="status",
        description="Show session, mode, context, token, and diagnostic status.",
        usage="/status",
        command_type=CommandType.LOCAL,
        handler=_status,
    )
    yield CommandSpec(
        name="agent",
        description="List, inspect, retrieve, or cancel SubAgent tasks.",
        usage="/agent [status|result|cancel] [task-id]",
        argument_hint="optional action and task id",
        command_type=CommandType.LOCAL,
        handler=_agent,
    )
    yield CommandSpec(
        name="team",
        description="Create, open, inspect, or leave a durable Agent team.",
        usage="/team [create|open|status|leave] [team-name]",
        argument_hint="operation and optional team name",
        command_type=CommandType.LOCAL,
        handler=_team,
    )
    yield CommandSpec(
        name="audit",
        description="Compatibility alias that runs the current review Skill.",
        usage="/audit [focus]",
        argument_hint="optional review focus",
        command_type=CommandType.PROMPT,
        handler=_audit,
    )
    yield CommandSpec(
        name="resume",
        description="Resume a saved project session.",
        usage="/resume <session-id>",
        argument_hint="session id",
        command_type=CommandType.LOCAL,
        handler=_resume,
    )
    yield CommandSpec(
        name="exit",
        aliases=("quit",),
        description="Exit the interactive session.",
        usage="/exit",
        command_type=CommandType.UI_STATE,
        handler=_exit,
    )


def _help(context: CommandContext) -> CommandResult:
    arguments = context.arguments.strip()
    context.ui.show_message(context.registry.help_for(arguments or None))
    return CommandResult()


def _compact(context: CommandContext) -> CommandResult:
    preparation = context.session.compact_context()
    diagnostic = preparation.diagnostic
    lines = [
        f"Context: {diagnostic.message}",
        f"Action: {diagnostic.action}",
        f"Estimated input: {diagnostic.estimated_input_tokens} tokens",
        f"Request budget: {diagnostic.request_budget_tokens} tokens",
        f"Safety margin: {diagnostic.safety_margin_tokens} tokens",
    ]
    if diagnostic.summary_path:
        lines.append(f"Summary path: {diagnostic.summary_path}")
    if diagnostic.stored_paths:
        lines.append("Stored result paths:")
        lines.extend(f"  - {path}" for path in diagnostic.stored_paths)
    if diagnostic.errors:
        lines.append("Diagnostics:")
        lines.extend(f"  - {error}" for error in diagnostic.errors)
    context.ui.show_message("\n".join(lines))
    return CommandResult()


def _clear(context: CommandContext) -> CommandResult:
    context.ui.clear_display()
    context.ui.refresh_status()
    return CommandResult()


def _reset(context: CommandContext) -> CommandResult:
    context.session.reset_session()
    context.ui.set_mode(InteractionMode.DEFAULT)
    context.ui.refresh_status()
    context.ui.show_message("Started a new conversation session; active Skills and plan state were cleared.")
    return CommandResult(mode_changed=True)


def _plan(context: CommandContext) -> CommandResult:
    context.ui.set_mode(InteractionMode.PLAN)
    context.ui.refresh_status()
    if not context.arguments.strip():
        return CommandResult()
    task = context.arguments.strip()
    context.ui.show_progress(f"Planning: {task[:80]}...")
    context.ui.send_user_message(task, AgentMode.PLAN)
    return CommandResult(agent_sent=True)


def _do(context: CommandContext) -> CommandResult:
    if not getattr(context.session, "plan_context", None):
        message = "No plan context found. Run `/plan <task>` first."
        context.ui.show_error(message)
        return CommandResult(error=message)
    context.ui.set_mode(InteractionMode.DEFAULT)
    context.ui.refresh_status()
    context.ui.show_progress("Executing plan...")
    context.ui.send_user_message("Execute the plan.", AgentMode.EXECUTE)
    return CommandResult(agent_sent=True)


def _session(context: CommandContext) -> CommandResult:
    summaries = context.session.list_sessions()
    active_id = getattr(context.session, "active_session_id", "unknown")
    lines = [f"Current session: {active_id}"]
    if not summaries:
        lines.append("No saved sessions for this project.")
    else:
        lines.append("Saved sessions:")
        for summary in summaries:
            activity = summary.last_activity.isoformat() if summary.last_activity else "unknown"
            status = "recoverable" if summary.recoverable else f"unrecoverable: {summary.reason}"
            lines.append(
                f"{summary.session_id} | {summary.message_count} messages | "
                f"{activity} | {status} | {summary.title}"
            )
    _append_session_diagnostics(context, lines)
    context.ui.show_message("\n".join(lines))
    return CommandResult()


def _resume(context: CommandContext) -> CommandResult:
    session_id = context.arguments.strip()
    if not session_id:
        message = "Usage: /resume <session-id>"
        context.ui.show_error(message)
        return CommandResult(error=message)
    outcome = context.session.resume_session(session_id)
    if outcome.success:
        lines = [
            f"Resumed session {session_id} with {len(outcome.result.messages)} messages."
        ]
        if outcome.compacted:
            lines.append("The restored history was compacted before use.")
        if outcome.diagnostics:
            lines.append("Diagnostics:")
            lines.extend(f"  - {item}" for item in outcome.diagnostics)
        context.ui.show_message("\n".join(lines))
        return CommandResult()
    message = f"Resume failed: {outcome.reason}"
    context.ui.show_error(message)
    return CommandResult(error=message)


def _memory(context: CommandContext) -> CommandResult:
    session = context.session
    bundle = getattr(session, "instruction_bundle", None)
    lines = [
        "Memory status:",
        f"Project instructions: {'loaded' if getattr(bundle, 'project_text', '') else 'none'}",
        f"User instructions: {'loaded' if getattr(bundle, 'user_text', '') else 'none'}",
    ]
    for label, repository in (
        ("Project memory", getattr(session, "project_memory", None)),
        ("User memory", getattr(session, "user_memory", None)),
    ):
        if repository is None:
            lines.append(f"{label}: unavailable")
            continue
        index, diagnostics = repository.read_index()
        lines.append(f"{label} ({repository.index_path}):")
        lines.append(index.strip() or "(empty)")
        lines.extend(f"Diagnostic: {item.message}" for item in diagnostics)
    _append_session_diagnostics(context, lines)
    context.ui.show_message("\n".join(lines))
    return CommandResult()


def _permission(context: CommandContext) -> CommandResult:
    session = context.session
    engine = getattr(session, "permission_engine", None)
    mode = getattr(engine, "mode", getattr(session, "permission_mode", "unknown"))
    rules = load_permission_rules()
    sources: dict[str, int] = {}
    for rule in rules:
        sources[rule.source] = sources.get(rule.source, 0) + 1
    lines = [f"Permission mode: {getattr(mode, 'value', mode)}", f"Loaded rules: {len(rules)}"]
    if sources:
        lines.append("Rules by source: " + ", ".join(f"{key}={value}" for key, value in sorted(sources.items())))
    else:
        lines.append("Rules by source: none")
    context.ui.show_message("\n".join(lines))
    return CommandResult()


def _status(context: CommandContext) -> CommandResult:
    session = context.session
    status = context.ui.token_status()
    snapshot = getattr(session, "status_snapshot", lambda: None)()
    provider = getattr(session, "provider_config", None)
    provider_name = getattr(snapshot, "provider_name", getattr(provider, "name", "unknown"))
    model_name = getattr(snapshot, "model", getattr(provider, "model", "unknown"))
    registered = getattr(snapshot, "mcp_registered_tools", 0)
    failed = getattr(snapshot, "mcp_failed_servers", 0)
    mode = context.ui.get_mode()
    lines = [
        f"Mode: {mode.label}",
        f"Provider: {provider_name}",
        f"Model: {model_name}",
        f"Plan context: {'yes' if getattr(snapshot, 'has_plan_context', getattr(session, 'plan_context', None)) else 'no'}",
        f"Tokens: input={status.input_tokens}, output={status.output_tokens}, thinking={status.thinking_tokens}",
        f"Context: estimated={status.estimated_input_tokens}, budget={status.request_budget_tokens}, margin={status.safety_margin_tokens}",
        f"Context action: {getattr(snapshot, 'context_action', status.action)}",
        f"MCP: registered={registered}, failed={failed}",
        (
            "Hooks: "
            f"started={getattr(snapshot, 'hooks_started', False)}, "
            f"active={getattr(snapshot, 'hook_active_rules', 0)}, "
            f"skipped={getattr(snapshot, 'hook_skipped_rules', 0)}, "
            f"trust={getattr(snapshot, 'hook_project_trust', 'pending')}, "
            f"once={getattr(snapshot, 'hook_once_count', 0)}, "
            f"background={getattr(snapshot, 'hook_background_count', 0)}"
        ),
    ]
    diagnostic = getattr(snapshot, "context_diagnostic", status.diagnostic)
    if diagnostic:
        lines.append(f"Context diagnostic: {diagnostic}")
    summary_path = getattr(snapshot, "summary_path", status.summary_path)
    if summary_path:
        lines.append(f"Summary path: {summary_path}")
    result_paths = getattr(snapshot, "result_paths", tuple(status.result_paths))
    if result_paths:
        lines.append("Result paths:\n" + "\n".join(f"  - {path}" for path in result_paths))
    diagnostics = getattr(snapshot, "diagnostics", ())
    if diagnostics:
        lines.append("Diagnostics:\n" + "\n".join(f"  - {item}" for item in diagnostics))
    hook_overrides = getattr(snapshot, "hook_overrides", ())
    if hook_overrides:
        lines.append("Hook overrides: " + ", ".join(hook_overrides))
    hook_diagnostics = getattr(snapshot, "hook_diagnostics", ())
    if hook_diagnostics:
        lines.append(
            "Recent Hook diagnostics:\n"
            + "\n".join(f"  - {item}" for item in hook_diagnostics[-10:])
        )
    effective_skills = getattr(snapshot, "effective_skills", ())
    active_skills = getattr(snapshot, "active_skills", ())
    skill_tools = getattr(snapshot, "skill_tools", ())
    if effective_skills:
        lines.append("Skills: " + ", ".join(effective_skills))
    lines.append("Active Skills: " + (", ".join(active_skills) if active_skills else "none"))
    if skill_tools:
        lines.append("Visible Skill tools: " + ", ".join(skill_tools))
    skill_details = getattr(snapshot, "skill_details", ())
    if skill_details:
        lines.append("Skill sources: " + ", ".join(skill_details))
    if snapshot is not None:
        lines.append(f"Skill catalog generation: {getattr(snapshot, 'skill_generation', 0)}")
    context.ui.show_message("\n".join(lines))
    return CommandResult()


def _agent(context: CommandContext) -> CommandResult:
    manager = getattr(context.session, "subagent_tasks", None)
    if manager is None:
        message = "SubAgent task manager is unavailable."
        context.ui.show_error(message)
        return CommandResult(error=message)
    parts = context.arguments.split()
    if not parts:
        counts = manager.counts()
        rendered = ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))
        context.ui.show_message("SubAgent tasks: " + (rendered or "none"))
        return CommandResult()
    action = parts[0].lower()
    if action not in {"status", "result", "cancel"} or len(parts) != 2:
        message = "Usage: /agent [status|result|cancel] [task-id]"
        context.ui.show_error(message)
        return CommandResult(error=message)
    task_id = parts[1]
    if action == "status":
        snapshot = manager.status(task_id)
        context.ui.show_message(
            f"{task_id}: {snapshot.state.value}; background={snapshot.background}; "
            f"summary={snapshot.summary or '(pending)'}"
        )
    elif action == "result":
        result = manager.result(task_id)
        context.ui.show_message(result.result or f"{task_id}: no result yet ({result.state.value})")
    else:
        snapshot = manager.cancel(task_id)
        context.ui.show_message(f"{task_id}: {snapshot.state.value}")
    return CommandResult()


def _team(context: CommandContext) -> CommandResult:
    parts = context.arguments.strip().split(maxsplit=1)
    operation = parts[0] if parts else "status"
    name = parts[1].strip() if len(parts) > 1 else ""
    try:
        if operation == "create":
            if not name:
                message = "Usage: /team create <team-name>"
                context.ui.show_error(message)
                return CommandResult(error=message)
            value = context.session.activate_team(name, create=True)
            context.ui.show_message(f"Team Lead activated: {value['name']} ({value['team_id']})")
            return CommandResult()
        if operation == "open":
            if not name:
                message = "Usage: /team open <team-name>"
                context.ui.show_error(message)
                return CommandResult(error=message)
            value = context.session.activate_team(name, create=False)
            context.ui.show_message(f"Team Lead resumed: {value['name']} ({value['team_id']})")
            return CommandResult()
        if operation == "status":
            value = context.session.team_status()
            context.ui.show_message(__import__("json").dumps(value, ensure_ascii=False, indent=2, default=str))
            return CommandResult()
        if operation == "leave":
            context.session.leave_team()
            context.ui.show_message("Left the active team; durable team data was kept.")
            return CommandResult()
        message = "Usage: /team create <name> | /team open <name> | /team status | /team leave"
        context.ui.show_error(message)
        return CommandResult(error=message)
    except Exception as exc:
        message = f"Team command failed: {exc}"
        context.ui.show_error(message)
        return CommandResult(error=message)


def _audit(context: CommandContext) -> CommandResult:
    context.ui.show_progress("Reviewing the current project...")
    context.ui.run_skill("review", context.arguments, AgentMode.FULL)
    return CommandResult(agent_sent=True)


def _exit(context: CommandContext) -> CommandResult:
    return CommandResult(continue_loop=False)


def _append_session_diagnostics(context: CommandContext, lines: list[str]) -> None:
    drain = getattr(context.session, "drain_diagnostics", None)
    if drain is None:
        return
    diagnostics = drain()
    if diagnostics:
        lines.append("Diagnostics:")
        lines.extend(f"  - {item}" for item in diagnostics)
