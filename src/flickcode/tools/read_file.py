"""ReadFile tool — reads a text file, optionally within a line range."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from flickcode.tools.cache import FileContentCache
from flickcode.tools.paths import resolve_tool_path
from flickcode.tools.base import BaseTool, ToolParameter, ToolResult, ToolSpec


class ReadFileTool(BaseTool):
    """Read a text file from the filesystem."""

    spec = ToolSpec(
        name="read_file",
        description=(
            "Read the contents of a text file. "
            "Optionally specify *offset* (0-based line index) and "
            "*limit* (max lines) to read only a portion."
        ),
        parameters=[
            ToolParameter(
                name="path",
                type="string",
                description="Absolute or relative path to the file.",
                required=True,
            ),
            ToolParameter(
                name="offset",
                type="integer",
                description=(
                    "0-based line index to start reading from. "
                    "Omit to read from the beginning."
                ),
                required=False,
                default=0,
            ),
            ToolParameter(
                name="limit",
                type="integer",
                description=(
                    "Maximum number of lines to return. "
                    "Omit to read the whole file."
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
        path: str = params["path"]  # required
        offset: int = params.get("offset", 0)
        limit: int | None = params.get("limit")

        try:
            resolved = resolve_tool_path(cwd, path)
            content = (
                file_cache.read_text(resolved)
                if file_cache is not None
                else resolved.read_text(encoding="utf-8")
            )
            lines = content.splitlines(keepends=True)
        except FileNotFoundError:
            return ToolResult(
                success=False,
                error=f"File not found: {path}",
            )
        except PermissionError:
            return ToolResult(
                success=False,
                error=f"Permission denied: {path}",
            )
        except IsADirectoryError:
            return ToolResult(
                success=False,
                error=f"Path is a directory, not a file: {path}",
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Error reading {path}: {exc}",
            )

        # Slice lines according to offset/limit
        if limit is not None:
            chunk = lines[offset : offset + limit]
        else:
            chunk = lines[offset:]

        content = "".join(chunk)
        return ToolResult(
            success=True,
            output=content,
        )
