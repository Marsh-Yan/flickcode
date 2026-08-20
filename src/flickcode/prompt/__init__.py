"""System prompt builder package.

The ``SystemPromptBuilder`` assembles structured system prompts from
modular ``PromptSection`` subclasses, splitting content into a cached
system channel and a dynamic messages channel.
"""

from flickcode.prompt.builder import PromptSection, SystemPromptBuilder
from flickcode.prompt.sections import (
    ActionExecutionSection,
    ActiveSkillsSection,
    IdentitySection,
    IsolatedSkillHandoffSection,
    ProjectInstructionsSection,
    ProjectMemorySection,
    SystemConstraintsSection,
    SkillCatalogSection,
    TaskModeSection,
    TextOutputSection,
    ToneStyleSection,
    ToolUseSection,
    UserInstructionsSection,
    UserMemorySection,
)
from flickcode.prompt.whisper import (
    WHISPER_TAG,
    make_mode_instruction,
    make_whisper_message,
    should_inject_full_mode_instruction,
)

__all__ = [
    "PromptSection",
    "SystemPromptBuilder",
    # Sections
    "IdentitySection",
    "ProjectInstructionsSection",
    "UserInstructionsSection",
    "ProjectMemorySection",
    "UserMemorySection",
    "SystemConstraintsSection",
    "TaskModeSection",
    "ActionExecutionSection",
    "ActiveSkillsSection",
    "SkillCatalogSection",
    "IsolatedSkillHandoffSection",
    "ToolUseSection",
    "ToneStyleSection",
    "TextOutputSection",
    # Whisper
    "WHISPER_TAG",
    "make_whisper_message",
    "should_inject_full_mode_instruction",
    "make_mode_instruction",
]
