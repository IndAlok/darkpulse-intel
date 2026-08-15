from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from urllib.parse import urlsplit

import httpx


class CollectionError(RuntimeError):
    def __init__(self, code: str, source_id: str) -> None:
        self.code = code
        self.source_id = source_id
        super().__init__(f"collection failed: {code} ({source_id})")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_retries: int = 3
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 8.0

    def __post_init__(self) -> None:
        if not 0 <= self.max_retries <= 8:
            raise ValueError("max_retries must be between 0 and 8")
        if self.backoff_base_seconds < 0 or self.backoff_max_seconds < 0:
            raise ValueError("retry delays cannot be negative")

    def delay(self, retry_number: int) -> float:
        value = self.backoff_base_seconds * (2 ** (retry_number - 1))
        return float(min(value, self.backoff_max_seconds))


@dataclass(frozen=True, slots=True)
class HttpFetchResult:
    body: bytes
    mime_type: str
    status_code: int
    latency_ms: int
    retries: int


class BoundedHttpClient:
    RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        retry_policy: RetryPolicy,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._retry_policy = retry_policy
        self._sleep = sleep

    async def fetch(
        self,
        *,
        source_id: str,
        url: str,
        max_response_bytes: int,
        timeout_seconds: float,
        allowed_mime_types: frozenset[str],
    ) -> HttpFetchResult:
        scheme = urlsplit(url).scheme.casefold()
        if scheme not in {"http", "https"}:
            raise CollectionError("unsupported_url_scheme", source_id)

        for attempt in range(self._retry_policy.max_retries + 1):
            started = perf_counter()
            try:
                async with self._client.stream(
                    "GET",
                    url,
                    timeout=timeout_seconds,
                    follow_redirects=False,
                    headers={"Accept": ", ".join(sorted(allowed_mime_types))},
                ) as response:
                    if response.status_code in self.RETRYABLE_STATUS_CODES:
                        if attempt < self._retry_policy.max_retries:
                            await self._sleep(self._retry_policy.delay(attempt + 1))
                            continue
                        raise CollectionError("retry_exhausted", source_id)
                    if response.is_redirect:
                        raise CollectionError("redirect_rejected", source_id)
                    if response.status_code != 200:
                        raise CollectionError("unexpected_status", source_id)

                    mime_type = response.headers.get("content-type", "").split(";", 1)[0]
                    mime_type = mime_type.strip().casefold()
                    if mime_type not in allowed_mime_types:
                        raise CollectionError("mime_type_rejected", source_id)

                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            if int(content_length) > max_response_bytes:
                                raise CollectionError("response_too_large", source_id)
                        except ValueError:
                            raise CollectionError("invalid_content_length", source_id) from None

                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > max_response_bytes:
                            raise CollectionError("response_too_large", source_id)
                    return HttpFetchResult(
                        body=bytes(body),
                        mime_type=mime_type,
                        status_code=response.status_code,
                        latency_ms=max(0, int((perf_counter() - started) * 1000)),
                        retries=attempt,
                    )
            except CollectionError:
                raise
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt >= self._retry_policy.max_retries:
                    raise CollectionError("retry_exhausted", source_id) from None
                await self._sleep(self._retry_policy.delay(attempt + 1))

        raise CollectionError("retry_exhausted", source_id)  # pragma: no cover
