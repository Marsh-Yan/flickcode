"""Explicit working-directory path helpers for tools."""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def normalize_cwd(cwd: Optional[Path] = None) -> Path:
    """Return an absolute directory for a tool call.

    Production AgentLoop calls always provide cwd. The fallback remains only
    for direct legacy tool invocations and is deliberately kept in this
    compatibility helper instead of scattered through individual tools.
    """
    root = Path(cwd) if cwd is not None else Path.cwd()
    root = root.expanduser().resolve()
    if not root.is_absolute() or not root.is_dir():
        raise ValueError(f"Tool cwd must be an existing absolute directory: {root}")
    return root


def resolve_tool_path(cwd: Optional[Path], raw: str) -> Path:
    root = normalize_cwd(cwd)
    if not isinstance(raw, str) or not raw:
        raise ValueError("Tool path must be a non-empty string")
    value = Path(raw)
    resolved = value.expanduser() if value.is_absolute() else root / value
    return resolved.resolve(strict=False)


__all__ = ["normalize_cwd", "resolve_tool_path"]
