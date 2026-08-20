"""Immutable data models for FlickCode skills."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, FrozenSet, Mapping, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from flickcode.agent import AgentMode
    from flickcode.tools.base import BaseTool


class SkillMode(str, Enum):
    SHARED = "shared"
    ISOLATED = "isolated"


class SkillSource(str, Enum):
    BUILTIN = "builtin"
    USER = "user"
    PROJECT = "project"


class SkillInvocationOrigin(str, Enum):
    TOOL = "tool"
    SLASH = "slash"


@dataclass(frozen=True)
class SkillToolDefinition:
    name: str
    description: str
    input_schema: Dict[str, Any]
    entrypoint: Path
    package_root: Path
    script_source: str
    fingerprint: str


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    tool_names: Tuple[str, ...]
    mode: SkillMode
    history: Optional[int]
    model: Optional[str]
    instructions: str
    source: SkillSource
    entry_path: Path
    package_root: Optional[Path]
    custom_tools: Tuple[SkillToolDefinition, ...]
    fingerprint: str

    def render(self, user_input: str) -> str:
        return self.instructions.replace("{{input}}", user_input)


@dataclass(frozen=True)
class SkillDiagnostic:
    severity: str
    phase: str
    message: str
    path: Optional[Path] = None
    skill_name: Optional[str] = None


@dataclass(frozen=True)
class SkillCatalogSnapshot:
    generation: int = 0
    effective: Mapping[str, SkillDefinition] = field(default_factory=dict)
    shadowed: Mapping[str, Tuple[SkillDefinition, ...]] = field(default_factory=dict)
    diagnostics: Tuple[SkillDiagnostic, ...] = ()
    source_signatures: Mapping[Path, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillCatalogCandidate:
    previous: SkillCatalogSnapshot
    current: SkillCatalogSnapshot
    added: Tuple[str, ...] = ()
    changed: Tuple[str, ...] = ()
    removed: Tuple[str, ...] = ()
    retained_invalid: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ActiveSkill:
    definition: SkillDefinition
    user_input: str
    rendered_instructions: str
    activation_order: int


@dataclass(frozen=True)
class ActivationResult:
    success: bool
    active_skill: Optional[ActiveSkill] = None
    diagnostics: Tuple[SkillDiagnostic, ...] = ()
    changed_tool_names: Tuple[str, ...] = ()
    rebound: bool = False


@dataclass(frozen=True)
class SkillRuntimeSnapshot:
    catalog: SkillCatalogSnapshot
    active_skills: Tuple[ActiveSkill, ...]
    allowed_tool_names: FrozenSet[str]
    diagnostics: Tuple[SkillDiagnostic, ...] = ()


@dataclass(frozen=True)
class SkillRuntimeCandidate:
    previous: SkillRuntimeSnapshot
    catalog: SkillCatalogSnapshot
    active_skills: Tuple[ActiveSkill, ...]
    allowed_tool_names: FrozenSet[str]
    custom_tool_instances: Tuple["BaseTool", ...]
    diagnostics: Tuple[SkillDiagnostic, ...] = ()


@dataclass(frozen=True)
class SkillInvocation:
    definition: SkillDefinition
    user_input: str
    origin: SkillInvocationOrigin
    parent_session_id: str
    parent_agent_mode: "AgentMode"


@dataclass(frozen=True)
class SkillExecutionResult:
    success: bool
    mode: SkillMode
    summary: str
    child_session_id: Optional[str] = None
    diagnostics: Tuple[SkillDiagnostic, ...] = ()


@dataclass(frozen=True)
class ChildSessionMetadata:
    child_session_id: str
    parent_session_id: str
    skill_name: str
    skill_source: SkillSource
    model: str
    status: str


@dataclass(frozen=True)
class ArchivedSkillActivation:
    name: str
    user_input: str
    recorded_source: str
