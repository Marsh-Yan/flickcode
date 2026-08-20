"""Narrow host protocol used to compose the Skill executor."""

from __future__ import annotations

from typing import Protocol, Sequence

from flickcode.agent import AgentMode
from flickcode.providers.base import Message


class SkillHost(Protocol):
    @property
    def active_session_id(self) -> str: ...

    @property
    def messages(self) -> Sequence[Message]: ...

    def refresh_skills(self) -> None: ...

    def current_agent_mode(self) -> AgentMode: ...

