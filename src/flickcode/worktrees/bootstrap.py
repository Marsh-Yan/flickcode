"""Explicit Worktree environment initialization."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from flickcode.worktrees.git import GitRepository
from flickcode.worktrees.models import (
    WorktreeBootstrapConfig,
    WorktreeConfigError,
)


MAX_COPY_FILES = 2_000
MAX_COPY_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class BootstrapPlanItem:
    kind: str
    source: Path
    target: Path
    size: int = 0


@dataclass(frozen=True)
class BootstrapReport:
    success: bool
    copied: tuple[Path, ...] = ()
    linked: tuple[Path, ...] = ()
    ignored: tuple[Path, ...] = ()
    diagnostics: tuple[str, ...] = ()
    plan: tuple[BootstrapPlanItem, ...] = ()


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _contains_git_segment(path: Path) -> bool:
    return ".git" in path.parts


class WorktreeBootstrapper:
    def __init__(
        self,
        *,
        max_files: int = MAX_COPY_FILES,
        max_bytes: int = MAX_COPY_BYTES,
    ) -> None:
        self.max_files = max_files
        self.max_bytes = max_bytes

    def apply(
        self,
        config: WorktreeBootstrapConfig,
        *,
        main_project_root: Path,
        child_project_root: Path,
        repository: GitRepository,
    ) -> BootstrapReport:
        main = main_project_root.expanduser().resolve()
        child = child_project_root.expanduser().resolve(strict=False)
        try:
            plan = self.plan(
                config,
                main_project_root=main,
                child_project_root=child,
                repository=repository,
            )
        except (OSError, WorktreeConfigError, RuntimeError, ValueError) as exc:
            return BootstrapReport(False, diagnostics=(str(exc),))
        copied: list[Path] = []
        linked: list[Path] = []
        ignored: list[Path] = []
        try:
            for item in plan:
                item.target.parent.mkdir(parents=True, exist_ok=True)
                if item.kind in {"copy", "ignored"}:
                    self._copy(item.source, item.target)
                    (ignored if item.kind == "ignored" else copied).append(item.target)
                elif item.kind == "symlink":
                    if item.target.exists() or item.target.is_symlink():
                        raise WorktreeConfigError(
                            f"Bootstrap target already exists: {item.target}"
                        )
                    os.symlink(
                        str(item.source), str(item.target), target_is_directory=item.source.is_dir()
                    )
                    linked.append(item.target)
                else:
                    raise WorktreeConfigError(f"Unknown bootstrap action: {item.kind}")
            repository.configure_hooks(child.parent if child == main else child_project_root)
        except (OSError, WorktreeConfigError, RuntimeError, ValueError) as exc:
            return BootstrapReport(
                False,
                tuple(copied),
                tuple(linked),
                tuple(ignored),
                (str(exc),),
                tuple(plan),
            )
        return BootstrapReport(
            True,
            tuple(copied),
            tuple(linked),
            tuple(ignored),
            (),
            tuple(plan),
        )

    def plan(
        self,
        config: WorktreeBootstrapConfig,
        *,
        main_project_root: Path,
        child_project_root: Path,
        repository: GitRepository,
    ) -> tuple[BootstrapPlanItem, ...]:
        main = main_project_root.expanduser().resolve()
        child = child_project_root.expanduser().resolve(strict=False)
        if not main.is_dir():
            raise WorktreeConfigError(f"Main project root is not a directory: {main}")
        if not _within(child, repository.identity.repository_root):
            raise WorktreeConfigError(f"Child project root is invalid: {child}")
        items: list[BootstrapPlanItem] = []
        literal_targets: set[Path] = set()
        for raw in config.copy:
            source, target = self._resolve_pair(raw, main, child)
            self._validate_source(source, main, raw)
            if target in literal_targets:
                raise WorktreeConfigError(f"Bootstrap target is duplicated: {raw}")
            literal_targets.add(target)
            items.extend(self._items_for_copy(source, target, "copy"))
        for raw in config.symlink:
            source, target = self._resolve_pair(raw, main, child)
            self._validate_source(source, main, raw)
            if not source.is_dir():
                raise WorktreeConfigError(f"symlink source must be a directory: {raw}")
            if target in literal_targets:
                raise WorktreeConfigError(f"Bootstrap target is duplicated: {raw}")
            literal_targets.add(target)
            items.append(BootstrapPlanItem("symlink", source, target, 0))
        for pattern in config.ignored:
            for source in sorted(main.glob(pattern)):
                if len(items) >= self.max_files:
                    raise WorktreeConfigError(
                        f"Bootstrap copy exceeds limits: files>{self.max_files}"
                    )
                if not source.is_file() or source.is_symlink():
                    continue
                self._validate_source(source, main, pattern)
                if not repository.is_ignored(source):
                    raise WorktreeConfigError(
                        f"ignored bootstrap pattern matched a non-ignored path: {source}"
                    )
                relative = source.relative_to(main)
                target = (child / relative).resolve(strict=False)
                _assert_target(target, child, pattern)
                if target in literal_targets:
                    raise WorktreeConfigError(f"Bootstrap target is duplicated: {relative}")
                literal_targets.add(target)
                items.append(
                    BootstrapPlanItem("ignored", source, target, source.stat().st_size)
                )
        files = 0
        total = 0
        for item in items:
            if item.kind == "symlink":
                continue
            if item.source.is_dir():
                count, size = self._tree_size(item.source)
            else:
                count, size = 1, item.size or item.source.stat().st_size
            files += count
            total += size
            if files > self.max_files or total > self.max_bytes:
                raise WorktreeConfigError(
                    f"Bootstrap copy exceeds limits: files={files}, bytes={total}"
                )
        return tuple(items)

    @staticmethod
    def _resolve_pair(raw: str, main: Path, child: Path) -> tuple[Path, Path]:
        source = (main / Path(raw)).resolve(strict=False)
        target = (child / Path(raw)).resolve(strict=False)
        _assert_target(source, main, raw)
        _assert_target(target, child, raw)
        return source, target

    @staticmethod
    def _validate_source(source: Path, main: Path, raw: str) -> None:
        _assert_target(source, main, raw)
        if _contains_git_segment(source.relative_to(main)):
            raise WorktreeConfigError(f"Bootstrap cannot access .git: {raw}")
        if not source.exists():
            raise WorktreeConfigError(f"Bootstrap source does not exist: {raw}")
        if source.is_symlink():
            raise WorktreeConfigError(f"Bootstrap source must not be a symlink: {raw}")

    @staticmethod
    def _items_for_copy(source: Path, target: Path, kind: str) -> list[BootstrapPlanItem]:
        if source.is_dir():
            return [BootstrapPlanItem(kind, source, target, 0)]
        return [BootstrapPlanItem(kind, source, target, source.stat().st_size)]

    def _tree_size(self, source: Path) -> tuple[int, int]:
        count = 0
        total = 0
        for path in source.rglob("*"):
            if ".git" in path.relative_to(source).parts:
                raise WorktreeConfigError(f"Bootstrap cannot access .git: {path}")
            if path.is_symlink():
                raise WorktreeConfigError(f"Bootstrap source contains a symlink: {path}")
            if path.is_file():
                count += 1
                total += path.stat().st_size
                if count > self.max_files or total > self.max_bytes:
                    raise WorktreeConfigError(
                        f"Bootstrap copy exceeds limits: files={count}, bytes={total}"
                    )
        return count, total

    @staticmethod
    def _copy(source: Path, target: Path) -> None:
        if target.exists() or target.is_symlink():
            raise WorktreeConfigError(f"Bootstrap target already exists: {target}")
        if source.is_dir():
            shutil.copytree(str(source), str(target), symlinks=False)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(source), str(target), follow_symlinks=False)


def _assert_target(path: Path, root: Path, label: str) -> None:
    try:
        path.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise WorktreeConfigError(f"Bootstrap path escapes root ({label})") from exc


__all__ = [
    "BootstrapPlanItem",
    "BootstrapReport",
    "WorktreeBootstrapper",
    "MAX_COPY_BYTES",
    "MAX_COPY_FILES",
]
