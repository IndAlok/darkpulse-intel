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
    version: int = 0

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
        self._redis = Redis.from_url(
            redis_url, decode_responses=True, socket_connect_timeout=5, socket_timeout=10
        )
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
                version=int(payload.get("version", 0)),
            )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            # ponytail: corrupt payload keeps the previous good value by
            # treating it as absent; an explicit last-good cache is the
            # upgrade if collectors ever need to survive their own bad write
            logger.warning("checkpoint.corrupt source_id=%s", source_id)
            return None

    async def save(self, source_id: str, checkpoint: CollectorCheckpoint) -> None:
        # ponytail: CAS on version keeps the highest value; a lost update
        # raises so the caller retries rather than silently rewinding
        current = await self.load(source_id)
        expected_version = current.version if current else 0
        if checkpoint.version < expected_version:
            raise ValueError(
                f"checkpoint for {source_id} is stale: "
                f"{checkpoint.version} < {expected_version}"
            )
        bumped = CollectorCheckpoint(
            cursor=checkpoint.cursor,
            updated_at=checkpoint.updated_at,
            version=expected_version + 1,
        )
        payload = asdict(bumped)
        payload["updated_at"] = bumped.updated_at.isoformat()
        await self._redis.set(
            self._key(source_id),
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
        )

    async def close(self) -> None:
        await self._redis.aclose()
