"""Tool-free LLM proposals and non-blocking application of memory changes."""

from __future__ import annotations

import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from flickcode.memory.models import MemoryCategory, MemoryChange, MemoryNote
from flickcode.memory.notes import MemoryRepository
from flickcode.providers.base import BaseProvider, Message


MEMORY_UPDATE_SYSTEM_PROMPT = """You maintain FlickCode long-term memory. Review only the supplied conversation and existing notes. Return a JSON array and nothing else. Each item must contain scope ('user' or 'project'), action ('upsert' or 'discard'), optional note_id, category (one of user_preference, correction_feedback, project_knowledge, reference), and content. Record durable facts only. Put project-specific facts only in project scope. Decide duplicate and conflict handling yourself: use discard when no update is useful. Do not call tools or invent facts."""


class MemoryUpdateClient:
    """Ask a provider for structured memory changes without tool recursion."""

    def __init__(self, provider: BaseProvider) -> None:
        self.provider = provider

    def propose(
        self,
        messages: list[Message],
        user_notes: list[MemoryNote],
        project_notes: list[MemoryNote],
    ) -> list[MemoryChange]:
        payload = {
            "conversation": [self._message_dict(message) for message in messages],
            "existing_user_notes": [self._note_dict(note) for note in user_notes],
            "existing_project_notes": [self._note_dict(note) for note in project_notes],
        }
        parts: list[str] = []
        done = False
        try:
            for event in self.provider.stream_chat(
                [Message(role="user", content=json.dumps(payload, ensure_ascii=False))],
                thinking=False,
                tools=None,
                system=MEMORY_UPDATE_SYSTEM_PROMPT,
            ):
                if event.type == "text":
                    parts.append(event.content)
                elif event.type == "error":
                    raise ValueError(f"Memory update provider error: {event.content}")
                elif event.type == "done":
                    done = True
        except Exception as exc:
            raise ValueError(f"Memory update request failed: {exc}") from exc
        if not done:
            raise ValueError("Memory update provider ended without a done event")
        try:
            raw_changes = json.loads("".join(parts))
        except json.JSONDecodeError as exc:
            raise ValueError("Memory update response was not valid JSON") from exc
        if not isinstance(raw_changes, list) or len(raw_changes) > 20:
            raise ValueError("Memory update response must be an array of at most 20 changes")
        return [self._parse_change(item) for item in raw_changes]

    @staticmethod
    def _message_dict(message: Message) -> dict:
        return {
            "role": message.role,
            "content": message.content,
            "tool_call_id": message.tool_call_id,
            "tool_calls": message.tool_calls,
        }

    @staticmethod
    def _note_dict(note: MemoryNote) -> dict:
        return {
            "id": note.note_id,
            "category": note.category.value,
            "content": note.content,
            "updated_at": note.updated_at.isoformat(),
        }

    @staticmethod
    def _parse_change(raw: object) -> MemoryChange:
        if not isinstance(raw, dict):
            raise ValueError("Memory update item must be an object")
        scope = raw.get("scope")
        action = raw.get("action")
        note_id = raw.get("note_id")
        category_raw = raw.get("category")
        content = raw.get("content", "")
        if scope not in ("user", "project") or action not in ("upsert", "discard"):
            raise ValueError("Memory update has invalid scope or action")
        if note_id is not None and not isinstance(note_id, str):
            raise ValueError("Memory update note_id must be a string")
        if not isinstance(content, str):
            raise ValueError("Memory update content must be a string")
        category = None
        if action == "upsert":
            try:
                category = MemoryCategory(category_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("Memory update category is invalid") from exc
            if not content.strip():
                raise ValueError("Memory update content must not be empty")
        return MemoryChange(scope, action, note_id, category, content)


class MemoryUpdateScheduler:
    """Serialize background memory updates for one Session without blocking UI."""

    def __init__(
        self,
        client: MemoryUpdateClient,
        user_repository: MemoryRepository,
        project_repository: MemoryRepository,
        report: Callable[[str], None],
    ) -> None:
        self.client = client
        self.user_repository = user_repository
        self.project_repository = project_repository
        self.report = report
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="flick-memory")
        self._closed = False
        self._lock = threading.Lock()

    def submit(self, messages: list[Message]) -> None:
        with self._lock:
            if self._closed:
                return
            snapshot = copy.deepcopy(messages)
            self._executor.submit(self._run, snapshot)

    def _run(self, messages: list[Message]) -> None:
        try:
            user_notes, user_errors = self.user_repository.read_notes_for_update()
            project_notes, project_errors = self.project_repository.read_notes_for_update()
            for diagnostic in user_errors + project_errors:
                self.report(diagnostic.message)
            changes = self.client.propose(messages, user_notes, project_notes)
            for diagnostic in self.user_repository.apply([c for c in changes if c.scope == "user"]):
                self.report(diagnostic.message)
            for diagnostic in self.project_repository.apply([c for c in changes if c.scope == "project"]):
                self.report(diagnostic.message)
        except Exception as exc:
            self.report(f"Memory update failed: {exc}")

    def shutdown(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._executor.shutdown(wait=False)

