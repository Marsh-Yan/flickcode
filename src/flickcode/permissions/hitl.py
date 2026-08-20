"""Session-level HITL (human-in-the-loop) permit memory.

When a user chooses "Allow this session", the decision is recorded
here so the same tool + pattern combination won't prompt again
until the session ends.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch


@dataclass
class HITLMemory:
    """In-memory store of session-level permits.

    Usage::

        mem = HITLMemory()
        mem.add("execute_command", "npm *")
        mem.check("execute_command", {"command": "npm install"})  # True
    """

    _session_permits: dict[str, list[str]] = field(default_factory=dict)

    def add(self, tool: str, pattern: str) -> None:
        """Record a session-level permit for *tool* + *pattern*."""
        self._session_permits.setdefault(tool, []).append(pattern)

    def check(self, tool_name: str, params: dict) -> bool:
        """Return True when a session permit covers this call."""
        permits = self._session_permits.get(tool_name, [])
        if not permits:
            return False
        for v in params.values():
            if isinstance(v, str):
                for pat in permits:
                    if fnmatch(v, pat):
                        return True
        return False

    def clear(self) -> None:
        """Reset all session permits (e.g. on session restart)."""
        self._session_permits.clear()
