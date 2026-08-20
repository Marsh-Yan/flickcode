"""Terminal user interface for FlickCode conversations."""

import json
import os
import sys

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style

from flickcode.agent import AgentEvent, AgentMode, StopReason
from flickcode.commands import (
    InteractionMode,
    InputRouter,
    TokenStatus,
    build_default_registry,
)
from flickcode.config import DEFAULT_CONFIG_DIR
from flickcode.renderer import Renderer
from flickcode.session import Session

# ── Safe I/O ─────────────────────────────────────────────────────────

_STDOUT_BUF = sys.stdout.buffer
_STDERR_BUF = sys.stderr.buffer
_STDOUT_ENCODING = sys.stdout.encoding or "utf-8"


def _safe_write(stream_buf, text: str) -> None:
    """Write text to a binary stream, handling encoding errors."""
    encoded = text.encode(_STDOUT_ENCODING, errors="replace")
    stream_buf.write(encoded)


def _safe_print(text: str, end: str = "\n") -> None:
    """Print text safely, replacing unencodable characters."""
    _safe_write(_STDOUT_BUF, text)
    if end:
        _safe_write(_STDOUT_BUF, end)
    _STDOUT_BUF.flush()

# ── Styles ──────────────────────────────────────────────────────────

TUI_STYLE = Style.from_dict(
    {
        "prompt": "bold cyan",
        "info": "ansibrightblack",
        "logo_fire": "ansibrightyellow bold",
        "logo_name": "ansibrightyellow bold",
        "logo_sub": "ansibrightblack",
    }
)


def _build_logo(session: "Session") -> HTML:
    """Build the startup logo with fire art + FLICK CODE and model info."""
    model_name = session.provider_config.model
    fire_art = [
        " <logo_fire>▐██▌     </logo_fire>",
        "<logo_fire>▐■■■■▌    </logo_fire>",
        "<logo_fire>▐■■■■▌    </logo_fire>",
        " <logo_fire>▐■■▌     </logo_fire>",
        "  <logo_fire>▝▘      </logo_fire>",
    ]

    flick_rows = [
        '<logo_name>██████   ██       ██████   ██████   ██  ██</logo_name>',
        '<logo_name>██       ██         ██     ██       ██ ██ </logo_name>',
        '<logo_name>█████    ██         ██     ██       ████  </logo_name>',
        '<logo_name>██       ██         ██     ██       ██ ██ </logo_name>',
        '<logo_name>██       ██████   ██████   ██████   ██  ██</logo_name>',
    ]

    code_rows = [
        '<logo_name>             ██████   ██████   █████    ██████</logo_name>',
        '<logo_name>             ██       ██  ██   ██  ██   ██    </logo_name>',
        '<logo_name>             ██       ██  ██   ██  ██   █████ </logo_name>',
        '<logo_name>             ██       ██  ██   ██  ██   ██    </logo_name>',
        '<logo_name>             ██████   ██████   █████    ██████</logo_name>',
    ]

    lines = []
    # Fire + FLICK side by side (5 rows)
    for i in range(5):
        lines.append(fire_art[i] + "    " + flick_rows[i])

    lines.append("")

    # CODE rows
    for row in code_rows:
        lines.append(row)

    lines.append("")
    lines.append(f'<logo_sub>             v0.1.0 — {_escape(model_name)}</logo_sub>')
    lines.append('<logo_sub>             by Marshall</logo_sub>')

    return HTML("\n".join(lines))

WELCOME_MSG = HTML(
    "<info>"
    "Type your message and press Enter to send (Alt+Enter for new line).\n"
    "Commands: /help for all commands; /plan, /do, /compact; /exit or /quit to quit; Ctrl+D to exit.\n"
    "</info>"
)


class CommandCompleter(Completer):
    """Complete registered slash command names without touching arguments."""

    def __init__(self, registry, before_complete=None) -> None:
        self.registry = registry
        self.before_complete = before_complete

    def get_completions(self, document: Document, complete_event):
        if self.before_complete is not None:
            try:
                self.before_complete()
            except Exception:
                pass
        before = document.text_before_cursor
        command_text = before.lstrip()
        if not command_text.startswith("/") or any(ch.isspace() for ch in command_text):
            return
        for candidate in self.registry.completions(command_text[1:]):
            yield Completion(
                candidate,
                start_position=-len(command_text),
                display=candidate,
            )


