import httpx
import pytest

from darkpulse.ingestion.collectors.http import (
    BoundedHttpClient,
    CollectionError,
    RetryPolicy,
)

ALLOWED_MIME_TYPES = frozenset({"text/html", "text/plain"})


@pytest.mark.asyncio
async def test_bounded_client_fetches_allowed_text() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/plain; charset=utf-8"},
            content=b"approved fixture",
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        result = await BoundedHttpClient(
            client=client,
            retry_policy=RetryPolicy(max_retries=0),
        ).fetch(
            source_id="surface-a",
            url="https://example.invalid/approved",
            max_response_bytes=100,
            timeout_seconds=1,
            allowed_mime_types=ALLOWED_MIME_TYPES,
        )

    assert result.body == b"approved fixture"
    assert result.mime_type == "text/plain"
    assert result.retries == 0


@pytest.mark.asyncio
async def test_bounded_client_retries_retryable_status() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok")

    async def record_delay(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await BoundedHttpClient(
            client=client,
            retry_policy=RetryPolicy(max_retries=2, backoff_base_seconds=0.25),
            sleep=record_delay,
        ).fetch(
            source_id="surface-a",
            url="https://example.invalid/approved",
            max_response_bytes=100,
            timeout_seconds=1,
            allowed_mime_types=ALLOWED_MIME_TYPES,
        )

    assert result.retries == 1
    assert delays == [0.25]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (httpx.Response(302, headers={"location": "https://other.invalid"}), "redirect_rejected"),
        (httpx.Response(200, headers={"content-type": "image/png"}), "mime_type_rejected"),
        (
            httpx.Response(
                200,
                headers={"content-type": "text/plain", "content-length": "101"},
            ),
            "response_too_large",
        ),
    ],
)
async def test_bounded_client_rejects_unsafe_responses(
    response: httpx.Response,
    expected_code: str,
) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        with pytest.raises(CollectionError) as caught:
            await BoundedHttpClient(
                client=client,
                retry_policy=RetryPolicy(max_retries=0),
            ).fetch(
                source_id="surface-a",
                url="https://example.invalid/approved",
                max_response_bytes=100,
                timeout_seconds=1,
                allowed_mime_types=ALLOWED_MIME_TYPES,
            )

    assert caught.value.code == expected_code


@pytest.mark.asyncio
async def test_bounded_client_errors_do_not_expose_source_url() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("transport details", request=request)

    url = "https://user:password@example.invalid/private?token=secret"
    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(CollectionError) as caught:
            await BoundedHttpClient(
                client=client,
                retry_policy=RetryPolicy(max_retries=0),
            ).fetch(
                source_id="surface-a",
                url=url,
                max_response_bytes=100,
                timeout_seconds=1,
                allowed_mime_types=ALLOWED_MIME_TYPES,
            )

    assert caught.value.code == "retry_exhausted"
    assert url not in str(caught.value)
