"""BoundedClientCache: LRU semantics + closer hook."""
from __future__ import annotations

from opentoken.providers._client_cache import (
    BoundedClientCache,
    close_httpx_backed_client,
)


def test_cache_returns_stored_values():
    cache: BoundedClientCache[int] = BoundedClientCache()
    cache.set("a", 1)
    assert cache.get("a") == 1
    assert cache.get("missing") is None


def test_cache_evicts_lru_when_over_capacity():
    cache: BoundedClientCache[int] = BoundedClientCache(max_size=2)
    cache.set("a", 1)
    cache.set("b", 2)
    # "a" is now the LRU; touching it via get bumps it back to MRU.
    cache.get("a")
    cache.set("c", 3)  # Should evict "b", not "a".

    assert cache.get("a") == 1
    assert cache.get("b") is None
    assert cache.get("c") == 3


def test_cache_invokes_closer_on_eviction():
    closed: list[int] = []

    cache: BoundedClientCache[int] = BoundedClientCache(max_size=1, closer=closed.append)
    cache.set("a", 1)
    cache.set("b", 2)  # Evicts "a".

    assert closed == [1]


def test_cache_clear_closes_all_entries():
    closed: list[int] = []

    cache: BoundedClientCache[int] = BoundedClientCache(closer=closed.append)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.clear()

    assert sorted(closed) == [1, 2]
    assert cache.get("a") is None
    assert cache.get("b") is None


def test_close_httpx_backed_client_prefers_public_close():
    class WrapperWithClose:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    w = WrapperWithClose()
    close_httpx_backed_client(w)
    assert w.closed is True


def test_close_httpx_backed_client_falls_back_to_inner_client():
    class InnerHttpx:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class WrapperNoClose:
        def __init__(self):
            self._client = InnerHttpx()

    w = WrapperNoClose()
    close_httpx_backed_client(w)
    assert w._client.closed is True


def test_close_httpx_backed_client_swallows_errors():
    class Boom:
        def close(self):
            raise RuntimeError("boom")

    # Must not raise — eviction can't be allowed to propagate.
    close_httpx_backed_client(Boom())


def test_cache_eviction_closes_inner_httpx_client():
    """End-to-end: an evicted provider-style wrapper has its inner httpx client
    closed, so rotating through more than max_size credentials doesn't leak
    connection pools."""
    class InnerHttpx:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeClient:
        def __init__(self):
            self._client = InnerHttpx()

    cache: BoundedClientCache[FakeClient] = BoundedClientCache(
        max_size=1, closer=close_httpx_backed_client
    )
    first = FakeClient()
    cache.set("a", first)
    cache.set("b", FakeClient())  # Evicts "a".
    assert first._client.closed is True


def test_cache_get_or_create_only_calls_factory_once():
    calls: list[int] = []

    def factory():
        calls.append(1)
        return "x"

    cache: BoundedClientCache[str] = BoundedClientCache()
    assert cache.get_or_create("k", factory) == "x"
    assert cache.get_or_create("k", factory) == "x"
    assert len(calls) == 1


def test_cache_set_replacing_existing_key_closes_old_value():
    """同 key 用新 value 替换时,旧 value 也要走 closer —— 否则反复 re-login
    同一 provider 会泄漏 FD（每次 set 同 key 但旧 wrapper 不 close）。"""
    closed: list[int] = []
    cache: BoundedClientCache[int] = BoundedClientCache(closer=closed.append)
    cache.set("a", 1)
    cache.set("a", 2)
    assert closed == [1]
    cache.set("a", 3)
    assert closed == [1, 2]
    assert cache.get("a") == 3