class _BaseCommandUI:
    """Shared command UI state and safe status snapshot mapping."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.mode = InteractionMode.DEFAULT

    def get_mode(self) -> InteractionMode:
        return self.mode

    def set_mode(self, mode: InteractionMode) -> None:
        self.mode = mode

    def token_status(self) -> TokenStatus:
        snapshot = getattr(self.session, "status_snapshot", lambda: None)()
        if snapshot is None:
            return TokenStatus()
        return TokenStatus(
            input_tokens=snapshot.input_tokens,
            output_tokens=snapshot.output_tokens,
            thinking_tokens=snapshot.thinking_tokens,
            estimated_input_tokens=snapshot.estimated_input_tokens,
            request_budget_tokens=snapshot.request_budget_tokens,
            safety_margin_tokens=snapshot.safety_margin_tokens,
            diagnostic=snapshot.context_diagnostic,
            action=snapshot.context_action,
            summary_path=snapshot.summary_path,
            result_paths=list(snapshot.result_paths),
        )


class TUICommandUI(_BaseCommandUI):
    """Renderer-backed command adapter for interactive TUI mode."""

    def __init__(self, session: Session, renderer: Renderer) -> None:
        super().__init__(session)
        self.renderer = renderer

    def show_message(self, text: str) -> None:
        self.renderer.render_progress(text)

    def show_progress(self, text: str) -> None:
        self.renderer.render_progress(text)

    def show_error(self, text: str) -> None:
        self.renderer.render_error(text)

    def send_user_message(self, text: str, mode: AgentMode) -> None:
        _consume_agent_events(self.renderer, self.session.agent_chat(text, mode=mode))
        _render_session_diagnostics(self.session, self.renderer)

    def run_skill(self, name: str, user_input: str, mode: AgentMode) -> None:
        _consume_agent_events(self.renderer, self.session.invoke_skill(name, user_input, mode))
        _render_session_diagnostics(self.session, self.renderer)

    def refresh_status(self) -> None:
        self.renderer.render_progress(f"Mode: {self.mode.label}")

    def clear_display(self) -> None:
        self.renderer.console.clear()


class PipeCommandUI(_BaseCommandUI):
    """Safe stdout/stderr command adapter for piped input."""

    def show_message(self, text: str) -> None:
        _safe_print(text)

    def show_progress(self, text: str) -> None:
        _safe_print(text)

    def show_error(self, text: str) -> None:
        _safe_write(_STDERR_BUF, f"Error: {text}\n")
        _STDERR_BUF.flush()

    def send_user_message(self, text: str, mode: AgentMode) -> None:
        _consume_pipe_agent_events(self.session.agent_chat(text, mode=mode))
        _write_session_diagnostics_to_stderr(self.session)

    def run_skill(self, name: str, user_input: str, mode: AgentMode) -> None:
        _consume_pipe_agent_events(self.session.invoke_skill(name, user_input, mode))
        _write_session_diagnostics_to_stderr(self.session)

    def refresh_status(self) -> None:
        _safe_print(f"Mode: {self.mode.label}")

    def clear_display(self) -> None:
        _safe_print("\x1b[2J\x1b[H")


def _consume_pipe_agent_events(agent_gen) -> None:
    """Render AgentEvent streams using safe pipe output."""
    for event in agent_gen:
        if event.type == "text":
            _safe_write(_STDOUT_BUF, event.content)
            _STDOUT_BUF.flush()
        elif event.type in ("thinking", "thinking_delta"):
            _safe_write(_STDERR_BUF, f"[thinking] {event.content}\n")
            _STDERR_BUF.flush()
        elif event.type == "tool_call":
            try:
                data = json.loads(event.content)
            except (TypeError, json.JSONDecodeError):
                data = {"name": "?"}
            _safe_write(_STDERR_BUF, f"[tool: {data.get('name', '?')}]\n")
            _STDERR_BUF.flush()
        elif event.type == "tool_result":
            try:
                data = json.loads(event.content)
            except (TypeError, json.JSONDecodeError):
                data = {"result": {}}
            result = data.get("result", {})
            if result.get("output"):
                _safe_write(_STDOUT_BUF, result["output"] + "\n")
                _STDOUT_BUF.flush()
        elif event.type == "error":
            _safe_write(_STDERR_BUF, f"Error: {event.content}\n")
            _STDERR_BUF.flush()
        elif event.type == "done":
            _safe_write(_STDOUT_BUF, "\n")
            _STDOUT_BUF.flush()


def _run_piped_loop(session: Session) -> None:
    """Simple non-interactive loop for piped input."""
    session.start()
    registry = session.command_registry
    router = InputRouter(registry, before_handle=session.refresh_skills)
    ui = PipeCommandUI(session)
    for line in sys.stdin:
        user_input = line.rstrip("\r\n")
        result = router.handle(user_input, session=session, ui=ui)
        _write_session_diagnostics_to_stderr(session)
        if not result.continue_loop:
            break


def _consume_agent_events(
    renderer: Renderer,
    agent_gen,
) -> StopReason:
    """Consume AgentEvent generator, dispatching to the renderer.

    Handles streaming text, tool calls/results, progress updates,
    usage info, and stop conditions.

    Args:
        renderer: The output renderer.
        agent_gen: Generator yielding ``AgentEvent`` from ``session.agent_chat()``.

    Returns:
        The ``StopReason`` from the completed agent loop.
    """
    first_text = True
    stop_reason = StopReason.COMPLETED

    try:
        for event in agent_gen:
            if event.type == "text":
                if first_text:
                    renderer.render_assistant_init()
                    first_text = False
                renderer.render_assistant_stream(event.content)

            elif event.type == "tool_call":
                try:
                    data = json.loads(event.content)
                except json.JSONDecodeError:
                    data = {"name": "?", "arguments": {}}
                renderer.render_tool_call(
                    data.get("name", "?"),
                    data.get("arguments", {}),
                )

            elif event.type == "tool_result":
                try:
                    data = json.loads(event.content)
                except json.JSONDecodeError:
                    data = {"name": "tool", "result": {}}
                result = data.get("result", {})
                summary = "completed"
                if result.get("output"):
                    summary = result["output"][:100]
                elif result.get("error"):
                    summary = result["error"][:100]
                renderer.render_tool_result(
                    data.get("name", "tool"),
                    result.get("success", False),
                    summary,
                )

            elif event.type == "usage":
                try:
                    data = json.loads(event.content)
                except json.JSONDecodeError:
                    data = {}
                renderer.render_usage(
                    data.get("input_tokens", 0),
                    data.get("output_tokens", 0),
                    data.get("thinking_tokens", 0),
                )

            elif event.type == "progress":
                renderer.render_progress(event.content)

            elif event.type == "done":
                if not first_text:
                    renderer.render_assistant_end()
                try:
                    data = json.loads(event.content) if event.content else {}
                except json.JSONDecodeError:
                    data = {}
                raw = data.get("stop_reason", "completed")
                stop_reason = StopReason(raw)

                if stop_reason == StopReason.MAX_ITERATIONS:
                    renderer.render_error(
                        "Reached max iterations. Task may be incomplete."
                    )
                elif stop_reason == StopReason.UNKNOWN_TOOL:
                    renderer.render_error(
                        "Stopped: too many unknown tool calls."
                    )
                elif stop_reason == StopReason.PROVIDER_ERROR:
                    renderer.render_error(
                        "Provider error during agent execution."
                    )
                elif stop_reason == StopReason.USER_CANCELLED:
                    renderer.render_error("Cancelled by user.")

            elif event.type in ("thinking", "thinking_delta"):
                renderer.render_thinking(event.content)

            elif event.type == "error":
                renderer.render_error(event.content)

    except KeyboardInterrupt:
        stop_reason = StopReason.USER_CANCELLED
        if not first_text:
            renderer.render_assistant_end()
        renderer.render_error("Agent loop cancelled by user.")

    return stop_reason


def _create_output():
    """Create the appropriate prompt_toolkit output backend for the terminal.

    On Windows under Cygwin/Git Bash/MSYS2 the Win32Output backend
    fails because the terminal is not a real Windows console. This
    detects that case and returns a Vt100Output instead.
    """
    if sys.platform == "win32":
        # Git Bash / MSYS2 / Cygwin set MSYSTEM; regular terminals don't.
        if "MSYSTEM" in os.environ:
            from prompt_toolkit.output.vt100 import Vt100_Output

            return Vt100_Output.from_pty(sys.stdout)

    from prompt_toolkit.output.defaults import create_output

    return create_output()


def run_interactive_loop(session: Session) -> None:
    """Run the main interactive TUI loop.

    Presents a prompt, accepts user input, streams responses,
    and continues until the user exits. Falls back to a simple
    readline loop if stdin is not a TTY.
    """
    if not sys.stdin.isatty():
        try:
            return _run_piped_loop(session)
        finally:
            session.close()

    renderer = Renderer()
    registry = session.command_registry
    output = _create_output()
    history_path = DEFAULT_CONFIG_DIR / "history"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    # Key bindings: Enter to submit, Alt+Enter to insert newline
    kb = KeyBindings()

    @kb.add("enter")
    def _submit(event):
        """Enter sends the message."""
        buffer = event.app.current_buffer
        buffer.validate_and_handle()

    @kb.add("escape", "enter")
    def _newline(event):
        """Alt+Enter (Esc then Enter) inserts a newline."""
        buffer = event.app.current_buffer
        buffer.insert_text("\n")

    prompt_session: PromptSession = PromptSession(
        multiline=True,
        history=FileHistory(str(history_path)),
        style=TUI_STYLE,
        output=output,
        key_bindings=kb,
        completer=CommandCompleter(registry, before_complete=session.refresh_skills_safely),
    )

    command_ui = TUICommandUI(session, renderer)
    router = InputRouter(registry, before_handle=session.refresh_skills)

    # A foreground SubAgent blocks inside its tool call. Polling here keeps
    # Ctrl+B available during that wait without exposing terminal access to
    # worker threads. Non-Windows terminals retain timeout/explicit controls.
    foreground = getattr(session, "subagent_foreground", None)
    if foreground is not None and os.name == "nt":
        def _poll_ctrl_b() -> bool:
            import msvcrt
            if not msvcrt.kbhit():
                return False
            key = msvcrt.getwch()
            if key == "\x02":
                renderer.render_progress("SubAgent detached; continuing in background.")
                return True
            return False
        foreground.set_poll_callback(_poll_ctrl_b)

    # ── High-risk command confirmation callback ──────────────────
    def _confirm_high_risk(tool_name: str, arguments: dict) -> bool:
        """Ask the user before executing a destructive command."""
        command = arguments.get("command", "")
        try:
            result = prompt_session.prompt(
                HTML(
                    "<prompt>⚠️  High-risk command: </prompt>"
                    f"{_escape(command[:200])}\n"
                    "<prompt>Confirm execution? (y/N) </prompt>"
                ),
                style=TUI_STYLE,
            )
            return result.strip().lower() in ("y", "yes")
        except (KeyboardInterrupt, EOFError):
            return False

    # ── HITL permission callback ─────────────────────────────────
    def _hitl_permission_callback(tool_name: str, arguments: dict) -> str:
        """Ask the user how to handle a tool call not covered by rules.

        Returns: "allow_once" | "allow_session" | "allow_forever" | "deny"
        """
        # Build a one-line summary of the arguments
        arg_summary = " ".join(
            f"{k}={v}" for k, v in arguments.items()
        )[:200]

        try:
            result = prompt_session.prompt(
                HTML(
                    "<prompt>⛔  Permission needed: </prompt>"
                    f"{_escape(tool_name)}({_escape(arg_summary)})\n"
                    "<prompt>    [a] Allow once  "
                    "[s] Allow session  "
                    "[f] Allow forever  "
                    "[d] Deny </prompt>"
                ),
                style=TUI_STYLE,
            )
            choice = result.strip().lower()
            if choice in ("a", "allow", "once"):
                return "allow_once"
            if choice in ("s", "session"):
                return "allow_session"
            if choice in ("f", "forever", "permanent"):
                return "allow_forever"
            return "deny"
        except (KeyboardInterrupt, EOFError):
            return "deny"

    def _confirm_hook_trust(project_root, summaries) -> bool:
        counts = {}
        for summary in summaries:
            counts[summary.action] = counts.get(summary.action, 0) + 1
        action_summary = ", ".join(
            f"{name}={count}" for name, count in sorted(counts.items())
        )
        try:
            result = prompt_session.prompt(
                HTML(
                    "<prompt>⚠️  Project Hooks request trust: </prompt>"
                    f"{_escape(str(project_root))}\n"
                    f"<prompt>Rules: {len(summaries)} ({_escape(action_summary)})\n"
                    "Trust project Hooks for this session? (y/N) </prompt>"
                ),
                style=TUI_STYLE,
            )
            return result.strip().lower() in ("y", "yes")
        except (KeyboardInterrupt, EOFError):
            return False

    session.confirm_callback = _confirm_high_risk
    session.permission_engine._hitl_callback = _hitl_permission_callback
    session.start(_confirm_hook_trust)

    print_formatted_text(_build_logo(session), style=TUI_STYLE, output=output)
    print_formatted_text(WELCOME_MSG, style=TUI_STYLE, output=output)
    command_ui.refresh_status()
    _render_mcp_startup_summary(session, renderer)

    while True:
        try:
            user_input = prompt_session.prompt(
                HTML("<prompt>▌ </prompt>"),
                style=TUI_STYLE,
            )
        except KeyboardInterrupt:
            try:
                confirm = prompt_session.prompt(
                    HTML("<prompt>Really quit? (y/N) </prompt>"),
                    style=TUI_STYLE,
                )
                if confirm.strip().lower() in ("y", "yes"):
                    break
                else:
                    continue
            except (KeyboardInterrupt, EOFError):
                break
            continue
        except EOFError:
            break

        result = router.handle(user_input, session=session, ui=command_ui)
        if not result.continue_loop:
            break
        continue

        trimmed = user_input.strip()

        # ── Built-in commands ────────────────────────────────────────
        if trimmed.lower() in ("/exit", "/quit"):
            break

        if trimmed.lower() == "/compact":
            _run_compact_command(session, renderer)
            continue

        if trimmed.lower() == "/sessions":
            _run_sessions_command(session, renderer)
            continue

        if trimmed.lower() == "/resume" or trimmed.lower().startswith("/resume "):
            parts = trimmed.split(maxsplit=1)
            if len(parts) != 2:
                renderer.render_error("Usage: /resume <session-id>")
            else:
                _run_resume_command(session, renderer, parts[1].strip())
            continue

        if trimmed.lower() == "/do":
            if not session.plan_context:
                renderer.render_error(
                    "No plan context found. Run `/plan <task>` first."
                )
                continue
            renderer.render_progress("Executing plan...")
            agent_gen = session.agent_chat(
                "Execute the plan.",
                mode=AgentMode.EXECUTE,
            )
            _consume_agent_events(renderer, agent_gen)
            _render_session_diagnostics(session, renderer)
            continue

        if trimmed.startswith("/plan "):
            task = trimmed[6:].strip()
            if not task:
                renderer.render_error("Usage: /plan <task description>")
                continue
            renderer.render_progress(f"Planning: {task[:80]}...")
            agent_gen = session.agent_chat(task, mode=AgentMode.PLAN)
            _consume_agent_events(renderer, agent_gen)
            _render_session_diagnostics(session, renderer)
            continue

        # ── Default: run agent loop ──────────────────────────────────
        agent_gen = session.agent_chat(trimmed, mode=AgentMode.FULL)
        _consume_agent_events(renderer, agent_gen)
        _render_session_diagnostics(session, renderer)

    renderer.console.print("[bold]Bye![/bold]")
    session.close()


def _render_mcp_startup_summary(session: Session, renderer: Renderer) -> None:
    """Show a compact MCP startup summary without exposing secrets."""
    report = getattr(session, "mcp_startup_report", None)
    config_errors = getattr(session, "mcp_startup_errors", [])
    if report is None and not config_errors:
        return
    registered = len(report.registered_tools) if report is not None else 0
    failed = len(report.failed_servers) if report is not None else 0
    failed += len(config_errors)
    if registered:
        renderer.render_progress(f"MCP: registered {registered} external tool(s).")
    if failed:
        renderer.render_error(
            f"MCP: skipped {failed} server configuration/connection error(s)."
        )


def _render_context_diagnostic(renderer: Renderer, diagnostic) -> None:
    """Render compact context status without echoing large tool results."""
    message = (
        f"Context: {diagnostic.message} "
        f"(estimated {diagnostic.estimated_input_tokens}/"
        f"{diagnostic.request_budget_tokens} input tokens; "
        f"safety margin {diagnostic.safety_margin_tokens})"
    )
    if diagnostic.action in ("blocked", "summary_failed", "circuit_open"):
        renderer.render_error(message)
    else:
        renderer.render_progress(message)
    for path in diagnostic.stored_paths:
        renderer.render_progress(f"Context result stored: {path}")
    if diagnostic.summary_path:
        renderer.render_progress(f"Context summary stored: {diagnostic.summary_path}")
    for error in diagnostic.errors:
        renderer.render_error(f"Context diagnostic: {error}")


def _run_compact_command(session: Session, renderer: Renderer):
    """Execute `/compact` in a testable command branch."""
    renderer.render_progress("Compacting conversation context...")
    preparation = session.compact_context()
    _render_context_diagnostic(renderer, preparation.diagnostic)
    return preparation


def _run_sessions_command(session: Session, renderer: Renderer):
    """Render managed sessions without invoking the provider."""
    summaries = session.list_sessions()
    if not summaries:
        renderer.render_progress("No saved sessions for this project.")
    for summary in summaries:
        activity = summary.last_activity.isoformat() if summary.last_activity else "unknown"
        status = "recoverable" if summary.recoverable else f"unrecoverable: {summary.reason}"
        renderer.render_progress(
            f"{summary.session_id} | {summary.message_count} messages | "
            f"{activity} | {status} | {summary.title}"
        )
    _render_session_diagnostics(session, renderer)
    return summaries


def _resume_message(outcome) -> str:
    """Format an explicit restore result without exposing archive contents."""
    pieces = [f"Restored {len(outcome.result.messages)} message(s)."]
    if outcome.result.truncated:
        pieces.append("Incomplete tool-call history was truncated.")
    if outcome.result.inserted_time_gap_notice:
        pieces.append("Inserted a time-gap reminder.")
    if outcome.compacted:
        pieces.append("Context was compacted.")
    skipped = sum(1 for item in outcome.result.diagnostics if item.line is not None)
    if skipped:
        pieces.append(f"Skipped {skipped} invalid archive record(s).")
    return " ".join(pieces)


def _run_resume_command(session: Session, renderer: Renderer, session_id: str):
    """Run one explicit resume attempt and preserve the prior session on failure."""
    outcome = session.resume_session(session_id)
    if outcome.success:
        renderer.render_progress(_resume_message(outcome))
    else:
        renderer.render_error(f"Resume failed: {outcome.reason}")
    for message in outcome.diagnostics:
        renderer.render_error(f"Resume diagnostic: {message}")
    _render_session_diagnostics(session, renderer)
    return outcome


def _render_session_diagnostics(session: Session, renderer: Renderer) -> None:
    for diagnostic in getattr(session, "drain_diagnostics", lambda: [])():
        renderer.render_error(f"Session diagnostic: {diagnostic}")


def _write_session_diagnostics_to_stderr(session: Session) -> None:
    for diagnostic in getattr(session, "drain_diagnostics", lambda: [])():
        _safe_write(_STDERR_BUF, f"Session diagnostic: {diagnostic}\n")
    _STDERR_BUF.flush()


def _escape(text: str) -> str:
    """Escape HTML special characters for prompt_toolkit HTML formatting."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
