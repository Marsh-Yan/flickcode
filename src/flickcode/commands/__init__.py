"""Slash-command registration, parsing, and dispatch for FlickCode."""

from flickcode.commands.adapters import CommandUI, InMemoryCommandUI
from flickcode.commands.builtin import build_default_registry
from flickcode.commands.dispatcher import CommandDispatcher, InputRouter
from flickcode.commands.models import (
    CommandContext,
    CommandHandler,
    CommandResult,
    CommandSpec,
    CommandType,
    InteractionMode,
    ParsedCommand,
    TokenStatus,
)
from flickcode.commands.parser import CommandParser
from flickcode.commands.registry import CommandRegistrationError, CommandRegistry
from flickcode.skills.commands import SkillCommandManager

__all__ = [
    "CommandContext",
    "CommandDispatcher",
    "CommandHandler",
    "CommandParser",
    "CommandRegistrationError",
    "CommandRegistry",
    "CommandResult",
    "CommandSpec",
    "CommandType",
    "CommandUI",
    "build_default_registry",
    "InMemoryCommandUI",
    "InputRouter",
    "InteractionMode",
    "ParsedCommand",
    "TokenStatus",
    "SkillCommandManager",
]
