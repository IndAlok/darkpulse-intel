from collections.abc import AsyncIterator

import pytest

from darkpulse.ingestion.checkpoints import InMemoryCheckpointStore
from darkpulse.ingestion.collectors.base import (
    BaseCollector,
    CollectorHealth,
    HealthStatus,
)
from darkpulse.ingestion.records import SourceRecord
from darkpulse.models import SourceClass


class StubCollector(BaseCollector):
    def __init__(self, record: SourceRecord, *, enabled: bool = True) -> None:
        super().__init__(
            source_id="stub-source",
            source_class=SourceClass.DNM_DATASET,
            checkpoints=InMemoryCheckpointStore(),
            enabled=enabled,
        )
        self._record = record

    async def _collect(self) -> AsyncIterator[SourceRecord]:
        yield self._record

    async def _health(self) -> CollectorHealth:
        return CollectorHealth.create(self.source_id, HealthStatus.HEALTHY)


@pytest.mark.asyncio
async def test_base_collector_emits_records_and_persists_checkpoint(source_record) -> None:
    collector = StubCollector(source_record)

    records = [record async for record in collector.collect()]
    await collector.save_checkpoint("row-12")

    assert records == [source_record]
    assert (await collector.checkpoint()).cursor == "row-12"
    assert (await collector.health()).status is HealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_disabled_collector_emits_nothing_and_reports_disabled(source_record) -> None:
    collector = StubCollector(source_record, enabled=False)

    assert [record async for record in collector.collect()] == []
    assert (await collector.health()).status is HealthStatus.DISABLED


@pytest.mark.asyncio
async def test_base_collector_rejects_wrong_source_class(source_record) -> None:
    collector = StubCollector(source_record)
    collector.source_class = SourceClass.TELEGRAM

    with pytest.raises(ValueError, match="wrong source class"):
        _ = [record async for record in collector.collect()]
