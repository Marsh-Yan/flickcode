"""Bounded background cleanup for managed Worktrees."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from flickcode.worktrees.lifecycle import WorktreeLifecycle
from flickcode.worktrees.models import WorktreeConfig, WorktreeRecoveryError
from flickcode.worktrees.paths import WorktreeLayout, WorktreeName, WorktreeNameError


@dataclass(frozen=True)
class CleanupReport:
    scanned: int = 0
    expired: int = 0
    removed: int = 0
    skipped_path: int = 0
    skipped_ownership: int = 0
    skipped_active: int = 0
    retained: int = 0
    failed: int = 0
    diagnostics: tuple[str, ...] = ()


class WorktreeJanitor:
    """Run safe cleanup without blocking the Agent loop."""

    def __init__(
        self,
        lifecycle: WorktreeLifecycle,
        *,
        config: Optional[WorktreeConfig] = None,
        interval_seconds: float = 60.0 * 60.0,
        max_candidates: int = 256,
    ) -> None:
        self.lifecycle = lifecycle
        self.config = config or WorktreeConfig()
        self.interval_seconds = max(0.1, float(interval_seconds))
        self.max_candidates = max(1, int(max_candidates))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="flick-worktree-janitor",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        # The initial scan is asynchronous so Session startup never waits for
        # Git or a large state directory.
        try:
            self.run_once()
        except Exception:
            pass
        while not self._stop.wait(self.interval_seconds):
            try:
                self.run_once()
            except Exception:
                continue

    def close(self, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(max(0.0, timeout))
        self._thread = None

    def run_once(self, now: Optional[datetime] = None) -> CleanupReport:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        try:
            identity = self.lifecycle.identity
        except Exception as exc:
            return CleanupReport(diagnostics=(str(exc),))
        try:
            layout = WorktreeLayout.from_identity(identity)
        except Exception as exc:
            return CleanupReport(diagnostics=(str(exc),))
        if not layout.state_root.is_dir():
            return CleanupReport()
        files = sorted(layout.state_root.glob("*.json"), key=lambda path: path.name)
        files = files[: self.max_candidates]
        scanned = expired = removed = path_skips = ownership_skips = 0
        active_skips = retained = failed = 0
        diagnostics: list[str] = []
        cutoff = timedelta(days=self.config.expiry_days)
        for state_path in files:
            scanned += 1
            try:
                if state_path.is_symlink() or not state_path.is_file():
                    path_skips += 1
                    continue
                raw = json.loads(state_path.read_text(encoding="utf-8"))
                from flickcode.worktrees.models import WorktreeMetadata

                metadata = WorktreeMetadata.from_mapping(raw)
                name = WorktreeName.parse(metadata.logical_name)
                target = layout.target(name)
                if metadata.worktree_root != target or metadata.repository_fingerprint != identity.fingerprint:
                    ownership_skips += 1
                    continue
                try:
                    target.relative_to(layout.managed_root)
                except ValueError:
                    path_skips += 1
                    continue
                if not target.exists() or metadata.initialization_state != "ready":
                    ownership_skips += 1
                    continue
                if now - metadata.last_used_at < cutoff:
                    continue
                expired += 1
                if self.lifecycle.is_active(target):
                    active_skips += 1
                    continue
                handle = self.lifecycle.load_handle(name)
                outcome = self.lifecycle.delete(handle)
                if outcome.disposition.value == "removed":
                    removed += 1
                elif outcome.disposition.value in {
                    "retained_changes",
                    "retained_unpushed",
                }:
                    retained += 1
                else:
                    failed += 1
                    diagnostics.append(outcome.reason)
            except WorktreeNameError as exc:
                path_skips += 1
                diagnostics.append(f"{state_path}: {exc}")
            except WorktreeRecoveryError as exc:
                ownership_skips += 1
                diagnostics.append(f"{state_path}: {exc}")
            except json.JSONDecodeError as exc:
                ownership_skips += 1
                diagnostics.append(f"{state_path}: {exc}")
            except OSError as exc:
                failed += 1
                diagnostics.append(f"{state_path}: {exc}")
            except ValueError as exc:
                failed += 1
                diagnostics.append(f"{state_path}: {exc}")
            except Exception as exc:
                failed += 1
                diagnostics.append(f"{state_path}: {exc}")
        return CleanupReport(
            scanned=scanned,
            expired=expired,
            removed=removed,
            skipped_path=path_skips,
            skipped_ownership=ownership_skips,
            skipped_active=active_skips,
            retained=retained,
            failed=failed,
            diagnostics=tuple(diagnostics[:64]),
        )


__all__ = ["CleanupReport", "WorktreeJanitor"]
