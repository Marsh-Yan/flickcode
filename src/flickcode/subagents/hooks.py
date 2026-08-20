"""Task-local Hook state backed by the parent's shared Hook infrastructure."""

from __future__ import annotations

from flickcode.hooks import HookEngine
from flickcode.worktrees.models import WorkspaceContext


class SubAgentHookScope(HookEngine):
    def __init__(
        self,
        parent: HookEngine,
        spec,
        workspace: WorkspaceContext | None = None,
    ) -> None:
        project_root = workspace.project_root if workspace is not None else parent.project_root
        super().__init__(
            parent.catalog,
            project_root,
            diagnostic_callback=parent.diagnostic_callback,
            shell_runner=parent.actions.shell_runner,
            http_opener=parent.actions.http_opener,
            background=parent.background,
        )
        self.project_trust = parent.project_trust
        self._started = parent._started
        self._closed = parent._closed
        self._session_id = spec.task_id
        self._turn_mode = spec.mode.value
        self._agent_values = {
            "agent_task_id": spec.task_id,
            "agent_parent_task_id": spec.parent_session_id,
            "agent_kind": "subagent",
            "agent_invocation_type": spec.invocation_type.value,
            "agent_role_name": spec.role.name if spec.role else "",
            "agent_state": "running",
            "agent_background": spec.forced_background,
            "agent_isolation": workspace.isolation.value if workspace is not None else "shared",
            "agent_project_root": str(project_root),
            "agent_worktree_root": str(workspace.repository_root) if workspace is not None else str(project_root),
            "agent_branch": workspace.branch if workspace is not None else "",
        }
        self.prompt_state.begin_session()

    def make_event(self, name, **values):
        for key, value in self._agent_values.items():
            values.setdefault(key, value)
        return super().make_event(name, **values)

    def advance_agent_round(self, number: int, mode: str) -> None:
        self.set_turn(number, mode)

    def close_scope(self) -> None:
        self.prompt_state.end_session()

    def close(self) -> None:
        """The parent owns the shared executor and closes it exactly once."""
