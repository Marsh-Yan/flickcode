"""Command dispatch and the shared ordinary/slash input router."""

from __future__ import annotations

from typing import Callable, Optional

from flickcode.agent import AgentMode
from flickcode.commands.adapters import CommandUI
from flickcode.commands.models import (
    CommandContext,
    CommandResult,
    InteractionMode,
    ParsedCommand,
)
from flickcode.commands.parser import CommandParser
from flickcode.commands.registry import CommandRegistry


class CommandDispatcher:
    """Resolve and execute parsed commands without knowing a concrete UI."""

    def __init__(self, registry: CommandRegistry) -> None:
        self.registry = registry

    def dispatch(self, parsed: ParsedCommand, *, session, ui: CommandUI) -> CommandResult:
        if parsed.error:
            ui.show_error(parsed.error)
            return CommandResult(error=parsed.error)

        spec = self.registry.resolve(parsed.name)
        if spec is None:
            error = f"Unknown command '/{parsed.name}'. Use /help to list available commands."
            ui.show_error(error)
            return CommandResult(error=error)

        context = CommandContext(
            spec=spec,
            arguments=parsed.arguments,
            session=session,
            ui=ui,
            registry=self.registry,
        )
        try:
            result = spec.handler(context)
        except Exception as exc:
            message = f"Command '/{spec.name}' failed: {exc}"
            ui.show_error(message)
            return CommandResult(error=message)
        if result is None:
            result = CommandResult()
        if result.mode_changed:
            ui.refresh_status()
        return result


class InputRouter:
    """Route every submitted line through one command/Agent decision point."""

    def __init__(
        self,
        registry: CommandRegistry,
        parser: Optional[CommandParser] = None,
        dispatcher: Optional[CommandDispatcher] = None,
        before_handle: Optional[Callable[[], None]] = None,
    ) -> None:
        self.parser = parser or CommandParser()
        self.dispatcher = dispatcher or CommandDispatcher(registry)
        self.before_handle = before_handle

    def handle(self, raw_input: str, *, session, ui: CommandUI) -> CommandResult:
        if raw_input is None or not raw_input.strip():
            return CommandResult(handled=False)

        if self.before_handle is not None:
            try:
                self.before_handle()
            except Exception as exc:
                show = getattr(ui, "show_error", None)
                if show is not None:
                    show(f"Skill refresh failed; using the previous snapshot: {exc}")

        parsed = self.parser.parse(raw_input)
        if parsed is not None:
            return self.dispatcher.dispatch(parsed, session=session, ui=ui)

        mode = ui.get_mode()
        agent_mode = AgentMode.PLAN if mode is InteractionMode.PLAN else AgentMode.FULL
        try:
            ui.send_user_message(raw_input, agent_mode)
        except Exception as exc:
            message = f"Input failed: {exc}"
            ui.show_error(message)
            return CommandResult(error=message)
        return CommandResult(agent_sent=True)
