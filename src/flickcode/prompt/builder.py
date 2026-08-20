"""System prompt builder — modular, cache-aware system prompt assembly.

Provides ``PromptSection`` (abstract base) and ``SystemPromptBuilder``
that assembles sections into a two-channel output:

- **system channel** — stable content cached by the API provider.
- **messages channel** — dynamic content (env info, runtime whispers).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from flickcode.providers.base import Message


# ── Section base ─────────────────────────────────────────────────────

class PromptSection(ABC):
    """A single logical module of the system prompt.

    Subclasses call ``super().__init__()`` with the section's metadata
    and override ``render()`` to produce the section's text.

    Sections are ordered by ``priority`` (lower = earlier). The
    ``channel`` attribute determines where the rendered text goes:

    - ``"system"`` — into the API's system parameter (cached).
    - ``"messages"`` — into a ``Message(role="system")`` in the
      messages list (not cached).
    """

    def __init__(
        self,
        name: str = "",
        priority: int = 100,
        channel: str = "system",
    ):
        self.name = name
        self.priority = priority
        self.channel = channel

    @abstractmethod
    def render(self, context: dict[str, Any]) -> str:
        """Render this section's content.

        Args:
            context: Runtime context dict (mode, iteration, cwd, …).

        Returns:
            The section text, or an empty string to omit this section.
        """
        ...


# ── Builder ──────────────────────────────────────────────────────────

class SystemPromptBuilder:
    """Assembles a set of ``PromptSection`` instances into a two-channel
    system prompt.

    Usage::

        builder = SystemPromptBuilder()
        builder.add_section(MySection())

        stable, extra = builder.build({
            "mode": AgentMode.FULL,
            "iteration": 1,
            "cwd": "/home/project",
        })
        # stable  → API system parameter (cached)
        # extra   → list[Message] injected into the messages list
    """

    def __init__(self) -> None:
        self._sections: dict[str, PromptSection] = {}

    # ── Registration ─────────────────────────────────────────────────

    def add_section(self, section: PromptSection) -> None:
        """Register a section. Replaces any existing section with the
        same ``name``."""
        self._sections[section.name] = section

    def remove_section(self, name: str) -> None:
        """Unregister a section by name.  No-op if not found."""
        self._sections.pop(name, None)

    def get_section(self, name: str) -> PromptSection | None:
        """Look up a registered section by name."""
        return self._sections.get(name)

    def list_sections(self) -> list[str]:
        """Return registered section names in render order."""
        return [s.name for s in self._sorted_sections()]

    # ── Build ────────────────────────────────────────────────────────

    def build(
        self,
        context: dict[str, Any] | None = None,
    ) -> tuple[str, list[Message]]:
        """Build the system prompt.

        Args:
            context: Runtime context passed to each section's ``render()``.

        Returns:
            A ``(stable_prompt, extra_messages)`` pair:

            - **stable_prompt** — all ``channel="system"`` sections,
              concatenated with blank-line separators.  Pass this to
              the provider's ``system`` parameter.
            - **extra_messages** — ``Message(role="system")`` objects
              for every ``channel="messages"`` section.  Inject these
              into the messages list before the current user turn.
        """
        ctx = context or {}
        stable_parts: list[str] = []
        extra_msgs: list[Message] = []

        for section in self._sorted_sections():
            text = section.render(ctx)
            if not text:
                continue
            if section.channel == "system":
                stable_parts.append(text)
            else:
                extra_msgs.append(
                    Message(role="system", content=text)
                )

        stable_prompt = "\n\n".join(stable_parts)
        return stable_prompt, extra_msgs

    # ── Internal ─────────────────────────────────────────────────────

    def _sorted_sections(self) -> list[PromptSection]:
        """Return all sections sorted by priority (ascending)."""
        return sorted(self._sections.values(), key=lambda s: s.priority)
