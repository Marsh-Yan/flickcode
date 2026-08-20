"""Lock-protected durable member mailboxes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

from flickcode.teams.locking import locked
from flickcode.teams.models import TeamMessage
from flickcode.teams.paths import TeamLayout
from flickcode.teams.protocol import ProtocolCodec
from flickcode.teams.registry import NameRegistry


class MailboxStore:
    def __init__(self, layout: TeamLayout, *, retry_seconds: float = 2.0, stale_seconds: float = 30.0) -> None:
        self.layout = layout
        self.retry_seconds = retry_seconds
        self.stale_seconds = stale_seconds
        self.codec = ProtocolCodec()
        self.registry = NameRegistry(layout, retry_seconds=retry_seconds, stale_seconds=stale_seconds)

    def _append(self, member_id: str, message: TeamMessage) -> TeamMessage:
        member = self.layout.member(member_id)
        member.root.mkdir(parents=True, exist_ok=True)
        with locked(member.mailbox_lock, retry_seconds=self.retry_seconds, stale_seconds=self.stale_seconds):
            with member.mailbox.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(message.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        return message

    def send_to_name(
        self,
        *,
        team_id: str,
        sender_id: str,
        recipient_name: str,
        kind: str,
        payload: dict,
        body: str = "",
        summary: str = "",
    ) -> TeamMessage:
        route = self.registry.resolve(recipient_name)
        message = self.codec.encode(
            team_id=team_id,
            sender_id=sender_id,
            recipient_id=str(route["member_id"]),
            kind=kind,
            payload=payload,
            body=body,
            summary=summary,
        )
        return self._append(str(route["member_id"]), message)

    def send(self, member_id: str, message: TeamMessage) -> TeamMessage:
        if message.recipient_id not in {None, member_id}:
            raise ValueError("message recipient does not match mailbox")
        return self._append(member_id, message)

    def broadcast(
        self,
        *,
        team_id: str,
        sender_id: str,
        kind: str,
        payload: dict,
        member_names: Optional[Iterable[str]] = None,
        include_sender: bool = False,
        body: str = "",
        summary: str = "",
    ) -> tuple[TeamMessage, ...]:
        routes = self.registry.routes()
        names = list(member_names) if member_names is not None else sorted(routes)
        result = []
        for name in names:
            route = self.registry.resolve(name)
            if not include_sender and str(route["member_id"]) == sender_id:
                continue
            message = self.codec.encode(
                team_id=team_id,
                sender_id=sender_id,
                recipient_id=str(route["member_id"]),
                kind=kind,
                payload=payload,
                body=body,
                summary=summary,
            )
            result.append(self._append(str(route["member_id"]), message))
        return tuple(result)

    def list_messages(self, member_id: str, *, unread_only: bool = False) -> tuple[TeamMessage, ...]:
        member = self.layout.member(member_id)
        if not member.mailbox.exists():
            return ()
        result = []
        with locked(member.mailbox_lock, retry_seconds=self.retry_seconds, stale_seconds=self.stale_seconds):
            with member.mailbox.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    try:
                        message = TeamMessage.from_dict(json.loads(line))
                    except (ValueError, KeyError, json.JSONDecodeError) as exc:
                        raise ValueError(f"invalid mailbox record at line {line_number}") from exc
                    if not unread_only or not message.read:
                        result.append(message)
        return tuple(result)

    def mark_read(self, member_id: str, message_ids: Iterable[str]) -> int:
        wanted = set(message_ids)
        if not wanted:
            return 0
        member = self.layout.member(member_id)
        if not member.mailbox.exists():
            return 0
        changed = 0
        with locked(member.mailbox_lock, retry_seconds=self.retry_seconds, stale_seconds=self.stale_seconds):
            messages = []
            with member.mailbox.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    message = TeamMessage.from_dict(json.loads(line))
                    if message.message_id in wanted and not message.read:
                        message = TeamMessage(**{**message.__dict__, "read": True})
                        changed += 1
                    messages.append(message)
            temporary = member.mailbox.with_name(member.mailbox.name + ".tmp")
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                for message in messages:
                    handle.write(json.dumps(message.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
            temporary.replace(member.mailbox)
        return changed

    def count_unread(self, member_id: str) -> int:
        return len(self.list_messages(member_id, unread_only=True))

