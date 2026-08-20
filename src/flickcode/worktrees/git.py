"""Bounded, explicit-cwd Git operations used by Worktree lifecycle code."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

from flickcode.worktrees.models import (
    RepositoryIdentity,
    WorktreeGitError,
    WorktreeSafetyReport,
)
from flickcode.worktrees.paths import WorktreeLayout


@dataclass(frozen=True)
class GitResult:
    args: tuple[str, ...]
    cwd: Path
    returncode: int
    stdout: str
    stderr: str


class GitRunner:
    """Run Git without a shell and with an explicit working directory."""

    def __init__(self, executable: str = "git", output_limit: int = 16_384) -> None:
        self.executable = executable
        self.output_limit = output_limit

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        timeout: float = 30.0,
        check: bool = True,
    ) -> GitResult:
        root = cwd.expanduser().resolve()
        if not root.is_absolute() or not root.is_dir():
            raise WorktreeGitError(f"Git cwd must be an existing absolute directory: {root}")
        command = tuple(str(item) for item in args)
        try:
            completed = subprocess.run(
                [self.executable, *command],
                cwd=str(root),
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise WorktreeGitError(
                f"Git command timed out after {timeout:g}s: {' '.join(command[:4])}"
            ) from exc
        except OSError as exc:
            raise WorktreeGitError(f"Git could not start: {exc}") from exc
        result = GitResult(
            command,
            root,
            completed.returncode,
            completed.stdout[: self.output_limit],
            completed.stderr[: self.output_limit],
        )
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().replace("\x00", " ")
            raise WorktreeGitError(
                f"Git command failed ({result.returncode}): {' '.join(command[:6])}; "
                f"{detail[:2048]}"
            )
        return result


@dataclass(frozen=True)
class GitWorktreeEntry:
    path: Path
    head: str
    branch: str = ""


class GitRepository:
    """Git semantics for one previously probed repository."""

    def __init__(
        self,
        identity: RepositoryIdentity,
        runner: Optional[GitRunner] = None,
    ) -> None:
        self.identity = identity
        self.runner = runner or GitRunner()

    def _run(
        self,
        args: Sequence[str],
        *,
        cwd: Optional[Path] = None,
        check: bool = True,
        timeout: float = 30.0,
    ) -> GitResult:
        return self.runner.run(
            args,
            cwd=cwd or self.identity.main_project_root,
            timeout=timeout,
            check=check,
        )

    def validate_identity(self) -> None:
        top = self._run(["rev-parse", "--show-toplevel"]).stdout.strip()
        if Path(top).expanduser().resolve() != self.identity.repository_root:
            raise WorktreeGitError("Git repository top-level does not match probed identity")
        common_raw = self._run(["rev-parse", "--git-common-dir"]).stdout.strip()
        common = Path(common_raw)
        if not common.is_absolute():
            common = self.identity.main_project_root / common
        if common.resolve() != self.identity.common_git_dir:
            raise WorktreeGitError("Git common directory does not match probed identity")

    def resolve_head(self) -> str:
        value = self._run(["rev-parse", "--verify", "HEAD^{commit}"]).stdout.strip()
        if not value:
            raise WorktreeGitError("Repository HEAD is empty")
        return value

    def validate_branch_name(self, branch: str) -> None:
        self._run(["check-ref-format", "--branch", branch])

    def ensure_managed_root_excluded(self, layout: WorktreeLayout) -> None:
        layout.managed_root.mkdir(parents=True, exist_ok=True)
        exclude = self.identity.common_git_dir / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        marker = "# FlickCode managed Worktrees"
        rule = "/.flickcode/worktrees/"
        try:
            current = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
            lines = current.splitlines()
            if rule not in lines:
                suffix = "\n" if current and not current.endswith("\n") else ""
                block = f"{suffix}{marker}\n{rule}\n"
                temporary = exclude.with_name(exclude.name + ".flickcode.tmp")
                with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                    handle.write(current + block)
                os.replace(str(temporary), str(exclude))
        except OSError as exc:
            raise WorktreeGitError(f"Cannot update Git info/exclude: {exc}") from exc
        check = self._run(
            ["check-ignore", "--no-index", "--quiet", str(layout.managed_root)],
            check=False,
        )
        if check.returncode != 0:
            raise WorktreeGitError("Managed Worktree root is not excluded by Git")

    def add_worktree(self, path: Path, branch: str, base_commit: str) -> None:
        target = path.expanduser().resolve(strict=False)
        if target.exists():
            raise WorktreeGitError(f"Worktree target already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        self._run(["worktree", "add", "-b", branch, str(target), base_commit])

    def configure_hooks(self, worktree_root: Path) -> None:
        configured = self._run(
            ["config", "--path", "--get", "core.hooksPath"], check=False
        ).stdout.strip()
        if configured:
            hooks = Path(configured)
            if not hooks.is_absolute():
                hooks = self.identity.repository_root / hooks
        else:
            hooks_raw = self._run(["rev-parse", "--git-path", "hooks"]).stdout.strip()
            hooks = Path(hooks_raw)
            if not hooks.is_absolute():
                hooks = self.identity.repository_root / hooks
        hooks = hooks.resolve(strict=False)
        self._run(["config", "extensions.worktreeConfig", "true"])
        self._run(
            ["config", "--worktree", "core.hooksPath", str(hooks)],
            cwd=worktree_root,
        )

    def status_paths(self, worktree_root: Path) -> tuple[str, ...]:
        result = self._run(
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=worktree_root,
        )
        fields = result.stdout.split("\x00")
        paths: list[str] = []
        index = 0
        while index < len(fields):
            field = fields[index]
            index += 1
            if not field:
                continue
            path = field[3:] if len(field) >= 3 else field
            paths.append(path)
            # Porcelain v1 rename/copy entries contain the destination as the
            # next NUL field. Retain both names in the safety summary.
            if len(field) >= 2 and field[0] in {"R", "C"} and index < len(fields):
                if fields[index]:
                    paths.append(fields[index])
                index += 1
        return tuple(paths)

    def is_ignored(self, path: Path) -> bool:
        result = self._run(
            ["check-ignore", "--quiet", str(path)],
            cwd=self.identity.main_project_root,
            check=False,
        )
        if result.returncode == 0:
            return True
        if result.returncode == 1:
            return False
        raise WorktreeGitError(
            f"Git could not determine whether path is ignored: {path}"
        )

    def unique_commits(self, worktree_root: Path, base_commit: str) -> tuple[str, ...]:
        result = self._run(
            ["rev-list", f"{base_commit}..HEAD"], cwd=worktree_root
        )
        return tuple(item for item in result.stdout.splitlines() if item.strip())

    def remote_refs_containing(self, worktree_root: Path, commit: str) -> tuple[str, ...]:
        result = self._run(
            [
                "for-each-ref",
                "--format=%(refname)",
                "--contains",
                commit,
                "refs/remotes",
            ],
            cwd=worktree_root,
        )
        return tuple(item for item in result.stdout.splitlines() if item.strip())

    def list_worktrees(self) -> tuple[GitWorktreeEntry, ...]:
        result = self._run(["worktree", "list", "--porcelain"])
        entries: list[GitWorktreeEntry] = []
        current_path: Optional[Path] = None
        current_head = ""
        current_branch = ""
        for line in result.stdout.splitlines() + [""]:
            if line.startswith("worktree "):
                if current_path is not None:
                    entries.append(GitWorktreeEntry(current_path, current_head, current_branch))
                current_path = Path(line[9:]).expanduser().resolve()
                current_head = ""
                current_branch = ""
            elif line.startswith("HEAD "):
                current_head = line[5:].strip()
            elif line.startswith("branch "):
                ref = line[7:].strip()
                current_branch = ref[len("refs/heads/") :] if ref.startswith("refs/heads/") else ref
            elif not line and current_path is not None:
                entries.append(GitWorktreeEntry(current_path, current_head, current_branch))
                current_path = None
        return tuple(entries)

    def remove_worktree(self, path: Path) -> None:
        self._run(["worktree", "remove", "--force", str(path)])

    def delete_branch(self, branch: str) -> None:
        self._run(["branch", "-D", branch])


__all__ = ["GitRepository", "GitResult", "GitRunner", "GitWorktreeEntry"]
