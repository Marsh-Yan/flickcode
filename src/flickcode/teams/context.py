"""Persistent Agent context snapshots for team members."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Optional

from flickcode.providers.base import Message
from flickcode.teams.paths import MemberLayout


def _message_to_dict(message: Message) -> dict[str, Any]:
    return {
        "role": message.role,
        "content": message.content,
        "tool_call_id": message.tool_call_id,
        "tool_calls": list(message.tool_calls),
    }


def _message_from_dict(value: dict[str, Any]) -> Message:
    return Message(
        role=str(value.get("role", "")),
        content=str(value.get("content", "")),
        tool_call_id=str(value.get("tool_call_id", "")),
        tool_calls=list(value.get("tool_calls", [])),
    )


class MemberContextStore:
    def __init__(self, layout: MemberLayout) -> None:
        self.layout = layout

    def load(self) -> dict[str, Any]:
        if not self.layout.context.exists():
            return {"messages": [], "last_task_id": None, "summary": ""}
        try:
            with self.layout.context.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            if not isinstance(value, dict):
                raise ValueError("member context must be a map")
            messages = [_message_from_dict(item) for item in value.get("messages", [])]
            return {
                "messages": messages,
                "last_task_id": value.get("last_task_id"),
                "summary": str(value.get("summary", "")),
            }
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"member context could not be recovered: {exc}") from exc

    def save(
        self,
        messages: Iterable[Message],
        *,
        last_task_id: Optional[str] = None,
        summary: str = "",
    ) -> None:
        self.layout.root.mkdir(parents=True, exist_ok=True)
        value = {
            "messages": [_message_to_dict(message) for message in messages],
            "last_task_id": last_task_id,
            "summary": summary,
        }
        temporary = self.layout.context.with_name(self.layout.context.name + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.replace(self.layout.context)

    def append(self, messages: Iterable[Message], *, last_task_id: Optional[str] = None, summary: str = "") -> dict[str, Any]:
        current = self.load()
        combined = list(current["messages"]) + list(messages)
        self.save(
            combined,
            last_task_id=last_task_id if last_task_id is not None else current.get("last_task_id"),
            summary=summary or current.get("summary", ""),
        )
        return self.load()

