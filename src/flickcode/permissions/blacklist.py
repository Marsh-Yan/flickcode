"""Hard-coded dangerous-command blacklist.

Patterns are matched with :func:`re.fullmatch` and are **never**
configurable — this is the innermost safety net that cannot be
overridden by rule files or permission modes.
"""

from __future__ import annotations

import re
from typing import ClassVar

# ── Each pattern is a (regex, description) pair ───────────────────
# We use match(), so each pattern describes a *prefix* of a
# dangerous command (e.g. "dd if=" matches "dd if=/dev/sda ...").
_PATTERNS: ClassVar[list[tuple[re.Pattern, str]]] = [
    # ── Recursive filesystem destruction ──────────────────────────
    (re.compile(r"^\s*rm\s+(-rf|--recursive)\s+/\s*$"),
     "rm -rf / (filesystem root deletion)"),
    (re.compile(r"^\s*rm\s+(-rf|--recursive)\s+/\s+"),
     "rm -rf / (filesystem root deletion)"),

    # ── Block-device raw writes ───────────────────────────────────
    (re.compile(r"^\s*dd\s+if="),
     "dd if= (raw block-device write)"),

    # ── Formatting / partitioning ─────────────────────────────────
    (re.compile(r"^\s*mkfs\."),
     "mkfs.* (filesystem creation)"),
    (re.compile(r"^\s*mkfs\s"),
     "mkfs (filesystem creation)"),
    (re.compile(r"^\s*fdisk\s"),
     "fdisk (partition manipulation)"),
    (re.compile(r"^\s*parted\s"),
     "parted (partition manipulation)"),

    # ── System power management ───────────────────────────────────
    (re.compile(r"^\s*shutdown\s"),
     "shutdown (system shutdown)"),
    (re.compile(r"^\s*reboot\s"),
     "reboot (system reboot)"),
    (re.compile(r"^\s*poweroff\s"),
     "poweroff (system power-off)"),
    (re.compile(r"^\s*init\s"),
     "init (runlevel change)"),
    (re.compile(r"^\s*halt\s"),
     "halt (system halt)"),

    # ── Process mass-kill ─────────────────────────────────────────
    (re.compile(r"^\s*killall\s"),
     "killall (kill all processes by name)"),
    (re.compile(r"^\s*pkill\s"),
     "pkill (kill processes by pattern)"),

    # ── Permission destruction ────────────────────────────────────
    (re.compile(r"^\s*chmod\s+(-R|--recursive)\s+777\s+/"),
     "chmod -R 777 / (world-writable root)"),

    # ── Direct block-device redirection ───────────────────────────
    (re.compile(r"^\s*[>]+\s+/dev/sd"),
     "redirect to /dev/sd* (raw block-device write)"),
    (re.compile(r"^\s*>\s+/dev/sd"),
     "redirect to /dev/sd* (raw block-device write)"),
]


def check(command: str) -> str | None:
    """Check *command* against the built-in blacklist.

    Uses :func:`re.match` so that patterns only need to describe
    the *prefix* of a dangerous command (e.g. ``dd if=`` covers
    ``dd if=/dev/sda of=/tmp/backup``).

    Args:
        command: The full command string about to be executed.

    Returns:
        *None* when the command passes (not blacklisted), or a
        human-readable description of *why* it was blocked.
    """
    trimmed = command.strip()
    for pattern, description in _PATTERNS:
        if pattern.match(trimmed):
            return description
    return None
