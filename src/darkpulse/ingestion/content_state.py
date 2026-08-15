from __future__ import annotations

import asyncio
from typing import Protocol

from redis.asyncio import Redis


class ContentStateStore(Protocol):
    async def is_unchanged(self, artifact_id: str, content_sha256: str) -> bool: ...

    async def commit(self, artifact_id: str, content_sha256: str) -> None: ...

    async def close(self) -> None: ...


class InMemoryContentStateStore:
    def __init__(self) -> None:
        self._hashes: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def is_unchanged(self, artifact_id: str, content_sha256: str) -> bool:
        async with self._lock:
            return self._hashes.get(artifact_id) == content_sha256

    async def commit(self, artifact_id: str, content_sha256: str) -> None:
        async with self._lock:
            self._hashes[artifact_id] = content_sha256

    async def close(self) -> None:
        return None


class RedisContentStateStore:
    def __init__(
        self,
        redis_url: str,
        *,
        prefix: str = "darkpulse:content-state:",
        ttl_seconds: int = 7776000,
    ) -> None:
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._prefix = prefix
        self._ttl_seconds = ttl_seconds

    def _key(self, artifact_id: str) -> str:
        return f"{self._prefix}{artifact_id}"

    async def is_unchanged(self, artifact_id: str, content_sha256: str) -> bool:
        value: str | None = await self._redis.get(self._key(artifact_id))
        return value == content_sha256

    async def commit(self, artifact_id: str, content_sha256: str) -> None:
        await self._redis.set(self._key(artifact_id), content_sha256, ex=self._ttl_seconds)

    async def close(self) -> None:
        await self._redis.aclose()
