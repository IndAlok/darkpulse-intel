from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram


class IngestionMetrics:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry(auto_describe=True)
        self.seen = Counter(
            "darkpulse_ingestion_records_seen_total",
            "Source records presented to the D1 pipeline.",
            ["source_class"],
            registry=self.registry,
        )
        self.published = Counter(
            "darkpulse_ingestion_records_published_total",
            "Contract 1 records persisted to the MongoDB queue.",
            ["source_class"],
            registry=self.registry,
        )
        self.duplicates = Counter(
            "darkpulse_ingestion_duplicates_total",
            "Records rejected by exact deduplication.",
            ["source_class"],
            registry=self.registry,
        )
        self.rejected = Counter(
            "darkpulse_ingestion_records_rejected_total",
            "Records rejected before broker persistence.",
            ["source_class", "reason"],
            registry=self.registry,
        )
        self.failures = Counter(
            "darkpulse_ingestion_failures_total",
            "Pipeline failures that prevented a publish acknowledgement.",
            ["stage"],
            registry=self.registry,
        )
        self.duration = Histogram(
            "darkpulse_ingestion_pipeline_seconds",
            "Time spent processing one source record.",
            ["source_class", "outcome"],
            buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, float("inf")),
            registry=self.registry,
        )
        self.collector_runs = Counter(
            "darkpulse_ingestion_collector_runs_total",
            "Completed collector runs by configured source and outcome.",
            ["source_id", "source_class", "outcome"],
            registry=self.registry,
        )
        self.collector_records = Counter(
            "darkpulse_ingestion_collector_records_total",
            "Records observed from each configured collector.",
            ["source_id", "source_class", "outcome"],
            registry=self.registry,
        )
