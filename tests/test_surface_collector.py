import httpx
import pytest

from darkpulse.ingestion.checkpoints import InMemoryCheckpointStore
from darkpulse.ingestion.collectors.base import HealthStatus
from darkpulse.ingestion.collectors.http import BoundedHttpClient, CollectionError, RetryPolicy
from darkpulse.ingestion.collectors.registry import SourceDefinition
from darkpulse.ingestion.collectors.surface import SurfaceCollector, validate_public_surface_url
from darkpulse.ingestion.content_state import InMemoryContentStateStore
from darkpulse.models import ContentType, SourceClass


def make_source(*, locator: str = "https://example.invalid/approved") -> SourceDefinition:
    return SourceDefinition(
        source_id="surface-a",
        source_class=SourceClass.SURFACE_MARKET,
        enabled=True,
        locator=locator,
    )


def make_http(response: httpx.Response) -> tuple[httpx.AsyncClient, BoundedHttpClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response))
    return client, BoundedHttpClient(client=client, retry_policy=RetryPolicy(max_retries=0))


@pytest.mark.parametrize(
    "url",
    [
        "http://example.invalid/source",
        "https://localhost/source",
        "https://127.0.0.1/source",
        "https://example.onion/source",
        "https://user:password@example.invalid/source",
        "https://example.invalid/source?token=secret",
        "https://example.invalid/source#fragment",
    ],
)
def test_surface_url_policy_rejects_non_public_locators(url: str) -> None:
    with pytest.raises(ValueError):
        validate_public_surface_url(url)


@pytest.mark.asyncio
async def test_surface_collector_extracts_static_html_and_checkpoints() -> None:
    response = httpx.Response(
        200,
        headers={"content-type": "text/html"},
        content=b"<script>ignored()</script><main>Visible fixture</main>",
    )
    client, http = make_http(response)
    checkpoints = InMemoryCheckpointStore()
    collector = SurfaceCollector(source=make_source(), checkpoints=checkpoints, http=http)

    assert (await collector.health()).status is HealthStatus.DEGRADED
    records = [record async for record in collector.collect()]

    assert records[0].raw_content == "Visible fixture"
    assert records[0].content_type is ContentType.HTML
    assert await collector.checkpoint() is not None
    assert (await collector.health()).status is HealthStatus.HEALTHY
    await client.aclose()


@pytest.mark.asyncio
async def test_surface_collector_rejects_invalid_json_content_free() -> None:
    response = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=b"not-json-sensitive-content",
    )
    client, http = make_http(response)
    collector = SurfaceCollector(
        source=make_source(),
        checkpoints=InMemoryCheckpointStore(),
        http=http,
    )

    with pytest.raises(CollectionError) as caught:
        _ = [record async for record in collector.collect()]

    assert caught.value.code == "invalid_json"
    assert "not-json-sensitive-content" not in str(caught.value)
    assert (await collector.health()).status is HealthStatus.UNHEALTHY
    await client.aclose()


@pytest.mark.asyncio
async def test_surface_collector_skips_unchanged_content_after_successful_yield() -> None:
    response = httpx.Response(200, headers={"content-type": "text/plain"}, content=b"fixture")
    client, http = make_http(response)
    collector = SurfaceCollector(
        source=make_source(),
        checkpoints=InMemoryCheckpointStore(),
        http=http,
        content_state=InMemoryContentStateStore(),
    )

    assert len([record async for record in collector.collect()]) == 1
    assert [record async for record in collector.collect()] == []
    await client.aclose()


@pytest.mark.asyncio
async def test_surface_collector_splits_rss_items() -> None:
    feed = b"""<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>Surat police seize weed</title>
        <description>Cannabis recovered in Adajan</description>
        <link>https://example.invalid/weed</link>
      </item>
      <item>
        <title>NDPS raid in Varachha</title>
        <description>Heroin seized overnight</description>
        <link>https://example.invalid/heroin</link>
      </item>
    </channel></rss>"""
    response = httpx.Response(200, headers={"content-type": "application/rss+xml"}, content=feed)
    client, http = make_http(response)
    collector = SurfaceCollector(
        source=make_source(),
        checkpoints=InMemoryCheckpointStore(),
        http=http,
    )
    records = [record async for record in collector.collect()]
    assert len(records) == 2
    assert "weed" in records[0].raw_content.lower()
    assert records[0].source_ref == "https://example.invalid/weed"
    assert "heroin" in records[1].raw_content.lower()
    await client.aclose()
