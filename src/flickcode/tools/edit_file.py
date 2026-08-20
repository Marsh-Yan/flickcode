"""EditFile tool — string-replacement based file editing.

Uses exact-match-then-replace with strict uniqueness checking.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from flickcode.tools.cache import FileContentCache
from flickcode.tools.paths import resolve_tool_path
from flickcode.tools.base import BaseTool, ToolParameter, ToolResult, ToolSpec


class EditFileTool(BaseTool):
    """Edit a file by replacing an *old_string* with a *new_string*.

    The replacement is a single exact-match-then-replace operation.
    If *old_string* appears zero or multiple times the tool returns a
    descriptive error so the model can try again with more context.
    """

    spec = ToolSpec(
        name="edit_file",
        description=(
            "Replace an exact string match in a file. "
            "The old_string must match exactly once. "
            "If it is not found, or found multiple times, "
            "a clear error is returned so you can adjust your input."
        ),
        parameters=[
            ToolParameter(
                name="path",
                type="string",
                description="Absolute or relative path to the file.",
                required=True,
            ),
            ToolParameter(
                name="old_string",
                type="string",
                description=(
                    "The exact text to search for. "
                    "Must match exactly once in the file."
                ),
                required=True,
            ),
            ToolParameter(
                name="new_string",
                type="string",
                description="The text to replace old_string with.",
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
        old_string: str = params["old_string"]
        new_string: str = params["new_string"]

        try:
            resolved = resolve_tool_path(cwd, path)
            content = (
                file_cache.read_text(resolved)
                if file_cache is not None
                else resolved.read_text(encoding="utf-8")
            )
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
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Error reading {path}: {exc}",
            )

        count = content.count(old_string)
        if count == 0:
            return ToolResult(
                success=False,
                error=(
                    f"old_string not found in {path}. "
                    "Make sure you include the exact text — "
                    "including surrounding context — from the file."
                ),
            )
        if count > 1:
            return ToolResult(
                success=False,
                error=(
                    f"old_string found {count} times in {path}, "
                    "expected exactly 1 match. "
                    "Include more surrounding context "
                    "to make the match unique."
                ),
            )

        new_content = content.replace(old_string, new_string, 1)

        try:
            resolved.write_text(new_content, encoding="utf-8")
            if file_cache is not None:
                file_cache.invalidate(resolved)
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Error writing {path}: {exc}",
            )

        return ToolResult(
            success=True,
            output=(
                f"Successfully edited {path}. "
                f"Replaced 1 occurrence."
            ),
        )
