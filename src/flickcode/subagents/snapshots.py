"""Thread-safe immutable parent request snapshots."""

from __future__ import annotations

import copy
import threading
from typing import Optional

from flickcode.subagents.models import ParentRequestSnapshot


class ParentRequestSnapshotStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: Optional[ParentRequestSnapshot] = None

    def put(self, snapshot: ParentRequestSnapshot) -> None:
        with self._lock:
            self._snapshot = self._copy(snapshot)

    def get(self) -> Optional[ParentRequestSnapshot]:
        with self._lock:
            return self._copy(self._snapshot) if self._snapshot is not None else None

    def reset(self) -> None:
        with self._lock:
            self._snapshot = None

    @staticmethod
    def _copy(snapshot: ParentRequestSnapshot) -> ParentRequestSnapshot:
        return ParentRequestSnapshot(
            session_id=snapshot.session_id,
            turn_number=snapshot.turn_number,
            mode=snapshot.mode,
            messages=tuple(copy.deepcopy(list(snapshot.messages))),
            system_prompt=snapshot.system_prompt,
            tool_view=snapshot.tool_view.snapshot(),
            provider_config=copy.copy(snapshot.provider_config),
            thinking=snapshot.thinking,
        )
