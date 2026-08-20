"""Single source of truth for command metadata, lookup, help, and completion."""

from __future__ import annotations

from typing import Optional

from flickcode.commands.models import CommandSpec


class CommandRegistrationError(RuntimeError):
    """Raised when startup command registration finds a name collision."""


class CommandRegistry:
    """Case-insensitive command registry with eager collision detection."""

    def __init__(self) -> None:
        self._commands: list[CommandSpec] = []
        self._dynamic: list[CommandSpec] = []
        self._index: dict[str, CommandSpec] = {}
        self._sources: dict[str, str] = {}

    def register(self, spec: CommandSpec) -> None:
        words = (spec.name,) + tuple(spec.aliases)
        local_words: set[str] = set()
        for word in words:
            key = self._normalize(word)
            if key in local_words:
                raise CommandRegistrationError(
                    f"Command name collision for '{word}' within '{spec.name}'."
                )
            local_words.add(key)
            if key in self._index:
                previous = self._sources[key]
                raise CommandRegistrationError(
                    f"Command name collision for '{word}' between "
                    f"'{previous}' and '{spec.name}'."
                )
        self._commands.append(spec)
        for word in words:
            key = self._normalize(word)
            self._index[key] = spec
            self._sources[key] = spec.name

    def replace_dynamic(self, specs: tuple[CommandSpec, ...] | list[CommandSpec]) -> None:
        """Atomically replace generated commands after full collision validation."""
        candidate = CommandRegistry()
        for existing in self._commands:
            candidate.register(existing)
        for spec in specs:
            candidate.register(spec)
        candidate.validate()
        self._dynamic = list(specs)
        self._rebuild_index()

    def stable_names(self) -> tuple[str, ...]:
        return tuple(word for spec in self._commands for word in (spec.name,) + tuple(spec.aliases))

    def stable(self, *, include_hidden: bool = True) -> tuple[CommandSpec, ...]:
        if include_hidden:
            return tuple(self._commands)
        return tuple(spec for spec in self._commands if not spec.hidden)

    def _rebuild_index(self) -> None:
        self._index = {}
        self._sources = {}
        for spec in self._commands + self._dynamic:
            for word in (spec.name,) + tuple(spec.aliases):
                key = self._normalize(word)
                self._index[key] = spec
                self._sources[key] = spec.name

    def validate(self) -> None:
        """Validate the already-built index at the startup boundary."""
        seen: set[str] = set()
        for spec in self._commands + self._dynamic:
            for word in (spec.name,) + tuple(spec.aliases):
                key = self._normalize(word)
                if key in seen:
                    raise CommandRegistrationError(
                        f"Command name collision for '{word}' in '{spec.name}'."
                    )
                seen.add(key)
                if self._index.get(key) is not spec:
                    raise CommandRegistrationError(
                        f"Command index is inconsistent for '{word}'."
                    )

    def resolve(self, name: str) -> Optional[CommandSpec]:
        if not isinstance(name, str):
            return None
        normalized = name.strip()
        if normalized.startswith("/"):
            normalized = normalized[1:]
        if not normalized:
            return None
        return self._index.get(self._normalize(normalized))

    def all(self, *, include_hidden: bool = False) -> tuple[CommandSpec, ...]:
        if include_hidden:
            return tuple(self._commands + self._dynamic)
        return tuple(spec for spec in self._commands + self._dynamic if not spec.hidden)

    def completions(self, prefix: str) -> tuple[str, ...]:
        normalized_prefix = self._normalize(prefix.lstrip("/"))
        candidates: list[str] = []
        for spec in self._commands + self._dynamic:
            if spec.hidden:
                continue
            matches_name = self._normalize(spec.name).startswith(normalized_prefix)
            matches_alias = any(
                self._normalize(alias).startswith(normalized_prefix)
                for alias in spec.aliases
            )
            if matches_name or matches_alias:
                candidates.append("/" + spec.name)
        return tuple(dict.fromkeys(candidates))

    def help_for(self, name: Optional[str] = None) -> str:
        if name:
            spec = self.resolve(name)
            if spec is None or spec.hidden:
                return f"Unknown command '{name}'. Use /help to list available commands."
            return self._format_detail(spec)

        visible = self.all()
        lines = ["Available commands:"]
        for spec in visible:
            aliases = f" (aliases: {', '.join('/' + alias for alias in spec.aliases)})" if spec.aliases else ""
            lines.append(
                f"  /{spec.name}{aliases} - {spec.description} "
                f"[{spec.command_type.value}]"
            )
            lines.append(f"      usage: {spec.usage}")
        lines.append("Use /help <command> for details.")
        return "\n".join(lines)

    @staticmethod
    def _normalize(value: str) -> str:
        return value.strip().lower()

    @staticmethod
    def _format_detail(spec: CommandSpec) -> str:
        aliases = ", ".join("/" + alias for alias in spec.aliases) or "none"
        lines = [
            f"/{spec.name}",
            f"Description: {spec.description}",
            f"Aliases: {aliases}",
            f"Usage: {spec.usage}",
            f"Type: {spec.command_type.value}",
            f"Triggers AI: {'yes' if spec.command_type.value == 'prompt' else 'no'}",
        ]
        if spec.argument_hint:
            lines.append(f"Arguments: {spec.argument_hint}")
        return "\n".join(lines)
