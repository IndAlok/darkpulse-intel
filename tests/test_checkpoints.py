from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from darkpulse.ingestion.checkpoints import (
    CollectorCheckpoint,
    InMemoryCheckpointStore,
    RedisCheckpointStore,
)


def test_checkpoint_requires_cursor_and_timezone() -> None:
    with pytest.raises(ValueError, match="cursor"):
        CollectorCheckpoint(cursor="", updated_at=datetime.now(UTC))
    with pytest.raises(ValueError, match="timezone"):
        CollectorCheckpoint(cursor="row-10", updated_at=datetime.now())


@pytest.mark.asyncio
async def test_in_memory_checkpoint_round_trip() -> None:
    store = InMemoryCheckpointStore()
    checkpoint = CollectorCheckpoint.now("row-10")

    assert await store.load("source-a") is None
    await store.save("source-a", checkpoint)

    assert await store.load("source-a") == checkpoint


@pytest.mark.asyncio
async def test_redis_checkpoint_is_content_free_json() -> None:
    store = RedisCheckpointStore("redis://localhost:6379/0")
    store._redis = AsyncMock()  # type: ignore[assignment]
    checkpoint = CollectorCheckpoint.now("row-10")

    await store.save("source-a", checkpoint)

    saved_payload = store._redis.set.await_args.args[1]
    assert "row-10" in saved_payload
    assert "raw_content" not in saved_payload

    store._redis.get.return_value = saved_payload
    assert await store.load("source-a") == checkpoint
    await store.close()
    store._redis.aclose.assert_awaited_once()
