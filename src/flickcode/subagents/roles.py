"""Strict Markdown role parsing and priority-resolved catalogs."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Optional

import yaml

from flickcode.subagents.models import (
    AgentModelAlias,
    AgentPermissionMode,
    AgentRoleCatalogCandidate,
    AgentRoleCatalogSnapshot,
    AgentRoleDefinition,
    AgentRoleDiagnostic,
    AgentRoleSource,
)
from flickcode.worktrees.models import AgentIsolationMode

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_TOOL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
_FIELDS = {
    "name",
    "description",
    "tools",
    "model",
    "max_turns",
    "permission_mode",
    "isolation",
}
_PRIORITY = (
    AgentRoleSource.PROJECT,
    AgentRoleSource.USER,
    AgentRoleSource.BUILTIN,
    AgentRoleSource.PLUGIN,
)


class AgentRoleParseError(ValueError):
    def __init__(self, message: str, path: Path, role_name: str = "") -> None:
        self.path = path
        self.role_name = role_name
        super().__init__(f"{path}: {message}")


class AgentRoleParser:
    def parse_file(self, path: Path, source: AgentRoleSource) -> AgentRoleDefinition:
        unresolved = path.expanduser().absolute()
        if unresolved.is_symlink():
            raise AgentRoleParseError("role file must not be a symlink", unresolved)
        path = unresolved.resolve()
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise AgentRoleParseError(f"cannot read role: {exc}", path) from exc
        metadata, body = self._split(raw, path)
        values = self._validate(metadata, path)
        return AgentRoleDefinition(
            name=values["name"],
            description=values["description"],
            allowed_tools=frozenset(values["allow"]),
            denied_tools=frozenset(values["deny"]),
            model=values["model"],
            max_turns=values["max_turns"],
            permission_mode=values["permission_mode"],
            system_prompt=body,
            source=source,
            source_path=path,
            fingerprint=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            isolation=values["isolation"],
        )

    @staticmethod
    def _split(raw: str, path: Path) -> tuple[dict, str]:
        lines = raw.splitlines(keepends=True)
        if not lines or lines[0].strip() != "---":
            raise AgentRoleParseError("file must start with YAML frontmatter", path)
        closing = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if closing is None:
            raise AgentRoleParseError("frontmatter closing delimiter is missing", path)
        try:
            metadata = yaml.safe_load("".join(lines[1:closing]))
        except yaml.YAMLError as exc:
            raise AgentRoleParseError(f"invalid YAML: {exc}", path) from exc
        if not isinstance(metadata, dict):
            raise AgentRoleParseError("frontmatter must be a mapping", path)
        body = "".join(lines[closing + 1:]).strip()
        if not body:
            raise AgentRoleParseError("role system prompt must not be empty", path, str(metadata.get("name", "")))
        return metadata, body

    @staticmethod
    def _validate(raw: dict, path: Path) -> dict:
        name_hint = raw.get("name") if isinstance(raw.get("name"), str) else ""
        required_fields = _FIELDS - {"isolation"}
        missing = sorted(required_fields - set(raw))
        unknown = sorted(set(raw) - _FIELDS)
        if missing or unknown:
            parts = []
            if missing:
                parts.append("missing " + ", ".join(missing))
            if unknown:
                parts.append("unknown " + ", ".join(unknown))
            raise AgentRoleParseError("invalid frontmatter fields: " + "; ".join(parts), path, name_hint)
        name = raw["name"]
        description = raw["description"]
        tools = raw["tools"]
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise AgentRoleParseError("name must match ^[a-z][a-z0-9-]*$", path, name_hint)
        if not isinstance(description, str) or not description.strip() or "\n" in description:
            raise AgentRoleParseError("description must be one non-empty line", path, name)
        if not isinstance(tools, dict) or set(tools) != {"allow", "deny"}:
            raise AgentRoleParseError("tools must contain exactly allow and deny", path, name)
        allow, deny = tools["allow"], tools["deny"]
        for label, values in (("allow", allow), ("deny", deny)):
            if not isinstance(values, list) or not all(isinstance(x, str) and _TOOL_RE.fullmatch(x) for x in values):
                raise AgentRoleParseError(f"tools.{label} must be a list of tool names", path, name)
            if len(values) != len(set(values)):
                raise AgentRoleParseError(f"tools.{label} must not contain duplicates", path, name)
        try:
            model = AgentModelAlias(raw["model"])
        except (TypeError, ValueError) as exc:
            raise AgentRoleParseError("model must be inherit, haiku, sonnet, or opus", path, name) from exc
        try:
            permission = AgentPermissionMode(raw["permission_mode"])
        except (TypeError, ValueError) as exc:
            raise AgentRoleParseError("permission_mode is invalid", path, name) from exc
        max_turns = raw["max_turns"]
        if not isinstance(max_turns, int) or isinstance(max_turns, bool) or max_turns <= 0:
            raise AgentRoleParseError("max_turns must be a positive integer", path, name)
        try:
            isolation = AgentIsolationMode(raw.get("isolation", "shared"))
        except (TypeError, ValueError) as exc:
            raise AgentRoleParseError("isolation must be shared or worktree", path, name) from exc
        return {
            "name": name,
            "description": description.strip(),
            "allow": tuple(allow),
            "deny": tuple(deny),
            "model": model,
            "max_turns": max_turns,
            "permission_mode": permission,
            "isolation": isolation,
        }


class AgentRoleCatalog:
    def __init__(
        self,
        project_root: Path,
        user_root: Path,
        builtin_root: Path,
        plugin_roots: Iterable[Path] = (),
        parser: Optional[AgentRoleParser] = None,
    ) -> None:
        self._roots = {
            AgentRoleSource.PROJECT: (Path(project_root),),
            AgentRoleSource.USER: (Path(user_root),),
            AgentRoleSource.BUILTIN: (Path(builtin_root),),
            AgentRoleSource.PLUGIN: tuple(Path(p) for p in plugin_roots),
        }
        self._parser = parser or AgentRoleParser()
        self._snapshot = AgentRoleCatalogSnapshot()

    @property
    def snapshot(self) -> AgentRoleCatalogSnapshot:
        return self._snapshot

    def resolve(self, name: str) -> Optional[AgentRoleDefinition]:
        return self._snapshot.effective.get(name)

    def prepare_refresh(self) -> AgentRoleCatalogCandidate:
        diagnostics: list[AgentRoleDiagnostic] = []
        by_source: dict[AgentRoleSource, dict[str, list[AgentRoleDefinition]]] = {
            source: defaultdict(list) for source in _PRIORITY
        }
        for source in _PRIORITY:
            for path in self._discover(self._roots[source]):
                try:
                    definition = self._parser.parse_file(path, source)
                except AgentRoleParseError as exc:
                    diagnostics.append(AgentRoleDiagnostic("error", "parse", str(exc), exc.path, exc.role_name))
                    continue
                by_source[source][definition.name].append(definition)
        effective: dict[str, AgentRoleDefinition] = {}
        shadowed: dict[str, tuple[AgentRoleDefinition, ...]] = {}
        all_names = sorted({n for values in by_source.values() for n in values})
        for name in all_names:
            selected: Optional[AgentRoleDefinition] = None
            hidden: list[AgentRoleDefinition] = []
            for source in _PRIORITY:
                values = by_source[source].get(name, [])
                if len(values) > 1:
                    diagnostics.append(AgentRoleDiagnostic(
                        "error", "catalog", f"duplicate role {name!r} in {source.value} tier", role_name=name
                    ))
                    hidden.extend(values)
                    continue
                if values and selected is None:
                    selected = values[0]
                elif values:
                    hidden.extend(values)
            if selected is not None:
                effective[name] = selected
                if hidden:
                    shadowed[name] = tuple(hidden)
        old_key = self._key(self._snapshot)
        candidate = AgentRoleCatalogSnapshot(
            generation=self._snapshot.generation,
            effective=MappingProxyType(effective),
            shadowed=MappingProxyType(shadowed),
            diagnostics=tuple(diagnostics),
        )
        if self._key(candidate) != old_key:
            candidate = AgentRoleCatalogSnapshot(
                generation=self._snapshot.generation + 1,
                effective=candidate.effective,
                shadowed=candidate.shadowed,
                diagnostics=candidate.diagnostics,
            )
        return AgentRoleCatalogCandidate(self._snapshot, candidate)

    def commit(
        self,
        candidate: AgentRoleCatalogCandidate,
        current: AgentRoleCatalogSnapshot | None = None,
    ) -> AgentRoleCatalogSnapshot:
        if candidate.previous is not self._snapshot:
            raise RuntimeError("stale role catalog candidate")
        self._snapshot = current or candidate.current
        return self._snapshot

    def refresh(self) -> AgentRoleCatalogSnapshot:
        return self.commit(self.prepare_refresh())

    @staticmethod
    def _discover(roots: Iterable[Path]) -> tuple[Path, ...]:
        found = []
        for root in roots:
            if not root.expanduser().is_dir():
                continue
            try:
                found.extend(p.absolute() for p in root.expanduser().iterdir() if p.is_file() and p.suffix.lower() == ".md")
            except OSError:
                continue
        return tuple(sorted(found, key=lambda p: str(p).casefold()))

    @staticmethod
    def _key(snapshot: AgentRoleCatalogSnapshot) -> tuple:
        return (
            tuple((n, d.source.value, str(d.source_path), d.fingerprint) for n, d in sorted(snapshot.effective.items())),
            tuple((n, tuple(d.fingerprint for d in values)) for n, values in sorted(snapshot.shadowed.items())),
            tuple((d.severity, d.phase, d.message, str(d.path)) for d in snapshot.diagnostics),
        )


class AgentRoleValidator:
    def validate(self, snapshot: AgentRoleCatalogSnapshot, tool_names: Iterable[str]) -> AgentRoleCatalogSnapshot:
        known = set(tool_names)
        effective = dict(snapshot.effective)
        diagnostics = list(snapshot.diagnostics)
        for name, role in list(effective.items()):
            missing = sorted(role.allowed_tools - known)
            if missing:
                effective.pop(name)
                diagnostics.append(AgentRoleDiagnostic(
                    "error", "validate", "unknown allowed tool(s): " + ", ".join(missing), role.source_path, name
                ))
            unknown_denied = sorted(role.denied_tools - known)
            if unknown_denied:
                diagnostics.append(AgentRoleDiagnostic(
                    "warning", "validate", "unknown denied tool(s): " + ", ".join(unknown_denied), role.source_path, name
                ))
        return AgentRoleCatalogSnapshot(
            generation=snapshot.generation,
            effective=MappingProxyType(effective),
            shadowed=snapshot.shadowed,
            diagnostics=tuple(diagnostics),
        )
