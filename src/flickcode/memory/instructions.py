"""Layered AGENTS.md loading with bounded, root-confined includes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from flickcode.config import DEFAULT_CONFIG_DIR, MemoryConfig
from flickcode.memory.models import (
    InstructionBundle,
    InstructionDiagnostic,
)


_INCLUDE_RE = re.compile(r"^\s*@include\s+(?:<([^>]+)>|(\S+))\s*$")


class InstructionLoader:
    """Load project and user instructions without allowing path escape."""

    def __init__(
        self,
        config: MemoryConfig | None = None,
        user_root: Path | None = None,
    ) -> None:
        self.config = config or MemoryConfig()
        self.user_root = (user_root or DEFAULT_CONFIG_DIR).expanduser().resolve()

    def load(self, project_root: Path) -> InstructionBundle:
        project_root = project_root.expanduser().resolve()
        diagnostics: list[InstructionDiagnostic] = []
        visited: set[Path] = set()
        name = self.config.instruction_filename
        project_paths = (
            project_root / name,
            project_root / ".flickcode" / name,
        )
        project_parts = [
            self._read_root(path, project_root, visited, diagnostics)
            for path in project_paths
        ]
        user_text = self._read_root(
            self.user_root / name,
            self.user_root,
            visited,
            diagnostics,
        )
        observed = set(visited)
        observed.update(path.resolve(strict=False) for path in project_paths)
        observed.add((self.user_root / name).resolve(strict=False))
        return InstructionBundle(
            project_text=self._join_parts(project_parts),
            user_text=user_text,
            diagnostics=diagnostics,
            source_paths=tuple(sorted(observed)),
        )

    @staticmethod
    def _join_parts(parts: Iterable[str]) -> str:
        return "\n\n".join(part for part in parts if part.strip())

    def _read_root(
        self,
        path: Path,
        allowed_root: Path,
        visited: set[Path],
        diagnostics: list[InstructionDiagnostic],
    ) -> str:
        if not path.exists():
            return ""
        return self._read_file(
            path,
            allowed_root,
            visited,
            diagnostics,
            depth=0,
            include_line=None,
        )

    def _read_file(
        self,
        path: Path,
        allowed_root: Path,
        visited: set[Path],
        diagnostics: list[InstructionDiagnostic],
        *,
        depth: int,
        include_line: int | None,
    ) -> str:
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            # Keep missing includes in the observed set so a later file
            # creation invalidates path-scoped resource caches.
            visited.add(path.expanduser().resolve(strict=False))
            diagnostics.append(
                InstructionDiagnostic(path, f"Cannot resolve instruction file: {exc}", include_line)
            )
            return ""

        if not self._is_within(resolved, allowed_root):
            diagnostics.append(
                InstructionDiagnostic(path, "Included file is outside the allowed root", include_line)
            )
            return ""
        if resolved.suffix.lower() not in (".md", ".markdown"):
            diagnostics.append(
                InstructionDiagnostic(resolved, "Included file must be Markdown", include_line)
            )
            return ""
        if depth > self.config.include_max_depth:
            diagnostics.append(
                InstructionDiagnostic(resolved, "Include nesting depth exceeded", include_line)
            )
            return ""
        if resolved in visited:
            diagnostics.append(
                InstructionDiagnostic(resolved, "Include cycle or duplicate skipped", include_line)
            )
            return ""
        if not resolved.is_file():
            diagnostics.append(
                InstructionDiagnostic(resolved, "Instruction path is not a regular file", include_line)
            )
            return ""

        visited.add(resolved)
        try:
            text = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            diagnostics.append(
                InstructionDiagnostic(resolved, f"Cannot read instruction file: {exc}", include_line)
            )
            return ""

        rendered: list[str] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = _INCLUDE_RE.match(line)
            if not match:
                rendered.append(line)
                continue
            raw_target = match.group(1) or match.group(2) or ""
            target = Path(raw_target)
            if target.is_absolute():
                diagnostics.append(
                    InstructionDiagnostic(resolved, "Include path must be relative", line_number)
                )
                continue
            rendered.append(
                self._read_file(
                    resolved.parent / target,
                    allowed_root,
                    visited,
                    diagnostics,
                    depth=depth + 1,
                    include_line=line_number,
                )
            )
        return "\n".join(rendered).strip()

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False
