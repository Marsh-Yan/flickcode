"""Shared models for local instructions and long-term memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class MemoryCategory(str, Enum):
    """The only note classes that the automatic updater may write."""

    USER_PREFERENCE = "user_preference"
    CORRECTION_FEEDBACK = "correction_feedback"
    PROJECT_KNOWLEDGE = "project_knowledge"
    REFERENCE = "reference"


@dataclass
class InstructionDiagnostic:
    source: Path
    message: str
    line: Optional[int] = None


@dataclass
class InstructionBundle:
    """Expanded instructions split by their model-priority scope."""

    project_text: str = ""
    user_text: str = ""
    diagnostics: list[InstructionDiagnostic] = field(default_factory=list)
    source_paths: tuple[Path, ...] = ()


@dataclass
class MemoryDiagnostic:
    source: Optional[Path]
    message: str


@dataclass
class MemoryNote:
    note_id: str
    category: MemoryCategory
    content: str
    created_at: datetime
    updated_at: datetime


@dataclass
class MemoryChange:
    """A validated-or-pending proposed edit for one note repository."""

    scope: str
    action: str
    note_id: Optional[str] = None
    category: Optional[MemoryCategory] = None
    content: str = ""
