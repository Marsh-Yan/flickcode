"""Focused tests for the initial Worktree lifecycle implementation."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from flickcode.worktrees.config import WorktreeConfigLoader
from flickcode.worktrees.lifecycle import WorktreeLifecycle
from flickcode.worktrees.git import GitRunner
from flickcode.worktrees.models import (
    AgentIsolationMode,
    WorktreeDisposition,
    WorkspaceRequest,
)
from flickcode.worktrees.paths import WorktreeName


class WorktreeNameTests(unittest.TestCase):
    def test_safe_nested_names_and_rejections(self):
        self.assertEqual(WorktreeName.parse("agents/task-1").segments, ("agents", "task-1"))
        for value in ("../x", "a//b", "/x", "x/", "a\\b", ".", "..", "A/x"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    WorktreeName.parse(value)


class WorktreeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.outer = tempfile.TemporaryDirectory(dir=".tmp")
        self.root = Path(self.outer.name).resolve()
        self._git("init", "-q")
        self._git("config", "user.email", "tests@example.invalid")
        self._git("config", "user.name", "Worktree Tests")
        (self.root / "README.md").write_text("base\n", encoding="utf-8")
        self._git("add", "README.md")
        self._git("commit", "-qm", "base")

    def tearDown(self):
        self.outer.cleanup()

    def _git(self, *args, cwd=None):
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd or self.root),
            check=True,
            capture_output=True,
            text=True,
        )

    def test_create_exit_clean_and_recover(self):
        lifecycle = WorktreeLifecycle(self.root)
        request = WorkspaceRequest(AgentIsolationMode.WORKTREE, "agent-abc123", "agents/agent-abc123")
        lease = lifecycle.enter(request)
        target = lease.handle.metadata.worktree_root
        self.assertTrue((target / "README.md").exists())
        self.assertTrue(lease.handle.metadata.branch.startswith("flick/agents/"))
        outcome = lifecycle.exit(lease)
        self.assertEqual(outcome.disposition, WorktreeDisposition.REMOVED)
        self.assertFalse(target.exists())

    def test_dirty_worktree_is_retained(self):
        lifecycle = WorktreeLifecycle(self.root)
        request = WorkspaceRequest(AgentIsolationMode.WORKTREE, "agent-dirty", "agents/agent-dirty")
        lease = lifecycle.enter(request)
        target = lease.handle.metadata.worktree_root
        (target / "dirty.txt").write_text("keep\n", encoding="utf-8")
        outcome = lifecycle.exit(lease)
        self.assertEqual(outcome.disposition, WorktreeDisposition.RETAINED_CHANGES)
        self.assertTrue(target.exists())

    def test_existing_recovery_performs_no_git_subprocess(self):
        lifecycle = WorktreeLifecycle(self.root)
        request = WorkspaceRequest(
            AgentIsolationMode.WORKTREE, "agent-recover", "agents/agent-recover"
        )
        lease = lifecycle.enter(request)

        class FailingRunner(GitRunner):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def run(self, *args, **kwargs):
                self.calls += 1
                raise AssertionError("filesystem recovery must not invoke Git")

        failing = FailingRunner()
        recovered = WorktreeLifecycle(self.root, runner=failing).create(request)
        self.assertTrue(recovered.recovered)
        self.assertEqual(failing.calls, 0)
        lifecycle.exit(lease)

    def test_missing_git_directory_is_not_an_isolation_fallback(self):
        plain = Path(self.outer.name) / "plain"
        plain.mkdir()
        lifecycle = WorktreeLifecycle(plain)
        with self.assertRaises(Exception):
            lifecycle.enter(
                WorkspaceRequest(AgentIsolationMode.WORKTREE, "agent-no-git", "agents/no-git")
            )


class WorktreeConfigTests(unittest.TestCase):
    def test_missing_config_is_safe_default(self):
        with tempfile.TemporaryDirectory(dir=".tmp") as raw:
            config, diagnostics = WorktreeConfigLoader().load(Path(raw))
            self.assertEqual(config.expiry_days, 7)
            self.assertFalse(diagnostics)


if __name__ == "__main__":
    unittest.main()
