"""Durable team and member metadata store."""

from __future__ import annotations

import json
import secrets
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from flickcode.teams.locking import locked
from flickcode.teams.models import (
    MemberBackendKind,
    MemberState,
    TeamMemberRecord,
    TeamRecord,
    TeamStatus,
    utc_now,
)
from flickcode.teams.paths import TeamLayout
from flickcode.teams.registry import NameRegistry


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    temporary.replace(path)


class TeamStore:
    def __init__(self, storage_dir: Path, *, lock_retry_seconds: float = 2.0, lock_stale_seconds: float = 30.0) -> None:
        self.storage_dir = Path(storage_dir).expanduser().resolve(strict=False)
        self.lock_retry_seconds = lock_retry_seconds
        self.lock_stale_seconds = lock_stale_seconds

    def layout_for_name(self, name: str) -> TeamLayout:
        return TeamLayout.for_name(self.storage_dir, name)

    def create(
        self,
        name: str,
        lead_name: str,
        *,
        lead_workdir: Optional[Path] = None,
        lead_backend: MemberBackendKind = MemberBackendKind.IN_PROCESS,
        coordinator_enabled: bool = False,
    ) -> TeamRecord:
        layout = self.layout_for_name(name)
        if layout.metadata.exists():
            raise FileExistsError(f"Team already exists: {name}")
        layout.root.mkdir(parents=True, exist_ok=False)
        layout.members_root.mkdir(parents=True, exist_ok=True)
        team_id = "team-" + secrets.token_hex(8)
        lead_id = "lead-" + secrets.token_hex(6)
        now = utc_now()
        team = TeamRecord(team_id, name.strip(), lead_id, layout.root, now, now, TeamStatus.ACTIVE, coordinator_enabled)
        _atomic_json(layout.metadata, team.to_dict())
        _atomic_json(layout.tasks, {})
        _atomic_json(layout.registry, {})
        lead_layout = layout.member(lead_id)
        lead_layout.root.mkdir(parents=True, exist_ok=True)
        member = TeamMemberRecord(
            member_id=lead_id,
            name=lead_name.strip() or "lead",
            team_id=team_id,
            role="lead",
            workdir=(lead_workdir or Path.cwd()).expanduser().resolve(strict=False),
            backend=lead_backend,
            backend_reason="lead session",
            state=MemberState.IDLE,
            mailbox_path=lead_layout.mailbox,
            context_path=lead_layout.context,
            created_at=now,
            updated_at=now,
        )
        _atomic_json(lead_layout.metadata, member.to_dict())
        NameRegistry(layout, retry_seconds=self.lock_retry_seconds, stale_seconds=self.lock_stale_seconds).register(
            name=member.name,
            member_id=member.member_id,
            mailbox_path=member.mailbox_path,
            context_path=member.context_path,
            backend=member.backend.value,
            state=member.state.value,
        )
        return team

    def open(self, name: str) -> TeamRecord:
        layout = self.layout_for_name(name)
        if not layout.metadata.exists():
            raise FileNotFoundError(f"Team not found: {name}")
        with layout.metadata.open("r", encoding="utf-8") as handle:
            team = TeamRecord.from_dict(json.load(handle))
        if team.root.resolve(strict=False) != layout.root.resolve(strict=False):
            raise ValueError("team metadata root does not match its storage layout")
        return team

    def save(self, team: TeamRecord) -> TeamRecord:
        layout = TeamLayout(team.root)
        with locked(layout.lock, retry_seconds=self.lock_retry_seconds, stale_seconds=self.lock_stale_seconds):
            current = self.open(team.name)
            if current.team_id != team.team_id:
                raise ValueError("team id changed while saving")
            saved = replace(team, updated_at=utc_now())
            _atomic_json(layout.metadata, saved.to_dict())
            return saved

    def close(self, team: TeamRecord) -> TeamRecord:
        return self.save(replace(team, status=TeamStatus.CLOSED))

    def list_members(self, team: TeamRecord) -> tuple[TeamMemberRecord, ...]:
        layout = TeamLayout(team.root)
        if not layout.members_root.exists():
            return ()
        result = []
        for path in sorted(layout.members_root.iterdir()):
            metadata = path / "member.json"
            if not path.is_dir() or not metadata.exists():
                continue
            with metadata.open("r", encoding="utf-8") as handle:
                member = TeamMemberRecord.from_dict(json.load(handle))
            if member.team_id != team.team_id:
                raise ValueError(f"member belongs to another team: {member.member_id}")
            result.append(member)
        return tuple(result)

    def get_member(self, team: TeamRecord, member_id: str) -> TeamMemberRecord:
        for member in self.list_members(team):
            if member.member_id == member_id:
                return member
        raise KeyError(f"Unknown team member id: {member_id}")

    def add_member(
        self,
        team: TeamRecord,
        *,
        name: str,
        role: str,
        workdir: Path,
        backend: MemberBackendKind,
        backend_reason: str = "",
        approval_required: bool = False,
        member_id: Optional[str] = None,
    ) -> TeamMemberRecord:
        if team.status is not TeamStatus.ACTIVE:
            raise RuntimeError("cannot add a member to a closed team")
        if not name.strip() or not role.strip():
            raise ValueError("member name and role must be non-empty")
        if any(item.name == name for item in self.list_members(team)):
            raise ValueError(f"member name already exists: {name}")
        identifier = member_id or ("member-" + secrets.token_hex(6))
        layout = TeamLayout(team.root)
        member_layout = layout.member(identifier)
        member_layout.root.mkdir(parents=True, exist_ok=False)
        now = utc_now()
        member = TeamMemberRecord(
            member_id=identifier,
            name=name.strip(),
            team_id=team.team_id,
            role=role.strip(),
            workdir=Path(workdir).expanduser().resolve(strict=False),
            backend=backend,
            backend_reason=backend_reason,
            approval_required=approval_required,
            state=MemberState.REGISTERED,
            mailbox_path=member_layout.mailbox,
            context_path=member_layout.context,
            created_at=now,
            updated_at=now,
        )
        _atomic_json(member_layout.metadata, member.to_dict())
        NameRegistry(layout, retry_seconds=self.lock_retry_seconds, stale_seconds=self.lock_stale_seconds).register(
            name=member.name,
            member_id=member.member_id,
            mailbox_path=member.mailbox_path,
            context_path=member.context_path,
            backend=member.backend.value,
            state=member.state.value,
        )
        return member

    def update_member(self, member: TeamMemberRecord) -> TeamMemberRecord:
        # Resolve through the member's persisted team root without accepting a
        # caller-controlled path outside the team layout.
        team = self._find_team_by_id(member.team_id)
        member_layout = TeamLayout(team.root).member(member.member_id)
        current = self.get_member(team, member.member_id)
        if current.team_id != member.team_id:
            raise ValueError("member team mismatch")
        saved = replace(member, updated_at=utc_now())
        _atomic_json(member_layout.metadata, saved.to_dict())
        NameRegistry(TeamLayout(team.root), retry_seconds=self.lock_retry_seconds, stale_seconds=self.lock_stale_seconds).update_runtime(
            saved.member_id,
            state=saved.state.value,
            runtime_handle=saved.runtime_handle,
            backend=saved.backend.value,
        )
        return saved

    def _find_team_by_id(self, team_id: str) -> TeamRecord:
        if not self.storage_dir.exists():
            raise KeyError(f"Unknown team id: {team_id}")
        for path in self.storage_dir.iterdir():
            metadata = path / "team.json"
            if not metadata.exists():
                continue
            try:
                with metadata.open("r", encoding="utf-8") as handle:
                    team = TeamRecord.from_dict(json.load(handle))
            except (OSError, ValueError, KeyError):
                continue
            if team.team_id == team_id:
                return team
        raise KeyError(f"Unknown team id: {team_id}")
