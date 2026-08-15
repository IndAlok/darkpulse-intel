from unittest.mock import AsyncMock

import pytest

from darkpulse.ingestion.content_state import InMemoryContentStateStore, RedisContentStateStore


@pytest.mark.asyncio
async def test_in_memory_content_state_changes_only_after_commit() -> None:
    store = InMemoryContentStateStore()

    assert not await store.is_unchanged("artifact-a", "hash-a")
    await store.commit("artifact-a", "hash-a")
    assert await store.is_unchanged("artifact-a", "hash-a")
    assert not await store.is_unchanged("artifact-a", "hash-b")


@pytest.mark.asyncio
async def test_redis_content_state_uses_content_free_key() -> None:
    store = RedisContentStateStore("redis://localhost:6379/0")
    store._redis = AsyncMock()  # type: ignore[assignment]
    store._redis.get.return_value = "hash-a"

    assert await store.is_unchanged("artifact-a", "hash-a")
    await store.commit("artifact-a", "hash-b")
    store._redis.set.assert_awaited_with("darkpulse:content-state:artifact-a", "hash-b", ex=7776000)
    await store.close()
