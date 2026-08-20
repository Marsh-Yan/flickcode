from __future__ import annotations

import unittest

from flickcode.config import ProviderConfig
from flickcode.subagents.provider_pool import ProviderPool


class _Client:
    def __init__(self):
        self.closed = 0
    def close(self):
        self.closed += 1


class _Wrapper:
    def __init__(self, config, client=None):
        self.config = config
        self.client = client or _Client()


class ProviderPoolTests(unittest.TestCase):
    def test_client_is_shared_and_closed_once(self):
        created = []
        def factory(config, client=None):
            wrapper = _Wrapper(config, client)
            created.append(wrapper)
            return wrapper
        config = ProviderConfig("p", "openai", "one", "http://x", "secret")
        pool = ProviderPool(factory)
        first = pool.create(config)
        second = pool.create(ProviderConfig("q", "openai", "two", "http://x", "secret"))
        self.assertIs(first.client, second.client)
        pool.close()
        pool.close()
        self.assertEqual(first.client.closed, 1)


if __name__ == "__main__":
    unittest.main()
