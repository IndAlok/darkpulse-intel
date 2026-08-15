from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote_plus, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from darkpulse.ingestion.collectors.http import BoundedHttpClient, CollectionError
from darkpulse.ingestion.collectors.onion import V3_ONION_HOST, canonical_onion_url
from darkpulse.ingestion.hashing import sha256_hex

ONION_URL_PATTERN = re.compile(
    rb"(?<![\w.])(?:https?://)?([a-z2-7]{56}\.onion)(/[A-Za-z0-9._~!$&'()*+,;=:@%/?#-]*)?",
    re.IGNORECASE,
)
SEARCH_MIME_TYPES = frozenset({"application/xhtml+xml", "text/html", "text/plain"})


class DiscoveryEngine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    engine_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,99}$")
    search_url_template: str
    max_response_bytes: int = Field(default=1_000_000, ge=1, le=2_000_000)
    timeout_seconds: float = Field(default=60, gt=0, le=120)

    @field_validator("search_url_template")
    @classmethod
    def validate_template(cls, value: str) -> str:
        if value.count("{query}") != 1:
            raise ValueError("search URL template must contain one {query} placeholder")
        parsed = urlsplit(value.replace("{query}", "test"))
        hostname = (parsed.hostname or "").casefold()
        if parsed.scheme == "https" and hostname and not hostname.endswith(".onion"):
            return value
        if parsed.scheme == "http" and V3_ONION_HOST.fullmatch(hostname):
            return value
        raise ValueError("discovery engine must use HTTPS or an HTTP v3 onion service")


@dataclass(frozen=True, slots=True)
class OnionCandidate:
    candidate_id: str
    url: str
    discovered_by: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    candidates: tuple[OnionCandidate, ...]
    failed_engines: tuple[str, ...]


class DarkWebSearchAggregator:
    def __init__(
        self,
        *,
        engines: list[DiscoveryEngine],
        clients: dict[str, BoundedHttpClient],
        max_candidates: int = 200,
    ) -> None:
        if not 1 <= max_candidates <= 1000:
            raise ValueError("max_candidates must be between 1 and 1000")
        if {engine.engine_id for engine in engines} != set(clients):
            raise ValueError("every discovery engine requires exactly one HTTP client")
        self._engines = tuple(engines)
        self._clients = clients
        self._max_candidates = max_candidates

    async def search(self, query: str) -> DiscoveryResult:
        clean_query = " ".join(query.split())
        if not clean_query or len(clean_query) > 200:
            raise ValueError("search query must contain 1 to 200 characters")
        found: dict[str, set[str]] = {}
        failed: list[str] = []
        for engine in self._engines:
            try:
                response = await self._clients[engine.engine_id].fetch(
                    source_id=engine.engine_id,
                    url=engine.search_url_template.format(query=quote_plus(clean_query)),
                    max_response_bytes=engine.max_response_bytes,
                    timeout_seconds=engine.timeout_seconds,
                    allowed_mime_types=SEARCH_MIME_TYPES,
                )
            except (CollectionError, KeyError, ValueError):
                failed.append(engine.engine_id)
                continue
            for candidate_url in self._extract_candidates(response.body):
                found.setdefault(candidate_url, set()).add(engine.engine_id)
                if len(found) >= self._max_candidates:
                    break
            if len(found) >= self._max_candidates:
                break
        candidates = tuple(
            OnionCandidate(
                candidate_id=sha256_hex(url.encode("utf-8")),
                url=url,
                discovered_by=tuple(sorted(engine_ids)),
            )
            for url, engine_ids in sorted(found.items())
        )
        return DiscoveryResult(candidates=candidates, failed_engines=tuple(sorted(failed)))

    @staticmethod
    def _extract_candidates(source_bytes: bytes) -> tuple[str, ...]:
        candidates: set[str] = set()
        for hostname, path in ONION_URL_PATTERN.findall(source_bytes):
            raw_url = f"http://{hostname.decode('ascii').casefold()}{path.decode('ascii')}"
            try:
                candidates.add(canonical_onion_url(raw_url))
            except ValueError:
                continue
        return tuple(sorted(candidates))
