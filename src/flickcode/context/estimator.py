"""Approximate token accounting based on usage anchors and character deltas."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Iterable, Optional

from flickcode.context.models import ContextConfig, ContextState, SafetyMode, TokenEstimate
from flickcode.providers.base import Message


class TokenEstimator:
    """Estimate request input size without a model-specific tokenizer."""

    def __init__(self, config: ContextConfig):
        self.config = config

    def estimate(
        self,
        messages: list[Message],
        state: ContextState,
        *,
        system_prompt: Optional[str] = None,
        tools: Optional[list[dict]] = None,
        transient_messages: Optional[list[Message]] = None,
    ) -> TokenEstimate:
        """Return an approximate input-token count for the next request."""
        extra_chars = self._extra_chars(system_prompt, tools, transient_messages)
        anchored = self._anchor_is_valid(messages, state)

        if anchored and state.last_input_tokens is not None:
            new_messages = messages[state.anchor_message_count :]
            delta_chars = self._message_chars(new_messages) + extra_chars - state.anchor_extra_chars
            delta_tokens = self._chars_to_tokens(delta_chars)
            message_tokens = max(
                0,
                state.last_input_tokens + delta_tokens,
            )
            message_tokens += len(new_messages) * self.config.message_overhead_tokens
            full_message_tokens = self.estimate_messages(messages)
            extra_tokens = max(0, message_tokens - full_message_tokens)
            return TokenEstimate(
                input_tokens=message_tokens,
                message_tokens=full_message_tokens,
                extra_tokens=extra_tokens,
                anchored=True,
            )

        message_tokens = self.estimate_messages(messages)
        extra_tokens = self._chars_to_tokens(extra_chars)
        return TokenEstimate(
            input_tokens=message_tokens + extra_tokens,
            message_tokens=message_tokens,
            extra_tokens=extra_tokens,
            anchored=False,
        )

    def estimate_messages(self, messages: Iterable[Message]) -> int:
        """Estimate the token cost of persisted conversation messages."""
        materialized = list(messages)
        return self._chars_to_tokens(self._message_chars(materialized)) + (
            len(materialized) * self.config.message_overhead_tokens
        )

    def record_usage(
        self,
        state: ContextState,
        input_tokens: int,
        messages: list[Message],
        *,
        system_prompt: Optional[str] = None,
        tools: Optional[list[dict]] = None,
        transient_messages: Optional[list[Message]] = None,
    ) -> None:
        """Create a new exact usage anchor for a successful main request."""
        if input_tokens < 0:
            return
        state.last_input_tokens = input_tokens
        state.anchor_message_count = len(messages)
        state.anchor_message_fingerprint = self.fingerprint(messages)
        state.anchor_extra_chars = self._extra_chars(
            system_prompt,
            tools,
            transient_messages,
        )

    @staticmethod
    def invalidate(state: ContextState) -> None:
        """Discard an anchor after history was rewritten."""
        state.last_input_tokens = None
        state.anchor_message_count = 0
        state.anchor_message_fingerprint = ""
        state.anchor_extra_chars = 0

    def request_budget(self, mode: SafetyMode) -> int:
        """Return the input budget after output reservation and safety margin."""
        margin = self.safety_margin(mode)
        return max(
            0,
            self.config.context_window_tokens
            - self.config.max_output_tokens
            - margin,
        )

    def safety_margin(self, mode: SafetyMode) -> int:
        if mode == SafetyMode.MANUAL:
            return self.config.manual_safety_margin_tokens
        return self.config.automatic_safety_margin_tokens

    @staticmethod
    def fingerprint(messages: Iterable[Message]) -> str:
        """Produce a stable digest over all persisted message fields."""
        payload = [TokenEstimator._message_payload(message) for message in messages]
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _anchor_is_valid(self, messages: list[Message], state: ContextState) -> bool:
        if state.last_input_tokens is None:
            return False
        if state.anchor_message_count > len(messages):
            return False
        return state.anchor_message_fingerprint == self.fingerprint(
            messages[: state.anchor_message_count]
        )

    def _message_chars(self, messages: Iterable[Message]) -> int:
        return sum(
            len(
                json.dumps(
                    self._message_payload(message),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
            )
            for message in messages
        )

    @staticmethod
    def _message_payload(message: Message) -> dict:
        return {
            "role": message.role,
            "content": message.content,
            "tool_call_id": message.tool_call_id,
            "tool_calls": message.tool_calls,
        }

    def _extra_chars(
        self,
        system_prompt: Optional[str],
        tools: Optional[list[dict]],
        transient_messages: Optional[list[Message]],
    ) -> int:
        system_chars = len(system_prompt or "")
        tools_chars = len(
            json.dumps(
                tools or [],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        )
        transient_chars = self._message_chars(transient_messages or [])
        return system_chars + tools_chars + transient_chars

    def _chars_to_tokens(self, chars: int) -> int:
        if chars == 0:
            return 0
        return math.ceil(chars / self.config.chars_per_token)
