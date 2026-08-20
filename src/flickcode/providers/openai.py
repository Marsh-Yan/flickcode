"""OpenAI provider implementation."""

from __future__ import annotations

import json
from typing import Any, Generator, List

import openai

from flickcode.providers.base import BaseProvider, Message, StreamEvent


class OpenAIProvider(BaseProvider):
    """Provider for OpenAI Chat Completions API with streaming support."""

    def __init__(self, config: "ProviderConfig", client=None):
        super().__init__(config)
        self.client = client or openai.OpenAI(
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
        """Send messages to OpenAI and yield streaming events.

        In addition to text events this version can also yield
        ``tool_call`` events when the model decides to use a function.

        Note: OpenAI does not support extended thinking;
        the ``thinking`` parameter is accepted for interface compatibility
        but has no effect.

        Args:
            messages: Conversation history.
            thinking: Ignored (OpenAI does not support this).
            tools: Optional OpenAI-format tool definitions.
            system: Optional system prompt. When provided it is inserted
                as a ``{"role": "system"}`` message at the head of the
                conversation.

        Yields:
            StreamEvent — text, tool_call, done, or error.
        """
        openai_messages = self._to_openai_messages(messages)
        if system is not None:
            openai_messages.insert(0, {"role": "system", "content": system})

        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": openai_messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools

        try:
            stream = self.client.chat.completions.create(**kwargs)

            # Tool-call state: index → {id, name, args_buffer}
            tool_call_buffers: dict[int, dict[str, Any]] = {}
            finish_reason: str | None = None
            usage_data: dict[str, int] = {}

            for chunk in stream:
                if not chunk.choices:
                    # Some chunks (e.g. the last one) may only carry usage
                    if hasattr(chunk, "usage") and chunk.usage:
                        usage_data["input_tokens"] = getattr(chunk.usage, "prompt_tokens", 0)
                        usage_data["output_tokens"] = getattr(chunk.usage, "completion_tokens", 0)
                        details = getattr(chunk.usage, "prompt_tokens_details", None)
                        if details is not None:
                            usage_data["cache_read_input_tokens"] = getattr(details, "cached_tokens", 0) or 0
                    continue

                choice = chunk.choices[0]

                # Track usage from final chunk
                if hasattr(chunk, "usage") and chunk.usage:
                    usage_data["input_tokens"] = getattr(chunk.usage, "prompt_tokens", 0)
                    usage_data["output_tokens"] = getattr(chunk.usage, "completion_tokens", 0)
                    details = getattr(chunk.usage, "prompt_tokens_details", None)
                    if details is not None:
                        usage_data["cache_read_input_tokens"] = getattr(details, "cached_tokens", 0) or 0

                # Track finish reason for the last chunk
                if choice.finish_reason is not None:
                    finish_reason = choice.finish_reason

                # ── Text delta ───────────────────────────────────────
                if choice.delta and choice.delta.content:
                    yield StreamEvent("text", choice.delta.content)

                # ── Tool-call delta ──────────────────────────────────
                if (
                    choice.delta
                    and choice.delta.tool_calls
                ):
                    for tc_delta in choice.delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_call_buffers:
                            tool_call_buffers[idx] = {
                                "id": tc_delta.id or "",
                                "name": "",
                                "args_buffer": [],
                            }
                        buf = tool_call_buffers[idx]
                        if tc_delta.id:
                            buf["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                buf["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                buf["args_buffer"].append(
                                    tc_delta.function.arguments
                                )

                # ── Finish: emit tool_call events ────────────────────
                if finish_reason == "tool_calls":
                    for idx in sorted(tool_call_buffers):
                        buf = tool_call_buffers[idx]
                        raw = "".join(buf["args_buffer"])
                        try:
                            parsed = json.loads(raw) if raw.strip() else {}
                        except json.JSONDecodeError:
                            parsed = {"_raw": raw}
                        yield StreamEvent(
                            "tool_call",
                            json.dumps({
                                "id": buf["id"],
                                "name": buf["name"],
                                "arguments": parsed,
                            }),
                        )
                    tool_call_buffers.clear()
                    finish_reason = None

                # ── Stream complete ──────────────────────────────────
                if choice.finish_reason == "stop":
                    done_content = json.dumps({"usage": usage_data}) if usage_data else ""
                    yield StreamEvent("done", done_content)

        except openai.APIStatusError as e:
            yield StreamEvent(
                "error",
                f"API error ({e.status_code}): {e.response.text}",
            )
        except openai.APIConnectionError as e:
            yield StreamEvent("error", f"Connection error: {e}")
        except openai.RateLimitError as e:
            yield StreamEvent(
                "error",
                f"Rate limit exceeded: {e.response.text}",
            )
        except Exception as e:
            yield StreamEvent("error", f"Unexpected error: {e}")

    # ── Message format helpers ──────────────────────────────────────

    def _to_openai_messages(self, messages: List[Message]) -> List[dict]:
        """Convert internal Message list to OpenAI Chat Completions format.

        Handles ``user``, ``assistant``, ``system``, and ``tool`` roles.
        ``thinking`` messages are skipped (not used by OpenAI).
        """
        result = []
        for msg in messages:
            if msg.role == "thinking":
                continue
            if msg.role == "tool":
                result.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content,
                })
            elif msg.role == "assistant" and msg.tool_calls:
                # Include tool_calls in the assistant message
                oai_tool_calls = []
                for tc in msg.tool_calls:
                    oai_tool_calls.append({
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["input"]),
                        },
                    })
                entry: dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.content or None,
                }
                if oai_tool_calls:
                    entry["tool_calls"] = oai_tool_calls
                result.append(entry)
            else:
                result.append({"role": msg.role, "content": msg.content})
        return result


# Late import for type hints
from flickcode.config import ProviderConfig  # noqa: E402, F401
