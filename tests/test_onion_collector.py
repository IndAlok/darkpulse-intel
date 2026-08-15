import httpx
import pytest

from darkpulse.ingestion.checkpoints import InMemoryCheckpointStore
from darkpulse.ingestion.collectors.http import BoundedHttpClient, RetryPolicy
from darkpulse.ingestion.collectors.onion import (
    ApprovedOnionSource,
    OnionCollector,
    OnionReviewPolicy,
    canonical_onion_url,
    isolated_socks_proxy_url,
)
from darkpulse.ingestion.collectors.registry import SourceDefinition
from darkpulse.models import SourceClass

ONION_HOST = f"{'a' * 56}.onion"
SEED_URL = f"http://{ONION_HOST}/"


def make_source(locator: str = SEED_URL) -> SourceDefinition:
    return SourceDefinition(
        source_id="reviewed-market",
        source_class=SourceClass.TOR_MARKET,
        enabled=True,
        locator=locator,
    )


def make_policy(*, max_depth: int = 1, max_pages: int = 5) -> OnionReviewPolicy:
    return OnionReviewPolicy(
        policy_version="review-v1",
        approved=[
            ApprovedOnionSource(
                source_id="reviewed-market",
                seed_url=SEED_URL,
                max_depth=max_depth,
                max_pages=max_pages,
            )
        ],
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "http://abcdefghijklmnop.onion/",
        f"https://{ONION_HOST}/",
        f"http://user:password@{ONION_HOST}/",
    ],
)
def test_onion_policy_rejects_non_v3_or_credentialed_urls(url: str) -> None:
    with pytest.raises(ValueError):
        canonical_onion_url(url)


def test_tor_proxy_uses_stable_per_source_socks_auth_isolation() -> None:
    first = isolated_socks_proxy_url("socks5://tor:9050", "source-a")
    second = isolated_socks_proxy_url("socks5://tor:9050", "source-b")

    assert first.startswith("socks5://") and first.endswith("@tor:9050")
    assert first != second
    assert "source-a" not in first


def test_onion_collector_requires_exact_local_review() -> None:
    with pytest.raises(ValueError, match="not locally reviewed"):
        OnionCollector(
            source=make_source(),
            review_policy=OnionReviewPolicy(policy_version="review-v1", approved=[]),
            checkpoints=InMemoryCheckpointStore(),
            http=None,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_onion_collector_stays_on_reviewed_host_and_respects_depth() -> None:
    visited: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        visited.append(str(request.url))
        if request.url.path == "/":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=(
                    b'<main>Seed fixture</main><a href="/next">next</a>'
                    b'<a href="https://example.com/out">external</a>'
                ),
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"Second fixture",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = OnionCollector(
            source=make_source(),
            review_policy=make_policy(),
            checkpoints=InMemoryCheckpointStore(),
            http=BoundedHttpClient(client=client, retry_policy=RetryPolicy(max_retries=0)),
        )
        records = [record async for record in collector.collect()]

    assert len(records) == 2
    assert visited == [SEED_URL, f"http://{ONION_HOST}/next"]
    assert all(record.source_metadata["review_policy_version"] == "review-v1" for record in records)
    assert await collector.checkpoint() is not None


@pytest.mark.asyncio
async def test_onion_collector_page_bound_is_hard_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b'<p>fixture</p><a href="/one">one</a><a href="/two">two</a>',
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = OnionCollector(
            source=make_source(),
            review_policy=make_policy(max_depth=2, max_pages=1),
            checkpoints=InMemoryCheckpointStore(),
            http=BoundedHttpClient(client=client, retry_policy=RetryPolicy(max_retries=0)),
        )
        records = [record async for record in collector.collect()]

    assert len(records) == 1
