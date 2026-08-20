"""Strict parser for standalone and directory-based skills."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

from flickcode.skills.models import (
    SkillDefinition,
    SkillMode,
    SkillSource,
    SkillToolDefinition,
)


_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_FIELDS = {"name", "description", "tools", "mode", "history", "model"}


class SkillParseError(ValueError):
    def __init__(
        self,
        message: str,
        path: Path,
        skill_name: Optional[str] = None,
    ) -> None:
        self.path = path
        self.skill_name = skill_name
        super().__init__(f"{path}: {message}")


class SkillParser:
    def parse_file(self, path: Path, source: SkillSource) -> SkillDefinition:
        unresolved = path.expanduser().absolute()
        if unresolved.is_symlink():
            raise SkillParseError("standalone skill must not be a symlink", unresolved)
        path = unresolved.resolve()
        raw = self._read_text(path)
        metadata, body = self._split_frontmatter(raw, path)
        values = self._validate_metadata(metadata, path)
        fingerprint = self._hash_text(raw)
        return self._make_definition(
            values,
            body,
            source,
            path,
            package_root=None,
            custom_tools=(),
            fingerprint=fingerprint,
        )

    def parse_package(self, root: Path, source: SkillSource) -> SkillDefinition:
        unresolved_root = root.expanduser().absolute()
        if unresolved_root.is_symlink():
            raise SkillParseError("package root must not be a symlink", root)
        root = unresolved_root.resolve()
        entry = root / "SKILL.md"
        if not entry.is_file():
            raise SkillParseError("directory skill is missing SKILL.md", entry)
        raw = self._read_text(entry)
        metadata, body = self._split_frontmatter(raw, entry)
        values = self._validate_metadata(metadata, entry)
        custom_tools = self._parse_tools(root, values["name"])
        custom_names = {tool.name for tool in custom_tools}
        missing = sorted(custom_names - set(values["tools"]))
        if missing:
            raise SkillParseError(
                "custom tool(s) missing from tools whitelist: " + ", ".join(missing),
                entry,
                values["name"],
            )
        pieces = [raw]
        for tool in custom_tools:
            pieces.extend((tool.name, tool.fingerprint))
        return self._make_definition(
            values,
            body,
            source,
            entry.resolve(),
            package_root=root,
            custom_tools=custom_tools,
            fingerprint=self._hash_text("\n".join(pieces)),
        )

    def _parse_tools(
        self,
        root: Path,
        skill_name: str,
    ) -> Tuple[SkillToolDefinition, ...]:
        tools_dir = root / "tools"
        if not tools_dir.exists():
            return ()
        if tools_dir.is_symlink() or not tools_dir.is_dir():
            raise SkillParseError("tools must be a real directory", tools_dir, skill_name)
        parsed = []
        seen = set()
        for schema_path in sorted(tools_dir.glob("*.json"), key=lambda p: p.name):
            self._assert_safe_path(root, schema_path, skill_name)
            try:
                raw_text = self._read_text(schema_path)
                raw = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                raise SkillParseError(f"invalid tool JSON: {exc}", schema_path, skill_name) from exc
            if not isinstance(raw, dict):
                raise SkillParseError("tool declaration must be an object", schema_path, skill_name)
            allowed = {"name", "description", "input_schema", "entrypoint"}
            unknown = sorted(set(raw) - allowed)
            missing = sorted(allowed - set(raw))
            if unknown or missing:
                detail = []
                if missing:
                    detail.append("missing " + ", ".join(missing))
                if unknown:
                    detail.append("unknown " + ", ".join(unknown))
                raise SkillParseError("invalid tool declaration: " + "; ".join(detail), schema_path, skill_name)
            name = raw["name"]
            description = raw["description"]
            input_schema = raw["input_schema"]
            entrypoint = raw["entrypoint"]
            if not isinstance(name, str) or not _TOOL_NAME_RE.fullmatch(name):
                raise SkillParseError("tool name is invalid", schema_path, skill_name)
            if name in seen:
                raise SkillParseError(f"duplicate package tool: {name}", schema_path, skill_name)
            if not isinstance(description, str) or not description.strip() or "\n" in description:
                raise SkillParseError("tool description must be one non-empty line", schema_path, skill_name)
            self._validate_input_schema(input_schema, schema_path, skill_name)
            if not isinstance(entrypoint, str) or not entrypoint or Path(entrypoint).is_absolute():
                raise SkillParseError("entrypoint must be a relative path", schema_path, skill_name)
            unresolved_entry = root / entrypoint
            self._assert_safe_path(root, unresolved_entry, skill_name)
            resolved_entry = unresolved_entry.resolve()
            if resolved_entry.suffix.lower() != ".py" or not resolved_entry.is_file():
                raise SkillParseError("entrypoint must reference an existing .py file", schema_path, skill_name)
            script_source = self._read_text(resolved_entry)
            fingerprint = self._hash_text(raw_text + "\n" + script_source)
            parsed.append(
                SkillToolDefinition(
                    name=name,
                    description=description.strip(),
                    input_schema=dict(input_schema),
                    entrypoint=resolved_entry,
                    package_root=root,
                    script_source=script_source,
                    fingerprint=fingerprint,
                )
            )
            seen.add(name)
        return tuple(parsed)

    @staticmethod
    def _validate_input_schema(schema: Any, path: Path, skill_name: str) -> None:
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise SkillParseError("input_schema must be an object schema", path, skill_name)
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict):
            raise SkillParseError("input_schema.properties must be an object", path, skill_name)
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise SkillParseError("input_schema.required must be a string list", path, skill_name)
        if any(item not in properties for item in required):
            raise SkillParseError("input_schema.required references an unknown property", path, skill_name)

    def _split_frontmatter(self, raw: str, path: Path) -> Tuple[Dict[str, Any], str]:
        lines = raw.splitlines(keepends=True)
        if not lines or lines[0].strip() != "---":
            raise SkillParseError("file must start with YAML frontmatter", path)
        closing = None
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                closing = index
                break
        if closing is None:
            raise SkillParseError("frontmatter closing delimiter is missing", path)
        yaml_text = "".join(lines[1:closing])
        body = "".join(lines[closing + 1:]).strip()
        try:
            metadata = yaml.safe_load(yaml_text)
        except yaml.YAMLError as exc:
            raise SkillParseError(f"invalid YAML: {exc}", path) from exc
        if not isinstance(metadata, dict):
            raise SkillParseError("frontmatter must be a mapping", path)
        if not body:
            name = metadata.get("name") if isinstance(metadata.get("name"), str) else None
            raise SkillParseError("skill instructions must not be empty", path, name)
        return metadata, body

    def _validate_metadata(self, raw: Dict[str, Any], path: Path) -> Dict[str, Any]:
        name_hint = raw.get("name") if isinstance(raw.get("name"), str) else None
        unknown = sorted(set(raw) - _FIELDS)
        required = {"name", "description", "tools", "mode"}
        missing = sorted(required - set(raw))
        if unknown or missing:
            details = []
            if missing:
                details.append("missing " + ", ".join(missing))
            if unknown:
                details.append("unknown " + ", ".join(unknown))
            raise SkillParseError("invalid frontmatter fields: " + "; ".join(details), path, name_hint)
        name = raw["name"]
        description = raw["description"]
        tools = raw["tools"]
        mode_raw = raw["mode"]
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise SkillParseError("name must match ^[a-z][a-z0-9-]*$", path, name_hint)
        if not isinstance(description, str) or not description.strip() or "\n" in description:
            raise SkillParseError("description must be one non-empty line", path, name)
        if not isinstance(tools, list) or not all(isinstance(item, str) and item for item in tools):
            raise SkillParseError("tools must be a list of non-empty strings", path, name)
        if len(set(tools)) != len(tools):
            raise SkillParseError("tools must not contain duplicates", path, name)
        try:
            mode = SkillMode(mode_raw)
        except (TypeError, ValueError) as exc:
            raise SkillParseError("mode must be shared or isolated", path, name) from exc
        history = raw.get("history")
        model = raw.get("model")
        if mode is SkillMode.SHARED:
            if "history" in raw or "model" in raw:
                raise SkillParseError("shared skills must not declare history or model", path, name)
            history = None
            model = None
        else:
            if "history" not in raw or not isinstance(history, int) or isinstance(history, bool) or history < 0:
                raise SkillParseError("isolated skills require a non-negative integer history", path, name)
            if model is not None and (not isinstance(model, str) or not model.strip()):
                raise SkillParseError("model must be a non-empty string", path, name)
        return {
            "name": name,
            "description": description.strip(),
            "tools": tuple(tools),
            "mode": mode,
            "history": history,
            "model": model.strip() if isinstance(model, str) else None,
        }

    @staticmethod
    def _make_definition(
        values: Dict[str, Any],
        body: str,
        source: SkillSource,
        entry_path: Path,
        package_root: Optional[Path],
        custom_tools: Tuple[SkillToolDefinition, ...],
        fingerprint: str,
    ) -> SkillDefinition:
        return SkillDefinition(
            name=values["name"],
            description=values["description"],
            tool_names=values["tools"],
            mode=values["mode"],
            history=values["history"],
            model=values["model"],
            instructions=body,
            source=source,
            entry_path=entry_path,
            package_root=package_root,
            custom_tools=custom_tools,
            fingerprint=fingerprint,
        )

    @staticmethod
    def _read_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SkillParseError(f"cannot read UTF-8 file: {exc}", path) from exc

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _assert_safe_path(root: Path, path: Path, skill_name: str) -> None:
        root = root.resolve()
        unresolved = path.absolute()
        try:
            unresolved.relative_to(root)
        except ValueError as exc:
            raise SkillParseError("path escapes the skill package", path, skill_name) from exc
        current = root
        relative = unresolved.relative_to(root)
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise SkillParseError("symlinks are not allowed in skill packages", current, skill_name)
        try:
            unresolved.resolve().relative_to(root)
        except ValueError as exc:
            raise SkillParseError("resolved path escapes the skill package", path, skill_name) from exc
