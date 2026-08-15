from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from darkpulse.ingestion.checkpoints import CheckpointStore, CollectorCheckpoint
from darkpulse.ingestion.records import SourceRecord
from darkpulse.models import SourceClass


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class CollectorHealth:
    source_id: str
    status: HealthStatus
    checked_at: datetime
    reason_code: str | None = None

    @classmethod
    def create(
        cls,
        source_id: str,
        status: HealthStatus,
        *,
        reason_code: str | None = None,
    ) -> CollectorHealth:
        return cls(
            source_id=source_id,
            status=status,
            checked_at=datetime.now(UTC),
            reason_code=reason_code,
        )


class BaseCollector(ABC):
    def __init__(
        self,
        *,
        source_id: str,
        source_class: SourceClass,
        checkpoints: CheckpointStore,
        enabled: bool = True,
    ) -> None:
        if not source_id or len(source_id) > 200:
            raise ValueError("source_id must contain 1 to 200 characters")
        self.source_id = source_id
        self.source_class = source_class
        self.enabled = enabled
        self._checkpoints = checkpoints

    async def collect(self) -> AsyncIterator[SourceRecord]:
        if not self.enabled:
            return
        async for record in self._collect():
            if record.source_class is not self.source_class:
                raise ValueError("collector emitted a record with the wrong source class")
            yield record

    @abstractmethod
    async def _collect(self) -> AsyncIterator[SourceRecord]:
        if False:
            yield  # pragma: no cover

    async def health(self) -> CollectorHealth:
        if not self.enabled:
            return CollectorHealth.create(self.source_id, HealthStatus.DISABLED)
        return await self._health()

    @abstractmethod
    async def _health(self) -> CollectorHealth: ...

    async def checkpoint(self) -> CollectorCheckpoint | None:
        return await self._checkpoints.load(self.source_id)

    async def save_checkpoint(self, cursor: str) -> None:
        await self._checkpoints.save(self.source_id, CollectorCheckpoint.now(cursor))
