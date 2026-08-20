"""Selection of complete conversation turns for isolated skills."""

from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

from flickcode.providers.base import Message


class CompleteTurnSelector:
    """Copies the most recent complete user-led turns without system/thinking."""

    def select(self, messages: Sequence[Message], count: int) -> list[Message]:
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("history count must be a non-negative integer")
        if count == 0:
            return []
        turns: List[List[Message]] = []
        current: List[Message] = []
        for message in messages:
            if message.role == "user":
                if self._is_complete(current):
                    turns.append(current)
                current = [message]
            elif current and message.role in ("assistant", "tool"):
                current.append(message)
        if self._is_complete(current):
            turns.append(current)
        selected = turns[-count:]
        return [self._clone(message) for turn in selected for message in turn]

    @staticmethod
    def _is_complete(turn: Sequence[Message]) -> bool:
        if not turn or turn[0].role != "user" or not any(item.role == "assistant" for item in turn):
            return False
        pending = set()
        for message in turn[1:]:
            if message.role == "assistant" and message.tool_calls:
                pending.update(call.get("id", "") for call in message.tool_calls)
            elif message.role == "tool":
                pending.discard(message.tool_call_id)
        return not pending

    @staticmethod
    def _clone(message: Message) -> Message:
        return Message(
            role=message.role,
            content=message.content,
            tool_call_id=message.tool_call_id,
            tool_calls=[dict(call) for call in message.tool_calls],
        )

