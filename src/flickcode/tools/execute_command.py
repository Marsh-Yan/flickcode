"""ExecuteCommand tool — run shell commands with timeout control.

Includes a static high-risk command scanner so the TUI can prompt
for confirmation before destructive operations.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from flickcode.tools.base import BaseTool, ToolParameter, ToolResult, ToolSpec
from flickcode.tools.cache import FileContentCache
from flickcode.tools.paths import normalize_cwd

# Tokens that indicate a command may be destructive.
_HIGH_RISK_TOKENS = frozenset({
    "rm", "mv", "dd", "mkfs", "format", "fdisk",
    "shutdown", "reboot", "init", "killall",
})


def is_high_risk(command: str) -> bool:
    """Return True if the command looks destructive.

    Performs static token analysis only — never executes anything.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        # Unparseable shell syntax — conservatively treat as high risk
        return True

    # Check for shell operators that imply writes
    dangerous_operators = {">", ">>", ">&", "|", "||", "&&", ";", "`", "$("}
    for token in tokens:
        if token in _HIGH_RISK_TOKENS:
            return True
        if any(op in token for op in dangerous_operators):
            return True
    return False


@dataclass
class CommandResult:
    """Detailed results from a command execution."""

    stdout: str
    stderr: str
    exit_code: int


class ExecuteCommandTool(BaseTool):
    """Execute a shell command with a configurable timeout."""

    spec = ToolSpec(
        name="execute_command",
        description=(
            "Execute a shell command and return its output. "
            "The command runs with a configurable timeout "
            "(default 30 seconds). "
            "Non-zero exit codes are returned as successful results "
            "with the exit code included — "
            "they are *not* treated as tool errors."
        ),
        parameters=[
            ToolParameter(
                name="command",
                type="string",
                description="The shell command to run.",
                required=True,
            ),
            ToolParameter(
                name="timeout",
                type="integer",
                description=(
                    "Timeout in seconds. "
                    "Default is 30. Use 0 for no timeout."
                ),
                required=False,
                default=30,
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
        command: str = params["command"]
        timeout: int = params.get("timeout", 30)

        try:
            working_dir = normalize_cwd(cwd)
            completed = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=str(working_dir),
                timeout=None if timeout == 0 else timeout,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                error=(
                    f"Command timed out after {timeout}s: "
                    f"{command[:200]}"
                ),
            )
        except FileNotFoundError as exc:
            return ToolResult(
                success=False,
                error=f"Command not found: {exc}",
            )
        except PermissionError as exc:
            return ToolResult(
                success=False,
                error=f"Permission denied: {exc}",
            )
        except OSError as exc:
            return ToolResult(
                success=False,
                error=f"OS error running command: {exc}",
            )

        output_parts = []
        if completed.stdout:
            output_parts.append(completed.stdout.rstrip("\n"))
        if completed.stderr:
            output_parts.append(f"[stderr]\n{completed.stderr.rstrip(chr(10))}")
        if completed.returncode != 0:
            output_parts.append(f"[exit code: {completed.returncode}]")

        output = "\n".join(output_parts)

        return ToolResult(
            success=True,
            output=output,
        )
