"""UI ports and test doubles used by command handlers."""

from __future__ import annotations

from typing import Any, Protocol

from flickcode.agent import AgentMode
from flickcode.commands.models import InteractionMode, TokenStatus


class CommandUI(Protocol):
    """Framework-neutral interface required by command handlers."""

    def show_message(self, text: str) -> None: ...

    def show_progress(self, text: str) -> None: ...

    def show_error(self, text: str) -> None: ...

    def send_user_message(self, text: str, mode: AgentMode) -> None: ...

    def run_skill(self, name: str, user_input: str, mode: AgentMode) -> None: ...

    def get_mode(self) -> InteractionMode: ...

    def set_mode(self, mode: InteractionMode) -> None: ...

    def token_status(self) -> TokenStatus: ...

    def refresh_status(self) -> None: ...

    def clear_display(self) -> None: ...


class InMemoryCommandUI:
    """Deterministic UI fake for command unit tests and integrations."""

    def __init__(self, mode: InteractionMode = InteractionMode.DEFAULT) -> None:
        self.mode = mode
        self.messages: list[str] = []
        self.progress: list[str] = []
        self.errors: list[str] = []
        self.sent_messages: list[tuple[str, AgentMode]] = []
        self.skill_calls: list[tuple[str, str, AgentMode]] = []
        self.refresh_count = 0
        self.clear_count = 0
        self.status = TokenStatus()
        self.calls: list[tuple[str, Any]] = []

    def show_message(self, text: str) -> None:
        self.messages.append(text)
        self.calls.append(("message", text))

    def show_progress(self, text: str) -> None:
        self.progress.append(text)
        self.calls.append(("progress", text))

    def show_error(self, text: str) -> None:
        self.errors.append(text)
        self.calls.append(("error", text))

    def send_user_message(self, text: str, mode: AgentMode) -> None:
        self.sent_messages.append((text, mode))
        self.calls.append(("send", (text, mode)))

    def run_skill(self, name: str, user_input: str, mode: AgentMode) -> None:
        self.skill_calls.append((name, user_input, mode))
        self.calls.append(("run_skill", (name, user_input, mode)))
        if name == "review":
            prompt = "Review the current project and changes for correctness, risks, and missing tests."
            if user_input.strip():
                prompt += f" Focus especially on: {user_input.strip()}"
            self.sent_messages.append((prompt, mode))

    def get_mode(self) -> InteractionMode:
        self.calls.append(("get_mode", self.mode))
        return self.mode

    def set_mode(self, mode: InteractionMode) -> None:
        self.mode = mode
        self.calls.append(("set_mode", mode))

    def token_status(self) -> TokenStatus:
        self.calls.append(("token_status", self.status))
        return self.status

    def refresh_status(self) -> None:
        self.refresh_count += 1
        self.calls.append(("refresh_status", None))

    def clear_display(self) -> None:
        self.clear_count += 1
        self.calls.append(("clear_display", None))
