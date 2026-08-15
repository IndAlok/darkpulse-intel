from __future__ import annotations

import asyncio
from typing import Protocol

from redis.asyncio import Redis


class DedupStore(Protocol):
    async def reserve(self, dedup_key: str) -> bool: ...

    async def commit(self, dedup_key: str) -> None: ...

    async def release(self, dedup_key: str) -> None: ...

    async def close(self) -> None: ...


class InMemoryDedupStore:
    def __init__(self) -> None:
        self._states: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def reserve(self, dedup_key: str) -> bool:
        async with self._lock:
            if dedup_key in self._states:
                return False
            self._states[dedup_key] = "pending"
            return True

    async def commit(self, dedup_key: str) -> None:
        async with self._lock:
            self._states[dedup_key] = "done"

    async def release(self, dedup_key: str) -> None:
        async with self._lock:
            if self._states.get(dedup_key) == "pending":
                self._states.pop(dedup_key, None)

    async def close(self) -> None:
        return None


class RedisDedupStore:
    _RELEASE_PENDING_SCRIPT = """
    if redis.call('GET', KEYS[1]) == ARGV[1] then
      return redis.call('DEL', KEYS[1])
    end
    return 0
    """

    _COMMIT_PENDING_SCRIPT = """
    if redis.call('GET', KEYS[1]) == 'pending' then
      return redis.call('SET', KEYS[1], 'done', 'EX', ARGV[1])
    end
    return nil
    """

    def __init__(
        self,
        redis_url: str,
        *,
        ttl_seconds: int,
        pending_ttl_seconds: int = 300,
        prefix: str = "darkpulse:dedup:",
    ) -> None:
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._ttl_seconds = ttl_seconds
        self._pending_ttl_seconds = pending_ttl_seconds
        self._prefix = prefix

    def _key(self, dedup_key: str) -> str:
        return f"{self._prefix}{dedup_key}"

    async def reserve(self, dedup_key: str) -> bool:
        reserved = await self._redis.set(
            self._key(dedup_key),
            "pending",
            ex=self._pending_ttl_seconds,
            nx=True,
        )
        return bool(reserved)

    async def commit(self, dedup_key: str) -> None:
        await self._redis.eval(
            self._COMMIT_PENDING_SCRIPT,
            1,
            self._key(dedup_key),
            self._ttl_seconds,
        )

    async def release(self, dedup_key: str) -> None:
        await self._redis.eval(
            self._RELEASE_PENDING_SCRIPT,
            1,
            self._key(dedup_key),
            "pending",
        )

    async def ping(self) -> bool:
        return bool(await self._redis.ping())

    async def close(self) -> None:
        await self._redis.aclose()
