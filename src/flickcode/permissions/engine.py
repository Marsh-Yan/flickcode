"""PermissionEngine — orchestrates all five layers of permission checks.

Flow::

    check(tool_name, params)
      ├─ 1. Blacklist (execute_command only) ──→ DENY if hit
      ├─ 2. PathSandbox (file tools only) ─────→ DENY if outside
      ├─ 3. HITL session memory ───────────────→ ALLOW if memorised
      ├─ 4. Rule engine ───────────────────────→ rule verdict
      └─ 5. Mode fallback ─────────────────────→ strict=DENY
                                                   permissive=ALLOW
                                                   default=HITL (→ callback)
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from flickcode.permissions.blacklist import check as blacklist_check
from flickcode.permissions.hitl import HITLMemory
from flickcode.permissions.models import CheckResult, PermissionMode
from flickcode.permissions.rules import evaluate as rule_evaluate
from flickcode.permissions.sandbox import PathSandbox

# Tools whose ``path`` parameter should be sandbox-checked.
_PATH_TOOLS = frozenset({"read_file", "write_file", "edit_file", "glob"})

# Callback signature: (tool_name, params) -> "allow_once" | "allow_session" | "allow_forever" | "deny"
HITLCallback = Callable[[str, dict], str]


class PermissionEngine:
    """Orchestrates the five permission layers.

    Args:
        mode:          The global permission mode.
        project_root:  Root of the project directory for the path sandbox.
        hitl_callback: Optional callable invoked when HITL input is needed.
                       When *None*, ``check()`` returns ``allowed=None``
                       and the caller is responsible for resolving the
                       decision.
    """

    def __init__(
        self,
        mode: PermissionMode = PermissionMode.DEFAULT,
        project_root: str | Path | None = None,
        hitl_callback: HITLCallback | None = None,
    ) -> None:
        self.mode = mode
        self._sandbox = PathSandbox(project_root or Path.cwd())
        self._hitl_memory = HITLMemory()
        self._hitl_callback = hitl_callback

    # ── Public API ─────────────────────────────────────────────────

    def check(self, tool_name: str, params: dict, cwd: str | Path | None = None) -> CheckResult:
        """Run the full permission check pipeline for a tool call.

        Args:
            tool_name: Name of the tool being invoked.
            params:    Parameters passed to the tool.

        Returns:
            A ``CheckResult`` with the verdict.
        """
        # ── Layer 1: Blacklist (execute_command only) ──────────────
        if tool_name == "execute_command":
            command = params.get("command", "")
            hit = blacklist_check(command)
            if hit is not None:
                return CheckResult(
                    allowed=False,
                    reason=f"Blocked by blacklist: {hit}",
                    layer="blacklist",
                )

        # ── Layer 2: Path sandbox (file tools only) ────────────────
        if tool_name in _PATH_TOOLS:
            path = params.get("path", "")
            err = self._sandbox.check(path, cwd=cwd)
            if err is not None:
                return CheckResult(
                    allowed=False,
                    reason=f"Blocked by sandbox: {err}",
                    layer="sandbox",
                )
            # For glob, also check the ``pattern`` argument if it looks
            # like a path prefix (e.g. "../../etc/").
            if tool_name == "glob":
                pattern = params.get("pattern", "")
                # Extract any directory prefix from the glob pattern
                prefix = Path(pattern).parent
                if str(prefix) not in ("", "."):
                    prefix_str = str(prefix)
                    if not prefix_str.startswith(str(self._sandbox.project_root)):
                        err2 = self._sandbox.check(prefix_str, cwd=cwd)
                        if err2 is not None:
                            return CheckResult(
                                allowed=False,
                                reason=f"Blocked by sandbox: {err2}",
                                layer="sandbox",
                            )

        # ── Layer 3: HITL session memory ───────────────────────────
        if self._hitl_memory.check(tool_name, params):
            return CheckResult(
                allowed=True,
                reason="Session permit",
                layer="hitl_memory",
            )

        # ── Layer 4: Rule engine ───────────────────────────────────
        matched = rule_evaluate(tool_name, params)
        if matched is not None:
            if matched.action == "allow":
                return CheckResult(True, f"Rule allow: {matched.pattern}", "rule")
            else:
                return CheckResult(False, f"Rule deny: {matched.pattern}", "rule")

        # ── Layer 5: Mode fallback ─────────────────────────────────
        if self.mode == PermissionMode.STRICT:
            return CheckResult(
                allowed=False,
                reason=f"No matching rule in strict mode for {tool_name}",
                layer="mode",
            )

        if self.mode == PermissionMode.PERMISSIVE:
            return CheckResult(
                allowed=True,
                reason="Permissive mode — no rule required",
                layer="mode",
            )

        # DEFAULT mode → HITL (or callback)
        if self._hitl_callback is not None:
            decision = self._hitl_callback(tool_name, params)
            if decision == "allow_once":
                return CheckResult(True, "HITL allow (once)", "hitl")
            if decision == "allow_session":
                # Record the session permit — figure out pattern from params
                pattern = self._infer_pattern(tool_name, params)
                self._hitl_memory.add(tool_name, pattern)
                return CheckResult(True, f"HITL allow (session): {pattern}", "hitl")
            if decision == "allow_forever":
                pattern = self._infer_pattern(tool_name, params)
                from flickcode.permissions.rules import persist

                persist("allow", tool_name, pattern)
                return CheckResult(True, f"HITL allow (permanent): {pattern}", "hitl")
            # "deny"
            return CheckResult(False, "HITL deny", "hitl")

        # No callback registered — return undecided
        return CheckResult(
            allowed=None,
            reason=f"Needs human decision for {tool_name}",
            layer="hitl",
        )

    # ── HITL helpers ───────────────────────────────────────────────

    def add_session_permit(self, tool: str, pattern: str) -> None:
        """Record a session-level permit (used by TUI after HITL)."""
        self._hitl_memory.add(tool, pattern)

    def add_permanent_rule(self, action: str, tool: str, pattern: str) -> None:
        """Write a permanent rule to the local permissions file."""
        from flickcode.permissions.rules import persist

        persist(action, tool, pattern)

    # ── Internal helpers ───────────────────────────────────────────

    @staticmethod
    def _infer_pattern(tool_name: str, params: dict) -> str:
        """Guess a glob pattern from the first string parameter value."""
        for v in params.values():
            if isinstance(v, str) and v.strip():
                # Use the first word as a pattern wildcard
                first_word = v.strip().split()[0] if v.strip() else v.strip()
                return f"{first_word} *"
        return "*"

    @property
    def project_root(self) -> Path:
        """The resolved project root used by the path sandbox."""
        return self._sandbox.project_root
