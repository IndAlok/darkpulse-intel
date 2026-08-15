from __future__ import annotations

import ipaddress
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlsplit

from darkpulse.ingestion.checkpoints import CheckpointStore
from darkpulse.ingestion.collectors.base import BaseCollector, CollectorHealth, HealthStatus
from darkpulse.ingestion.collectors.http import BoundedHttpClient, CollectionError
from darkpulse.ingestion.collectors.registry import SourceDefinition
from darkpulse.ingestion.content_state import ContentStateStore
from darkpulse.ingestion.extraction import html_to_text
from darkpulse.ingestion.hashing import sha256_hex
from darkpulse.ingestion.records import SourceRecord
from darkpulse.models import ContentType, CrawlMetadata, SourceClass

ALLOWED_SOURCE_CLASSES = frozenset(
    {SourceClass.PASTE, SourceClass.SURFACE_MARKET, SourceClass.SOCIAL}
)
MAX_FEED_ITEMS = 25
FEED_MIME_TYPES = frozenset(
    {
        "application/rss+xml",
        "application/atom+xml",
        "application/xml",
        "text/xml",
    }
)
ALLOWED_MIME_TYPES = frozenset(
    {
        "application/json",
        "application/xhtml+xml",
        "application/rss+xml",
        "application/atom+xml",
        "application/xml",
        "text/html",
        "text/plain",
        "text/xml",
    }
)
SENSITIVE_QUERY_KEYS = frozenset(
    {"access_token", "api_key", "apikey", "auth", "key", "password", "secret", "token"}
)


def validate_public_surface_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        raise ValueError("surface sources must use HTTPS")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("surface source locators cannot contain credentials or fragments")
    if parsed.hostname.casefold() == "localhost" or parsed.hostname.casefold().endswith(".onion"):
        raise ValueError("surface source hostname is not public")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address and not address.is_global:
        raise ValueError("surface source IP address is not public")
    query_keys = {key.casefold() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    if query_keys & SENSITIVE_QUERY_KEYS:
        raise ValueError("surface source locator contains a sensitive query parameter")


def _hostname_is_public(resolved: list[str]) -> bool:
    for addr in resolved:
        try:
            address = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if not address.is_global:
            return False
    return bool(resolved)


async def _assert_resolved_hostname_public(hostname: str) -> None:
    import asyncio

    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(hostname, None)
    except OSError:
        return
    resolved = sorted({str(info[4][0]) for info in infos})
    if resolved and not _hostname_is_public(resolved):
        raise ValueError("surface source hostname resolves to a non-public address")


class SurfaceCollector(BaseCollector):
    def __init__(
        self,
        *,
        source: SourceDefinition,
        checkpoints: CheckpointStore,
        http: BoundedHttpClient,
        content_state: ContentStateStore | None = None,
    ) -> None:
        if source.source_class not in ALLOWED_SOURCE_CLASSES:
            raise ValueError("surface collector requires a public HTTPS surface source")
        validate_public_surface_url(source.locator)
        super().__init__(
            source_id=source.source_id,
            source_class=source.source_class,
            checkpoints=checkpoints,
            enabled=source.enabled,
        )
        self._source = source
        self._http = http
        self._content_state = content_state
        self._last_failure_code: str | None = None
        self._has_succeeded = False

    async def _collect(self) -> AsyncIterator[SourceRecord]:
        try:
            await _assert_resolved_hostname_public(urlsplit(self._source.locator).hostname or "")
            result = await self._http.fetch(
                source_id=self.source_id,
                url=self._source.locator,
                max_response_bytes=self._source.max_response_bytes,
                timeout_seconds=self._source.request_timeout_seconds,
                allowed_mime_types=ALLOWED_MIME_TYPES,
            )
            raw_content, content_type = self._extract_content(result.body, result.mime_type)
        except CollectionError as error:
            self._last_failure_code = error.code
            raise
        except ValueError as error:
            self._last_failure_code = "invalid_locator"
            raise CollectionError("invalid_locator", self.source_id) from error

        captured_at = datetime.now(UTC)
        content_sha256 = sha256_hex(raw_content.encode("utf-8"))
        artifact_id = sha256_hex(self._source.locator.encode("utf-8"))
        self._last_failure_code = None
        self._has_succeeded = True
        if self._content_state and await self._content_state.is_unchanged(
            artifact_id, content_sha256
        ):
            return
        items = (
            _feed_items(result.body)
            if result.mime_type in FEED_MIME_TYPES
            else []
        )
        if items:
            for item in items:
                item_bytes = item["text"].encode("utf-8")
                item_hash = sha256_hex(item_bytes)
                source_ref = self._source.locator
                if item.get("link"):
                    try:
                        validate_public_surface_url(item["link"])
                        source_ref = item["link"]
                    except ValueError:
                        source_ref = self._source.locator
                yield SourceRecord(
                    source_class=self.source_class,
                    source_ref=source_ref,
                    content_type=ContentType.TEXT,
                    mime_type=result.mime_type,
                    raw_content=item["text"],
                    source_bytes=item_bytes,
                    captured_at=captured_at,
                    crawl_metadata=CrawlMetadata(
                        source_item_id=item_hash,
                        status_code=result.status_code,
                        latency_ms=result.latency_ms,
                        retries=result.retries,
                    ),
                    source_metadata={
                        "collector": "static_http",
                        "source_id": self.source_id,
                        "feed_locator": self._source.locator,
                        "feed_title": item.get("title") or "",
                    },
                )
        else:
            yield SourceRecord(
                source_class=self.source_class,
                source_ref=self._source.locator,
                content_type=content_type,
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
                    "collector": "static_http",
                    "source_id": self.source_id,
                },
            )
        if self._content_state:
            await self._content_state.commit(artifact_id, content_sha256)
        await self.save_checkpoint(content_sha256)

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

    def _extract_content(self, source_bytes: bytes, mime_type: str) -> tuple[str, ContentType]:
        if mime_type in {"text/html", "application/xhtml+xml"}:
            raw_content = html_to_text(source_bytes)
            content_type = ContentType.HTML
        elif mime_type in FEED_MIME_TYPES:
            raw_content = _feed_to_text(source_bytes)
            content_type = ContentType.TEXT
        elif mime_type == "application/json":
            try:
                payload = json.loads(source_bytes)
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise CollectionError("invalid_json", self.source_id) from None
            raw_content = _json_to_text(payload)
            content_type = ContentType.TEXT
        else:
            raw_content = source_bytes.decode("utf-8", errors="replace")
            content_type = ContentType.TEXT
        if not raw_content.strip():
            raise CollectionError("empty_content", self.source_id)
        return raw_content, content_type


