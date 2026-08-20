"""Base provider interface for LLM backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generator, List


@dataclass
class StreamEvent:
    """A single event in a streaming LLM response.

    ``type`` may be one of:
        "text"            — A text content delta.
        "thinking"        — Start of a Claude thinking block.
        "thinking_delta"  — A delta within a Claude thinking block.
        "tool_call"       — The model issued a tool call (content is
                            a JSON object with keys *id*, *name*, *arguments*).
        "tool_result"     — A tool execution result (content is a JSON
                            object with keys *tool_call_id*, *result*).
        "done"            — The stream is finished. Content is a JSON
                            object with optional ``usage`` key:
                            ``{"usage": {"input_tokens": N, "output_tokens": N, "thinking_tokens": N}}``.
        "error"           — An error occurred (content is the message).
    """

    type: str
    content: str


@dataclass
class ToolCallData:
    """Data extracted from a streaming tool-call event."""

    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass
class ToolResultData:
    """Data for a tool execution result event."""

    tool_call_id: str
    result: dict  # Serialised ToolResult dict


@dataclass
class Message:
    """A single message in a conversation.

    ``role`` may be one of:
        "user"      — A human message.
        "assistant" — An assistant message.
        "thinking"  — Claude thinking content.
        "system"    — A system prompt message.
        "tool"      — A tool execution result (carried internally;
                      serialised to API-specific format by the provider).
    """

    role: str
    content: str = ""
    tool_call_id: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class BaseProvider(ABC):
    """Abstract base class for LLM providers.

    All LLM backends must implement stream_chat().
    """

    def __init__(self, config: "ProviderConfig"):
        self.config = config

    @abstractmethod
    def stream_chat(
        self,
        messages: List[Message],
        thinking: bool = False,
        tools: list[dict] | None = None,
        system: str | None = None,
    ) -> Generator[StreamEvent, None, None]:
        """Send messages to the LLM and yield streaming events.

        Args:
            messages: Conversation history.
            thinking: Whether to enable extended thinking (Claude only).
            tools: Optional tool definitions (provider-specific format).
            system: Optional system prompt. When provided it takes
                precedence over any ``role="system"`` messages in the
                ``messages`` list.  This is the primary channel for
                stable/cached prompt content.

        Yields:
            StreamEvent objects for each chunk of the response.
        """
        ...


# Import here to avoid circular dependency at module level
from flickcode.config import ProviderConfig  # noqa: E402, F401
