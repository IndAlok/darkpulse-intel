from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter
from uuid import uuid4

from darkpulse.ingestion.dedup import DedupStore
from darkpulse.ingestion.hashing import (
    derive_dedup_key,
    sanitize_source_ref,
    sha256_hex,
    source_ref_fingerprint,
)
from darkpulse.ingestion.metrics import IngestionMetrics
from darkpulse.ingestion.publisher import RecordPublisher
from darkpulse.ingestion.records import SourceRecord
from darkpulse.ingestion.safety import SafetyPolicy
from darkpulse.ingestion.validation import ContractValidator
from darkpulse.models import (
    EvidenceMetadata,
    RawIngest,
    SafetyMetadata,
)

logger = logging.getLogger(__name__)


class OutcomeStatus(StrEnum):
    PUBLISHED = "published"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class PipelineOutcome:
    status: OutcomeStatus
    dedup_key: str | None = None
    reasons: tuple[str, ...] = ()


class IngestionPipeline:
    def __init__(
        self,
        *,
        safety_policy: SafetyPolicy,
        dedup_store: DedupStore,
        publisher: RecordPublisher,
        validator: ContractValidator,
        metrics: IngestionMetrics,
        collector_id: str,
        collector_version: str,
    ) -> None:
        self._safety_policy = safety_policy
        self._dedup_store = dedup_store
        self._publisher = publisher
        self._validator = validator
        self._metrics = metrics
        self._collector_id = collector_id
        self._collector_version = collector_version

    async def process(self, record: SourceRecord) -> PipelineOutcome:
        started = perf_counter()
        source_class = record.source_class.value
        self._metrics.seen.labels(source_class=source_class).inc()

        safe_source_ref = sanitize_source_ref(record.source_ref)
        record = record.with_source_ref(safe_source_ref)
        source_sha256 = sha256_hex(record.source_bytes)
        content_bytes = record.raw_content.encode("utf-8")
        content_sha256 = sha256_hex(content_bytes)

        decision = self._safety_policy.evaluate(
            record,
            source_sha256=source_sha256,
            content_bytes=content_bytes,
            content_sha256=content_sha256,
        )
        if not decision.accepted:
            reasons = tuple(reason.value for reason in decision.reasons)
            for reason in reasons:
                self._metrics.rejected.labels(
                    source_class=source_class,
                    reason=reason,
                ).inc()
            self._metrics.duration.labels(
                source_class=source_class,
                outcome=OutcomeStatus.REJECTED.value,
            ).observe(perf_counter() - started)
            logger.warning(
                "record_rejected",
                extra={
                    "event": "record_rejected",
                    "source_class": source_class,
                    "source_ref_sha256": source_ref_fingerprint(safe_source_ref),
                    "reasons": reasons,
                },
            )
            return PipelineOutcome(status=OutcomeStatus.REJECTED, reasons=reasons)

        dedup_key = derive_dedup_key(
            source_class=source_class,
            source_ref=safe_source_ref,
            content_sha256=content_sha256,
        )
        if not await self._dedup_store.reserve(dedup_key):
            self._metrics.duplicates.labels(source_class=source_class).inc()
            self._metrics.duration.labels(
                source_class=source_class,
                outcome=OutcomeStatus.DUPLICATE.value,
            ).observe(perf_counter() - started)
            logger.debug(
                "record_duplicate",
                extra={
                    "event": "record_duplicate",
                    "source_class": source_class,
                    "source_ref_sha256": source_ref_fingerprint(safe_source_ref),
                    "dedup_key": dedup_key,
                },
            )
            return PipelineOutcome(
                status=OutcomeStatus.DUPLICATE,
                dedup_key=dedup_key,
            )

        try:
            contract_record = RawIngest(
                ingest_id=uuid4(),
                trace_id=record.trace_id or uuid4(),
                dedup_key=dedup_key,
                source_class=record.source_class,
                source_ref=safe_source_ref,
                content_type=record.content_type,
                raw_content=record.raw_content,
                captured_at=record.captured_at,
                source_observed_at=record.source_observed_at,
                lang_hint=record.lang_hint,
                geo_hints=list(record.geo_hints),
                crawl_metadata=record.crawl_metadata,
                source_metadata=record.source_metadata,
                evidence=EvidenceMetadata(
                    source_sha256=source_sha256,
                    content_sha256=content_sha256,
                    source_size_bytes=len(record.source_bytes),
                    content_size_bytes=len(content_bytes),
                    captured_at=record.captured_at,
                    collector_id=self._collector_id,
                    collector_version=self._collector_version,
                ),
                safety=SafetyMetadata(
                    policy_version=decision.policy_version,
                    checks=list(decision.checks),
                ),
            )
            self._validator.validate(contract_record)
            await self._publisher.publish(contract_record)
        except Exception:
            await self._dedup_store.release(dedup_key)
            self._metrics.failures.labels(stage="validate_or_publish").inc()
            logger.exception(
                "record_publish_failed",
                extra={
                    "event": "record_publish_failed",
                    "source_class": source_class,
                    "source_ref_sha256": source_ref_fingerprint(safe_source_ref),
                    "dedup_key": dedup_key,
                },
            )
            raise

        try:
            await self._dedup_store.commit(dedup_key)
        except Exception:
            import asyncio

            committed = False
            for attempt in range(3):
                try:
                    await asyncio.sleep(0.5 * (2**attempt))
                    await self._dedup_store.commit(dedup_key)
                    committed = True
                    break
                except Exception:
                    logger.warning(
                        "dedup_commit_retry_failed",
                        extra={
                            "event": "dedup_commit_retry_failed",
                            "dedup_key": dedup_key,
                            "attempt": attempt + 1,
                        },
                    )
            if not committed:
                self._metrics.failures.labels(stage="dedup_commit").inc()
                logger.exception(
                    "dedup_commit_failed_after_publish",
                    extra={
                        "event": "dedup_commit_failed_after_publish",
                        "source_class": source_class,
                        "dedup_key": dedup_key,
                    },
                )

        self._metrics.published.labels(source_class=source_class).inc()
        self._metrics.duration.labels(
            source_class=source_class,
            outcome=OutcomeStatus.PUBLISHED.value,
        ).observe(perf_counter() - started)
        logger.debug(
            "record_published",
            extra={
                "event": "record_published",
                "source_class": source_class,
                "source_ref_sha256": source_ref_fingerprint(safe_source_ref),
                "dedup_key": dedup_key,
                "trace_id": str(contract_record.trace_id),
            },
        )
        return PipelineOutcome(
            status=OutcomeStatus.PUBLISHED,
            dedup_key=dedup_key,
        )
