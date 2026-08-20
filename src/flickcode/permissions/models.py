"""Core data models for the permission system."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PermissionMode(str, Enum):
    """Global permission strictness level.

    ``STRICT``     — Blacklist + sandbox + rules only; anything not
                     explicitly allowed is denied. No HITL prompts.
    ``DEFAULT``    — Blacklist + sandbox + rules; falls through to HITL
                     when no rule matches.
    ``PERMISSIVE`` — Blacklist only; everything else is allowed.
    """

    STRICT = "strict"
    DEFAULT = "default"
    PERMISSIVE = "permissive"


@dataclass
class CheckResult:
    """The outcome of a single permission check.

    Attributes:
        allowed: True when the operation is permitted, False when denied,
                 and **None** when the engine cannot decide and needs
                 human-in-the-loop input (HITL mode only).
        reason:  A human-readable explanation (displayed in the TUI).
        layer:   Which layer produced the verdict:
                 ``"blacklist"`` | ``"sandbox"`` | ``"rule"`` |
                 ``"hitl_memory"`` | ``"mode"`` | ``"hitl"``
    """

    allowed: bool | None
    reason: str
    layer: str
