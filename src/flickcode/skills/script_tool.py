"""Subprocess adapter for tools bundled in directory skills."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Optional

from flickcode.skills.models import SkillToolDefinition
from flickcode.tools.base import BaseTool, ToolResult, ToolSpec
from flickcode.tools.cache import FileContentCache


class SkillScriptTool(BaseTool):
    """Executes an immutable Python source snapshot over a JSON protocol."""

    def __init__(
        self,
        definition: SkillToolDefinition,
        project_root: Path,
        timeout_seconds: float = 60.0,
        environment: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.definition = definition
        self.project_root = Path(project_root).resolve()
        self.timeout_seconds = timeout_seconds
        self._environment = dict(environment) if environment is not None else self._minimal_environment()
        self.spec = ToolSpec(
            name=definition.name,
            description=definition.description,
            input_schema=dict(definition.input_schema),
        )

    def execute(
        self,
        params: dict[str, Any],
        *,
        cwd: Optional[Path] = None,
        file_cache: Optional[FileContentCache] = None,
    ) -> ToolResult:
        unsafe = self._validate_definition_path()
        if unsafe:
            return ToolResult(success=False, error=unsafe)
        try:
            payload = json.dumps(params, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            return ToolResult(success=False, error=f"Skill tool input is not JSON serializable: {exc}")
        try:
            completed = subprocess.run(
                [sys.executable, "-c", self.definition.script_source],
                input=payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(Path(cwd).expanduser().resolve() if cwd is not None else self.project_root),
                env=self._environment,
                timeout=self.timeout_seconds,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error=f"Skill tool timed out after {self.timeout_seconds:g} seconds")
        except OSError as exc:
            return ToolResult(success=False, error=f"Skill tool could not start: {self._safe_error(str(exc))}")
        if completed.returncode != 0:
            detail = self._safe_error(completed.stderr.strip()) or "no stderr"
            return ToolResult(success=False, error=f"Skill tool exited with code {completed.returncode}: {detail}")
        if not completed.stdout.strip():
            return ToolResult(success=False, error="Skill tool returned empty stdout")
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            return ToolResult(success=False, error=f"Skill tool returned invalid JSON: {exc}")
        if not isinstance(result, dict) or set(result) - {"success", "output", "error"}:
            return ToolResult(success=False, error="Skill tool result must contain only success, output, and error")
        if not isinstance(result.get("success"), bool):
            return ToolResult(success=False, error="Skill tool result success must be a boolean")
        output = result.get("output", "")
        error = result.get("error")
        if not isinstance(output, str) or (error is not None and not isinstance(error, str)):
            return ToolResult(success=False, error="Skill tool result output/error must be strings")
        return ToolResult(success=result["success"], output=output, error=error)

    def _validate_definition_path(self) -> Optional[str]:
        root = self.definition.package_root.resolve()
        entry = self.definition.entrypoint
        if entry.is_symlink():
            return "Skill tool entrypoint must not be a symlink"
        try:
            entry.resolve().relative_to(root)
        except ValueError:
            return "Skill tool entrypoint escapes its package"
        return None

    @staticmethod
    def _minimal_environment() -> dict[str, str]:
        result = {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        for name in ("SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR"):
            value = os.environ.get(name)
            if value:
                result[name] = value
        return result

    def _safe_error(self, message: str) -> str:
        sanitized = message
        for value in self._environment.values():
            if len(value) >= 8:
                sanitized = sanitized.replace(value, "[redacted]")
        return sanitized[:2048]
