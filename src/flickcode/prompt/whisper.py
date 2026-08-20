"""Runtime-injection helpers: whisper messages and mode-instruction
frequency control.

Whisper messages carry supplementary instructions that *do not*
participate in the cached system prompt.  They are injected into
the messages list before each provider call.
"""

from __future__ import annotations

from typing import Any

from flickcode.providers.base import Message

# ── Tag ──────────────────────────────────────────────────────────────

WHISPER_TAG = "[whisper]"


def make_whisper_message(text: str) -> Message:
    """Create a whisper-tagged message for runtime injection.

    The message uses ``role="system"`` with the ``[whisper]`` prefix
    so provider layers can distinguish it from ordinary user content.
    """
    return Message(role="system", content=f"{WHISPER_TAG}{text}")


# ── Mode-instruction frequency control ──────────────────────────────

def should_inject_full_mode_instruction(iteration: int) -> bool:
    """Decide whether this iteration should receive the *full* mode
    instruction or a condensed one.

    Schedule (1-indexed iterations)::

        1 → full
        2 → condensed
        3 → condensed
        4 → full
        5 → condensed
        6 → condensed
        7 → full … and so on.

    Args:
        iteration: The current ReAct loop iteration (1-indexed).

    Returns:
        ``True`` when a full instruction should be injected.
    """
    if iteration <= 0:
        return False
    return (iteration - 1) % 3 == 0  # 1, 4, 7, 10 …


# Lazy import for AgentMode to avoid circular dependency
# (agent.py → prompt → whisper → agent)
_MODE_INSTRUCTIONS: dict[str, str] | None = None
_MODE_CONDENSED: dict[str, str] | None = None


def _ensure_mode_dicts() -> None:
    """Populate mode instruction dicts on first use."""
    global _MODE_INSTRUCTIONS, _MODE_CONDENSED
    if _MODE_INSTRUCTIONS is not None:
        return

    from flickcode.agent import AgentMode

    _MODE_INSTRUCTIONS = {
        AgentMode.PLAN: (
            "You are in **Plan Mode**. Only the following read-only tools "
            "are available: ``read_file``, ``glob``, ``grep``. You may "
            "NOT call ``write_file``, ``edit_file``, or "
            "``execute_command``. Use this mode to explore the codebase "
            "and produce a written plan."
        ),
        AgentMode.EXECUTE: (
            "You are in **Execute Mode**. All tools are available, "
            "including ``write_file``, ``edit_file``, and "
            "``execute_command``. Carry out the changes needed based on "
            "the plan."
        ),
        AgentMode.FULL: (
            "You are in **Full Mode**. All tools are available."
        ),
    }

    _MODE_CONDENSED = {
        AgentMode.PLAN: "[whisper]Plan Mode — read-only (read_file, glob, grep).",
        AgentMode.EXECUTE: "[whisper]Execute Mode — all tools available.",
        AgentMode.FULL: "",
    }


def make_mode_instruction(
    mode: Any,
    full: bool = True,
) -> str | None:
    """Generate the mode-instruction text for a given mode.

    Args:
        mode: The current ``AgentMode`` value.
        full: ``True`` for the complete instruction, ``False`` for
              a condensed one-liner.

    Returns:
        The instruction text, or ``None`` when there is nothing to
        inject (e.g. FULL mode in condensed form).
    """
    _ensure_mode_dicts()
    if full:
        return _MODE_INSTRUCTIONS.get(mode)
    condensed = _MODE_CONDENSED.get(mode, "")
    return condensed or None
