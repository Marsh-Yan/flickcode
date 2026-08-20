"""Hook action preparation, execution, interception, and bounded background work."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import replace
from typing import Any, Callable, Optional

from flickcode.hooks.models import (
    ActionResult,
    HookAction,
    HookEvent,
    HttpAction,
    InterceptDecision,
    InterceptResult,
    PromptAction,
    ShellAction,
    SubAgentAction,
)
from flickcode.hooks.prompt_state import PromptState
from flickcode.hooks.template import expand

MAX_CAPTURE = 16 * 1024
_SENSITIVE_NAMES = ("authorization", "token", "api_key", "apikey", "secret", "password")


def truncate(text: str) -> str:
    if len(text) <= MAX_CAPTURE:
        return text
    return text[:MAX_CAPTURE] + "\n[truncated]"


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    result = text
    for secret in secrets:
        if secret:
            result = result.replace(secret, "[redacted]")
    return result


def _context_secrets(value: Any, key: str = "") -> tuple[str, ...]:
    found: list[str] = []
    if isinstance(value, dict) or hasattr(value, "items"):
        for child_key, child in value.items():
            found.extend(_context_secrets(child, str(child_key)))
    elif isinstance(value, (list, tuple)):
        for child in value:
            found.extend(_context_secrets(child, key))
    elif any(marker in key.lower() for marker in _SENSITIVE_NAMES):
        found.append(str(value))
    return tuple(item for item in found if item)


def prepare_action(action: HookAction, event: HookEvent) -> HookAction:
    context = event.context
    if isinstance(action, ShellAction):
        return replace(
            action,
            command=expand(action.command, context),
            cwd=expand(action.cwd, context) if action.cwd else None,
            env=expand(action.env, context),
        )
    if isinstance(action, PromptAction):
        return replace(action, content=expand(action.content, context))
    if isinstance(action, HttpAction):
        return replace(
            action,
            url=expand(action.url, context),
            headers=expand(action.headers, context),
            body=expand(action.body, context),
        )
    if isinstance(action, SubAgentAction):
        return replace(action, task=expand(action.task, context))
    raise ValueError(f"unsupported Hook action: {type(action).__name__}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ActionExecutor:
    def __init__(
        self,
        project_root,
        prompt_state: PromptState,
        shell_runner: Optional[Callable[..., Any]] = None,
        http_opener: Any = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.project_root = project_root
        self.prompt_state = prompt_state
        self.shell_runner = shell_runner or subprocess.run
        self.http_opener = http_opener or urllib.request.build_opener(_NoRedirect())
        self.clock = clock

    def execute(self, rule_id: str, action: HookAction, event: HookEvent) -> ActionResult:
        if isinstance(action, ShellAction):
            return self._shell(action, event)
        if isinstance(action, HttpAction):
            return self._http(action, event)
        if isinstance(action, PromptAction):
            return self._prompt(rule_id, action, event)
        if isinstance(action, SubAgentAction):
            return ActionResult(
                False,
                error="SubAgent Hook actions are declared but not executable in this release.",
            )
        return ActionResult(False, error="Unsupported Hook action.")

    def _shell(self, action: ShellAction, event: HookEvent) -> ActionResult:
        started = self.clock()
        env = os.environ.copy()
        env.update(dict(action.env))
        secrets = tuple(
            str(value) for key, value in action.env.items()
            if any(marker in key.lower() for marker in _SENSITIVE_NAMES)
        ) + _context_secrets(event.context)
        try:
            completed = self.shell_runner(
                action.command,
                shell=True,
                cwd=action.cwd or str(self.project_root),
                env=env,
                capture_output=True,
                text=True,
                timeout=action.timeout_seconds,
            )
            elapsed = self.clock() - started
            stdout = redact(truncate(completed.stdout or ""), secrets)
            stderr = redact(truncate(completed.stderr or ""), secrets)
            return ActionResult(
                completed.returncode == 0,
                output=stdout,
                error=stderr if completed.returncode == 0 else (stderr or f"exit code {completed.returncode}"),
                elapsed_seconds=elapsed,
                exit_code=completed.returncode,
            )
        except subprocess.TimeoutExpired:
            return ActionResult(False, error="Shell Hook timed out.", elapsed_seconds=self.clock() - started)
        except Exception as exc:
            return ActionResult(False, error=f"Shell Hook failed: {exc}", elapsed_seconds=self.clock() - started)

    def _http(self, action: HttpAction, event: HookEvent) -> ActionResult:
        started = self.clock()
        headers = dict(action.headers)
        body = action.body
        if isinstance(body, (dict, list, tuple)):
            data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        elif body is None:
            data = None
        else:
            data = str(body).encode("utf-8")
        secrets = tuple(
            str(value) for key, value in headers.items()
            if any(marker in key.lower() for marker in _SENSITIVE_NAMES)
        ) + _context_secrets(event.context)
        request = urllib.request.Request(
            action.url,
            data=data,
            headers=headers,
            method=action.method,
        )
        try:
            with self.http_opener.open(request, timeout=action.timeout_seconds) as response:
                status = int(getattr(response, "status", response.getcode()))
                content = response.read(MAX_CAPTURE + 1).decode("utf-8", errors="replace")
                content = redact(truncate(content), secrets)
                success = 200 <= status < 300
                return ActionResult(
                    success,
                    output=content if success else "",
                    error="" if success else f"HTTP Hook returned {status}.",
                    elapsed_seconds=self.clock() - started,
                    status_code=status,
                )
        except urllib.error.HTTPError as exc:
            return ActionResult(
                False,
                error=f"HTTP Hook returned {exc.code}.",
                elapsed_seconds=self.clock() - started,
                status_code=exc.code,
            )
        except Exception as exc:
            return ActionResult(
                False,
                error=f"HTTP Hook failed: {exc}",
                elapsed_seconds=self.clock() - started,
            )

    def _prompt(
        self,
        rule_id: str,
        action: PromptAction,
        event: HookEvent,
    ) -> ActionResult:
        if event.name.value == "system.started":
            self.prompt_state.add_system(rule_id, action.content)
        elif event.name.value in ("session.started", "session.resumed"):
            self.prompt_state.add_session(rule_id, action.content)
        else:
            self.prompt_state.add_pending(rule_id, action.content)
        return ActionResult(True, elapsed_seconds=0.0)


def parse_intercept(result: ActionResult) -> InterceptResult:
    if not result.success or not result.output.strip():
        return InterceptResult()
    try:
        raw = json.loads(result.output)
    except (TypeError, json.JSONDecodeError):
        return InterceptResult()
    if not isinstance(raw, dict):
        return InterceptResult()
    decision = raw.get("decision")
    if decision == InterceptDecision.ALLOW.value:
        return InterceptResult(InterceptDecision.ALLOW)
    if decision == InterceptDecision.DENY.value:
        reason = raw.get("reason")
        if isinstance(reason, str) and reason.strip():
            return InterceptResult(InterceptDecision.DENY, reason.strip())
    return InterceptResult()


class BoundedExecutor:
    def __init__(self, workers: int = 4, pending: int = 32) -> None:
        self._pool = ThreadPoolExecutor(max_workers=workers)
        self._slots = threading.BoundedSemaphore(workers + pending)
        self._lock = threading.Lock()
        self._futures: set[Future] = set()
        self._closed = False

    def submit(self, function: Callable[[], Any], callback: Callable[[Future], None]) -> bool:
        with self._lock:
            if self._closed or not self._slots.acquire(blocking=False):
                return False
            try:
                future = self._pool.submit(function)
            except Exception:
                self._slots.release()
                return False
            self._futures.add(future)

        def done(item: Future) -> None:
            try:
                callback(item)
            finally:
                with self._lock:
                    self._futures.discard(item)
                self._slots.release()

        future.add_done_callback(done)
        return True

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._futures)

    def close(self, grace_seconds: float = 2.0) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            futures = tuple(self._futures)
        if futures:
            wait(futures, timeout=grace_seconds)
        for future in futures:
            if not future.running():
                future.cancel()
        self._pool.shutdown(wait=False)
