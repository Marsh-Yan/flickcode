"""Anthropic Claude provider implementation."""

from __future__ import annotations

import json
import logging
from typing import Any, Generator, List

import anthropic

from flickcode.providers.base import BaseProvider, Message, StreamEvent

log = logging.getLogger("flickcode.providers.anthropic")


class AnthropicProvider(BaseProvider):
    """Provider for Anthropic Claude API with streaming support."""

    def __init__(self, config: "ProviderConfig", client=None):
        super().__init__(config)
        self.client = client or anthropic.Anthropic(
            api_key=config.api_key,
            base_url=config.base_url,
        )

    def stream_chat(
        self,
        messages: List[Message],
        thinking: bool = False,
        tools: list[dict] | None = None,
        system: str | None = None,
    ) -> Generator[StreamEvent, None, None]:
        """Send messages to Claude and yield streaming events.

        In addition to text/thinking events this version can also yield
        ``tool_call`` events when the model decides to use a tool.

        Args:
            messages: Conversation history.
            thinking: Whether to enable extended thinking.
            tools: Optional Anthropic-format tool definitions.
            system: Optional system prompt. When provided it takes
                precedence over any system messages in ``messages``.

        Yields:
            StreamEvent — text, thinking, tool_call, done, or error.
        """
        anthropic_messages = self._to_anthropic_messages(messages)
        system_prompt = system if system is not None else self._extract_system(messages)

        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": anthropic_messages,
            "stream": True,
            "max_tokens": 8192,
        }

        if system_prompt:
            kwargs["system"] = system_prompt
        if tools:
            kwargs["tools"] = tools
        if thinking:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": 4096}

        try:
            # State machine for tool-use parsing across stream chunks
            tool_use_id: str | None = None
            tool_use_name: str | None = None
            tool_args_buffer: list[str] = []
            usage_data: dict[str, int] = {}

            with self.client.messages.stream(**kwargs) as stream:
                for event in stream:
                    # ── message_start ────────────────────────────────
                    if event.type == "message_start":
                        if hasattr(event, "message") and event.message:
                            msg = event.message
                            if hasattr(msg, "usage") and msg.usage:
                                usage_data["input_tokens"] = getattr(msg.usage, "input_tokens", 0)
                                usage_data["output_tokens"] = getattr(msg.usage, "output_tokens", 0)
                                cache_create = getattr(msg.usage, "cache_creation_input_tokens", None)
                                cache_read = getattr(msg.usage, "cache_read_input_tokens", None)
                                if cache_create is not None:
                                    usage_data["cache_creation_input_tokens"] = cache_create
                                if cache_read is not None:
                                    usage_data["cache_read_input_tokens"] = cache_read

                    # ── content_block_start ──────────────────────────
                    elif event.type == "content_block_start":
                        cb = event.content_block
                        if cb.type == "thinking" and hasattr(cb, "thinking"):
                            yield StreamEvent("thinking", cb.thinking)
                        elif cb.type == "tool_use":
                            tool_use_id = cb.id
                            tool_use_name = cb.name
                            tool_args_buffer = []

                    # ── content_block_delta ──────────────────────────
                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            yield StreamEvent("text", delta.text)
                        elif delta.type == "thinking_delta":
                            yield StreamEvent("thinking_delta", delta.thinking)
                        elif delta.type == "input_json_delta" and tool_use_id:
                            tool_args_buffer.append(delta.partial_json)
                        elif delta.type == "signature_delta":
                            pass  # skip silently

                    # ── content_block_stop ───────────────────────────
                    elif event.type == "content_block_stop":
                        if tool_use_id and tool_use_name:
                            raw = "".join(tool_args_buffer)
                            try:
                                parsed = json.loads(raw) if raw.strip() else {}
                            except json.JSONDecodeError:
                                parsed = {"_raw": raw}
                            yield StreamEvent(
                                "tool_call",
                                json.dumps({
                                    "id": tool_use_id,
                                    "name": tool_use_name,
                                    "arguments": parsed,
                                }),
                            )
                            tool_use_id = None
                            tool_use_name = None
                            tool_args_buffer = []

                    # ── message_stop ─────────────────────────────────
                    elif event.type == "message_stop":
                        done_content = json.dumps({"usage": usage_data}) if usage_data else ""
                        yield StreamEvent("done", done_content)
                        # Log cache metrics at DEBUG level
                        if usage_data:
                            cache_create = usage_data.get("cache_creation_input_tokens")
                            cache_read = usage_data.get("cache_read_input_tokens")
                            if cache_create is not None or cache_read is not None:
                                log.debug(
                                    "Cache metrics — created: %s, read: %s, input: %s, output: %s",
                                    cache_create, cache_read,
                                    usage_data.get("input_tokens"),
                                    usage_data.get("output_tokens"),
                                )
                            else:
                                log.debug(
                                    "No cache — input: %s, output: %s",
                                    usage_data.get("input_tokens"),
                                    usage_data.get("output_tokens"),
                                )

                    # ── message_delta ────────────────────────────────
                    elif event.type == "message_delta":
                        # Capture usage from message_delta (output_tokens)
                        if hasattr(event, "usage") and event.usage:
                            usage_data["input_tokens"] = getattr(event.usage, "input_tokens", usage_data.get("input_tokens", 0))
                            usage_data["output_tokens"] = getattr(event.usage, "output_tokens", 0)
                            cache_create = getattr(event.usage, "cache_creation_input_tokens", None)
                            cache_read = getattr(event.usage, "cache_read_input_tokens", None)
                            if cache_create is not None:
                                usage_data["cache_creation_input_tokens"] = cache_create
                            if cache_read is not None:
                                usage_data["cache_read_input_tokens"] = cache_read
                        elif hasattr(event.delta, "usage") and event.delta.usage:
                            usage_data["input_tokens"] = getattr(event.delta.usage, "input_tokens", usage_data.get("input_tokens", 0))
                            usage_data["output_tokens"] = getattr(event.delta.usage, "output_tokens", 0)
                            cache_create = getattr(event.delta.usage, "cache_creation_input_tokens", None)
                            cache_read = getattr(event.delta.usage, "cache_read_input_tokens", None)
                            if cache_create is not None:
                                usage_data["cache_creation_input_tokens"] = cache_create
                            if cache_read is not None:
                                usage_data["cache_read_input_tokens"] = cache_read

        except anthropic.APIStatusError as e:
            yield StreamEvent(
                "error",
                f"API error ({e.status_code}): {e.response.text}",
            )
        except anthropic.APIConnectionError as e:
            yield StreamEvent("error", f"Connection error: {e}")
        except anthropic.RateLimitError as e:
            yield StreamEvent(
                "error",
                f"Rate limit exceeded: {e.response.text}",
            )
        except Exception as e:
            yield StreamEvent("error", f"Unexpected error: {e}")

    # ── Message format helpers ──────────────────────────────────────

    def _to_anthropic_messages(
        self, messages: List[Message]
    ) -> List[dict]:
        """Convert internal Message list to Anthropic Messages API format.

        Handles ``user``, ``assistant``, and ``tool`` roles.
        ``thinking`` messages are skipped (Anthropic passes them in
        the stream, not in message history).
        """
        result = []
        for msg in messages:
            if msg.role == "thinking":
                continue
            if msg.role == "user":
                result.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                # If the assistant message has tool_calls, include them
                if msg.tool_calls:
                    content: list[dict] = []
                    if msg.content:
                        content.append({"type": "text", "text": msg.content})
                    for tc in msg.tool_calls:
                        content.append({
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["name"],
                            "input": tc["input"],
                        })
                    result.append({"role": "assistant", "content": content})
                else:
                    result.append({"role": "assistant", "content": msg.content})
            elif msg.role == "tool":
                # Anthropic: tool_result goes inside a user-content block
                result.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.tool_call_id,
                            "content": msg.content,
                        }
                    ],
                })
        return result

    def _extract_system(self, messages: List[Message]) -> str:
        """Extract system messages for the Anthropic ``system`` param."""
        parts = [m.content for m in messages if m.role == "system"]
        return "\n".join(parts) if parts else ""


# Late import for type hints
from flickcode.config import ProviderConfig  # noqa: E402, F401
