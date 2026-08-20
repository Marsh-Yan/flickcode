"""Create, enter, exit and safely delete managed Git Worktrees."""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from flickcode.worktrees.bootstrap import WorktreeBootstrapper
from flickcode.worktrees.config import WorktreeConfigLoader
from flickcode.worktrees.git import GitRepository, GitRunner, GitWorktreeEntry
from flickcode.worktrees.models import (
    AgentIsolationMode,
    RepositoryIdentity,
    WorktreeConfig,
    WorktreeDisposition,
    WorktreeError,
    WorktreeHandle,
    WorktreeLease,
    WorktreeMetadata,
    WorktreeOutcome,
    WorktreeRecoveryError,
    WorktreeSafetyReport,
    WorkspaceContext,
    WorkspaceRequest,
)
from flickcode.worktrees.paths import (
    RepositoryLocator,
    WorktreeLayout,
    WorktreeMetadataStore,
    WorktreeName,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorktreeLifecycle:
    """Single-process lifecycle coordinator for managed Worktrees."""

    def __init__(
        self,
        main_project_root: Path,
        *,
        config: Optional[WorktreeConfig] = None,
        identity: Optional[RepositoryIdentity] = None,
        runner: Optional[GitRunner] = None,
        bootstrapper: Optional[WorktreeBootstrapper] = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.main_project_root = main_project_root.expanduser().resolve()
        self.config = config
        self._identity = identity
        self._runner = runner or GitRunner()
        self.bootstrapper = bootstrapper or WorktreeBootstrapper()
        self.clock = clock
        self._identity_lock = threading.RLock()
        self._locks_guard = threading.Lock()
        self._name_locks: dict[str, threading.RLock] = {}
        self._lease_lock = threading.RLock()
        self._leases: dict[Path, WorktreeLease] = {}

    @property
    def available(self) -> bool:
        try:
            self._get_identity()
            return True
        except WorktreeError:
            return False

    @property
    def identity(self) -> RepositoryIdentity:
        return self._get_identity()

    def _get_identity(self) -> RepositoryIdentity:
        with self._identity_lock:
            if self._identity is None:
                probe = RepositoryLocator.probe_filesystem(self.main_project_root)
                self._identity = probe.identity
            return self._identity

    def _repository(self) -> GitRepository:
        return GitRepository(self._get_identity(), self._runner)

    def _layout(self) -> WorktreeLayout:
        return WorktreeLayout.from_identity(self._get_identity())

    def _store(self) -> WorktreeMetadataStore:
        return WorktreeMetadataStore(self._layout())

    def _name_lock(self, name: WorktreeName) -> threading.RLock:
        with self._locks_guard:
            return self._name_locks.setdefault(name.casefold_key(), threading.RLock())

    def _request_name(self, request: WorkspaceRequest) -> WorktreeName:
        raw = request.logical_name or f"agents/{request.task_id}"
        return WorktreeName.parse(raw)

    def create(self, request: WorkspaceRequest) -> WorktreeHandle:
        if request.isolation is not AgentIsolationMode.WORKTREE:
            raise WorktreeError("create requires isolation=worktree")
        name = self._request_name(request)
        # The filesystem-only probe intentionally happens before the target
        # branch. A recovery path can therefore avoid all Git subprocesses.
        identity = self._get_identity()
        layout = WorktreeLayout.from_identity(identity)
        target = layout.target(name)
        store = WorktreeMetadataStore(layout)
        lock = self._name_lock(name)
        with lock:
            if target.exists():
                return self._recover_existing(name, target, identity, store, request.task_id)
            if store.load(name) is not None:
                raise WorktreeRecoveryError(
                    "Worktree metadata exists but its target directory is missing"
                )
            repository = GitRepository(identity, self._runner)
            repository.validate_identity()
            base_commit = repository.resolve_head()
            branch = layout.branch_name(name, request.task_id)
            repository.validate_branch_name(branch)
            repository.ensure_managed_root_excluded(layout)
            created = self.clock()
            child_project = (target / identity.project_relative_path).resolve(strict=False)
            metadata = WorktreeMetadata(
                schema_version=WorktreeMetadata.SCHEMA_VERSION,
                repository_fingerprint=identity.fingerprint,
                logical_name=name.value,
                worktree_root=target,
                project_root=child_project,
                branch=branch,
                base_commit=base_commit,
                created_at=created,
                last_used_at=created,
                initialization_state="creating",
            )
            repository.add_worktree(target, branch, base_commit)
            store.save(name, metadata)
            bootstrap_config = self.config.bootstrap if self.config else WorktreeConfig().bootstrap
            report = self.bootstrapper.apply(
                bootstrap_config,
                main_project_root=identity.main_project_root,
                child_project_root=child_project,
                repository=repository,
            )
            if not report.success:
                store.save(name, replace(metadata, initialization_state="failed"))
                detail = "; ".join(report.diagnostics) or "unknown bootstrap failure"
                raise WorktreeError(
                    f"Worktree initialization failed for {name.value}: {detail}; "
                    f"retained at {target}"
                )
            ready = replace(metadata, initialization_state="ready")
            store.save(name, ready)
            return self._handle(ready, identity, recovered=False, task_id=request.task_id)

    def _recover_existing(
        self,
        name: WorktreeName,
        target: Path,
        identity: RepositoryIdentity,
        store: WorktreeMetadataStore,
        task_id: str,
    ) -> WorktreeHandle:
        metadata = store.load(name)
        if metadata is None:
            raise WorktreeRecoveryError(
                "Existing Worktree directory has no managed metadata"
            )
        self._validate_metadata(metadata, name, target, identity)
        if metadata.initialization_state != "ready":
            raise WorktreeRecoveryError(
                f"Existing Worktree is not ready: {metadata.initialization_state}"
            )
        if not target.is_dir() or target.is_symlink():
            raise WorktreeRecoveryError("Existing Worktree target is not a regular directory")
        marker = target / ".git"
        if marker.is_symlink() or not marker.exists() or not (marker.is_file() or marker.is_dir()):
            raise WorktreeRecoveryError("Existing Worktree has no valid .git marker")
        return self._handle(metadata, identity, recovered=True, task_id=task_id)

    @staticmethod
    def _validate_metadata(
        metadata: WorktreeMetadata,
        name: WorktreeName,
        target: Path,
        identity: RepositoryIdentity,
    ) -> None:
        if metadata.logical_name != name.value:
            raise WorktreeRecoveryError("Worktree metadata name does not match request")
        if metadata.repository_fingerprint != identity.fingerprint:
            raise WorktreeRecoveryError("Worktree metadata repository does not match")
        if metadata.worktree_root != target:
            raise WorktreeRecoveryError("Worktree metadata path does not match request")
        expected_project = (target / identity.project_relative_path).resolve(strict=False)
        if metadata.project_root != expected_project:
            raise WorktreeRecoveryError("Worktree metadata project path does not match")

    @staticmethod
    def _handle(
        metadata: WorktreeMetadata,
        identity: RepositoryIdentity,
        *,
        recovered: bool,
        task_id: str = "",
    ) -> WorktreeHandle:
        workspace = WorkspaceContext(
            isolation=AgentIsolationMode.WORKTREE,
            project_root=metadata.project_root,
            repository_root=metadata.worktree_root,
            main_project_root=identity.main_project_root,
            task_id=task_id,
            logical_name=metadata.logical_name,
            branch=metadata.branch,
        )
        return WorktreeHandle(metadata, workspace, recovered)

    def enter(self, request: WorkspaceRequest) -> WorktreeLease:
        if request.isolation is AgentIsolationMode.SHARED:
            try:
                identity = self._get_identity()
                repository_root = identity.repository_root
                main = identity.main_project_root
            except WorktreeError:
                repository_root = self.main_project_root
                main = self.main_project_root
            workspace = WorkspaceContext(
                isolation=AgentIsolationMode.SHARED,
                project_root=main,
                repository_root=repository_root,
                main_project_root=main,
                task_id=request.task_id,
            )
            return WorktreeLease(
                WorktreeHandle(
                    WorktreeMetadata(
                        schema_version=WorktreeMetadata.SCHEMA_VERSION,
                        repository_fingerprint="shared",
                        logical_name="shared",
                        worktree_root=main,
                        project_root=main,
                        branch="shared",
                        base_commit="shared",
                        created_at=self.clock(),
                        last_used_at=self.clock(),
                        initialization_state="ready",
                    ),
                    workspace,
                    False,
                )
            )
        name = self._request_name(request)
        lock = self._name_lock(name)
        with lock:
            handle = self.create(request)
            target = handle.metadata.worktree_root
            with self._lease_lock:
                if target in self._leases:
                    raise WorktreeError(f"Worktree is already active: {target}")
                identity = self._get_identity()
                store = WorktreeMetadataStore(WorktreeLayout.from_identity(identity))
                updated = replace(handle.metadata, last_used_at=self.clock())
                store.save(name, updated)
                handle = WorktreeHandle(updated, handle.workspace, handle.recovered)
                lease = WorktreeLease(handle)
                self._leases[target] = lease
                return lease

    def is_active(self, path: Path) -> bool:
        with self._lease_lock:
            return path.expanduser().resolve() in self._leases

    def inspect(self, handle: WorktreeHandle) -> WorktreeSafetyReport:
        if handle.workspace.isolation is AgentIsolationMode.SHARED:
            return WorktreeSafetyReport(clean=True)
        identity = self._get_identity()
        self._validate_metadata(
            handle.metadata,
            WorktreeName.parse(handle.metadata.logical_name),
            handle.metadata.worktree_root,
            identity,
        )
        repository = GitRepository(identity, self._runner)
        diagnostics: list[str] = []
        try:
            entries = repository.list_worktrees()
            matching = [
                entry
                for entry in entries
                if entry.path == handle.metadata.worktree_root
            ]
            if len(matching) != 1 or matching[0].branch != handle.metadata.branch:
                diagnostics.append("Git Worktree list does not match managed metadata")
            changed = repository.status_paths(handle.metadata.worktree_root)
            unique = repository.unique_commits(
                handle.metadata.worktree_root, handle.metadata.base_commit
            )
            unpushed = tuple(
                commit
                for commit in unique
                if not repository.remote_refs_containing(
                    handle.metadata.worktree_root, commit
                )
            )
            return WorktreeSafetyReport(
                clean=not changed,
                changed_paths=changed,
                unique_commits=unique,
                unpushed_commits=unpushed,
                diagnostics=tuple(diagnostics),
            )
        except Exception as exc:
            return WorktreeSafetyReport(
                clean=False,
                diagnostics=(str(exc),),
            )

    def delete(self, handle: WorktreeHandle) -> WorktreeOutcome:
        if handle.workspace.isolation is AgentIsolationMode.SHARED:
            return WorktreeOutcome(WorktreeDisposition.NOT_USED, None, reason="shared workspace")
        try:
            name = WorktreeName.parse(handle.metadata.logical_name)
        except Exception as exc:
            return WorktreeOutcome(
                WorktreeDisposition.RETAINED_CHECK_FAILED,
                handle.metadata.worktree_root,
                handle.metadata.branch,
                f"Worktree name validation failed: {exc}",
            )
        lock = self._name_lock(name)
        with lock:
            if self.is_active(handle.metadata.worktree_root):
                return WorktreeOutcome(
                    WorktreeDisposition.RETAINED_CHECK_FAILED,
                    handle.metadata.worktree_root,
                    handle.metadata.branch,
                    "Worktree has an active lease",
                )
            try:
                identity = self._get_identity()
                current = WorktreeMetadataStore(
                    WorktreeLayout.from_identity(identity)
                ).load(name)
                if current is None or current.to_dict() != handle.metadata.to_dict():
                    return WorktreeOutcome(
                        WorktreeDisposition.RETAINED_CHECK_FAILED,
                        handle.metadata.worktree_root,
                        handle.metadata.branch,
                        "Worktree metadata changed or is missing",
                    )
            except Exception as exc:
                return WorktreeOutcome(
                    WorktreeDisposition.RETAINED_CHECK_FAILED,
                    handle.metadata.worktree_root,
                    handle.metadata.branch,
                    f"Worktree metadata check failed: {exc}",
                )
            try:
                report = self.inspect(handle)
            except Exception as exc:
                return WorktreeOutcome(
                    WorktreeDisposition.RETAINED_CHECK_FAILED,
                    handle.metadata.worktree_root,
                    handle.metadata.branch,
                    f"Worktree safety check failed: {exc}",
                )
            if report.diagnostics:
                return WorktreeOutcome(
                    WorktreeDisposition.RETAINED_CHECK_FAILED,
                    handle.metadata.worktree_root,
                    handle.metadata.branch,
                    "; ".join(report.diagnostics),
                )
            if report.changed_paths:
                return WorktreeOutcome(
                    WorktreeDisposition.RETAINED_CHANGES,
                    handle.metadata.worktree_root,
                    handle.metadata.branch,
                    "Worktree has uncommitted changes",
                )
            if report.unpushed_commits:
                return WorktreeOutcome(
                    WorktreeDisposition.RETAINED_UNPUSHED,
                    handle.metadata.worktree_root,
                    handle.metadata.branch,
                    "Worktree has commits not contained by a remote ref",
                )
            return self._delete_verified(handle, name)

    def _delete_verified(self, handle: WorktreeHandle, name: WorktreeName) -> WorktreeOutcome:
        try:
            identity = self._get_identity()
            store = WorktreeMetadataStore(WorktreeLayout.from_identity(identity))
            current = store.load(name)
        except Exception as exc:
            return WorktreeOutcome(
                WorktreeDisposition.RETAINED_CHECK_FAILED,
                handle.metadata.worktree_root,
                handle.metadata.branch,
                f"Worktree metadata check failed: {exc}",
            )
        if current is None or current.to_dict() != handle.metadata.to_dict():
            return WorktreeOutcome(
                WorktreeDisposition.RETAINED_CHECK_FAILED,
                handle.metadata.worktree_root,
                handle.metadata.branch,
                "Worktree metadata changed or is missing",
            )
        repository = GitRepository(identity, self._runner)
        try:
            repository.remove_worktree(handle.metadata.worktree_root)
            repository.delete_branch(handle.metadata.branch)
            store.delete(name)
            return WorktreeOutcome(
                WorktreeDisposition.REMOVED,
                handle.metadata.worktree_root,
                handle.metadata.branch,
                "Worktree was clean and had no unpushed commits",
            )
        except Exception as exc:
            return WorktreeOutcome(
                WorktreeDisposition.RETAINED_CHECK_FAILED,
                handle.metadata.worktree_root,
                handle.metadata.branch,
                f"Safe deletion failed: {exc}",
            )

    def exit(self, lease: WorktreeLease) -> WorktreeOutcome:
        if lease.released:
            return lease.outcome or WorktreeOutcome(
                WorktreeDisposition.NOT_USED,
                None,
                reason="lease already released",
            )
        handle = lease.handle
        if handle.workspace.isolation is AgentIsolationMode.SHARED:
            lease.released = True
            lease.outcome = WorktreeOutcome(
                WorktreeDisposition.NOT_USED, None, reason="shared workspace"
            )
            return lease.outcome
        name = WorktreeName.parse(handle.metadata.logical_name)
        lock = self._name_lock(name)
        with lock:
            try:
                outcome = self._exit_locked(lease, name)
            except Exception as exc:
                outcome = WorktreeOutcome(
                    WorktreeDisposition.RETAINED_CHECK_FAILED,
                    handle.metadata.worktree_root,
                    handle.metadata.branch,
                    f"Worktree exit failed: {exc}",
                )
            lease.released = True
            lease.outcome = outcome
            with self._lease_lock:
                self._leases.pop(handle.metadata.worktree_root, None)
            return outcome

    def _exit_locked(self, lease: WorktreeLease, name: WorktreeName) -> WorktreeOutcome:
        try:
            identity = self._get_identity()
            current = WorktreeMetadataStore(
                WorktreeLayout.from_identity(identity)
            ).load(name)
            if current is None or current.to_dict() != lease.handle.metadata.to_dict():
                return WorktreeOutcome(
                    WorktreeDisposition.RETAINED_CHECK_FAILED,
                    lease.handle.metadata.worktree_root,
                    lease.handle.metadata.branch,
                    "Worktree metadata changed or is missing",
                )
        except Exception as exc:
            return WorktreeOutcome(
                WorktreeDisposition.RETAINED_CHECK_FAILED,
                lease.handle.metadata.worktree_root,
                lease.handle.metadata.branch,
                f"Worktree metadata check failed: {exc}",
            )
        report = self.inspect(lease.handle)
        if report.diagnostics:
            return WorktreeOutcome(
                WorktreeDisposition.RETAINED_CHECK_FAILED,
                lease.handle.metadata.worktree_root,
                lease.handle.metadata.branch,
                "; ".join(report.diagnostics),
            )
        if report.changed_paths:
            return WorktreeOutcome(
                WorktreeDisposition.RETAINED_CHANGES,
                lease.handle.metadata.worktree_root,
                lease.handle.metadata.branch,
                "Worktree has uncommitted changes",
            )
        if report.unpushed_commits:
            return WorktreeOutcome(
                WorktreeDisposition.RETAINED_UNPUSHED,
                lease.handle.metadata.worktree_root,
                lease.handle.metadata.branch,
                "Worktree has commits not contained by a remote ref",
            )
        with self._lease_lock:
            self._leases.pop(lease.handle.metadata.worktree_root, None)
        return self._delete_verified(lease.handle, name)

    def load_handle(self, name: WorktreeName) -> WorktreeHandle:
        identity = self._get_identity()
        layout = WorktreeLayout.from_identity(identity)
        target = layout.target(name)
        metadata = WorktreeMetadataStore(layout).load(name)
        if metadata is None:
            raise WorktreeRecoveryError("Worktree metadata not found")
        self._validate_metadata(metadata, name, target, identity)
        return self._handle(metadata, identity, recovered=True)


__all__ = ["WorktreeLifecycle", "utc_now"]
