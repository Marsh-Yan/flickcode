"""Grep tool — search file contents by regular expression."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from flickcode.tools.base import BaseTool, ToolParameter, ToolResult, ToolSpec
from flickcode.tools.cache import FileContentCache
from flickcode.tools.paths import resolve_tool_path


class GrepTool(BaseTool):
    """Search file contents with a regular expression.

    Optionally filters by a glob include pattern and supports both
    content-view and file-list output modes.
    """

    spec = ToolSpec(
        name="grep",
        description=(
            "Search file contents using a regular expression. "
            "Returns matching lines with file names, "
            'or just file names when *output_mode* is "files_with_matches".'
        ),
        parameters=[
            ToolParameter(
                name="pattern",
                type="string",
                description="The regular expression to search for.",
                required=True,
            ),
            ToolParameter(
                name="path",
                type="string",
                description=(
                    "Directory to search in. "
                    "Defaults to the current working directory."
                ),
                required=False,
            ),
            ToolParameter(
                name="include",
                type="string",
                description=(
                    "Glob pattern to filter files "
                    '(e.g. ``"*.py"``, ``"*.{ts,tsx}"``).'
                ),
                required=False,
            ),
            ToolParameter(
                name="output_mode",
                type="string",
                description=(
                    '"content" — show matching lines with file names. '
                    '"files_with_matches" — show only file names.'
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
        include: str | None = params.get("include")
        output_mode: str = params.get("output_mode", "content")

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
            regex = re.compile(pattern)
        except re.error as exc:
            return ToolResult(
                success=False,
                error=f"Invalid regex pattern: {exc}",
            )

        # Collect files to search
        if include:
            import glob as glob_module

            include_path = Path(include)
            search = include_path if include_path.is_absolute() else root_path / include_path
            raw = glob_module.glob(str(search), recursive=True)
            files = [
                Path(f).resolve()
                for f in raw
                if Path(f).resolve().is_file()
                and (Path(f).resolve() == root_path or root_path in Path(f).resolve().parents)
            ]
        else:
            files = [p for p in root_path.rglob("*") if p.is_file()]

        results: list[str] = []
        matched_files: set[str] = set()

        try:
            for file_path in files:
                try:
                    if file_cache is not None:
                        content = file_cache.read_text(file_path)
                    else:
                        content = file_path.read_text(
                            encoding="utf-8", errors="replace"
                        )
                except Exception:
                    continue  # skip binary/unreadable files

                for lineno, line in enumerate(content.splitlines(), 1):
                    if regex.search(line):
                        rel = str(file_path.relative_to(root_path))
                        if output_mode == "files_with_matches":
                            matched_files.add(rel)
                            break  # one match per file is enough
                        else:
                            results.append(f"{rel}:{lineno}:{line}")
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Error during search: {exc}",
            )

        if output_mode == "files_with_matches":
            output = "\n".join(sorted(matched_files)) if matched_files else "(no matches)"
        else:
            output = "\n".join(results) if results else "(no matches)"

        return ToolResult(success=True, output=output)
