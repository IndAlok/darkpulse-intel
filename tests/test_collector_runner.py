from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from darkpulse.ingestion.checkpoints import InMemoryCheckpointStore
from darkpulse.ingestion.collectors.base import BaseCollector, CollectorHealth, HealthStatus
from darkpulse.ingestion.collectors.http import CollectionError
from darkpulse.ingestion.collectors.runner import CollectorRunner
from darkpulse.ingestion.metrics import IngestionMetrics
from darkpulse.ingestion.pipeline import OutcomeStatus, PipelineOutcome
from darkpulse.ingestion.records import SourceRecord


class RunnerCollector(BaseCollector):
    def __init__(
        self,
        source_id: str,
        record: SourceRecord,
        *,
        failure_code: str | None = None,
    ) -> None:
        super().__init__(
            source_id=source_id,
            source_class=record.source_class,
            checkpoints=InMemoryCheckpointStore(),
        )
        self._record = record
        self._failure_code = failure_code

    async def _collect(self) -> AsyncIterator[SourceRecord]:
        if self._failure_code:
            raise CollectionError(self._failure_code, self.source_id)
        yield self._record

    async def _health(self) -> CollectorHealth:
        return CollectorHealth.create(self.source_id, HealthStatus.HEALTHY)


@pytest.mark.asyncio
async def test_runner_sends_every_record_through_pipeline(source_record) -> None:
    pipeline = AsyncMock()
    pipeline.process.return_value = PipelineOutcome(status=OutcomeStatus.PUBLISHED)
    runner = CollectorRunner(pipeline)

    summary = await runner.run(RunnerCollector("source-a", source_record))

    pipeline.process.assert_awaited_once_with(source_record)
    assert summary.published == 1
    assert summary.failures == 0


@pytest.mark.asyncio
async def test_run_many_isolates_collector_failures(source_record) -> None:
    pipeline = AsyncMock()
    pipeline.process.return_value = PipelineOutcome(status=OutcomeStatus.REJECTED)
    runner = CollectorRunner(pipeline)

    summaries = await runner.run_many(
        [
            RunnerCollector("failing-source", source_record, failure_code="timeout"),
            RunnerCollector("healthy-source", source_record),
        ]
    )

    assert summaries[0].failure_code == "timeout"
    assert summaries[1].rejected == 1


@pytest.mark.asyncio
async def test_runner_masks_unexpected_failure_details(source_record, caplog) -> None:
    pipeline = AsyncMock()
    pipeline.process.side_effect = RuntimeError("sensitive upstream detail")
    runner = CollectorRunner(pipeline)

    summary = await runner.run(RunnerCollector("source-a", source_record))

    assert summary.failure_code == "unexpected_error"
    assert "sensitive upstream detail" not in caplog.text


@pytest.mark.asyncio
async def test_runner_records_content_free_source_metrics(source_record) -> None:
    pipeline = AsyncMock()
    pipeline.process.return_value = PipelineOutcome(status=OutcomeStatus.PUBLISHED)
    metrics = IngestionMetrics()
    runner = CollectorRunner(pipeline, metrics=metrics)

    await runner.run(RunnerCollector("source-a", source_record))

    assert (
        metrics.collector_runs.labels(
            source_id="source-a",
            source_class="dnm_dataset",
            outcome="completed",
        )._value.get()
        == 1
    )
