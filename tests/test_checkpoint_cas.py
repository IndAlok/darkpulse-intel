from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from darkpulse.ingestion.checkpoints import CollectorCheckpoint, RedisCheckpointStore


def _store() -> tuple[RedisCheckpointStore, MagicMock]:
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.aclose = AsyncMock()
    store = RedisCheckpointStore.__new__(RedisCheckpointStore)
    store._redis = redis
    store._prefix = "darkpulse:checkpoint:"
    return store, redis


@pytest.mark.asyncio
async def test_save_bumps_version() -> None:
    store, redis = _store()
    await store.save("src", CollectorCheckpoint.now("cursor-1"))
    written = redis.set.call_args.args[1]
    assert '"version":1' in written
    assert '"cursor":"cursor-1"' in written


@pytest.mark.asyncio
async def test_save_rejects_stale_version() -> None:
    store, redis = _store()
    redis.get = AsyncMock(
        return_value='{"cursor":"newer","updated_at":"2026-01-01T00:00:00+00:00","version":5}'
    )
    stale = CollectorCheckpoint(
        cursor="older", updated_at=datetime.now(UTC), version=2
    )
    with pytest.raises(ValueError, match="stale"):
        await store.save("src", stale)
    redis.set.assert_not_called()


@pytest.mark.asyncio
async def test_corrupt_payload_does_not_wipe_good_value() -> None:
    store, redis = _store()
    redis.get = AsyncMock(return_value="{not json")
    assert await store.load("src") is None
    redis.set.assert_not_called()
