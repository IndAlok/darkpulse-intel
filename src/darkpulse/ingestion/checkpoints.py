from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CollectorCheckpoint:
    cursor: str
    updated_at: datetime

    def __post_init__(self) -> None:
        if not self.cursor or len(self.cursor) > 2048:
            raise ValueError("checkpoint cursor must contain 1 to 2048 characters")
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("checkpoint timestamp must include a timezone")

    @classmethod
    def now(cls, cursor: str) -> CollectorCheckpoint:
        return cls(cursor=cursor, updated_at=datetime.now(UTC))


class CheckpointStore(Protocol):
    async def load(self, source_id: str) -> CollectorCheckpoint | None: ...

    async def save(self, source_id: str, checkpoint: CollectorCheckpoint) -> None: ...

    async def close(self) -> None: ...


class InMemoryCheckpointStore:
    def __init__(self) -> None:
        self._checkpoints: dict[str, CollectorCheckpoint] = {}
        self._lock = asyncio.Lock()

    async def load(self, source_id: str) -> CollectorCheckpoint | None:
        async with self._lock:
            return self._checkpoints.get(source_id)

    async def save(self, source_id: str, checkpoint: CollectorCheckpoint) -> None:
        async with self._lock:
            self._checkpoints[source_id] = checkpoint

    async def close(self) -> None:
        return None


class RedisCheckpointStore:
    def __init__(
        self,
        redis_url: str,
        *,
        prefix: str = "darkpulse:checkpoint:",
    ) -> None:
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._prefix = prefix

    def _key(self, source_id: str) -> str:
        return f"{self._prefix}{source_id}"

    async def load(self, source_id: str) -> CollectorCheckpoint | None:
        raw = await self._redis.get(self._key(source_id))
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            return CollectorCheckpoint(
                cursor=str(payload["cursor"]),
                updated_at=datetime.fromisoformat(str(payload["updated_at"])),
            )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            logger.warning("checkpoint.corrupt source_id=%s", source_id)
            return None

    async def save(self, source_id: str, checkpoint: CollectorCheckpoint) -> None:
        payload = asdict(checkpoint)
        payload["updated_at"] = checkpoint.updated_at.isoformat()
        await self._redis.set(
            self._key(source_id),
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
        )

    async def close(self) -> None:
        await self._redis.aclose()
