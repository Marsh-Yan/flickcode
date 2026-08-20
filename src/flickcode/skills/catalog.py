"""Discovery and transactional refresh for FlickCode skills."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from types import MappingProxyType
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from flickcode.skills.models import (
    SkillCatalogCandidate,
    SkillCatalogSnapshot,
    SkillDefinition,
    SkillDiagnostic,
    SkillSource,
)
from flickcode.skills.parser import SkillParseError, SkillParser


_SOURCE_PRIORITY = (SkillSource.PROJECT, SkillSource.USER, SkillSource.BUILTIN)


class SkillCatalog:
    """Maintains an immutable, priority-resolved view of available skills."""

    def __init__(
        self,
        project_root: Path,
        user_root: Path,
        builtin_root: Path,
        parser: Optional[SkillParser] = None,
    ) -> None:
        self._roots = {
            SkillSource.PROJECT: Path(project_root),
            SkillSource.USER: Path(user_root),
            SkillSource.BUILTIN: Path(builtin_root),
        }
        self._parser = parser or SkillParser()
        self._cache: Dict[Path, Tuple[str, SkillDefinition]] = {}
        self._snapshot = SkillCatalogSnapshot(
            effective=MappingProxyType({}),
            shadowed=MappingProxyType({}),
            source_signatures=MappingProxyType({}),
        )

    @property
    def snapshot(self) -> SkillCatalogSnapshot:
        return self._snapshot

    def resolve(self, name: str) -> Optional[SkillDefinition]:
        return self._snapshot.effective.get(name)

    def prepare_refresh(self) -> SkillCatalogCandidate:
        diagnostics: List[SkillDiagnostic] = []
        by_source: Dict[SkillSource, Dict[str, List[SkillDefinition]]] = {
            source: defaultdict(list) for source in _SOURCE_PRIORITY
        }
        signatures: Dict[Path, str] = {}
        invalid_names = set()

        for source in _SOURCE_PRIORITY:
            for path, is_package in self._discover(self._roots[source]):
                signature = self._path_signature(path, is_package)
                signatures[path] = signature
                cached = self._cache.get(path)
                try:
                    if cached is not None and cached[0] == signature:
                        definition = cached[1]
                    elif is_package:
                        definition = self._parser.parse_package(path, source)
                    else:
                        definition = self._parser.parse_file(path, source)
                except SkillParseError as exc:
                    self._cache.pop(path, None)
                    if exc.skill_name:
                        invalid_names.add(exc.skill_name)
                    diagnostics.append(
                        SkillDiagnostic(
                            severity="error",
                            phase="parse",
                            message=str(exc),
                            path=exc.path,
                            skill_name=exc.skill_name,
                        )
                    )
                    continue
                self._cache[path] = (signature, definition)
                by_source[source][definition.name].append(definition)

        effective: Dict[str, SkillDefinition] = {}
        shadowed: Dict[str, Tuple[SkillDefinition, ...]] = {}
        names = sorted({name for entries in by_source.values() for name in entries})
        for name in names:
            valid_by_source: Dict[SkillSource, SkillDefinition] = {}
            duplicates: List[SkillDefinition] = []
            for source in _SOURCE_PRIORITY:
                definitions = by_source[source].get(name, [])
                if len(definitions) > 1:
                    duplicates.extend(definitions)
                    diagnostics.append(
                        SkillDiagnostic(
                            severity="error",
                            phase="catalog",
                            message=(
                                f"duplicate skill name {name!r} in {source.value} tier: "
                                + ", ".join(str(item.entry_path) for item in definitions)
                            ),
                            skill_name=name,
                        )
                    )
                elif definitions:
                    valid_by_source[source] = definitions[0]
            selected = next(
                (valid_by_source[source] for source in _SOURCE_PRIORITY if source in valid_by_source),
                None,
            )
            if selected is None:
                continue
            effective[name] = selected
            lower = [
                valid_by_source[source]
                for source in _SOURCE_PRIORITY
                if source in valid_by_source and valid_by_source[source] is not selected
            ]
            lower.extend(duplicates)
            if lower:
                shadowed[name] = tuple(lower)

        current = self._build_snapshot(effective, shadowed, diagnostics, signatures)
        old_names = set(self._snapshot.effective)
        new_names = set(current.effective)
        changed = tuple(
            sorted(
                name
                for name in old_names & new_names
                if self._definition_key(self._snapshot.effective[name])
                != self._definition_key(current.effective[name])
            )
        )
        return SkillCatalogCandidate(
            previous=self._snapshot,
            current=current,
            added=tuple(sorted(new_names - old_names)),
            changed=changed,
            removed=tuple(sorted(old_names - new_names)),
            retained_invalid=tuple(sorted(invalid_names)),
        )

    def commit(self, candidate: SkillCatalogCandidate) -> SkillCatalogSnapshot:
        if candidate.previous is not self._snapshot:
            raise RuntimeError("stale skill catalog candidate")
        self._snapshot = candidate.current
        return self._snapshot

    def refresh(self) -> SkillCatalogSnapshot:
        return self.commit(self.prepare_refresh())

    def _build_snapshot(
        self,
        effective: Mapping[str, SkillDefinition],
        shadowed: Mapping[str, Tuple[SkillDefinition, ...]],
        diagnostics: Sequence[SkillDiagnostic],
        signatures: Mapping[Path, str],
    ) -> SkillCatalogSnapshot:
        content_key = (
            tuple((name, self._definition_key(value)) for name, value in sorted(effective.items())),
            tuple(
                (name, tuple(self._definition_key(item) for item in values))
                for name, values in sorted(shadowed.items())
            ),
            tuple((item.severity, item.phase, item.message, str(item.path), item.skill_name) for item in diagnostics),
            tuple((str(path), signature) for path, signature in sorted(signatures.items(), key=lambda item: str(item[0]))),
        )
        old_key = (
            tuple((name, self._definition_key(value)) for name, value in sorted(self._snapshot.effective.items())),
            tuple(
                (name, tuple(self._definition_key(item) for item in values))
                for name, values in sorted(self._snapshot.shadowed.items())
            ),
            tuple(
                (item.severity, item.phase, item.message, str(item.path), item.skill_name)
                for item in self._snapshot.diagnostics
            ),
            tuple(
                (str(path), signature)
                for path, signature in sorted(self._snapshot.source_signatures.items(), key=lambda item: str(item[0]))
            ),
        )
        generation = self._snapshot.generation + (content_key != old_key)
        return SkillCatalogSnapshot(
            generation=generation,
            effective=MappingProxyType(dict(effective)),
            shadowed=MappingProxyType(dict(shadowed)),
            diagnostics=tuple(diagnostics),
            source_signatures=MappingProxyType(dict(signatures)),
        )

    @staticmethod
    def _discover(root: Path) -> Tuple[Tuple[Path, bool], ...]:
        root = root.expanduser()
        if not root.is_dir():
            return ()
        found: List[Tuple[Path, bool]] = []
        try:
            entries = sorted(root.iterdir(), key=lambda path: path.name)
        except OSError:
            return ()
        for path in entries:
            if path.is_file() and path.suffix.lower() == ".md":
                found.append((path.absolute(), False))
            elif path.is_dir() and (path / "SKILL.md").is_file():
                found.append((path.absolute(), True))
        return tuple(found)

    @staticmethod
    def _path_signature(path: Path, is_package: bool) -> str:
        candidates: Iterable[Path]
        if is_package:
            candidates = (
                item
                for item in path.rglob("*")
                if item.is_file() and not item.is_symlink()
            )
        else:
            candidates = (path,)
        pieces = []
        for item in sorted(candidates, key=lambda value: str(value)):
            try:
                stat = item.stat()
                relative = item.relative_to(path) if is_package else item.name
                pieces.append(f"{relative}:{stat.st_mtime_ns}:{stat.st_size}")
            except OSError as exc:
                pieces.append(f"{item}:error:{exc}")
        return hashlib.sha256("\n".join(pieces).encode("utf-8")).hexdigest()

    @staticmethod
    def _definition_key(definition: SkillDefinition) -> Tuple[str, str, str]:
        return definition.source.value, str(definition.entry_path), definition.fingerprint
