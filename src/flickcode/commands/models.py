"""Framework-neutral data models for slash commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from flickcode.commands.registry import CommandRegistry


class CommandType(str, Enum):
    """The primary execution route for a command."""

    LOCAL = "local"
    UI_STATE = "ui_state"
    PROMPT = "prompt"


class InteractionMode(str, Enum):
    """Persistent mode used for subsequent ordinary user messages."""

    DEFAULT = "default"
    PLAN = "plan"

    @property
    def label(self) -> str:
        return "[PLAN]" if self is InteractionMode.PLAN else "[DEFAULT]"


@dataclass(frozen=True)
class CommandSpec:
    """Metadata and handler for one registered command."""

    name: str
    aliases: tuple[str, ...] = ()
    description: str = ""
    usage: str = ""
    command_type: CommandType = CommandType.LOCAL
    argument_hint: Optional[str] = None
    hidden: bool = False
    handler: Optional["CommandHandler"] = None

    def __post_init__(self) -> None:
        _validate_command_word(self.name, "name")
        aliases = tuple(self.aliases)
        for alias in aliases:
            _validate_command_word(alias, "alias")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("command description must be non-empty")
        if not isinstance(self.usage, str) or not self.usage.strip():
            raise ValueError("command usage must be non-empty")
        if not isinstance(self.command_type, CommandType):
            raise ValueError("command_type must be a CommandType")
        if self.argument_hint is not None and not isinstance(self.argument_hint, str):
            raise ValueError("argument_hint must be a string or None")
        if self.handler is None or not callable(self.handler):
            raise ValueError("command handler must be callable")
        object.__setattr__(self, "aliases", aliases)


@dataclass(frozen=True)
class ParsedCommand:
    """Result of parsing an input that starts with ``/``."""

    raw_input: str
    name: str
    arguments: str = ""
    is_command: bool = True
    error: Optional[str] = None


@dataclass
class TokenStatus:
    """Small, safe-to-display snapshot of token/context state."""

    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    estimated_input_tokens: int = 0
    request_budget_tokens: int = 0
    safety_margin_tokens: int = 0
    diagnostic: str = ""
    action: str = "unchanged"
    summary_path: Optional[str] = None
    result_paths: list[str] = field(default_factory=list)


@dataclass
class CommandResult:
    """Observable outcome returned by a command or input route."""

    handled: bool = True
    continue_loop: bool = True
    agent_sent: bool = False
    error: Optional[str] = None
    mode_changed: bool = False


@dataclass
class CommandContext:
    """Dependencies supplied to a command handler."""

    spec: CommandSpec
    arguments: str
    session: Any
    ui: Any
    registry: "CommandRegistry"

    @property
    def mode(self) -> InteractionMode:
        return self.ui.get_mode()


CommandHandler = Callable[[CommandContext], CommandResult]


def _validate_command_word(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"command {field_name} must be non-empty")
    if value != value.strip() or "/" in value or any(ch.isspace() for ch in value):
        raise ValueError(f"command {field_name} must be one word without '/'")
