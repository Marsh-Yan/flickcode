"""Project-local Worktree bootstrap configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from flickcode.worktrees.models import (
    WorktreeBootstrapConfig,
    WorktreeConfig,
    WorktreeConfigError,
    WorktreeDiagnostic,
)


_CONFIG_NAME = ".flickcode/worktrees.yaml"


def _validate_relative_rule(raw: Any, field: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise WorktreeConfigError(f"{field} entries must be non-empty strings")
    if "\\" in raw or ":" in raw or raw.startswith("/"):
        raise WorktreeConfigError(f"{field} entry must be a relative slash path: {raw}")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise WorktreeConfigError(f"{field} entry contains an unsafe path segment: {raw}")
    if len(raw) > 240:
        raise WorktreeConfigError(f"{field} entry is too long")
    # A glob is useful for ignored files, but patterns that begin with a
    # wildcard still remain rooted because the path is always joined to the
    # project root after this validation.
    return raw


class WorktreeConfigLoader:
    """Load a strict, optional project Worktree configuration."""

    def load(
        self, project_root: Path
    ) -> tuple[WorktreeConfig, tuple[WorktreeDiagnostic, ...]]:
        root = project_root.expanduser().resolve()
        path = root / _CONFIG_NAME
        if not path.exists():
            return WorktreeConfig(), ()
        diagnostics: list[WorktreeDiagnostic] = []
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            config = self._parse(raw)
        except (OSError, UnicodeError, yaml.YAMLError, WorktreeConfigError, TypeError) as exc:
            diagnostics.append(WorktreeDiagnostic("error", "config", str(exc), path))
            return WorktreeConfig(), tuple(diagnostics)
        return config, tuple(diagnostics)

    @staticmethod
    def _parse(raw: Any) -> WorktreeConfig:
        if raw is None:
            return WorktreeConfig()
        if not isinstance(raw, dict):
            raise WorktreeConfigError("Worktree config root must be a map")
        allowed = {"version", "expiry_days", "bootstrap"}
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise WorktreeConfigError("Unsupported Worktree setting(s): " + ", ".join(unknown))
        version = raw.get("version", 1)
        if isinstance(version, bool) or version != 1:
            raise WorktreeConfigError("Worktree config version must be 1")
        expiry = raw.get("expiry_days", 7)
        if isinstance(expiry, bool) or not isinstance(expiry, int) or expiry <= 0:
            raise WorktreeConfigError("expiry_days must be a positive integer")
        bootstrap_raw = raw.get("bootstrap", {})
        if bootstrap_raw is None:
            bootstrap_raw = {}
        if not isinstance(bootstrap_raw, dict):
            raise WorktreeConfigError("bootstrap must be a map")
        unknown_bootstrap = sorted(
            set(bootstrap_raw) - {"copy", "symlink", "ignored"}
        )
        if unknown_bootstrap:
            raise WorktreeConfigError(
                "Unsupported bootstrap setting(s): " + ", ".join(unknown_bootstrap)
            )
        values: dict[str, tuple[str, ...]] = {}
        for field in ("copy", "symlink", "ignored"):
            entries = bootstrap_raw.get(field, [])
            if not isinstance(entries, list):
                raise WorktreeConfigError(f"bootstrap.{field} must be a list")
            parsed = tuple(_validate_relative_rule(item, f"bootstrap.{field}") for item in entries)
            if len(parsed) != len(set(parsed)):
                raise WorktreeConfigError(f"bootstrap.{field} must not contain duplicates")
            values[field] = parsed
        literal = set(values["copy"]) | set(values["symlink"])
        if len(literal) != len(values["copy"]) + len(values["symlink"]):
            raise WorktreeConfigError("copy and symlink targets must not overlap")
        return WorktreeConfig(
            expiry_days=expiry,
            bootstrap=WorktreeBootstrapConfig(**values),
        )


__all__ = ["WorktreeConfigLoader"]
