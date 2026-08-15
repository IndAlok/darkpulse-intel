from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from darkpulse.ingestion.checkpoints import CheckpointStore
from darkpulse.ingestion.collectors.base import BaseCollector, CollectorHealth, HealthStatus
from darkpulse.ingestion.collectors.http import BoundedHttpClient, CollectionError
from darkpulse.ingestion.collectors.registry import SourceDefinition
from darkpulse.ingestion.content_state import ContentStateStore
from darkpulse.ingestion.extraction import html_to_text
from darkpulse.ingestion.hashing import sha256_hex
from darkpulse.ingestion.records import SourceRecord
from darkpulse.models import ContentType, CrawlMetadata, SourceClass

V3_ONION_HOST = re.compile(r"^[a-z2-7]{56}\.onion$")
TOR_SOURCE_CLASSES = frozenset({SourceClass.TOR_FORUM, SourceClass.TOR_MARKET})
ALLOWED_MIME_TYPES = frozenset({"application/xhtml+xml", "text/html", "text/plain"})


def isolated_socks_proxy_url(base_proxy_url: str, source_id: str) -> str:
    parsed = urlsplit(base_proxy_url)
    if parsed.scheme.casefold() != "socks5" or not parsed.hostname or not parsed.port:
        raise ValueError("Tor proxy must be a socks5 URL with an explicit port")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("base Tor proxy URL cannot contain credentials, query, or fragment")
    isolation_key = sha256_hex(source_id.encode("utf-8"))[:24]
    hostname = quote(parsed.hostname, safe="[]:.-")
    return f"socks5://{isolation_key}:{isolation_key}@{hostname}:{parsed.port}"


def create_isolated_tor_client(base_proxy_url: str, source_id: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        proxy=isolated_socks_proxy_url(base_proxy_url, source_id),
        follow_redirects=False,
        trust_env=False,
    )


def canonical_onion_url(url: str) -> str:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").casefold()
    if parsed.scheme.casefold() != "http" or not V3_ONION_HOST.fullmatch(hostname):
        raise ValueError("reviewed onion sources must use an HTTP v3 onion address")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("onion source cannot contain credentials or a fragment")
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit(("http", f"{hostname}{port}", parsed.path or "/", parsed.query, ""))


class ApprovedOnionSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1, max_length=200)
    seed_url: str
    max_depth: int = Field(default=1, ge=0, le=3)
    max_pages: int = Field(default=20, ge=1, le=100)
    max_response_bytes: int = Field(default=1_000_000, ge=1, le=2_000_000)

    @field_validator("seed_url")
    @classmethod
    def validate_seed_url(cls, value: str) -> str:
        return canonical_onion_url(value)


class OnionReviewPolicy:
    def __init__(self, *, policy_version: str, approved: list[ApprovedOnionSource]) -> None:
        if not policy_version:
            raise ValueError("onion review policy requires a version")
        by_id = {source.source_id: source for source in approved}
        if len(by_id) != len(approved):
            raise ValueError("onion review policy contains duplicate source IDs")
        self.policy_version = policy_version
        self._approved = by_id

    @classmethod
    def from_path(cls, path: Path) -> OnionReviewPolicy:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            policy_version=str(payload["policy_version"]),
            approved=[ApprovedOnionSource.model_validate(item) for item in payload["approved"]],
        )

    def require_approved(self, source: SourceDefinition) -> ApprovedOnionSource:
        try:
            approved = self._approved[source.source_id]
        except KeyError as error:
            raise ValueError("onion source is not locally reviewed") from error
        if canonical_onion_url(source.locator) != approved.seed_url:
            raise ValueError("configured onion source does not match reviewed seed")
        return approved


class _LinkExtractor(HTMLParser):
    def __init__(self, *, limit: int = 500) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self._limit = limit

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a" or len(self.links) >= self._limit:
            return
        href = next((value for name, value in attrs if name.casefold() == "href"), None)
        if href:
            self.links.append(href)