def _json_to_text(payload: object) -> str:
    parts: list[str] = []

    def walk(value: object) -> None:
        if len(parts) >= 40:
            return
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
            return
        if isinstance(value, dict):
            for key in ("title", "description", "summary", "text", "content", "headline"):
                item = value.get(key)
                if isinstance(item, str) and item.strip():
                    parts.append(item.strip())
            for item in value.values():
                walk(item)
            return
        if isinstance(value, list):
            for item in value[:20]:
                walk(item)

    walk(payload)
    if parts:
        return "\n".join(parts[:40])
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _node_text(node: object) -> str:
    text = getattr(node, "text", None)
    parts: list[str] = []
    if isinstance(text, str) and text.strip():
        parts.append(text.strip())
    children = getattr(node, "__iter__", None)
    if children is None:
        return " ".join(parts)
    for child in node:  # type: ignore[attr-defined]
        child_text = _node_text(child)
        if child_text:
            parts.append(child_text)
        tail = getattr(child, "tail", None)
        if isinstance(tail, str) and tail.strip():
            parts.append(tail.strip())
    return " ".join(parts)


def _feed_items(source_bytes: bytes) -> list[dict[str, str]]:
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(source_bytes)
    except ET.ParseError:
        return []
    items: list[dict[str, str]] = []
    for node in root.iter():
        if _local_tag(node.tag) not in {"item", "entry"}:
            continue
        title = ""
        description = ""
        link = ""
        for child in list(node):
            local = _local_tag(child.tag)
            if local == "title" and not title:
                title = _node_text(child)
            elif local in {"description", "summary", "content"} and not description:
                description = _node_text(child)
            elif local == "link" and not link:
                href = child.attrib.get("href") or _node_text(child)
                if href:
                    link = href.strip()
        text = "\n".join(part for part in (title, description) if part).strip()
        if not text:
            continue
        items.append({"title": title, "text": text, "link": link})
        if len(items) >= MAX_FEED_ITEMS:
            break
    return items


def _feed_to_text(source_bytes: bytes) -> str:
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(source_bytes)
    except ET.ParseError:
        return html_to_text(source_bytes)
    texts: list[str] = []
    for tag in ("title", "description", "summary", "content"):
        for node in root.iter():
            local = node.tag.rsplit("}", 1)[-1]
            if local == tag and node.text and node.text.strip():
                texts.append(node.text.strip())
            if len(texts) >= 40:
                break
        if len(texts) >= 40:
            break
    return "\n".join(texts) if texts else html_to_text(source_bytes)
