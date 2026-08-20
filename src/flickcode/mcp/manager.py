"""Lifecycle manager for multiple independent MCP servers."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import RLock

from flickcode.mcp.adapter import MCPToolAdapter
from flickcode.mcp.client import MCPServerClient
from flickcode.mcp.models import (
    MCPServerConfig,
    MCPServerReport,
    MCPStartupReport,
    MCPTimeouts,
    ServerState,
)
from flickcode.tools.registry import ToolRegistry

log = logging.getLogger("flickcode.mcp.manager")


class MCPClientManager:
    """Connect, cache, register and close multiple MCP servers."""

    def __init__(
        self,
        configs: dict[str, MCPServerConfig],
        timeouts: MCPTimeouts | None = None,
    ) -> None:
        self.configs = configs
        self.timeouts = timeouts or MCPTimeouts()
        self.clients: dict[str, MCPServerClient] = {}
        self.adapters: dict[str, MCPToolAdapter] = {}
        self._started = False
        self._closed = False
        self._lock = RLock()
        self.last_report = MCPStartupReport()

    def start_all(self, registry: ToolRegistry) -> MCPStartupReport:
        with self._lock:
            if self._started:
                return self.last_report
            self._started = True
        report = MCPStartupReport()
        if not self.configs:
            self.last_report = report
            return report

        with ThreadPoolExecutor(max_workers=max(1, len(self.configs))) as pool:
            futures = {
                pool.submit(self._connect_one, name, config): (name, config)
                for name, config in self.configs.items()
            }
            for future in as_completed(futures):
                name, config = futures[future]
                try:
                    client, adapters = future.result()
                except Exception as exc:
                    log.warning(
                        "MCP server failed name=%s transport=%s error=%s",
                        name,
                        config.transport,
                        exc,
                    )
                    report.servers.append(
                        MCPServerReport(
                            name=name,
                            transport=config.transport,
                            state=ServerState.FAILED,
                            error=str(exc),
                        )
                    )
                    continue

                registered = 0
                errors: list[str] = []
                for adapter in adapters:
                    try:
                        registry.register_instance(adapter)
                    except ValueError as exc:
                        errors.append(str(exc))
                        continue
                    self.adapters[adapter.spec.name] = adapter
                    report.registered_tools.append(adapter.spec.name)
                    registered += 1
                self.clients[name] = client
                report.servers.append(
                    MCPServerReport(
                        name=name,
                        transport=config.transport,
                        state=ServerState.READY,
                        tool_count=registered,
                        error="; ".join(errors) if errors else None,
                    )
                )
        report.servers.sort(key=lambda item: item.name)
        report.registered_tools.sort()
        self.last_report = report
        return report

    def _connect_one(
        self,
        name: str,
        config: MCPServerConfig,
    ) -> tuple[MCPServerClient, list[MCPToolAdapter]]:
        client = MCPServerClient(config, self.timeouts)
        try:
            definitions = client.connect_and_discover()
            adapters = [MCPToolAdapter(definition, client) for definition in definitions]
            return client, adapters
        except Exception:
            client.close()
            raise

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        for name, client in list(self.clients.items()):
            try:
                client.close()
            except Exception as exc:
                log.warning("MCP server close failed name=%s error=%s", name, exc)
