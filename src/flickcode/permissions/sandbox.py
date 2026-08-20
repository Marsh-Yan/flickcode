"""Path sandbox — restricts file I/O to within the project directory.

Symlinks are resolved before the prefix check so that
``/project/link -> /etc/passwd`` is correctly caught.
"""

from __future__ import annotations

from pathlib import Path


class PathSandbox:
    """Ensures file paths resolve to somewhere inside *project_root*.

    Usage::

        sandbox = PathSandbox("/home/user/project")
        err = sandbox.check("/home/user/project/src/main.py")   # None
        err = sandbox.check("/etc/passwd")                       # str
    """

    def __init__(self, project_root: str | Path) -> None:
        self._root = Path(project_root).resolve()

    def check(self, path: str, cwd: str | Path | None = None) -> str | None:
        """Check whether *path* is inside the sandbox.

        Returns *None* when the path is allowed, or an error message
        when it is outside the project directory.
        """
        try:
            candidate = Path(path)
            if not candidate.is_absolute():
                candidate = (Path(cwd).resolve() if cwd is not None else self._root) / candidate
            resolved = candidate.resolve()
        except (OSError, RuntimeError) as exc:
            return f"Path resolution error: {exc}"

        # The root itself is always allowed.
        if resolved == self._root:
            return None

        try:
            resolved.relative_to(self._root)
        except ValueError:
            return (
                f"Path '{path}' is outside the project directory "
                f"({self._root})."
            )

        return None

    @property
    def project_root(self) -> Path:
        """The resolved project root directory."""
        return self._root
