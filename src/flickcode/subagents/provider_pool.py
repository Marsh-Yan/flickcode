"""Shared protocol clients with task-local Provider wrappers."""

from __future__ import annotations

import hashlib
import threading
from typing import Any, Callable

from flickcode.config import ProviderConfig
from flickcode.providers import create_provider


class ProviderPool:
    def __init__(self, provider_factory: Callable[..., Any] = create_provider) -> None:
        self._factory = provider_factory
        self._clients: dict[tuple[str, str, str], Any] = {}
        self._lock = threading.Lock()
        self._closed = False

    @staticmethod
    def _key(config: ProviderConfig) -> tuple[str, str, str]:
        identity = hashlib.sha256(config.api_key.encode("utf-8")).hexdigest()
        return config.protocol, config.base_url, identity

    def create(self, config: ProviderConfig):
        key = self._key(config)
        with self._lock:
            if self._closed:
                raise RuntimeError("provider pool is closed")
            client = self._clients.get(key)
            if client is None:
                wrapper = self._factory(config)
                client = getattr(wrapper, "client", None)
                self._clients[key] = client
                return wrapper
        try:
            return self._factory(config, client=client)
        except TypeError:
            wrapper = self._factory(config)
            if client is not None and hasattr(wrapper, "client"):
                wrapper.client = client
            return wrapper

    def seed(self, config: ProviderConfig, provider: Any) -> None:
        """Reuse an already-created parent provider client for child wrappers."""
        client = getattr(provider, "client", None)
        if client is None:
            return
        with self._lock:
            if self._closed:
                raise RuntimeError("provider pool is closed")
            self._clients.setdefault(self._key(config), client)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            clients = list({id(v): v for v in self._clients.values() if v is not None}.values())
            self._clients.clear()
        for client in clients:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
