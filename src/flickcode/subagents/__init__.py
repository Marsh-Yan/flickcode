"""SubAgent delegation primitives for FlickCode."""

from flickcode.subagents.models import (
    AgentInvocationType,
    AgentModelAlias,
    AgentPermissionMode,
    AgentRoleSource,
    AgentToolOperation,
    AgentUsage,
    SubAgentTaskState,
)
from flickcode.subagents.coordinator import SubAgentCoordinator
from flickcode.subagents.foreground import ForegroundControl
from flickcode.subagents.notifications import NotificationInbox
from flickcode.subagents.provider_pool import ProviderPool
from flickcode.subagents.result_store import SubAgentResultStore
from flickcode.subagents.roles import AgentRoleCatalog, AgentRoleValidator
from flickcode.subagents.runtime import ChildRuntimeFactory, SubAgentRunner
from flickcode.subagents.snapshots import ParentRequestSnapshotStore
from flickcode.subagents.tasks import SubAgentTaskManager
from flickcode.subagents.tool import AgentTool

__all__ = [
    "AgentInvocationType",
    "AgentModelAlias",
    "AgentPermissionMode",
    "AgentRoleSource",
    "AgentToolOperation",
    "AgentUsage",
    "SubAgentTaskState",
    "AgentRoleCatalog",
    "AgentRoleValidator",
    "AgentTool",
    "ChildRuntimeFactory",
    "ForegroundControl",
    "NotificationInbox",
    "ParentRequestSnapshotStore",
    "ProviderPool",
    "SubAgentCoordinator",
    "SubAgentResultStore",
    "SubAgentRunner",
    "SubAgentTaskManager",
]
