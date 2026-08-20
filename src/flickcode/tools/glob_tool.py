"""Glob tool — find files matching a glob pattern."""

from __future__ import annotations

import glob as glob_module
from pathlib import Path
from typing import Optional

from flickcode.tools.base import BaseTool, ToolParameter, ToolResult, ToolSpec
from flickcode.tools.cache import FileContentCache
from flickcode.tools.paths import resolve_tool_path


class GlobTool(BaseTool):
    """Find files matching a glob pattern, with an optional root directory."""

    spec = ToolSpec(
        name="glob",
        description=(
            "Find files and directories matching a glob pattern. "
            "Supports ``**`` for recursive matching. "
            'Example: ``**/*.py`` finds all Python files recursively.'
        ),
        parameters=[
            ToolParameter(
                name="pattern",
                type="string",
                description="The glob pattern to match.",
                required=True,
            ),
            ToolParameter(
                name="path",
                type="string",
                description=(
                    "Root directory for the search. "
                    "Defaults to the current working directory."
                ),
                required=False,
            ),
        ],
    )

    def execute(
        self,
        params: dict,
        *,
        cwd: Optional[Path] = None,
        file_cache: Optional[FileContentCache] = None,
    ) -> ToolResult:
        pattern: str = params["pattern"]
        root: str = params.get("path", ".")

        try:
            root_path = resolve_tool_path(cwd, root)
        except (OSError, ValueError) as exc:
            return ToolResult(success=False, error=f"Path does not exist: {root} ({exc})")
        if not root_path.exists():
            return ToolResult(
                success=False,
                error=f"Path does not exist: {root}",
            )
        if not root_path.is_dir():
            return ToolResult(
                success=False,
                error=f"Path is not a directory: {root}",
            )

        try:
            pattern_path = Path(pattern)
            search = pattern_path if pattern_path.is_absolute() else root_path / pattern_path
            matches = glob_module.glob(str(search), recursive=True)
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Glob error: {exc}",
            )

        matches_sorted = sorted(
            str(Path(match).resolve().relative_to(root_path))
            for match in matches
            if Path(match).resolve() == root_path
            or root_path in Path(match).resolve().parents
        )
        output = "\n".join(matches_sorted) if matches_sorted else "(no matches)"

        return ToolResult(
            success=True,
            output=output,
        )
