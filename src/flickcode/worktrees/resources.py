"""Workspace-scoped instruction, memory and system-prompt resources."""

from __future__ import annotations

import hashlib
import platform
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from flickcode.config import DEFAULT_CONFIG_DIR, MemoryConfig
from flickcode.memory.instructions import InstructionLoader
from flickcode.memory.models import InstructionBundle
from flickcode.worktrees.models import WorkspaceContext


@dataclass(frozen=True)
class _Version:
    mtime_ns: int
    size: int
    inode: int = 0
    ctime_ns: int = 0


def _version(path: Path) -> Optional[_Version]:
    try:
        stat = path.stat()
    except OSError:
        return None
    return _Version(
        getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)),
        stat.st_size,
        getattr(stat, "st_ino", 0),
        getattr(stat, "st_ctime_ns", int(stat.st_ctime * 1_000_000_000)),
    )


class WorkspaceResourceCache:
    """Cache values only under absolute path/version based keys."""

    def __init__(self) -> None:
        self._instructions: Dict[Path, Tuple[Tuple[Tuple[Path, Optional[_Version]], ...], InstructionBundle]] = {}
        self._memory: Dict[Path, Tuple[Optional[_Version], str]] = {}
        self._prompts: Dict[Tuple[Path, str, str, str], str] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _instruction_signature(bundle: InstructionBundle) -> tuple:
        return tuple((path.resolve(), _version(path)) for path in bundle.source_paths)

    def instructions(self, project_root: Path, loader: InstructionLoader) -> InstructionBundle:
        root = project_root.expanduser().resolve()
        with self._lock:
            cached = self._instructions.get(root)
            if cached is not None:
                signature, bundle = cached
                current = tuple((path, _version(path)) for path, _ in signature)
                if current == signature:
                    return bundle
            bundle = loader.load(root)
            self._instructions[root] = (self._instruction_signature(bundle), bundle)
            return bundle

    def memory_index(self, index_path: Path) -> str:
        path = index_path.expanduser().resolve()
        current = _version(path)
        with self._lock:
            cached = self._memory.get(path)
            if cached is not None and cached[0] == current:
                return cached[1]
            if current is None:
                content = ""
            else:
                try:
                    content = path.read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    content = ""
            self._memory[path] = (current, content)
            return content

    def system_prompt(
        self,
        project_root: Path,
        role_fingerprint: str,
        resource_fingerprint: str,
        build: Callable[[], str],
    ) -> str:
        key = (
            project_root.expanduser().resolve(),
            role_fingerprint,
            resource_fingerprint,
            date.today().isoformat(),
        )
        with self._lock:
            if key not in self._prompts:
                self._prompts[key] = build()
            return self._prompts[key]

    def keys(self) -> tuple[tuple[Path, str, str, str], ...]:
        with self._lock:
            return tuple(self._prompts)


class WorkspacePromptFactory:
    def __init__(
        self,
        *,
        memory_config: Optional[MemoryConfig] = None,
        user_root: Optional[Path] = None,
        cache: Optional[WorkspaceResourceCache] = None,
    ) -> None:
        self.memory_config = memory_config or MemoryConfig()
        self.user_root = (user_root or DEFAULT_CONFIG_DIR).expanduser().resolve()
        self.cache = cache or WorkspaceResourceCache()

    def build_defined_prompt(
        self,
        *,
        role_prompt: str,
        role_fingerprint: str,
        workspace: WorkspaceContext,
    ) -> str:
        instruction_loader = InstructionLoader(self.memory_config, self.user_root)
        bundle = self.cache.instructions(workspace.project_root, instruction_loader)
        project_memory = self.cache.memory_index(workspace.project_root / "memory" / "index.md")
        user_memory = self.cache.memory_index(self.user_root / "memory" / "index.md")
        resource_parts = [
            bundle.project_text,
            bundle.user_text,
            project_memory,
            user_memory,
            f"workspace:{workspace.project_root}:{workspace.repository_root}:"
            f"{workspace.main_project_root}:{workspace.branch}:{workspace.isolation.value}",
        ]
        # Include absolute source paths and filesystem versions in the
        # prompt fingerprint, not only rendered text. This invalidates a
        # cached prompt when an include or memory index is deleted/recreated
        # with identical bytes.
        for source in bundle.source_paths:
            version = _version(source)
            resource_parts.append(
                f"source:{source.resolve()}:{version!r}"
            )
        for memory_path in (
            workspace.project_root / "memory" / "index.md",
            self.user_root / "memory" / "index.md",
        ):
            resource_parts.append(
                f"memory:{memory_path.expanduser().resolve()}:{_version(memory_path)!r}"
            )
        resource_fingerprint = hashlib.sha256(
            "\n\x00\n".join(resource_parts).encode("utf-8")
        ).hexdigest()

        def build() -> str:
            sections = [role_prompt.strip()]
            if bundle.project_text.strip():
                sections.append(
                    "[project instructions]\n" + bundle.project_text.strip()
                )
            if bundle.user_text.strip():
                sections.append("[user instructions]\n" + bundle.user_text.strip())
            if project_memory.strip():
                sections.append("[project memory]\n" + project_memory.strip())
            if user_memory.strip():
                sections.append("[user memory]\n" + user_memory.strip())
            sections.append(
                "[environment]\n"
                f"project_root: {workspace.project_root}\n"
                f"worktree_root: {workspace.repository_root}\n"
                f"main_project_root: {workspace.main_project_root}\n"
                f"branch: {workspace.branch or '(shared)'}\n"
                f"isolation: {workspace.isolation.value}\n"
                f"platform: {platform.system()}\n"
                f"date: {date.today().isoformat()}\n"
                "All file and command operations must target project_root explicitly."
            )
            return "\n\n".join(item for item in sections if item)

        return self.cache.system_prompt(
            workspace.project_root,
            role_fingerprint,
            resource_fingerprint,
            build,
        )


__all__ = ["WorkspacePromptFactory", "WorkspaceResourceCache"]
