"""Pure parser for slash-prefixed user input."""

from __future__ import annotations

import re
from typing import Optional

from flickcode.commands.models import ParsedCommand


_WHITESPACE = re.compile(r"\s")


class CommandParser:
    """Parse only the command boundary; never interpret shell syntax."""

    def parse(self, raw_input: str) -> Optional[ParsedCommand]:
        if raw_input is None:
            return None
        trimmed = raw_input.strip()
        if not trimmed or not trimmed.startswith("/"):
            return None

        body = trimmed[1:]
        separator = _WHITESPACE.search(body)
        if separator is None:
            command = body
            arguments = ""
        else:
            command = body[: separator.start()]
            arguments = body[separator.end() :].strip()

        if not command:
            return ParsedCommand(
                raw_input=trimmed,
                name="",
                arguments=arguments,
                error="Command name is missing. Use /help to see available commands.",
            )

        return ParsedCommand(
            raw_input=trimmed,
            name=command.lower(),
            arguments=arguments,
        )