class OnionCollector(BaseCollector):
    def __init__(
        self,
        *,
        source: SourceDefinition,
        review_policy: OnionReviewPolicy,
        checkpoints: CheckpointStore,
        http: BoundedHttpClient,
        content_state: ContentStateStore | None = None,
    ) -> None:
        if source.source_class not in TOR_SOURCE_CLASSES:
            raise ValueError("onion collector requires a tor_market or tor_forum source")
        self._approved = review_policy.require_approved(source)
        self._source = source
        super().__init__(
            source_id=source.source_id,
            source_class=source.source_class,
            checkpoints=checkpoints,
            enabled=source.enabled,
        )
        self._http = http
        self._content_state = content_state
        self._policy_version = review_policy.policy_version
        self._last_failure_code: str | None = None
        self._has_succeeded = False

    async def _collect(self) -> AsyncIterator[SourceRecord]:
        queue = deque([(self._approved.seed_url, 0)])
        visited: set[str] = set()
        timeout = self._source.request_timeout_seconds
        if timeout <= 0:
            timeout = 60.0
        while queue and len(visited) < self._approved.max_pages:
            url, depth = queue.popleft()
            if url in visited:
                continue
            visited.add(url)
            try:
                result = await self._http.fetch(
                    source_id=self.source_id,
                    url=url,
                    max_response_bytes=self._approved.max_response_bytes,
                    timeout_seconds=max(15.0, min(timeout, 120.0)),
                    allowed_mime_types=ALLOWED_MIME_TYPES,
                )
            except CollectionError as error:
                self._last_failure_code = error.code
                if url == self._approved.seed_url:
                    raise
                continue

            raw_content = (
                html_to_text(result.body)
                if result.mime_type in {"text/html", "application/xhtml+xml"}
                else result.body.decode("utf-8", errors="replace")
            )
            if not raw_content.strip():
                continue
            content_sha256 = sha256_hex(raw_content.encode("utf-8"))
            artifact_id = sha256_hex(url.encode("utf-8"))
            unchanged = self._content_state and await self._content_state.is_unchanged(
                artifact_id, content_sha256
            )
            if not unchanged:
                captured_at = datetime.now(UTC)
                yield SourceRecord(
                    source_class=self.source_class,
                    source_ref=url,
                    content_type=(
                        ContentType.HTML
                        if result.mime_type in {"text/html", "application/xhtml+xml"}
                        else ContentType.TEXT
                    ),
                    mime_type=result.mime_type,
                    raw_content=raw_content,
                    source_bytes=result.body,
                    captured_at=captured_at,
                    crawl_metadata=CrawlMetadata(
                        source_item_id=content_sha256,
                        status_code=result.status_code,
                        latency_ms=result.latency_ms,
                        retries=result.retries,
                    ),
                    source_metadata={
                        "collector": "reviewed_onion_static",
                        "depth": depth,
                        "review_policy_version": self._policy_version,
                        "source_id": self.source_id,
                    },
                )
                if self._content_state:
                    await self._content_state.commit(artifact_id, content_sha256)
                await self.save_checkpoint(content_sha256)
            if depth < self._approved.max_depth and result.mime_type in {
                "application/xhtml+xml",
                "text/html",
            }:
                queue.extend((link, depth + 1) for link in self._same_host_links(url, result.body))

        self._last_failure_code = None
        self._has_succeeded = True

    def _same_host_links(self, base_url: str, source_bytes: bytes) -> tuple[str, ...]:
        extractor = _LinkExtractor()
        extractor.feed(source_bytes.decode("utf-8", errors="replace"))
        approved_host = urlsplit(self._approved.seed_url).hostname
        links: set[str] = set()
        for href in extractor.links:
            candidate = urljoin(base_url, href)
            parsed = urlsplit(candidate)
            if parsed.hostname != approved_host or parsed.scheme != "http":
                continue
            try:
                links.add(canonical_onion_url(candidate))
            except ValueError:
                continue
        return tuple(sorted(links))

    async def _health(self) -> CollectorHealth:
        if self._last_failure_code:
            return CollectorHealth.create(
                self.source_id,
                HealthStatus.UNHEALTHY,
                reason_code=self._last_failure_code,
            )
        if not self._has_succeeded:
            return CollectorHealth.create(
                self.source_id,
                HealthStatus.DEGRADED,
                reason_code="not_collected",
            )
        return CollectorHealth.create(self.source_id, HealthStatus.HEALTHY)
