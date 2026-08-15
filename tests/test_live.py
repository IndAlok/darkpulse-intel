from unittest.mock import AsyncMock

import pytest

from darkpulse.ingestion.checkpoints import InMemoryCheckpointStore
from darkpulse.ingestion.collectors.registry import SourceDefinition
from darkpulse.ingestion.collectors.surface import SurfaceCollector
from darkpulse.ingestion.collectors.telegram import TelegramCollector
from darkpulse.ingestion.content_state import InMemoryContentStateStore
from darkpulse.ingestion.live import LiveSourceConfig, create_live_collector
from darkpulse.models import SourceClass


def make_config(tmp_path) -> LiveSourceConfig:
    return LiveSourceConfig(
        onion_review_policy_path=tmp_path / "onion-review.json",
        tor_proxy_url="socks5://127.0.0.1:9050",
        telegram_api_id=None,
        telegram_api_hash=None,
        telegram_runtime_root=tmp_path / "runtime",
        telegram_session_path=tmp_path / "runtime" / "session",
    )


def make_source(
    source_class: SourceClass,
    locator: str,
    *,
    enabled: bool = True,
) -> SourceDefinition:
    return SourceDefinition(
        source_id="source-a",
        source_class=source_class,
        enabled=enabled,
        locator=locator,
        max_retries=0,
    )


@pytest.mark.asyncio
async def test_surface_factory_uses_policy_checked_bounded_collector(tmp_path) -> None:
    handle = await create_live_collector(
        source=make_source(SourceClass.SURFACE_MARKET, "https://example.invalid/source"),
        config=make_config(tmp_path),
        checkpoints=InMemoryCheckpointStore(),
        content_state=InMemoryContentStateStore(),
    )
    try:
        assert isinstance(handle.collector, SurfaceCollector)
    finally:
        await handle.close()


@pytest.mark.asyncio
async def test_factory_rejects_disabled_and_unsupported_sources(tmp_path) -> None:
    config = make_config(tmp_path)
    checkpoints = InMemoryCheckpointStore()
    content_state = InMemoryContentStateStore()

    with pytest.raises(ValueError, match="disabled"):
        await create_live_collector(
            source=make_source(
                SourceClass.SURFACE_MARKET,
                "https://example.invalid/source",
                enabled=False,
            ),
            config=config,
            checkpoints=checkpoints,
            content_state=content_state,
        )
    with pytest.raises(ValueError, match="not supported"):
        await create_live_collector(
            source=make_source(SourceClass.DNM_DATASET, "/datasets/example"),
            config=config,
            checkpoints=checkpoints,
            content_state=content_state,
        )


@pytest.mark.asyncio
async def test_onion_factory_requires_exact_local_review_before_client(tmp_path) -> None:
    config = make_config(tmp_path)
    config.onion_review_policy_path.write_text(
        '{"policy_version":"test-v1","approved":[]}',
        encoding="utf-8",
    )
    source = make_source(
        SourceClass.TOR_MARKET,
        f"http://{'a' * 56}.onion/",
    )

    with pytest.raises(ValueError, match="not locally reviewed"):
        await create_live_collector(
            source=source,
            config=config,
            checkpoints=InMemoryCheckpointStore(),
            content_state=InMemoryContentStateStore(),
        )


@pytest.mark.asyncio
async def test_telegram_factory_uses_authorized_read_only_adapter(tmp_path, monkeypatch) -> None:
    client = AsyncMock()
    connector = AsyncMock(return_value=client)
    monkeypatch.setattr(
        "darkpulse.ingestion.live.connect_authorized_telegram_client",
        connector,
    )
    config = make_config(tmp_path)
    config = LiveSourceConfig(
        onion_review_policy_path=config.onion_review_policy_path,
        tor_proxy_url=config.tor_proxy_url,
        telegram_api_id=123,
        telegram_api_hash="configured-secret",
        telegram_runtime_root=config.telegram_runtime_root,
        telegram_session_path=config.telegram_session_path,
    )

    handle = await create_live_collector(
        source=make_source(SourceClass.TELEGRAM, "https://t.me/public_fixture"),
        config=config,
        checkpoints=InMemoryCheckpointStore(),
        content_state=InMemoryContentStateStore(),
    )

    assert isinstance(handle.collector, TelegramCollector)
    connector.assert_awaited_once()
    await handle.close()
    client.disconnect.assert_awaited_once()
