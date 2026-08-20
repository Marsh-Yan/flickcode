"""WriteFile tool — create or overwrite a file."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from flickcode.tools.cache import FileContentCache
from flickcode.tools.paths import resolve_tool_path
from flickcode.tools.base import BaseTool, ToolParameter, ToolResult, ToolSpec


class WriteFileTool(BaseTool):
    """Write text content to a file, creating directories as needed."""

    spec = ToolSpec(
        name="write_file",
        description=(
            "Write text content to a file. "
            "Creates parent directories if they don't exist. "
            "Overwrites the file if it already exists."
        ),
        parameters=[
            ToolParameter(
                name="path",
                type="string",
                description="Absolute or relative path to the file.",
                required=True,
            ),
            ToolParameter(
                name="content",
                type="string",
                description="The text content to write.",
                required=True,
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
        path: str = params["path"]
        content: str = params["content"]

        try:
            p = resolve_tool_path(cwd, path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            if file_cache is not None:
                file_cache.invalidate(p)
            return ToolResult(
                success=True,
                output=f"Successfully wrote {len(content)} bytes to {path}",
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
                error=f"Error writing {path}: {exc}",
            )
