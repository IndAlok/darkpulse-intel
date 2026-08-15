from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from darkpulse.ingestion.checkpoints import CheckpointStore
from darkpulse.ingestion.collectors.base import BaseCollector
from darkpulse.ingestion.collectors.http import BoundedHttpClient, RetryPolicy
from darkpulse.ingestion.collectors.onion import (
    OnionCollector,
    OnionReviewPolicy,
    create_isolated_tor_client,
)
from darkpulse.ingestion.collectors.registry import SourceDefinition
from darkpulse.ingestion.collectors.surface import SurfaceCollector, validate_public_surface_url
from darkpulse.ingestion.collectors.telegram import (
    TelegramCollector,
    TelethonPublicReader,
    connect_authorized_telegram_client,
    public_channel_name,
)
from darkpulse.ingestion.content_state import ContentStateStore
from darkpulse.models import SourceClass

SURFACE_SOURCE_CLASSES = frozenset(
    {SourceClass.PASTE, SourceClass.SURFACE_MARKET, SourceClass.SOCIAL}
)
TOR_SOURCE_CLASSES = frozenset({SourceClass.TOR_FORUM, SourceClass.TOR_MARKET})


@dataclass(frozen=True, slots=True)
class LiveSourceConfig:
    onion_review_policy_path: Path
    tor_proxy_url: str
    telegram_api_id: int | None
    telegram_api_hash: str | None
    telegram_runtime_root: Path
    telegram_session_path: Path
    telegram_max_messages: int = 100


@dataclass(frozen=True, slots=True)
class CollectorHandle:
    collector: BaseCollector
    close: Callable[[], Awaitable[None]]


async def create_live_collector(
    *,
    source: SourceDefinition,
    config: LiveSourceConfig,
    checkpoints: CheckpointStore,
    content_state: ContentStateStore,
) -> CollectorHandle:

    if not source.enabled:
        raise ValueError("source is disabled")

    collector: BaseCollector
    if source.source_class in SURFACE_SOURCE_CLASSES:
        validate_public_surface_url(source.locator)
        client = httpx.AsyncClient(follow_redirects=False, trust_env=False)
        collector = SurfaceCollector(
            source=source,
            checkpoints=checkpoints,
            http=_bounded_client(client, source),
            content_state=content_state,
        )
        return CollectorHandle(collector=collector, close=client.aclose)

    if source.source_class in TOR_SOURCE_CLASSES:
        review_policy = OnionReviewPolicy.from_path(config.onion_review_policy_path)
        review_policy.require_approved(source)
        client = create_isolated_tor_client(config.tor_proxy_url, source.source_id)
        collector = OnionCollector(
            source=source,
            review_policy=review_policy,
            checkpoints=checkpoints,
            http=_bounded_client(client, source),
            content_state=content_state,
        )
        return CollectorHandle(collector=collector, close=client.aclose)

    if source.source_class is SourceClass.TELEGRAM:
        public_channel_name(source.locator)
        if config.telegram_api_id is None or not config.telegram_api_hash:
            raise ValueError("Telegram API credentials are not configured")
        client = await connect_authorized_telegram_client(
            session_path=config.telegram_session_path,
            runtime_root=config.telegram_runtime_root,
            api_id=config.telegram_api_id,
            api_hash=config.telegram_api_hash,
        )
        collector = TelegramCollector(
            source=source,
            checkpoints=checkpoints,
            reader=TelethonPublicReader(client),
            max_messages=config.telegram_max_messages,
        )
        return CollectorHandle(collector=collector, close=client.disconnect)

    raise ValueError("source class is not supported by live collection")


def _bounded_client(client: httpx.AsyncClient, source: SourceDefinition) -> BoundedHttpClient:
    return BoundedHttpClient(
        client=client,
        retry_policy=RetryPolicy(max_retries=source.max_retries),
    )
