"""Fail-closed approval gate for team members."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional

from flickcode.teams.models import TeamMessage
from flickcode.teams.protocol import ApprovalRequest, ProtocolCodec


@dataclass(frozen=True)
class ApprovalState:
    request: ApprovalRequest
    decision: str = "pending"
    reason: str = ""


class ApprovalGate:
    def __init__(self, codec: Optional[ProtocolCodec] = None) -> None:
        self.codec = codec or ProtocolCodec()
        self._lock = threading.RLock()
        self._states: dict[str, ApprovalState] = {}

    def submit(self, request: ApprovalRequest) -> ApprovalState:
        with self._lock:
            state = ApprovalState(request)
            self._states[request.request_id] = state
            return state

    def state(self, request_id: str) -> Optional[ApprovalState]:
        with self._lock:
            return self._states.get(request_id)

    def is_approved(self, task_id: str) -> bool:
        with self._lock:
            return any(item.request.task_id == task_id and item.decision == "approve" for item in self._states.values())

    def apply(self, message: TeamMessage, *, request_id: str, request: ApprovalRequest, lead_member_id: str) -> ApprovalState:
        with self._lock:
            if not self.codec.validate_approval(message, request, lead_member_id=lead_member_id):
                state = ApprovalState(request, "rejected", "approval did not match request, digest, or Lead")
            else:
                state = ApprovalState(request, "approve", "approved by Lead")
            self._states[request_id] = state
            return state

