from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID

from darkpulse.models import (
    ContentType,
    CrawlMetadata,
    JsonScalar,
    SourceClass,
)


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_class: SourceClass
    source_ref: str
    content_type: ContentType
    mime_type: str
    raw_content: str
    source_bytes: bytes
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    source_observed_at: datetime | None = None
    lang_hint: str | None = None
    geo_hints: tuple[str, ...] = ()
    crawl_metadata: CrawlMetadata = field(default_factory=CrawlMetadata)
    source_metadata: dict[str, JsonScalar] = field(default_factory=dict)
    trace_id: UUID | None = None

    def with_source_ref(self, source_ref: str) -> SourceRecord:
        return replace(self, source_ref=source_ref)
