from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from darkpulse.ingestion.checkpoints import InMemoryCheckpointStore
from darkpulse.ingestion.collectors.base import HealthStatus
from darkpulse.ingestion.collectors.registry import SourceDefinition
from darkpulse.ingestion.collectors.telegram import (
    PublicTelegramMessage,
    TelegramCollector,
    bootstrap_telegram_session,
    public_channel_name,
)
from darkpulse.models import SourceClass


class StubTelegramReader:
    def __init__(self, messages: list[PublicTelegramMessage]) -> None:
        self.messages = messages
        self.min_id: int | None = None

    async def iter_public_messages(
        self,
        channel: str,
        *,
        min_id: int,
        limit: int,
    ) -> AsyncIterator[PublicTelegramMessage]:
        del channel
        self.min_id = min_id
        for message in self.messages[:limit]:
            if message.message_id > min_id:
                yield message


def make_source(locator: str = "https://t.me/public_fixture") -> SourceDefinition:
    return SourceDefinition(
        source_id="telegram-a",
        source_class=SourceClass.TELEGRAM,
        enabled=True,
        locator=locator,
    )


@pytest.mark.parametrize(
    "locator",
    [
        "http://t.me/channel",
        "https://t.me/+privateinvite",
        "https://t.me/joinchat/token",
        "https://t.me/channel/message",
        "https://example.invalid/channel",
    ],
)
def test_telegram_policy_rejects_non_public_channel_locators(locator: str) -> None:
    with pytest.raises(ValueError):
        public_channel_name(locator)


@pytest.mark.asyncio
async def test_telegram_collector_reads_text_ignores_media_and_resumes() -> None:
    reader = StubTelegramReader(
        [
            PublicTelegramMessage(
                message_id=11,
                text="Public text fixture",
                observed_at=datetime.now(UTC),
                media_ignored=True,
            )
        ]
    )
    checkpoints = InMemoryCheckpointStore()
    collector = TelegramCollector(
        source=make_source(),
        checkpoints=checkpoints,
        reader=reader,
    )

    records = [record async for record in collector.collect()]

    assert records[0].raw_content == "Public text fixture"
    assert records[0].source_metadata["media_ignored"] is True
    assert records[0].source_ref == "https://t.me/public_fixture/11"
    assert (await collector.checkpoint()).cursor == "11"
    assert (await collector.health()).status is HealthStatus.HEALTHY

    assert [record async for record in collector.collect()] == []
    assert reader.min_id == 11


@pytest.mark.asyncio
async def test_telegram_collector_does_not_checkpoint_failed_pipeline_yield() -> None:
    reader = StubTelegramReader(
        [
            PublicTelegramMessage(
                message_id=12,
                text="Fixture",
                observed_at=datetime.now(UTC),
            )
        ]
    )
    collector = TelegramCollector(
        source=make_source(),
        checkpoints=InMemoryCheckpointStore(),
        reader=reader,
    )

    stream = collector.collect()
    await anext(stream)
    await stream.aclose()

    assert await collector.checkpoint() is None


class StubAuthorizationClient:
    def __init__(self, authorized: bool = True) -> None:
        self.authorized = authorized
        self.started = False
        self.disconnected = False

    async def start(self) -> None:
        self.started = True

    async def is_user_authorized(self) -> bool:
        return self.authorized

    async def disconnect(self) -> None:
        self.disconnected = True


@pytest.mark.asyncio
async def test_telegram_bootstrap_confines_session_and_disconnects(tmp_path) -> None:
    client = StubAuthorizationClient()
    runtime_root = tmp_path / "runtime"
    session_file = runtime_root / "session.session"

    def client_factory(*_) -> StubAuthorizationClient:
        session_file.write_text("session fixture", encoding="utf-8")
        session_file.chmod(0o644)
        return client

    await bootstrap_telegram_session(
        session_path=runtime_root / "session",
        runtime_root=runtime_root,
        api_id=123,
        api_hash="configured-secret",
        client_factory=client_factory,
    )

    assert client.started is True
    assert client.disconnected is True
    import sys

    if sys.platform != "win32":
        assert runtime_root.stat().st_mode & 0o777 == 0o700
        assert session_file.stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_telegram_bootstrap_rejects_session_outside_runtime(tmp_path) -> None:
    with pytest.raises(ValueError, match="inside the runtime"):
        await bootstrap_telegram_session(
            session_path=tmp_path / "outside" / "session",
            runtime_root=tmp_path / "runtime",
            api_id=123,
            api_hash="configured-secret",
            client_factory=lambda *_: StubAuthorizationClient(),
        )
