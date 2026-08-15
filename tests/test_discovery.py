import httpx
import pytest

from darkpulse.ingestion.collectors.discovery import DarkWebSearchAggregator, DiscoveryEngine
from darkpulse.ingestion.collectors.http import BoundedHttpClient, RetryPolicy

ONION_ONE = f"{'a' * 56}.onion"
ONION_TWO = f"{'b' * 56}.onion"


def client_for(response: httpx.Response) -> tuple[httpx.AsyncClient, BoundedHttpClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response))
    bounded = BoundedHttpClient(client=client, retry_policy=RetryPolicy(max_retries=0))
    return client, bounded


@pytest.mark.asyncio
async def test_discovery_aggregates_and_deduplicates_candidates_without_approving() -> None:
    first_client, first = client_for(
        httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=f'<a href="http://{ONION_ONE}/a">one</a>'.encode(),
        )
    )
    second_client, second = client_for(
        httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=f"http://{ONION_ONE}/a http://{ONION_TWO}/b".encode(),
        )
    )
    engines = [
        DiscoveryEngine(engine_id="engine-a", search_url_template="https://a.invalid/?q={query}"),
        DiscoveryEngine(engine_id="engine-b", search_url_template="https://b.invalid/?q={query}"),
    ]
    aggregator = DarkWebSearchAggregator(
        engines=engines,
        clients={"engine-a": first, "engine-b": second},
    )

    result = await aggregator.search("fixture query")

    assert len(result.candidates) == 2
    assert result.candidates[0].discovered_by == ("engine-a", "engine-b")
    assert result.failed_engines == ()
    await first_client.aclose()
    await second_client.aclose()


def test_discovery_engine_requires_safe_explicit_template() -> None:
    with pytest.raises(ValueError):
        DiscoveryEngine(engine_id="engine-a", search_url_template="http://example.com/?q={query}")
    with pytest.raises(ValueError):
        DiscoveryEngine(engine_id="engine-a", search_url_template="https://example.com/search")
