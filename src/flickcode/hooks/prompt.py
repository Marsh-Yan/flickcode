"""System-prompt section for persistent Hook injections."""

from __future__ import annotations

from typing import Any

from flickcode.prompt.builder import PromptSection


class HookPromptSection(PromptSection):
    def __init__(self) -> None:
        super().__init__(name="hook_prompts", priority=5, channel="system")

    def render(self, context: dict[str, Any]) -> str:
        prompts = tuple(context.get("hook_prompts", ()))
        if not prompts:
            return ""
        return "## Hook Instructions\n\n" + "\n\n".join(str(item) for item in prompts)
