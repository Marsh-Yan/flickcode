"""Structured team messages and approval protocol."""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from flickcode.teams.models import TeamMessage, utc_now


KNOWN_KINDS = frozenset({
    "task.assign",
    "task.status",
    "approval.request",
    "approval.decision",
    "member.idle",
    "task.completed",
    "member.wakeup",
})


@dataclass(frozen=True)
class ProtocolEnvelope:
    kind: str
    payload: Mapping[str, Any]
    known: bool


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    member_id: str
    task_id: str
    plan: str
    plan_digest: str
    expires_at: Optional[datetime] = None

    @classmethod
    def create(cls, member_id: str, task_id: str, plan: str, expires_at: Optional[datetime] = None) -> "ApprovalRequest":
        digest = hashlib.sha256(plan.encode("utf-8")).hexdigest()
        return cls("approval-" + secrets.token_hex(6), member_id, task_id, plan, digest, expires_at)


class ProtocolCodec:
    def encode(
        self,
        *,
        team_id: str,
        sender_id: str,
        kind: str,
        payload: Mapping[str, Any],
        recipient_id: Optional[str] = None,
        body: str = "",
        summary: str = "",
        message_id: Optional[str] = None,
    ) -> TeamMessage:
        if not isinstance(kind, str) or not kind:
            raise ValueError("message kind must be non-empty")
        if not isinstance(payload, Mapping):
            raise ValueError("message payload must be a map")
        if not summary:
            summary = body or json.dumps(dict(payload), ensure_ascii=False, sort_keys=True)
        return TeamMessage(
            message_id=message_id or "msg-" + secrets.token_hex(8),
            team_id=team_id,
            sender_id=sender_id,
            recipient_id=recipient_id,
            kind=kind,
            body=body,
            summary=summary[:2048],
            timestamp=utc_now(),
            read=False,
            protocol_version=1,
            payload=dict(payload),
        )

    def decode(self, message: TeamMessage) -> ProtocolEnvelope:
        if message.protocol_version != 1:
            raise ValueError(f"unsupported team protocol version: {message.protocol_version}")
        return ProtocolEnvelope(message.kind, dict(message.payload), message.kind in KNOWN_KINDS)

    def validate_approval(
        self,
        message: TeamMessage,
        request: ApprovalRequest,
        *,
        lead_member_id: str,
        now: Optional[datetime] = None,
    ) -> bool:
        if message.kind != "approval.decision" or message.sender_id != lead_member_id:
            return False
        payload = message.payload
        if payload.get("request_id") != request.request_id:
            return False
        if payload.get("decision") != "approve":
            return False
        if payload.get("plan_digest") != request.plan_digest:
            return False
        if request.expires_at is not None:
            current = now or utc_now()
            if current > request.expires_at:
                return False
        return True

