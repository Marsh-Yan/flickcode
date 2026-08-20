"""Safe filesystem layout for durable teams."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_MEMBER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def safe_team_slug(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("team name must be a non-empty string")
    value = name.strip()
    if value in {".", ".."} or any(char in value for char in '<>:"/\\|?*'):
        raise ValueError("team name contains unsafe path characters")
    value = re.sub(r"[^\w.-]+", "-", value, flags=re.UNICODE).strip(" .-")
    if not value:
        raise ValueError("team name does not contain a safe path component")
    return value[:96]


def validate_member_id(member_id: str) -> str:
    if not isinstance(member_id, str) or not _MEMBER_ID.fullmatch(member_id):
        raise ValueError("member id must be a safe identifier")
    return member_id


@dataclass(frozen=True)
class MemberLayout:
    root: Path

    @property
    def metadata(self) -> Path:
        return self.root / "member.json"

    @property
    def mailbox(self) -> Path:
        return self.root / "mailbox.ndjson"

    @property
    def mailbox_lock(self) -> Path:
        return self.root / "mailbox.lock"

    @property
    def context(self) -> Path:
        return self.root / "context.json"

    @property
    def runtime(self) -> Path:
        return self.root / "runtime.json"


@dataclass(frozen=True)
class TeamLayout:
    root: Path

    @classmethod
    def for_name(cls, storage_dir: Path, name: str) -> "TeamLayout":
        base = Path(storage_dir).expanduser().resolve(strict=False)
        root = (base / safe_team_slug(name)).resolve(strict=False)
        try:
            root.relative_to(base)
        except ValueError as exc:
            raise ValueError("team path escapes storage directory") from exc
        return cls(root)

    @property
    def metadata(self) -> Path:
        return self.root / "team.json"

    @property
    def lock(self) -> Path:
        return self.root / "team.lock"

    @property
    def tasks(self) -> Path:
        return self.root / "tasks.json"

    @property
    def tasks_lock(self) -> Path:
        return self.root / "tasks.lock"

    @property
    def registry(self) -> Path:
        return self.root / "registry.json"

    @property
    def diagnostics(self) -> Path:
        return self.root / "diagnostics.ndjson"

    @property
    def members_root(self) -> Path:
        return self.root / "members"

    def member(self, member_id: str) -> MemberLayout:
        member_id = validate_member_id(member_id)
        root = (self.members_root / member_id).resolve(strict=False)
        try:
            root.relative_to(self.members_root.resolve(strict=False))
        except ValueError as exc:
            raise ValueError("member path escapes team directory") from exc
        return MemberLayout(root)

