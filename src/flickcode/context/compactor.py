"""Tool-result reduction and history selection for context compression."""

from __future__ import annotations

from dataclasses import dataclass

from flickcode.context.estimator import TokenEstimator
from flickcode.context.models import ContextConfig
from flickcode.context.store import ContextStorageError, ResultStore
from flickcode.providers.base import Message


@dataclass
class ToolBatch:
    """One assistant tool-call message and every associated tool result."""

    assistant_index: int
    indexes: list[int]


@dataclass
class LightweightResult:
    """Outcome of tool-result storage before a provider request."""

    changed: bool
    stored_paths: list["Path"]
    errors: list[str]


class ContextCompactor:
    """Apply non-destructive reductions while preserving tool-message order."""

    def __init__(
        self,
        config: ContextConfig,
        store: ResultStore,
        estimator: TokenEstimator,
    ):
        self.config = config
        self.store = store
        self.estimator = estimator

    def lighten_tool_results(
        self,
        messages: list[Message],
        *,
        session_id: str,
    ) -> LightweightResult:
        """Externalize oversized tool content only after successfully storing it."""
        batches, metadata = self._tool_batches(messages)
        changed = False
        stored_paths = []
        errors: list[str] = []

        for index, message in enumerate(messages):
            if (
                message.role == "tool"
                and not self._is_stored_preview(message.content)
                and len(message.content) > self.config.single_tool_result_chars
            ):
                if self._store_one(
                    messages,
                    index,
                    metadata,
                    session_id,
                    stored_paths,
                    errors,
                ):
                    changed = True

        for batch in batches:
            candidates = [
                index
                for index in batch.indexes
                if messages[index].role == "tool"
                and not self._is_stored_preview(messages[index].content)
            ]
            total_chars = sum(len(messages[index].content) for index in candidates)
            if total_chars <= self.config.message_tool_result_chars:
                continue

            for index in sorted(candidates, key=lambda item: len(messages[item].content), reverse=True):
                if total_chars <= self.config.message_tool_result_chars:
                    break
                original_chars = len(messages[index].content)
                if self._store_one(
                    messages,
                    index,
                    metadata,
                    session_id,
                    stored_paths,
                    errors,
                ):
                    changed = True
                    total_chars -= original_chars

        return LightweightResult(
            changed=changed,
            stored_paths=stored_paths,
            errors=errors,
        )

    def select_recent_messages(
        self,
        messages: list[Message],
        *,
        target_tokens: int | None = None,
    ) -> tuple[list[Message], list[Message]]:
        """Select tail history without separating tool calls from their results."""
        if not messages:
            return [], []

        target = (
            self.config.recent_target_tokens
            if target_tokens is None
            else max(0, target_tokens)
        )
        units = self._message_units(messages)
        selected_start = len(messages)
        selected_count = 0
        selected_tokens = 0

        for start, end in reversed(units):
            # Leave at least one earlier unit available for summarization. A
            # single oversized old result must not be retained merely to meet
            # the approximate recent-token target.
            if start == 0 and selected_count > 0:
                break
            unit = messages[start:end]
            unit_tokens = self.estimator.estimate_messages(unit)
            if (
                selected_count >= self.config.recent_min_messages
                and selected_tokens >= target
            ):
                break
            selected_start = start
            selected_count += len(unit)
            selected_tokens += unit_tokens

        return messages[:selected_start], messages[selected_start:]

    @staticmethod
    def build_compacted_messages(
        summary: str,
        recent_messages: list[Message],
        *,
        summary_path: "Path | None" = None,
    ) -> list[Message]:
        """Build the persisted summary, boundary notice, then recent history."""
        summary_message = Message(
            role="assistant",
            content="[FlickCode context summary]\n" + summary,
        )
        path_line = f" Summary copy: {summary_path}." if summary_path else ""
        boundary_message = Message(
            role="user",
            content=(
                "[FlickCode context boundary]\n"
                "Earlier conversation content was compressed. File details are "
                "authoritative only in the stored result files. When details are "
                "needed, read those files again with an appropriate tool; do not "
                "invent or infer code details from this summary."
                + path_line
            ),
        )
        return [summary_message, boundary_message] + list(recent_messages)

    def _tool_batches(
        self, messages: list[Message]
    ) -> tuple[list[ToolBatch], dict[str, tuple[str, int]]]:
        call_metadata: dict[str, tuple[str, int]] = {}
        batch_results: dict[int, list[int]] = {}
        for index, message in enumerate(messages):
            if message.role == "assistant" and message.tool_calls:
                batch_results.setdefault(index, [])
                for call in message.tool_calls:
                    call_id = str(call.get("id", ""))
                    if call_id:
                        call_metadata[call_id] = (
                            str(call.get("name", "unknown")),
                            index,
                        )
            elif message.role == "tool" and message.tool_call_id in call_metadata:
                _, assistant_index = call_metadata[message.tool_call_id]
                batch_results.setdefault(assistant_index, []).append(index)

        batches = [
            ToolBatch(assistant_index=index, indexes=indexes)
            for index, indexes in batch_results.items()
            if indexes
        ]
        return batches, call_metadata

    def _message_units(self, messages: list[Message]) -> list[tuple[int, int]]:
        batches, _ = self._tool_batches(messages)
        batch_end_by_start = {
            batch.assistant_index: max(batch.indexes) + 1 for batch in batches
        }
        units: list[tuple[int, int]] = []
        index = 0
        while index < len(messages):
            end = batch_end_by_start.get(index, index + 1)
            units.append((index, end))
            index = end
        return units

    def _store_one(
        self,
        messages: list[Message],
        index: int,
        metadata: dict[str, tuple[str, int]],
        session_id: str,
        stored_paths: list,
        errors: list[str],
    ) -> bool:
        message = messages[index]
        tool_name, _ = metadata.get(message.tool_call_id, ("unknown", -1))
        try:
            stored = self.store.store_tool_result(
                session_id=session_id,
                message_index=index,
                tool_call_id=message.tool_call_id,
                tool_name=tool_name,
                content=message.content,
            )
        except ContextStorageError as exc:
            errors.append(str(exc))
            return False
        message.content = stored.preview
        stored_paths.append(stored.path)
        return True

    @staticmethod
    def _is_stored_preview(content: str) -> bool:
        return content.startswith("[FlickCode stored tool result]")


from pathlib import Path  # noqa: E402
