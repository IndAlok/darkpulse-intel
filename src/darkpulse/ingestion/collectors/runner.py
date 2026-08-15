from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from darkpulse.ingestion.collectors.base import BaseCollector
from darkpulse.ingestion.collectors.http import CollectionError
from darkpulse.ingestion.metrics import IngestionMetrics
from darkpulse.ingestion.pipeline import IngestionPipeline, OutcomeStatus
from darkpulse.ingestion.records import SourceRecord

logger = logging.getLogger(__name__)


class RecordProcessor(Protocol):
    async def process(self, record: SourceRecord) -> Any: ...


@dataclass(frozen=True, slots=True)
class CollectorRunSummary:
    source_id: str
    published: int = 0
    duplicates: int = 0
    rejected: int = 0
    failures: int = 0
    failure_code: str | None = None


class CollectorRunner:
    def __init__(
        self,
        pipeline: IngestionPipeline,
        *,
        metrics: IngestionMetrics | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._metrics = metrics

    async def run(self, collector: BaseCollector) -> CollectorRunSummary:
        counts = {
            OutcomeStatus.PUBLISHED: 0,
            OutcomeStatus.DUPLICATE: 0,
            OutcomeStatus.REJECTED: 0,
        }
        try:
            async for record in collector.collect():
                outcome = await self._pipeline.process(record)
                counts[outcome.status] += 1
        except CollectionError as error:
            logger.error(
                "collector_failed",
                extra={
                    "event": "collector_failed",
                    "source_id": collector.source_id,
                    "failure_code": error.code,
                },
            )
            summary = CollectorRunSummary(
                source_id=collector.source_id,
                published=counts[OutcomeStatus.PUBLISHED],
                duplicates=counts[OutcomeStatus.DUPLICATE],
                rejected=counts[OutcomeStatus.REJECTED],
                failures=1,
                failure_code=error.code,
            )
            self._record_metrics(collector, summary)
            return summary
        except Exception:
            logger.error(
                "collector_failed",
                extra={
                    "event": "collector_failed",
                    "source_id": collector.source_id,
                    "failure_code": "unexpected_error",
                },
            )
            summary = CollectorRunSummary(
                source_id=collector.source_id,
                published=counts[OutcomeStatus.PUBLISHED],
                duplicates=counts[OutcomeStatus.DUPLICATE],
                rejected=counts[OutcomeStatus.REJECTED],
                failures=1,
                failure_code="unexpected_error",
            )
            self._record_metrics(collector, summary)
            return summary

        summary = CollectorRunSummary(
            source_id=collector.source_id,
            published=counts[OutcomeStatus.PUBLISHED],
            duplicates=counts[OutcomeStatus.DUPLICATE],
            rejected=counts[OutcomeStatus.REJECTED],
        )
        self._record_metrics(collector, summary)
        return summary

    def _record_metrics(self, collector: BaseCollector, summary: CollectorRunSummary) -> None:
        if self._metrics is None:
            return
        labels = {
            "source_id": collector.source_id,
            "source_class": collector.source_class.value,
        }
        outcome = "failed" if summary.failures else "completed"
        self._metrics.collector_runs.labels(**labels, outcome=outcome).inc()
        for record_outcome, count in (
            ("published", summary.published),
            ("duplicate", summary.duplicates),
            ("rejected", summary.rejected),
        ):
            if count:
                self._metrics.collector_records.labels(
                    **labels,
                    outcome=record_outcome,
                ).inc(count)

    async def run_many(self, collectors: list[BaseCollector]) -> tuple[CollectorRunSummary, ...]:
        summaries = await asyncio.gather(*(self.run(collector) for collector in collectors))
        return tuple(summaries)
